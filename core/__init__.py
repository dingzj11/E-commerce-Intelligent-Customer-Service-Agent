"""核心模块：企业级分布式系统基础设施

Redis 分布式系统完整实现，涵盖面试中涉及的几乎所有技术点：

【模块索引】
- config.py              — 集中化配置（12-factor 风格）
- redis_client.py        — Redis 客户端（Pipeline/事务/Lua/HLL/BitMap/GEO/三级缓存防护）
- distributed_lock.py    — 分布式锁（单实例 + Redlock 多实例）
- redis_transaction.py   — 分布式事务（Saga编排/TCC/事务消息/本地消息表）
- redis_stream.py        — Redis Streams 消息队列（消费者组/ACK/死信队列）
- redis_bloom.py         — 布隆过滤器（BitMap实现/缓存穿透防护）
- redis_delay_queue.py   — 延迟队列（ZSET实现/失败重试/分布式消费）
- distributed_id.py      — 分布式 ID 生成（Redis INCR/Snowflake/号段模式）
- cache_decorator.py     — 缓存注解（@cacheable/@cache_evict）
- idempotency.py         — 幂等性保护
- rate_limiter.py        — 限流（滑动窗口/令牌桶/固定窗口）
"""

from core.config import AppConfig, get_config
from core.distributed_lock import (
    DistributedLock,
    distributed_lock,
    with_distributed_lock,
    Redlock,
    LockAcquisitionError,
)
from core.cache_decorator import cacheable, cache_evict, cache_key
from core.idempotency import (
    idempotent,
    IdempotencyRecord,
    IdempotencyStatus,
    IdempotencyConflictError,
    idempotent_request_id,
)
from core.rate_limiter import (
    RateLimiter,
    rate_limit,
    RateLimitExceededError,
    get_rate_limiter,
)
from core.redis_client import (
    get_redis_client,
    is_redis_available,
    get_or_set,
    get_or_set_advanced,
    cache_get,
    cache_get_json,
    cache_set,
    cache_delete,
    cache_incr,
    RedisPipeline,
    optimistic_transaction,
    atomic_deduct,
    atomic_check_and_purchase,
    publish,
    subscribe,
    pfadd,
    pfcount,
)
from core.redis_transaction import (
    TccCoordinator,
    SagaCoordinator,
    SagaStep,
    TransactionalOutbox,
    create_local_message,
    process_local_messages,
)
from core.redis_stream import RedisStream, DeadLetterQueue, StreamMessage
from core.redis_bloom import RedisBloomFilter, CachePenetrationGuard
from core.redis_delay_queue import DelayQueue
from core.distributed_id import (
    SnowflakeIDGenerator,
    next_id_redis,
    batch_next_ids,
    gen_order_id,
    gen_postsale_id,
)
