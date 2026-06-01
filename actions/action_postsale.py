from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet, ActionExecutionRejected
from rasa_sdk.executor import CollectingDispatcher

from uuid import uuid4
from .db import SessionLocal, get_session
from sqlalchemy import and_, or_
from datetime import datetime, timedelta
from .db_table_class import OrderDetail, Postsale, PostsaleReason
from core.distributed_lock import distributed_lock
from core.idempotency import idempotent


class AskOrderDetailIds(Action):
    """
    选择要进行售后的订单明细ID。注意以下要求：
    1、name()返回要与domain_postsale中的action名称一致
    """

    def name(self) -> str:
        return "action_ask_order_detail_ids"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        events = [] # 存储要返回的event

        # 1、从槽中获取订单ID
        order_id = tracker.get_slot("order_id")

        # 2、查询该订单没有售后记录或售后已完成的订单明细
        with SessionLocal() as session:
            order_details = (
                session.query(OrderDetail)
                .filter(
                    OrderDetail.order_id == order_id,
                    or_(
                        ~OrderDetail.postsale.any(),  # 没有关联的售后记录
                        and_(
                            OrderDetail.postsale.any(),  # 有售后记录
                            OrderDetail.postsale.any(
                                Postsale.complete_time != None
                            ),  # 所有售后都已完成
                        ),
                    ),
                )
                .all()
            )
        # 3、如果存在满足条件的订单明细，则返回订单明细信息
        if order_details:
            # 生成按钮
            buttons = [
                {
                    "title": f"{order_detail.order_detail_id} - \
                    {order_detail.sku_name} × {order_detail.sku_count} - \
                    {order_detail.total_amount}-{order_detail.discount_amount}={order_detail.final_amount}",
                    "payload": f"/SetSlots(order_detail_ids={order_detail.order_detail_id})",
                }
                for order_detail in order_details
            ]
            # 如果满足条件的订单明细数量大于1，则添加一个按钮，用于选择全部订单明细
            if len(order_details) > 1:
                buttons.append(
                    {
                        "title": "全部",
                        "payload": f"/SetSlots(order_detail_ids={'&'.join([order_detail.order_detail_id for order_detail in order_details])})",
                    }
                )
            # 添加取消按钮
            buttons.append(
                {"title": "取消", "payload": "/SetSlots(order_detail_ids=false)"}
            )
            # 发送按钮消息
            dispatcher.utter_message(text="请选择要申请售后的订单明细", buttons=buttons)
        # 4、如果不存在满足条件的订单明细，则返回提示信息，设置order_detail_ids为false，打断action_listen动作
        else:
            # 发送提示消息
            dispatcher.utter_message(text="没有可申请售后的订单明细")
            # 设置order_detail_ids为false
            events.append(SlotSet("order_detail_ids", "false"))
            # 打断action_listen动作
            events.append(ActionExecutionRejected("action_listen"))

        # 返回事件列表
        return events


class AskPostsaleReason(Action):
    """
    选择售后类型。注意以下要求：
    1、name()返回要与domain_postsale中的action名称一致
    """

    def name(self) -> str:
        return "action_ask_postsale_type"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # 1、 从槽中获取要售后的订单明细ID
        order_detail_ids = tracker.get_slot("order_detail_ids")
        order_detail_id = order_detail_ids.split("&")[0]

        # 2、 从数据库中获取订单明细信息
        with SessionLocal() as session:
            order_detail: OrderDetail = session.query(OrderDetail).get(order_detail_id)

        # 3、 展示订单明细信息，和售后类型的buttons
        dispatcher.utter_message(
            text=f"- {order_detail.order_detail_id}\
                    \n- {order_detail.sku_name} × {order_detail.sku_count}\
                    \n- {order_detail.total_amount}-{order_detail.discount_amount}={order_detail.final_amount}\
                    \n  请选择售后类型",
            buttons=[
                {"title": "退款", "payload": "/SetSlots(postsale_type=退款)"},
                {"title": "退货", "payload": " /SetSlots(postsale_type=退货)"},
                {"title": "换货", "payload": " /SetSlots(postsale_type=换货)"},
                {"title": "取消", "payload": " /SetSlots(postsale_type=false)"},
            ],
        )
        return []


