"""分布式 ID 生成器

基于 Redis 实现多种分布式 ID 生成算法。

【为什么需要分布式 ID】
单数据库的自增 ID 在分库分表后会冲突。
分布式 ID 需要满足：全局唯一、趋势递增、高性能。

【算法对比】
┌──────────────┬──────────┬──────────┬──────────┬──────────────┐
│ 方案          │ 唯一性   │ 有序性   │ 性能     │ 依赖          │
├──────────────┼──────────┼──────────┼──────────┼──────────────┤
│ UUID          │ 高       │ 无序     │ 高       │ 无            │
│ 数据库自增    │ 高       │ 递增     │ 低       │ DB(单点)      │
│ Snowflake     │ 高       │ 趋势递增 │ 极高     │ 时钟同步      │
│ Redis INCR    │ 高       │ 递增     │ 高       │ Redis         │
│ 号段模式(Leaf)│ 高       │ 递增     │ 极高     │ DB + 本地缓存 │
└──────────────┴──────────┴──────────┴──────────┴──────────────┘

【面试重点——Snowflake 原理】
64-bit 结构:
┌─┬──────────────────────┬──────────┬──────────┐
│1│      41-bit 时间戳    │10-bit 机器│12-bit 序列│
│ │  (毫秒，69年)         │ (1024节点)│ (4096/ms) │
└─┴──────────────────────┴──────────┴──────────┘

- 41 bit 毫秒时间戳：可表示约 69 年（从自定义 epoch 开始）
- 10 bit 机器 ID：1024 个节点（通常是 datacenter(5) + worker(5)）
- 12 bit 序列号：每毫秒 4096 个 ID

【时钟回拨问题及解决方案】
1. 短时间回拨（< 5ms）：等待追上上次时间
2. 长时间回拨：使用备用 worker ID 或抛出异常
3. 配置 NTP 同步，减少时钟偏差
"""

import logging
import time
import threading
from typing import Optional

from core.config import get_config
from core.redis_client import (
    _make_key,
    cache_incr,
    get_redis_client,
    is_redis_available,
)

logger = logging.getLogger("distributed_id")


# ==================== Redis INCR 方式 ====================


def next_id_redis(key: str = "global_id", step: int = 1) -> int:
    """Redis INCR 生成全局唯一自增 ID

    面试要点: Redis INCR 是原子操作，单线程模型保证不会重复。
    缺点：依赖 Redis 可用性；每次生成都要网络往返。

    适用场景: 订单号、售后单号等需要递增的业务 ID
    """
    return cache_incr(key, step, ttl=None)


def batch_next_ids(key: str = "global_id", count: int = 100) -> tuple:
    """号段模式：一次取一批 ID 缓存在本地，减少网络请求

    面试要点: 美团 Leaf 号段模式的核心思想。
    每次从 Redis 取一个号段 [start, end]，本地自增，
    用完了再取下一段。性能极高（无网络开销）。
    """
    end = cache_incr(key, count)
    start = end - count + 1
    return start, end


# ==================== Snowflake 风格 ====================


class SnowflakeIDGenerator:
    """Snowflake 分布式 ID 生成器

    面试完整实现：包括 worker ID 自动分配、时钟回拨处理。
    本项目利用 Redis 分配 worker ID（K8s 环境下 Pod 漂移后仍能正确分配）。

    使用示例:
        gen = SnowflakeIDGenerator()
        gen.start()
        order_id = gen.next_id()  # 1285938401234567890
    """

    # Snowflake 位分配
    EPOCH = 1700000000000  # 自定义起始时间（2023-11-14 00:00:00 UTC）
    WORKER_ID_BITS = 10
    SEQUENCE_BITS = 12

    MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1  # 1023
    MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1    # 4095

    def __init__(self, worker_id: Optional[int] = None):
        self._worker_id = worker_id
        self._sequence = 0
        self._last_timestamp = -1
        self._lock = threading.Lock()

    def start(self) -> int:
        """启动并获取 worker ID（通过 Redis 自动分配）"""
        if self._worker_id is not None:
            return self._worker_id

        if not is_redis_available():
            # Redis 不可用，使用 hash of hostname 作为 worker ID
            import socket
            self._worker_id = abs(hash(socket.gethostname())) % (self.MAX_WORKER_ID + 1)
            logger.warning("Redis 不可用，使用 hostname hash 作为 worker_id: %s", self._worker_id)
            return self._worker_id

        # 通过 Redis 注册 worker，获取唯一编号
        worker_key = _make_key("snowflake:worker_ids")
        client = get_redis_client()

        # 尝试分配一个未使用的 worker ID
        for _ in range(self.MAX_WORKER_ID + 1):
            for candidate in range(self.MAX_WORKER_ID + 1):
                acquired = client.setbit(worker_key, candidate, 1)
                if acquired == 0:  # 该位置之前是 0，现在被我们设为 1
                    self._worker_id = candidate
                    # 设置过期时间，防止 worker 宕机后 ID 永久占用
                    client.expire(worker_key, 300)  # 5 分钟后过期
                    logger.info("Snowflake worker ID 分配成功: %s", self._worker_id)
                    return self._worker_id

        raise RuntimeError("无法分配 Snowflake worker ID (已满)")

    def _current_millis(self) -> int:
        return int(time.time() * 1000)

    def next_id(self) -> int:
        """生成下一个 ID"""
        with self._lock:
            timestamp = self._current_millis()

            # 时钟回拨处理
            if timestamp < self._last_timestamp:
                offset = self._last_timestamp - timestamp
                if offset <= 5:
                    # 短回拨：等待追上
                    logger.warning("时钟回拨 %sms，等待中...", offset)
                    time.sleep(offset / 1000 + 0.001)
                    timestamp = self._current_millis()
                else:
                    # 长回拨：抛异常（或切换到备用 worker_id）
                    raise ClockBackwardsError(
                        f"时钟回拨 {offset}ms，超过容忍范围"
                    )

            if timestamp == self._last_timestamp:
                # 同一毫秒内，序列号自增
                self._sequence = (self._sequence + 1) & self.MAX_SEQUENCE
                if self._sequence == 0:
                    # 序列号用完，等待下一毫秒
                    timestamp = self._wait_next_millis(self._last_timestamp)
            else:
                self._sequence = 0

            self._last_timestamp = timestamp

            # 组装 64-bit ID
            result = (
                ((timestamp - self.EPOCH) << (self.WORKER_ID_BITS + self.SEQUENCE_BITS))
                | (self._worker_id << self.SEQUENCE_BITS)
                | self._sequence
            )
            return result

    def _wait_next_millis(self, last_timestamp: int) -> int:
        """自旋等待下一毫秒"""
        timestamp = self._current_millis()
        while timestamp <= last_timestamp:
            timestamp = self._current_millis()
        return timestamp


class ClockBackwardsError(Exception):
    """时钟回拨异常"""
    pass


# ==================== 业务 ID 格式化 ====================


def gen_order_id(worker_id: int = 0) -> str:
    """生成业务订单号: ORD + 时间戳 + worker + 序列号

    格式: ORD20260529143005W001S0001
    """
    now = time.strftime("%Y%m%d%H%M%S")
    seq = next_id_redis("order_seq:{now}", 1)
    return f"ORD{now}W{worker_id:03d}S{seq:04d}"


def gen_postsale_id(worker_id: int = 0) -> str:
    """生成售后单号: PTS + 时间戳 + worker + 序列号"""
    now = time.strftime("%Y%m%d%H%M%S")
    seq = next_id_redis(f"postsale_seq:{now}", 1)
    return f"PTS{now}W{worker_id:03d}S{seq:04d}"
