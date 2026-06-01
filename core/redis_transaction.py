"""分布式事务模块

基于 Redis 实现分布式事务的多种模式，解决跨服务数据一致性问题。

【核心模式】
1. Saga（编排型 + 协调型）：长事务拆分为多个本地事务，失败时补偿回滚
2. TCC（Try-Confirm-Cancel）：两阶段提交的变种，资源预留 + 确认/取消
3. 事务消息（Transactional Outbox）：先持久化消息，再异步执行
4. 基于 WATCH 的乐观锁事务：适用于竞争不激烈的场景

【面试核心——分布式事务方案对比】
┌──────────┬──────────┬────────────┬──────────┬──────────┐
│ 方案     │ 一致性   │ 性能       │ 复杂度   │ 适用场景 │
├──────────┼──────────┼────────────┼──────────┼──────────┤
│ 2PC      │ 强一致   │ 差(同步阻塞)│ 低      │ 单体→分布式过渡│
│ TCC      │ 最终一致 │ 好          │ 高(需实现3接口)│ 资金交易  │
│ Saga     │ 最终一致 │ 好          │ 中      │ 长流程业务│
│ 事务消息 │ 最终一致 │ 好          │ 中      │ 异步解耦  │
│ 本地消息表│ 最终一致 │ 好          │ 低      │ 通用      │
└──────────┴──────────┴────────────┴──────────┴──────────┘

【为什么不用 2PC？】
XA 协议的 2PC（两阶段提交）有严重的性能问题：
1. 同步阻塞：Prepare 阶段锁定资源，所有参与者必须等待协调者决策
2. 单点故障：协调者宕机，所有参与者无限等待（未收到 commit/rollback 指令）
3. 数据不一致：网络分区时，部分参与者收到 commit，部分未收到
因此在互联网高并发场景下，普遍使用 TCC 或 Saga 替代 2PC。
"""

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.redis_client import (
    _make_key,
    cache_delete,
    cache_get,
    cache_get_json,
    cache_set,
    cache_set_string,
    get_redis_client,
    is_redis_available,
)

logger = logging.getLogger("redis_transaction")


# ==================== TCC 分布式事务 ====================


class TccPhase(Enum):
    TRY = "try"           # 资源预留
    CONFIRM = "confirm"   # 确认提交
    CANCEL = "cancel"     # 补偿回滚


class TccStatus(Enum):
    INIT = "init"
    TRYING = "trying"
    TRY_SUCCEEDED = "try_succeeded"
    TRY_FAILED = "try_failed"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


@dataclass
class TccRecord:
    """TCC 事务记录（持久化到 Redis）"""
    txn_id: str
    status: str
    participants: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    timeout: int = 30  # 事务超时（秒）

    def to_dict(self) -> dict:
        return self.__dict__