class AskPostsaleReason(Action):
    """
    选择售后原因。注意以下要求：
    1、name()返回要与domain_postsale中的action名称一致
    """

    def name(self) -> str:
        return "action_ask_postsale_reason"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # 1、 从槽中获取要售后订单详情ID
        order_detail_ids = tracker.get_slot("order_detail_ids")
        order_detail_id = order_detail_ids.split("&")[0]

        # 2、 从数据库中获取该商品对应类别和无类别的售后原因
        with SessionLocal() as session:
            # 获取该订单详情
            order_detail: OrderDetail = session.query(OrderDetail).get(order_detail_id)
            # 获取该订单详情的商品类别
            product_category = order_detail.sku.product_category # 获取商品类别
            # 从售后原因表中获取该商品类别对应的售后原因和没有类别对应的售后原因
            postsale_reasons = (
                session.query(PostsaleReason)
                .filter(
                    or_(
                        PostsaleReason.product_category.is_(None), # 售后原因表的商品类别为空
                        PostsaleReason.product_category
                        == product_category.product_category, # 售后原因表的类别存在该商品的类别
                    ),
                )
                .all()
            )
        # 3、生成售后信息原因选项的buttons，并添加"其他"和"取消"
        buttons = [
            {
                "title": postsale_reason.postsale_reason,
                "payload": f"/SetSlots(postsale_reason={postsale_reason.postsale_reason})",
            }
            for postsale_reason in postsale_reasons
        ] + [
            {"title": "其他", "payload": " /SetSlots(postsale_reason=other)"},
            {"title": "取消", "payload": " /SetSlots(postsale_reason=false)"},
        ]

        # 4、发送该订单明细信息，并给出售后原因列表buttons
        dispatcher.utter_message(
            text=f"- {order_detail.order_detail_id}\
                    \n- {order_detail.sku_name} × {order_detail.sku_count}\
                    \n- {order_detail.total_amount}-{order_detail.discount_amount}={order_detail.final_amount}\
                    \n  请选择售后原因",
            buttons=buttons,
        )
        return []


class CommitPostsale(Action):
    """Submit after-sale request with distributed lock and idempotency protection."""

    def name(self) -> str:
        return "action_commit_postsale"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # 1、从槽中获取要售后的订单详情ID、售后原因、售后类型
        order_detail_ids = tracker.get_slot("order_detail_ids")
        order_detail_id = order_detail_ids.split("&")[0]
        postsale_reason = tracker.get_slot("postsale_reason")
        postsale_type = tracker.get_slot("postsale_type")
        user_id = tracker.get_slot("user_id")

        # 2、分布式锁 + 幂等保护
        lock = distributed_lock(f"postsale:{order_detail_id}", ttl=15)
        try:
            with lock.guard():
                return self._do_commit(
                    dispatcher, order_detail_ids, order_detail_id,
                    postsale_reason, postsale_type, tracker
                )
        except Exception as e:
            import logging
            logging.getLogger("action_postsale").warning(
                "售后提交失败 (并发冲突): %s", e
            )
            dispatcher.utter_message(
                text="该订单明细正在处理中，请勿重复提交售后申请"
            )
            return []

    def _do_commit(
        self, dispatcher, order_detail_ids, order_detail_id,
        postsale_reason, postsale_type, tracker
    ):
        """实际的售后提交逻辑（在锁保护下执行）"""
        import logging
        logger = logging.getLogger("action_postsale")

        # 构造售后信息对象
        postsale = Postsale(
            postsale_id="pts" + uuid4().hex[:16],
            create_time=datetime.now(),
            order_detail_id=order_detail_id,
            postsale_reason=postsale_reason,
            postsale_status="审核中",
            receive_id=None,
            complete_time=None,
            refund_amount=None,
            postsale_type=postsale_type,
        )

        with get_session() as session:
            # 查询订单详情
            order_detail: OrderDetail = session.query(OrderDetail).get(order_detail_id)

            # 重复提交检查：检查是否已有进行中的售后记录
            existing_active = (
                session.query(Postsale)
                .filter(
                    Postsale.order_detail_id == order_detail_id,
                    Postsale.complete_time.is_(None),
                )
                .first()
            )
            if existing_active:
                dispatcher.utter_message(
                    text=f"该订单明细已有进行中的售后申请（售后ID: {existing_active.postsale_id}），请勿重复提交"
                )
                return []

            # 设置售后单的收货信息为订单的收货信息
            postsale.receive_id = order_detail.order.receive_id
            # 设置售后单的退款金额
            postsale.refund_amount = (
                None if postsale_type == "换货" else order_detail.final_amount
            )

            # 7天无理由退换货自动审核
            if (
                postsale_reason == "不喜欢/不想要了"
                and datetime.now() - order_detail.order.delivered_time
                < timedelta(days=7)
                and order_detail.total_amount < 100
                and postsale_type in ["退货", "换货"]
            ):
                postsale.postsale_status = (
                    "退货中" if postsale_type == "退货" else "换退货"
                )
                dispatcher.utter_message(
                    text=f"满足7天退换货条件，系统将自动为您安排{postsale_type}"
                )
            else:
                if postsale_reason == "other":
                    postsale.postsale_reason = tracker.latest_message["text"]
                dispatcher.utter_message(
                    text=f"您的{postsale_type}申请已提交，审核结果将在48小时内通知您"
                )
            # 添加售后记录
            session.add(postsale)
            # commit 在 with get_session() 内自动执行

            logger.info(
                "售后申请已提交: postsale_id=%s, order_detail_id=%s, type=%s",
                postsale.postsale_id, order_detail_id, postsale_type
            )

        # 设置售后的订单详情id到slot中（移除处理过的第一个详情id）
        return [SlotSet("order_detail_ids", "&".join(order_detail_ids.split("&")[1:]))]
