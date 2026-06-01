"""幂等性模块

基于 Redis 实现请求幂等性，防止重复提交。

核心机制:
- 请求级幂等键（idempotency_key）：客户端生成的唯一请求 ID
- 业务级幂等键（business_key）：由业务字段计算的唯一键
- 首次处理缓存结果，重复请求直接返回缓存结果
- 过期时间自动清理

使用场景:
- 售后申请：防止用户多次点击产生重复售后单
- 订单取消：防止重复取消
- 物流投诉：防止重复提交投诉
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional

from core.config import get_config
from core.redis_client import cache_get_json, cache_set, cache_delete

logger = logging.getLogger("idempotency")


class IdempotencyStatus(Enum):
    PROCESSING = "processing"   # 处理中
    COMPLETED = "completed"     # 已完成
    FAILED = "failed"           # 失败


@dataclass
class IdempotencyRecord:
    """幂等记录"""
    key: str
    status: IdempotencyStatus
    result: Any = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


def _build_idempotency_key(prefix: str, *key_parts: str) -> str:
    """构建幂等键"""
    combined = "|".join(key_parts)
    key_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]
    return f"idempotent:{prefix}:{key_hash}"


def _is_idempotency_enabled() -> bool:
    """检查幂等功能是否可用"""
    from core.redis_client import is_redis_available
    return is_redis_available()


def idempotent(
    prefix: str,
    key_func: Optional[Callable] = None,
    ttl: int = 3600,
    allow_retry_on_failed: bool = True,
):
    """幂等装饰器

    Args:
        prefix: 业务前缀（如 "postsale", "cancel_order"）
        key_func: 自定义 key 构建函数，接收 (*args, **kwargs) 返回 key_parts
        ttl: 幂等记录过期时间（秒），默认 1 小时
        allow_retry_on_failed: 失败后是否允许重试

    用法:
        @idempotent("postsale")
        def commit_postsale(order_detail_id: str, reason: str):
            ...

        @idempotent("cancel_order", key_func=lambda order_id: (order_id,))
        def cancel_order(order_id: str):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _is_idempotency_enabled():
                return func(*args, **kwargs)

            # 构建幂等键
            if key_func:
                key_parts = key_func(*args, **kwargs)
                if isinstance(key_parts, str):
                    key_parts = (key_parts,)
            else:
                # 基于所有参数的哈希
                args_repr = json.dumps(
                    {"args": args, "kwargs": kwargs}, sort_keys=True, default=str
                )
                key_parts = (hashlib.sha256(args_repr.encode()).hexdigest()[:16],)

            idem_key = _build_idempotency_key(prefix, *key_parts)

            # 检查是否已有记录
            try:
                existing = cache_get_json(idem_key)
                if existing:
                    record = IdempotencyRecord(**existing)
                    if record.status == IdempotencyStatus.COMPLETED.value:
                        logger.info("幂等命中（已完成）: %s, 直接返回缓存结果", idem_key)
                        return record.result
                    elif record.status == IdempotencyStatus.PROCESSING.value:
                        logger.warning("幂等命中（处理中）: %s, 可能重复提交", idem_key)
                        raise IdempotencyConflictError(
                            f"请求正在处理中，请勿重复提交: {prefix}"
                        )
                    elif (
                        record.status == IdempotencyStatus.FAILED.value
                        and not allow_retry_on_failed
                    ):
                        raise IdempotencyConflictError(
                            f"请求已失败，不允许重试: {prefix}"
                        )
            except IdempotencyConflictError:
                raise
            except Exception as e:
                logger.warning("读取幂等记录异常: %s", e)

            # 设置为处理中
            record = IdempotencyRecord(
                key=idem_key,
                status=IdempotencyStatus.PROCESSING,
            )
            cache_set(idem_key, record.__dict__, ttl=ttl, nx=True)

            try:
                result = func(*args, **kwargs)

                # 标记为完成，缓存结果
                record.status = IdempotencyStatus.COMPLETED
                record.result = result
                record.completed_at = time.time()
                cache_set(idem_key, record.__dict__, ttl=ttl)

                return result

            except Exception as e:
                # 标记为失败
                record.status = IdempotencyStatus.FAILED
                record.result = {"error": str(e)}
                record.completed_at = time.time()
                try:
                    cache_set(idem_key, record.__dict__, ttl=ttl)
                except Exception:
                    pass
                raise

        return wrapper

    return decorator


class IdempotencyConflictError(Exception):
    """幂等冲突异常"""
    pass


def idempotent_request_id(request_id: str, operation: str, ttl: int = 300) -> bool:
    """检查请求 ID 是否已处理（请求级幂等）

    Args:
        request_id: 客户端提供的唯一请求 ID
        operation: 操作名称
        ttl: 过期时间

    Returns:
        True 表示是新请求，False 表示已处理过
    """
    key = f"request_id:{operation}:{request_id}"
    # SET NX 成功 → 新请求; 失败 → 已处理
    from core.redis_client import cache_set
    return cache_set(key, int(time.time()), ttl=ttl, nx=True)