class TccCoordinator:
    """TCC 事务协调者

    TCC 将二阶段提交的资源锁定变为"业务层面"的资源预留：
    - Try:   预留资源（冻结库存、冻结余额），判断是否可执行
    - Confirm: 使用预留的资源，真正执行（扣库存、转账）
    - Cancel:  释放预留的资源（解冻库存、退回余额）

    面试重点: TCC vs 2PC 的核心区别
    - 2PC 是数据库层面的事务，Prepare 后资源被锁定无法被其他事务使用
    - TCC 是业务层面，"预留"不影响其他操作（如冻结库存≠减库存）
    - TCC 需要开发者编写 Try/Confirm/Cancel 三个逻辑，复杂度更高但性能更好

    使用示例:
        coordinator = TccCoordinator()

        def try_create_order(txn_id, **params):
            # 冻结库存
            return atomic_deduct(f"stock:frozen:{sku_id}", quantity)

        def confirm_create_order(txn_id, **params):
            # 真正扣库存
            atomic_deduct(f"stock:real:{sku_id}", quantity)
            # 创建订单
            create_order_in_db(**params)

        def cancel_create_order(txn_id, **params):
            # 解冻库存
            cache_incr(f"stock:frozen:{sku_id}", quantity)

        coordinator.register("create_order", try_create_order,
                            confirm_create_order, cancel_create_order)

        ok = coordinator.execute("create_order", sku_id="SKU001", quantity=2)
    """

    def __init__(self, timeout: int = 30):
        self._participants: Dict[str, Tuple[Callable, Callable, Callable]] = {}
        self._timeout = timeout

    def register(
        self,
        name: str,
        try_fn: Callable[..., bool],
        confirm_fn: Callable[..., None],
        cancel_fn: Callable[..., None],
    ):
        """注册 TCC 参与者"""
        self._participants[name] = (try_fn, confirm_fn, cancel_fn)

    def execute(self, name: str, **params) -> Tuple[bool, str]:
        """执行 TCC 事务

        Returns:
            (True, txn_id) 成功
            (False, error_msg) 失败
        """
        if name not in self._participants:
            return False, f"未知的 TCC 参与者: {name}"

        txn_id = f"tcc:{name}:{uuid.uuid4().hex[:16]}"
        try_fn, confirm_fn, cancel_fn = self._participants[name]

        record = TccRecord(txn_id=txn_id, status=TccStatus.TRYING.value)
        cache_set(f"tcc_record:{txn_id}", record.to_dict(), ttl=self._timeout)

        # ===== Phase 1: Try =====
        logger.info("TCC[%s] Try 阶段开始", txn_id)
        try:
            success = try_fn(txn_id, **params)
        except Exception as e:
            logger.error("TCC[%s] Try 异常: %s", txn_id, e)
            success = False

        if not success:
            record.status = TccStatus.TRY_FAILED.value
            cache_set(f"tcc_record:{txn_id}", record.to_dict(), ttl=self._timeout)
            return False, "Try 阶段失败，事务终止"

        record.status = TccStatus.TRY_SUCCEEDED.value
        cache_set(f"tcc_record:{txn_id}", record.to_dict(), ttl=self._timeout)

        # ===== Phase 2: Confirm =====
        logger.info("TCC[%s] Confirm 阶段开始", txn_id)
        record.status = TccStatus.CONFIRMING.value
        cache_set(f"tcc_record:{txn_id}", record.to_dict(), ttl=self._timeout)

        try:
            confirm_fn(txn_id, **params)
            record.status = TccStatus.CONFIRMED.value
            cache_set(f"tcc_record:{txn_id}", record.to_dict(), ttl=self._timeout)
            logger.info("TCC[%s] 完成", txn_id)
            return True, txn_id
        except Exception as e:
            logger.error("TCC[%s] Confirm 失败，执行 Cancel 补偿", txn_id)
            record.status = TccStatus.CANCELLING.value
            cache_set(f"tcc_record:{txn_id}", record.to_dict(), ttl=self._timeout)

            try:
                cancel_fn(txn_id, **params)
                record.status = TccStatus.CANCELLED.value
                cache_set(f"tcc_record:{txn_id}", record.to_dict(), ttl=self._timeout)
            except Exception as cancel_err:
                logger.critical(
                    "TCC[%s] Cancel 也失败了！需要人工介入！err=%s", txn_id, cancel_err
                )
                return False, f"TCC Cancel 失败(需人工处理): {cancel_err}"

            return False, f"Confirm 失败，已通过 Cancel 补偿回滚"


# ==================== Saga 分布式事务 ====================


class SagaStepStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


@dataclass
class SagaStep:
    """Saga 事务步骤"""
    name: str
    execute: Callable[..., bool]
    compensate: Callable[..., None]
    status: SagaStepStatus = SagaStepStatus.PENDING


