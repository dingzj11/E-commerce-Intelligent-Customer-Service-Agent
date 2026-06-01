"""延迟队列模块

基于 Redis Sorted Set 实现可靠的延迟任务队列。

【原理】
- 使用 ZSET 的 score 存储任务执行时间戳
- 定时轮询 ZSET，将到期的任务取出并执行
- 配合分布式锁保证每个任务只被一个 worker 执行

【使用场景——本项目】
- 订单超时取消（下单 30 分钟后未支付自动取消）
- 售后审核超时提醒（48 小时未审核发通知）
- 物流投诉处理超时升级
- 延迟重试（发送失败后 5 分钟重试）

【面试对比：Redis ZSET vs RabbitMQ Delayed vs Scheduler】
┌─────────────┬──────────┬────────────┬──────────┐
│ 方案         │ 可靠性   │ 精度       │ 运维成本 │
├─────────────┼──────────┼────────────┼──────────┤
│ Redis ZSET   │ 中       │ 秒级       │ 低(已有) │
│ RabbitMQ Dlx │ 高       │ 秒级       │ 中       │
│ XXL-Job      │ 中       │ 秒级       │ 中       │
│ DB 轮询      │ 高       │ 分钟级     │ 低       │
└─────────────┴──────────┴────────────┴──────────┘
"""

import json
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from redis.exceptions import RedisError

from core.distributed_lock import DistributedLock
from core.redis_client import _make_key, get_redis_client, is_redis_available

logger = logging.getLogger("delay_queue")


