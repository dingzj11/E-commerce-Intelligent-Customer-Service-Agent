"""限流模块

基于 Redis 实现多种维度的限流。

支持的限流策略:
- 固定窗口计数器（简单高效）
- 滑动窗口（更精确，使用 Sorted Set）
- 令牌桶（平滑限流，使用 Lua 脚本）

限流维度:
- 全局：保护系统整体
- 按用户：防止单用户滥用
- 按 IP：防止 IP 攻击
- 按业务：特定操作的频率限制
"""

import logging
import time
from functools import wraps
from typing import Callable, Optional

from core.config import get_config

logger = logging.getLogger("rate_limiter")

# 滑动窗口限流 Lua 脚本
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

-- 移除窗口外的记录
redis.call("ZREMRANGEBYSCORE", key, 0, now - window)

-- 统计当前窗口内的请求数
local count = redis.call("ZCARD", key)
if count < limit then
    redis.call("ZADD", key, now, now .. "|" .. count)
    redis.call("EXPIRE", key, math.ceil(window))
    return 1
else
    return 0
end
"""

# 令牌桶 Lua 脚本
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local bucket = redis.call("HMGET", key, "tokens", "last_refill")
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

-- 计算新增的令牌数
local elapsed = math.max(now - last_refill, 0)
local new_tokens = math.floor(elapsed * rate)
tokens = math.min(tokens + new_tokens, capacity)
last_refill = now

local allowed = false
if tokens >= requested then
    tokens = tokens - requested
    allowed = true
end

redis.call("HMSET", key, "tokens", tokens, "last_refill", last_refill)
redis.call("EXPIRE", key, math.ceil(capacity / rate) + 10)

return allowed and 1 or 0
"""


class RateLimiter:
    """限流器"""

    def __init__(self):
        self._scripts_loaded = False

    def _load_scripts(self):
        """预加载 Lua 脚本到 Redis"""
        if self._scripts_loaded:
            return
        try:
            from core.redis_client import get_redis_client
            client = get_redis_client()
            self._sliding_window = client.register_script(_SLIDING_WINDOW_LUA)
            self._token_bucket = client.register_script(_TOKEN_BUCKET_LUA)
            self._scripts_loaded = True
        except Exception as e:
            logger.warning("无法预加载限流脚本: %s", e)

    def _ensure_scripts(self):
        if not self._scripts_loaded:
            self._load_scripts()

    def is_allowed_sliding_window(
        self,
        key: str,
        window: int = 1,
        limit: int = 10,
    ) -> bool:
        """滑动窗口限流

        Args:
            key: 限流键（如 "rate:user:1001"）
            window: 时间窗口（秒）
            limit: 窗口内最大请求数

        Returns:
            True 允许，False 限流
        """
        try:
            self._ensure_scripts()
            now = time.time()
            result = self._sliding_window(
                keys=[key], args=[window, limit, now]
            )
            return result == 1
        except Exception as e:
            logger.warning("限流检查异常: %s，降级放行", e)
            return True  # Redis 不可用时放行

    def is_allowed_token_bucket(
        self,
        key: str,
        capacity: int = 30,
        rate: float = 10.0,
        requested: int = 1,
    ) -> bool:
        """令牌桶限流（平滑限流）

        Args:
            key: 限流键
            capacity: 桶容量（最大突发）
            rate: 令牌生成速率（个/秒）
            requested: 请求令牌数
        """
        try:
            self._ensure_scripts()
            now = time.time()
            result = self._token_bucket(
                keys=[key], args=[capacity, rate, requested, now]
            )
            return result == 1
        except Exception:
            return True  # 降级放行

    def is_allowed_fixed_window(
        self,
        key: str,
        window: int = 1,
        limit: int = 10,
    ) -> bool:
        """固定窗口限流（最简单，边界可能存在突发）"""
        try:
            from core.redis_client import cache_incr, cache_ttl, get_redis_client

            current = cache_incr(key)
            if current == 1:
                # 首次设置过期时间
                get_redis_client().expire(key, window)
            elif current < 0:
                return True  # Redis 不可用

            return current <= limit
        except Exception:
            return True


# ==================== 全局限流器 ====================


_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


# ==================== 装饰器 ====================


def rate_limit(
    key_pattern: str = "global",
    window: int = 1,
    limit: int = 10,
    dimension: str = "sliding_window",
):
    """限流装饰器

    用法:
        @rate_limit("postsale:{user_id}", window=60, limit=5)
        def commit_postsale(user_id: str, *args, **kwargs):
            pass
    """
    import inspect

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            call_args = inspect.getcallargs(func, *args, **kwargs)
            key = key_pattern.format(**call_args)

            limiter = get_rate_limiter()

            if dimension == "sliding_window":
                allowed = limiter.is_allowed_sliding_window(key, window, limit)
            elif dimension == "token_bucket":
                allowed = limiter.is_allowed_token_bucket(key, capacity=limit, rate=limit/window)
            else:
                allowed = limiter.is_allowed_fixed_window(key, window, limit)

            if not allowed:
                raise RateLimitExceededError(
                    f"请求过于频繁，请稍后重试: {key_pattern} (window={window}s, limit={limit})"
                )

            return func(*args, **kwargs)

        return wrapper

    return decorator


class RateLimitExceededError(Exception):
    """限流超出异常"""
    pass