class SagaCoordinator:
    """Saga 事务协调者（编排型）

    Saga 将长事务拆分为多个有序的本地事务：
    - 每个本地事务有对应的补偿操作（语义回滚，不是数据库回滚）
    - 前一步成功 → 执行下一步
    - 某步失败 → 从当前步骤向前执行所有补偿操作

    面试重点:
    - 编排型(Orchestration)：有一个协调者告诉参与者做什么
    - 协同型(Choreography)：参与者之间通过事件互相通信，无中心协调者

    本项目使用编排型，因为流程清晰、易于监控和重试。

    使用示例:
        saga = SagaCoordinator("create_order_with_coupon")

        saga.add_step(
            "deduct_coupon",
            execute=lambda **p: deduct_coupon(p["coupon_id"]),
            compensate=lambda **p: restore_coupon(p["coupon_id"]),
        )
        saga.add_step(
            "deduct_stock",
            execute=lambda **p: deduct_stock(p["sku_id"], p["qty"]),
            compensate=lambda **p: restore_stock(p["sku_id"], p["qty"]),
        )
        saga.add_step(
            "create_order",
            execute=lambda **p: insert_order(p),
            compensate=lambda **p: delete_order(p["order_id"]),
        )

        ok, msg = saga.execute(coupon_id="C001", sku_id="S001", qty=2)
    """

    def __init__(self, saga_name: str, timeout: int = 60):
        self._name = saga_name
        self._steps: List[SagaStep] = []
        self._timeout = timeout
        self._executed_steps: List[SagaStep] = []

    def add_step(
        self,
        name: str,
        execute: Callable[..., bool],
        compensate: Callable[..., None],
    ):
        """添加 Saga 步骤"""
        self._steps.append(SagaStep(name=name, execute=execute, compensate=compensate))

    def execute(self, **params) -> Tuple[bool, str]:
        """执行 Saga 事务"""
        saga_id = f"saga:{self._name}:{uuid.uuid4().hex[:16]}"

        # 持久化 Saga 状态到 Redis
        saga_record = {
            "saga_id": saga_id,
            "name": self._name,
            "status": "running",
            "total_steps": len(self._steps),
        }
        cache_set(f"saga_record:{saga_id}", saga_record, ttl=self._timeout)

        # 正向执行
        for i, step in enumerate(self._steps):
            logger.info("Saga[%s] 步骤 %s/%s: %s", saga_id, i + 1, len(self._steps), step.name)
            step.status = SagaStepStatus.EXECUTING

            try:
                success = step.execute(**params)
            except Exception as e:
                logger.error("Saga[%s] 步骤 %s 执行异常: %s", saga_id, step.name, e)
                success = False

            if success:
                step.status = SagaStepStatus.SUCCEEDED
                self._executed_steps.append(step)
            else:
                step.status = SagaStepStatus.FAILED
                logger.warning("Saga[%s] 步骤 %s 失败，开始补偿回滚", saga_id, step.name)

                # 反向执行补偿
                compensation_error = self._compensate(saga_id, **params)

                saga_record["status"] = "compensated" if not compensation_error else "compensation_failed"
                cache_set(f"saga_record:{saga_id}", saga_record, ttl=self._timeout)

                return False, (
                    f"步骤 '{step.name}' 失败，已补偿回滚 {len(self._executed_steps)} 步"
                    + (f"（补偿异常: {compensation_error}）" if compensation_error else "")
                )

        saga_record["status"] = "completed"
        cache_set(f"saga_record:{saga_id}", saga_record, ttl=self._timeout)
        logger.info("Saga[%s] 完成", saga_id)
        return True, saga_id

    def _compensate(self, saga_id: str, **params) -> Optional[str]:
        """反向执行补偿"""
        for step in reversed(self._executed_steps):
            logger.info("Saga[%s] 补偿: %s", saga_id, step.name)
            step.status = SagaStepStatus.COMPENSATING
            try:
                step.compensate(**params)
                step.status = SagaStepStatus.COMPENSATED
            except Exception as e:
                logger.critical(
                    "Saga[%s] 补偿 %s 失败！需人工处理！%s", saga_id, step.name, e
                )
                return str(e)
        return None


# ==================== 事务消息（Transactional Outbox） ====================