class DelayQueue:
    """基于 Redis ZSET 的延迟队列

    使用示例:
        dq = DelayQueue("order_timeout")

        # 添加延迟任务：30 分钟后取消订单
        dq.add("cancel_order", {"order_id": "ORD123"}, delay_seconds=1800)

        # 消费者：处理到期任务
        def handle_cancel_order(data):
            cancel_order_in_db(data["order_id"])
            return True

        dq.register_handler("cancel_order", handle_cancel_order)
        dq.start_polling(poll_interval=1.0)  # 每秒轮询一次
    """

    def __init__(
        self,
        queue_name: str,
        max_retry_on_fail: int = 3,
        retry_delay_multiplier: int = 2,
    ):
        self._queue_key = _make_key(f"delay_queue:{queue_name}")
        self._handlers: Dict[str, Callable[[dict], bool]] = {}

        # 任务详情 Hash（key → 任务数据）
        self._task_data_prefix = f"delay_task:{queue_name}:"

        self._max_retry = max_retry_on_fail
        self._retry_delay_multiplier = retry_delay_multiplier
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def add(
        self,
        task_type: str,
        data: Dict[str, Any],
        delay_seconds: int = 0,
        execute_at: Optional[float] = None,
    ) -> Optional[str]:
        """添加延迟任务

        Args:
            task_type: 任务类型（用于路由到对应的 handler）
            data: 任务数据
            delay_seconds: 延迟秒数
            execute_at: 绝对执行时间戳（与 delay_seconds 二选一）

        Returns:
            任务 ID，失败返回 None

        面试要点: ZADD 的 score 可以是任意 double 值，
        我们用它存储执行时间戳（毫秒级精度），实现延迟功能。
        """
        task_id = f"task:{task_type}:{uuid.uuid4().hex[:16]}"

        if execute_at is None:
            execute_at = time.time() + delay_seconds

        task = {
            "id": task_id,
            "type": task_type,
            "data": data,
            "created_at": time.time(),
            "execute_at": execute_at,
            "retry_count": 0,
        }

        try:
            client = get_redis_client()
            # 任务详情存 Hash
            client.hset(
                _make_key(f"{self._task_data_prefix}{task_id}"),
                mapping={k: json.dumps(v, ensure_ascii=False) for k, v in task.items()},
            )
            client.expire(
                _make_key(f"{self._task_data_prefix}{task_id}"),
                int(execute_at - time.time()) + 86400,  # TTL = 延迟时间 + 1天
            )
            # 加入 ZSET，score 为执行时间
            client.zadd(self._queue_key, {task_id: execute_at})

            logger.debug("延迟任务已添加: %s (delay=%ss)", task_id, delay_seconds)
            return task_id
        except RedisError as e:
            logger.error("添加延迟任务失败: %s", e)
            return None

    def register_handler(self, task_type: str, handler: Callable[[dict], bool]):
        """注册任务处理器

        Args:
            task_type: 任务类型
            handler: 处理函数，接收任务 data dict，返回 True(成功) / False(失败需重试)
        """
        self._handlers[task_type] = handler

    def start_polling(self, poll_interval: float = 1.0):
        """开始轮询（后台线程）"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(poll_interval,),
            daemon=True,
            name=f"delay-queue-{self._queue_key.rsplit(':', 1)[-1]}",
        )
        self._thread.start()
        logger.info("延迟队列轮询启动: %s (interval=%ss)", self._queue_key, poll_interval)

    def stop_polling(self):
        """停止轮询"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _poll_loop(self, poll_interval: float):
        """轮询循环"""
        while self._running:
            try:
                self._process_due_tasks()
            except Exception as e:
                logger.error("延迟队列轮询异常: %s", e)
            time.sleep(poll_interval)

    def _process_due_tasks(self, batch_size: int = 20):
        """处理到期的任务

        核心逻辑: ZRANGEBYSCORE 取出 score <= now 的任务（即到期任务）
        """
        if not is_redis_available():
            return

        client = get_redis_client()
        now = time.time()

        # 原子操作：取出并删除到期的任务
        # 使用 Lua 脚本保证先取后删的原子性
        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local limit = tonumber(ARGV[2])
        local tasks = redis.call("ZRANGEBYSCORE", key, 0, now, "LIMIT", 0, limit)
        if #tasks > 0 then
            redis.call("ZREM", key, unpack(tasks))
        end
        return tasks
        """
        try:
            pop_tasks = client.register_script(lua_script)
            task_ids = pop_tasks(keys=[self._queue_key], args=[now, batch_size])
        except RedisError:
            return

        for task_id in task_ids:
            task_id_str = task_id.decode() if isinstance(task_id, bytes) else task_id
            self._execute_task(task_id_str)

    def _execute_task(self, task_id: str):
        """执行单个任务（带分布式锁 + 失败重试）"""
        lock = DistributedLock(f"delay_task:{task_id}", ttl=30)

        if not lock.acquire(blocking=False):
            return  # 其他 worker 正在处理

        try:
            task_raw = get_redis_client().hgetall(
                _make_key(f"{self._task_data_prefix}{task_id}")
            )
            if not task_raw:
                return

            task = {
                k.decode() if isinstance(k, bytes) else k: json.loads(
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in task_raw.items()
            }

            task_type = task["type"]
            handler = self._handlers.get(task_type)
            if handler is None:
                logger.warning("未注册的任务类型: %s (task=%s)", task_type, task_id)
                return

            try:
                success = handler(task["data"])
            except Exception as e:
                logger.error("任务执行异常: %s, err=%s", task_id, e)
                success = False

            if success:
                # 清理任务数据
                get_redis_client().delete(
                    _make_key(f"{self._task_data_prefix}{task_id}")
                )
                logger.debug("任务执行成功: %s", task_id)
            else:
                # 失败重试
                retry_count = task.get("retry_count", 0) + 1
                if retry_count < self._max_retry:
                    delay = 60 * (self._retry_delay_multiplier ** retry_count)
                    logger.warning("任务失败，%ss后第%s次重试: %s", delay, retry_count, task_id)
                    retry_task = dict(task)
                    retry_task["retry_count"] = retry_count
                    retry_task["last_error_time"] = time.time()
                    get_redis_client().hset(
                        _make_key(f"{self._task_data_prefix}{task_id}"),
                        mapping={k: json.dumps(v, ensure_ascii=False) for k, v in retry_task.items()},
                    )
                    get_redis_client().zadd(self._queue_key, {task_id: time.time() + delay})
                else:
                    logger.error("任务失败次数达到上限: %s", task_id)
                    # 移入死信（简化处理：标记为 failed）
                    get_redis_client().hset(
                        _make_key(f"{self._task_data_prefix}{task_id}"),
                        "status",
                        json.dumps("failed"),
                    )

        finally:
            lock.release()

    def get_pending_count(self) -> int:
        """获取待处理任务数"""
        try:
            return get_redis_client().zcard(self._queue_key)
        except RedisError:
            return 0

    def get_due_count(self) -> int:
        """获取已到期待处理的任务数"""
        try:
            return get_redis_client().zcount(self._queue_key, 0, time.time())
        except RedisError:
            return 0
