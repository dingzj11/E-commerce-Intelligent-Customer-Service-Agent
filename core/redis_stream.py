"""Redis Streams 模块

基于 Redis 5.0+ Streams 实现可靠消息队列，支持消费者组、ACK 机制、死信队列。

【Redis Stream vs Pub/Sub vs List】
┌──────────┬──────────┬──────────┬──────────────┬──────────────┐
│ 特性     │ Stream   │ Pub/Sub  │ List(BLPOP)  │ Kafka        │
├──────────┼──────────┼──────────┼──────────────┼──────────────┤
│ 持久化   │ 支持     │ 不支持   │ 支持         │ 支持         │
│ ACK 机制 │ 支持     │ 不支持   │ 无(消费即删) │ 支持         │
│ 消费者组 │ 支持     │ 不支持   │ 不支持       │ 支持         │
│ 消息回溯 │ 支持     │ 不支持   │ 不支持       │ 支持         │
│ 顺序保证 │ 分区内   │ 全局     │ 全局         │ 分区内       │
│ 适用场景 │ 可靠MQ   │ 实时通知 │ 简单队列     │ 大数据流     │
└──────────┴──────────┴──────────┴──────────────┴──────────────┘

【面试核心问题：为什么不用 Kafka 而用 Redis Stream？】
1. 项目已有 Redis，引入 Kafka 增加运维成本
2. 消息量级不大（< 10万/秒），Redis Stream 完全够用
3. 低延迟场景，Redis Stream 内存操作更快
4. 如果未来消息量增长到百万级 → 平滑迁移到 Kafka（两者 API 模型相似）

【使用场景——本项目中】
- 订单创建事件 → 通知物流系统、积分系统
- 售后申请事件 → 通知审核系统
- 对话事件流 → 分析系统、监控大盘
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from redis.exceptions import RedisError

from core.redis_client import _make_key, get_redis_client

logger = logging.getLogger("redis_stream")


@dataclass
class StreamMessage:
    """Stream 消息"""
    message_id: str
    data: Dict[str, str]
    stream_key: str = ""


class RedisStream:
    """Redis Streams 消息队列

    使用示例:
        stream = RedisStream("order_events")

        # 生产者：发送消息
        stream.add({"order_id": "ORD123", "event": "created"})

        # 消费者：处理消息
        def handle_order_event(msg: StreamMessage):
            print(f"收到: {msg.data}")

        stream.create_consumer_group("order_workers")
        stream.consume("order_workers", "worker-1", handle_order_event)
    """

    def __init__(
        self,
        stream_name: str,
        max_len: int = 100000,  # 最大消息数（防止内存无限增长）
        auto_trim: bool = True,
    ):
        self._name = _make_key(f"stream:{stream_name}")
        self._max_len = max_len
        self._auto_trim = auto_trim

    @property
    def name(self) -> str:
        return self._name

    def add(self, data: Dict[str, Any], max_len: Optional[int] = None) -> Optional[str]:
        """添加消息到 Stream

        Returns:
            消息 ID（如 "1234567890123-0"），失败返回 None
        """
        try:
            fields = {}
            for k, v in data.items():
                fields[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)

            msg_id = get_redis_client().xadd(
                self._name,
                fields,
                maxlen=max_len or self._max_len,
                approximate=True,  # 近似裁剪，提升性能
            )
            return msg_id.decode() if isinstance(msg_id, bytes) else msg_id
        except RedisError as e:
            logger.error("Stream 添加消息失败: %s", e)
            return None

    def create_consumer_group(
        self,
        group_name: str,
        start_from: str = "0",  # "0" 从最早开始, "$" 从最新开始
        mkstream: bool = True,
    ) -> bool:
        """创建消费者组

        面试要点: 消费者组允许多个消费者共享消费进度，实现负载均衡。
        同组内每条消息只被一个消费者处理。
        """
        try:
            get_redis_client().xgroup_create(
                self._name,
                group_name,
                id=start_from,
                mkstream=mkstream,
            )
            logger.info("消费者组 %s 创建成功 (stream=%s)", group_name, self._name)
            return True
        except RedisError as e:
            err = str(e)
            if "BUSYGROUP" in err:
                logger.debug("消费者组 %s 已存在", group_name)
                return True
            logger.error("创建消费者组失败: %s", e)
            return False

    def consume(
        self,
        group_name: str,
        consumer_name: str,
        callback: Callable[[StreamMessage], bool],
        batch_size: int = 10,
        block_ms: int = 5000,
        run_forever: bool = True,
    ):
        """消费者：拉取并处理消息（支持 ACK）

        Args:
            group_name: 消费者组名称
            consumer_name: 消费者名称（组内唯一）
            callback: 消息处理回调，返回 True 表示处理成功
            batch_size: 每次拉取的消息数
            block_ms: 阻塞等待时间（ms），0 表示不阻塞
            run_forever: True 持续监听，False 处理一批后返回

        Returns:
            threading.Thread (run_forever=True) 或处理消息数
        """
        if run_forever:
            thread = threading.Thread(
                target=self._consume_loop,
                args=(group_name, consumer_name, callback, batch_size, block_ms),
                daemon=True,
                name=f"stream-consumer-{consumer_name}",
            )
            thread.start()
            return thread
        else:
            return self._consume_batch(group_name, consumer_name, callback, batch_size, block_ms)

    def _consume_loop(
        self,
        group_name: str,
        consumer_name: str,
        callback: Callable[[StreamMessage], bool],
        batch_size: int,
        block_ms: int,
    ):
        """持续消费循环"""
        logger.info("消费者 %s/%s 开始监听 %s", group_name, consumer_name, self._name)
        while True:
            try:
                self._consume_batch(group_name, consumer_name, callback, batch_size, block_ms)
            except Exception as e:
                logger.error("消费者异常 (5s后重试): %s", e)
                time.sleep(5)

    def _consume_batch(
        self,
        group_name: str,
        consumer_name: str,
        callback: Callable[[StreamMessage], bool],
        batch_size: int,
        block_ms: int,
    ) -> int:
        """消费一批消息，返回处理成功的数量"""
        client = get_redis_client()
        success_count = 0

        try:
            results = client.xreadgroup(
                group_name,
                consumer_name,
                {self._name: ">"},  # ">" 表示只消费新消息
                count=batch_size,
                block=block_ms,
            )
        except RedisError as e:
            logger.error("xreadgroup 失败: %s", e)
            return 0

        for stream_name, messages in results:
            stream_name = stream_name.decode() if isinstance(stream_name, bytes) else stream_name

            for msg_id, fields in messages:
                msg_id = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                data = {}
                for k, v in fields.items():
                    k_str = k.decode() if isinstance(k, bytes) else k
                    v_str = v.decode() if isinstance(v, bytes) else v
                    try:
                        data[k_str] = json.loads(v_str)
                    except (json.JSONDecodeError, TypeError):
                        data[k_str] = v_str

                message = StreamMessage(message_id=msg_id, data=data, stream_key=stream_name)

                try:
                    if callback(message):
                        client.xack(self._name, group_name, msg_id)
                        success_count += 1
                    else:
                        logger.warning("消息处理失败(未ACK): %s", msg_id)
                except Exception as e:
                    logger.error("回调处理异常: %s", e)

        return success_count

    def get_pending_count(self, group_name: str) -> int:
        """获取消费者组中未 ACK 的消息数（监控用）"""
        try:
            info = get_redis_client().xpending(self._name, group_name)
            return info.get("pending", 0)
        except RedisError:
            return -1

    def claim_pending(
        self,
        group_name: str,
        consumer_name: str,
        min_idle_ms: int = 60000,  # 超过此时间未 ACK 的消息被认为是"失活"
        count: int = 100,
    ) -> List[StreamMessage]:
        """认领失活消息（故障转移：一个消费者挂了，其他消费者接管其未 ACK 的消息）

        面试要点: 这是 Stream 比 List/PubSub 高级的地方——自动故障转移。
        """
        client = get_redis_client()
        messages = []

        try:
            # 获取失活消息
            pending = client.xpending_range(
                self._name, group_name, min="-", max="+", count=count
            )
            stale_ids = [
                p["message_id"].decode() if isinstance(p["message_id"], bytes) else p["message_id"]
                for p in pending
                if p["time_since_delivered"] > min_idle_ms
            ]

            if stale_ids:
                claimed = client.xclaim(
                    self._name, group_name, consumer_name, min_idle_ms, stale_ids,
                )
                for msg_id, fields in claimed:
                    msg_id = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                    data = {
                        (k.decode() if isinstance(k, bytes) else k): (
                            v.decode() if isinstance(v, bytes) else v
                        )
                        for k, v in fields.items()
                    }
                    messages.append(StreamMessage(message_id=msg_id, data=data))

                logger.info("认领 %s 条失活消息", len(messages))
        except RedisError as e:
            logger.error("认领失活消息失败: %s", e)

        return messages

    def get_length(self) -> int:
        """获取 Stream 中消息总数"""
        try:
            return get_redis_client().xlen(self._name)
        except RedisError:
            return 0

    def trim(self, max_len: Optional[int] = None) -> int:
        """裁剪 Stream（删除旧消息）"""
        try:
            return get_redis_client().xtrim(
                self._name, maxlen=max_len or self._max_len, approximate=True,
            )
        except RedisError:
            return 0


class DeadLetterQueue:
    """死信队列

    面试要点: 多次消费失败的消息移入死信队列，用于人工排查和补偿。
    这是企业级消息队列的标准组件。

    使用示例:
        dlq = DeadLetterQueue("order_events_dlq")

        def handle(msg):
            if random.random() < 0.1:
                return False  # 模拟 10% 失败率
            return True

        # 消费时自动将失败超过 3 次的消息移入 DLQ
        stream.consume_with_dlq("workers", "w1", handle, dlq, max_retries=3)
    """

    def __init__(self, stream_name: str):
        self._stream = RedisStream(f"dlq:{stream_name}", max_len=50000)

    def push(self, original_stream: str, msg: StreamMessage, error: str, retry_count: int):
        """将消息移入死信队列"""
        data = {
            **msg.data,
            "_dlq_original_stream": original_stream,
            "_dlq_original_id": msg.message_id,
            "_dlq_error": error,
            "_dlq_retry_count": str(retry_count),
            "_dlq_time": str(time.time()),
        }
        self._stream.add(data)

    def replay(self, target_stream: RedisStream, batch_size: int = 50) -> int:
        """重放死信队列中的消息到原 Stream（人工修复后调用）"""
        replayed = 0

        def _replay_handler(msg: StreamMessage) -> bool:
            nonlocal replayed
            original_data = {k: v for k, v in msg.data.items() if not k.startswith("_dlq_")}
            target_stream.add(original_data)
            replayed += 1
            return True

        self._stream.consume(
            "dlq_replayer", f"replayer-{uuid.uuid4().hex[:8]}",
            _replay_handler, batch_size=batch_size, block_ms=1000, run_forever=False,
        )
        return replayed
