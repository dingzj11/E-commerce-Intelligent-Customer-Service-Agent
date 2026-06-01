from datetime import datetime
from typing import Any, Text, Dict, List

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher
from sqlalchemy.orm import joinedload

from actions.db import SessionLocal
from actions.db_table_class import LogisticsCompany, OrderInfo, Logistics, LogisticsComplaint, LogisticsComplaintsRecord
from core.cache_decorator import cacheable


class GetLogisticsCompanys(Action):
    """
    查询数据库，获取支持的快递公司列表
    使用 Redis 缓存减少数据库查询
    """
    def name(self) -> Text:
        return "action_get_logistics_companys"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        # 带缓存的查询
        logistics_companys = self._get_companies()

        # 封装返回的数据格式
        message = ["支持的快递有:"]
        message.extend([f"- {i}" for i in logistics_companys])

        dispatcher.utter_message(text="\n".join(message))
        return []

    @cacheable(ttl=86400, key_prefix="logistics:companies")
    def _get_companies(self):
        """获取快递公司列表（缓存 24 小时）"""
        with SessionLocal() as session:
            companies = session.query(LogisticsCompany).all()
        return [c.company_name for c in companies]


class GetLogisticsInfo(Action):
    """
    根据指定的订单id，查询详细的物流信息
    """
    def name(self) -> Text:
        return "action_get_logistics_info"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        # 1、从槽中获取指定的订单id
        order_id = tracker.get_slot("order_id")
        # 2、查询mysql中的物流信息、订单明细，关联订单表、物流表、订单明细表
        with SessionLocal() as session:
            order_info = (
                session.query(OrderInfo)
                .options(joinedload(OrderInfo.logistics))
                .options(joinedload(OrderInfo.order_detail))
                .filter_by(order_id=order_id)
                .first()
            )
        # 3、按要求封装返回的消息
        logistics = order_info.logistics[0] # 一个订单，只有一个物流，返回的是list，直接取0即可
        message = [f"- **订单ID**：{order_id}"]
        message.extend(
            [
                f"  - {order_detail.sku_name} × {order_detail.sku_count}"
                for order_detail in order_info.order_detail
            ]
        )
        message.append(f"- **物流ID**：{logistics.logistics_id}")
        message.append("- **物流信息**：")
        message.append("  - " + "\n  - ".join(logistics.logistics_tracking.split("\n")))

        # 4、返回封装的数据格式给用户
        dispatcher.utter_message("\n".join(message))

        # 5、将物流ID保存到slot中，方便其他流程使用
        return [SlotSet("logistics_id", logistics.logistics_id)]



class AskLogisticsComplaint(Action):
    """
    查询数据库中常见的投诉原因，返回多个button给用户选择
    """
    def name(self) -> Text:
        return "action_ask_logistics_complaint"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        # 1、查询指定物流id对应的物流信息
        logistics_id = tracker.get_slot("logistics_id")

        with SessionLocal() as session:
            logistics = (
                session.query(Logistics)
                .filter_by(logistics_id=logistics_id)
                .first()
            )

        # 2、判断当前物流是处于 已发货、还是已签收状态，通过 delivered_time字段判断
        status = "已发货" if logistics.delivered_time is None else "已签收"

        # 3、查询 logistics_complaint 表，获取常见投诉原因
        with SessionLocal() as session:
            logistics_complaints = (
                session.query(LogisticsComplaint)
                .filter_by(logistics_status = status)
                .all()
            )

        # 4、封装返回的信息和buttons
        buttons = [
            {
                "title": i.logistics_complaint,
                "payload": f"/SetSlots(logistics_complaint={i.logistics_complaint})"
            }
            for i in logistics_complaints
        ]
        # 添加"其他"和"取消投诉"的button
        buttons.append(
            {
                "title": "其他",
                "payload": "/SetSlots(logistics_complaint=other)"
            }
        )
        buttons.append(
            {
                "title": "取消投诉",
                "payload": "/SetSlots(logistics_complaint=false)"
            }
        )

        # 5、发送结果
        dispatcher.utter_button_message(
            text="请选择要反馈的问题：",
            buttons=buttons
        )

        return []



class RecordLogisticsComplaint(Action):
    """
    保存用户的投诉物流id、投诉原因 到mysql中
    """
    def name(self) -> Text:
        return "action_record_logistics_complaint"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        events =[]
        # 1、从槽中获取投诉的物流ID和投诉内容
        logistics_id = tracker.get_slot("logistics_id")
        logistics_complaint = tracker.get_slot("logistics_complaint")

        # 2、如果投诉内容为其他，从最新消息中获取
        if logistics_complaint == "other":
            # 2.1 通过tracker获取最新消息的text
            logistics_complaint = tracker.latest_message["text"]
            # 2.2 将投诉内容存入槽logistics_complaint中
            events.append(SlotSet("logistics_complaint", logistics_complaint))

        # 3、构造写入 logistics_complaints_record 表的数据
        with SessionLocal() as session:
            session.add(
                LogisticsComplaintsRecord(
                    logistics_id=logistics_id,
                    logistics_complaint=logistics_complaint,
                    complaint_time=datetime.now(),
                    user_id=tracker.get_slot("user_id"),
                )
            )
            # 4、执行写入
            session.commit()

        # 5、给用户返回消息
        dispatcher.utter_message(text="您的投诉已经收到，我们会尽快处理。")

        return events

