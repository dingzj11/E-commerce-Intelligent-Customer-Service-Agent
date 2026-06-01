"""缓存装饰器模块

提供声明式缓存注解，支持方法级别的自动缓存。

支持的缓存策略:
- @cacheable: 先查缓存，未命中则执行函数并缓存结果
- @cache_evict: 执行函数后清除缓存
- 支持自定义 key 生成器
- 降级：Redis 不可用时优雅降级（直接执行原函数）
"""

import functools
import hashlib
import inspect
import json
import logging
from typing import Any, Callable, Optional

from core.config import CacheTTL, get_config
from core.redis_client import (
    cache_set,
    cache_get_json,
    cache_delete,
    is_redis_available,
)

logger = logging.getLogger("cache")


def cache_key(prefix: str, *args, **kwargs) -> str:
    """构建标准化的缓存键

    用法:
        cache_key("regions", "all")
        cache_key("order", order_id)
        cache_key("postsale:reasons", category)
    """
    parts = [prefix]
    for arg in args:
        if arg is not None:
            parts.append(str(arg))
    for k, v in sorted(kwargs.items()):
        if v is not None:
            parts.append(f"{k}={v}")
    return ":".join(parts)


def _default_key(func: Callable, args: tuple, kwargs: dict) -> str:
    """默认缓存键生成器：函数限定名 + 参数的 MD5 哈希"""
    func_name = f"{func.__module__}.{func.__qualname__}"

    call_args = inspect.getcallargs(func, *args, **kwargs)
    # 排除 self/cls 参数
    call_args.pop("self", None)
    call_args.pop("cls", None)

    args_str = json.dumps(call_args, sort_keys=True, default=str)
    args_hash = hashlib.md5(args_str.encode()).hexdigest()[:12]

    return f"cache:{func_name}:{args_hash}"


def cacheable(
    ttl: Optional[int] = None,
    key_prefix: Optional[str] = None,
    key_builder: Optional[Callable] = None,
    unless: Optional[Callable[[Any], bool]] = None,
):
    """缓存装饰器：先查缓存，未命中则执行函数并写入缓存

    用法:
        @cacheable(ttl=3600, key_prefix="region")
        def get_all_regions():
            return session.query(Region).all()

        @cacheable(ttl=300)
        def get_order(order_id: str):
            return session.query(OrderInfo).filter_by(order_id=order_id).first()

    特性:
        - Redis 不可用时自动降级（直接执行原函数）
        - 返回 None 不缓存（防止缓存穿透）
        - unless 条件为 True 时不缓存
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 构建缓存键
            if key_builder:
                key = key_builder(func, args, kwargs)
            elif key_prefix:
                key = cache_key(key_prefix, *args, **kwargs)
            else:
                key = _default_key(func, args, kwargs)

            # 尝试从缓存获取
            if is_redis_available():
                cached = cache_get_json(key)
                if cached is not None:
                    logger.debug("缓存命中: %s", key)
                    return cached

            # 执行原函数
            result = func(*args, **kwargs)

            # 写入缓存
            if result is not None and is_redis_available():
                if unless is None or not unless(result):
                    _ttl = ttl or _default_ttl(func)
                    cache_set(key, result, _ttl)
                    logger.debug("写入缓存: %s (TTL=%ss)", key, _ttl)

            return result

        return wrapper

    return decorator


def cache_evict(
    key_prefix: Optional[str] = None,
    key_builder: Optional[Callable] = None,
    all_pattern: Optional[str] = None,
):
    """缓存清除装饰器：执行函数后清除缓存

    用法:
        @cache_evict(key_prefix="region")
        def update_region(province: str, city: str):
            pass

        @cache_evict(all_pattern="cache:actions.*:get_order_detail")  # 按模式批量删除
        def cancel_order(order_id: str):
            pass
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)

            if not is_redis_available():
                return result

            # 精确清除
            if key_builder:
                key = key_builder(func, args, kwargs)
                cache_delete(key)
            elif key_prefix:
                key = cache_key(key_prefix, *args, **kwargs)
                cache_delete(key)

            # 按模式批量清除
            if all_pattern:
                _delete_by_pattern(all_pattern)

            logger.debug("清除缓存: %s", key_prefix or all_pattern)
            return result

        return wrapper

    return decorator


def _delete_by_pattern(pattern: str):
    """按模式批量删除缓存键"""
    try:
        from core.redis_client import get_redis_client

        client = get_redis_client()
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=pattern, count=100)
            if keys:
                client.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning("批量清除缓存失败: %s", e)


def _default_ttl(func: Callable) -> int:
    """根据函数名推断默认 TTL"""
    cfg = get_config().cache_ttl
    name = func.__name__.lower()

    if "region" in name:
        return cfg.regions
    if "logistics" in name and "company" in name:
        return cfg.logistics_companies
    if "order" in name:
        return cfg.order_detail
    if "postsale" in name or "reason" in name:
        return cfg.postsale_reasons
    if "category" in name or "product" in name:
        return cfg.product_category

    return 300  # 默认 5 分钟