class TransactionalOutbox:
    """事务消息发件箱模式

    面试要点：解决"数据库写入"和"消息发送"的原子性问题。
    如果先写 DB 再发消息，发消息失败会导致数据不一致。
    Outbox 模式：把消息和业务数据在同一个 DB 事务中写入 outbox 表，
    然后异步从 outbox 中读出并发送到消息队列。

    这里的实现使用 Redis List 作为轻量级 outbox（生产环境建议用 DB 表）。

    DB 事务:
        BEGIN;
        INSERT INTO orders (...);
        INSERT INTO outbox (event_type, payload) VALUES ('order_created', '...');
        COMMIT;

    使用示例:
        outbox = TransactionalOutbox()

        # 发布事件（在 DB 事务中调用）
        outbox.publish("order_created", {"order_id": "ORD123"})

        # 异步发送（后台任务）
        outbox.dispatch(lambda event_type, payload: send_to_mq(event_type, payload))
    """

    def __init__(self, outbox_key: str = "outbox:messages"):
        self._outbox_key = outbox_key

    def publish(self, event_type: str, payload: dict) -> bool:
        """发布事件到发件箱（幂等写入）"""
        message = json.dumps(
            {
                "id": uuid.uuid4().hex[:16],
                "event_type": event_type,
                "payload": payload,
                "created_at": time.time(),
            },
            ensure_ascii=False,
        )
        try:
            get_redis_client().rpush(_make_key(self._outbox_key), message)
            return True
        except RedisError:
            return False

    def dispatch(self, sender: Callable[[str, dict], bool], batch_size: int = 50) -> int:
        """从发件箱取出消息并发送（at-least-once 语义）"""
        client = get_redis_client()
        sent_count = 0

        for _ in range(batch_size):
            raw = client.lpop(_make_key(self._outbox_key))
            if raw is None:
                break

            try:
                msg = json.loads(raw)
                success = sender(msg["event_type"], msg["payload"])
                if success:
                    sent_count += 1
                else:
                    # 发送失败，放回队列尾部（简化版死信处理）
                    client.rpush(_make_key(self._outbox_key), raw)
                    logger.warning("事务消息发送失败，放回队列: %s", msg["id"])
                    break
            except Exception as e:
                logger.error("事务消息处理异常: %s", e)
                client.rpush(_make_key(self._outbox_key), raw)

        return sent_count


# ==================== 本地消息表（简化版） ====================


def create_local_message(
    event_type: str,
    payload: dict,
    max_retry: int = 3,
    expire: int = 86400,
) -> str:
    """创建本地消息（基于 Redis List + Hash）

    模式说明:
    1. 业务操作和消息写入在同一个 DB 事务中（保证原子性）
    2. 后台定时任务扫描未发送的消息
    3. 发送成功后标记为已发送
    4. 失败重试，超过最大次数标记为失败
    """
    msg_id = f"msg:{uuid.uuid4().hex[:16]}"
    message = {
        "id": msg_id,
        "event_type": event_type,
        "payload": json.dumps(payload, ensure_ascii=False),
        "status": "pending",
        "retry_count": 0,
        "max_retry": max_retry,
    }
    # 用 Hash 存消息详情，用 List 存待发送队列
    try:
        client = get_redis_client()
        client.hset(_make_key(msg_id), mapping=message)
        client.expire(_make_key(msg_id), expire)
        client.rpush(_make_key("local_messages:pending"), msg_id)
    except RedisError:
        pass
    return msg_id


def process_local_messages(sender: Callable[[str, dict], bool], limit: int = 20) -> int:
    """处理本地消息表中的待发送消息"""
    client = get_redis_client()
    processed = 0

    for _ in range(limit):
        msg_id_raw = client.lpop(_make_key("local_messages:pending"))
        if msg_id_raw is None:
            break

        msg_id = msg_id_raw.decode("utf-8") if isinstance(msg_id_raw, bytes) else msg_id_raw
        raw = client.hgetall(_make_key(msg_id))
        if not raw:
            continue

        msg = {k.decode("utf-8"): v.decode("utf-8") for k, v in raw.items()}
        payload = json.loads(msg["payload"])
        retry_count = int(msg.get("retry_count", 0))
        max_retry = int(msg.get("max_retry", 3))

        try:
            success = sender(msg["event_type"], payload)
        except Exception:
            success = False

        if success:
            client.hset(_make_key(msg_id), "status", "sent")
            processed += 1
        else:
            new_count = retry_count + 1
            if new_count <= max_retry:
                client.hset(_make_key(msg_id), "retry_count", str(new_count))
                client.rpush(_make_key("local_messages:pending"), msg_id)
            else:
                client.hset(_make_key(msg_id), "status", "failed")
                client.rpush(_make_key("local_messages:dead"), msg_id)
                logger.error("消息发送失败（超过最大重试）: %s", msg_id)

    return processed
