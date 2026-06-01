from datetime import datetime, timedelta
from typing import Any, Text, Dict, List
from uuid import uuid4

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet, ActionExecutionRejected
from rasa_sdk.executor import CollectingDispatcher
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload

from actions.db import SessionLocal, get_session
from actions.db_table_class import OrderInfo, Postsale, ReceiveInfo, Region, OrderStatus
from core.distributed_lock import distributed_lock
from core.cache_decorator import cacheable, cache_evict
from core.rate_limiter import get_rate_limiter


class AskOrderID(Action):
    """
    查询订单ID，返回一个button列表给用户选择
    """

    def name(self) -> Text:
        return "action_ask_order_id"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        event = []

        # 1、查询mysql中的订单相关的表，包括：订单表、订单状态表、订单明细表
        with SessionLocal() as session:
            order_infos = (
                session.query(OrderInfo)
                .join(OrderInfo.order_status_)  # 关联订单状态表
                .options(joinedload(OrderInfo.order_detail))  # 预加载 order_detail
                # 这个action是通用的一个action
                # 不同的功能需求，对应不同的过滤条件
                # 通过 槽 goto 的值，决定 封装的过滤条件
                # 封装一个函数来处理过滤条件
                .filter(self.get_query_condition(tracker))
                .all()
            )

        # 2、根据查询的订单数量，分不同方式返回给用户
        order_num = len(order_infos)
        # 2.1 如果订单数量=1，直接给用户选择"是"/"否"
        if order_num == 1:
            order_info = order_infos[0]  # 结果是一个list，即使只有一条数据，也是list
            dispatcher.utter_message(
                text=f"您有一笔订单，订单ID为：{order_info.order_id}，是否查询？",
                buttons=[
                    {
                        "title": "是",
                        "payload": f"/SetSlots(order_id={order_info.order_id})",
                    },
                    {"title": "否", "payload": "/SetSlots(order_id=false)"},
                ],
            )

        # 2.2 如果订单数量>1，则返回一个button列表给用户选择，按钮的title为订单信息，payload为SetSlots(order_id=订单ID)
        elif order_num > 1:
            buttons = [
                {
                    "title": "\n".join(
                        [f"[{order_info.order_status}]订单ID：{order_info.order_id}"]
                        +
                        [
                            f"- {order_detail.sku_name} × {order_detail.sku_count}"
                            for order_detail in order_info.order_detail
                        ]
                    ),
                    "payload": f"/SetSlots(order_id={order_info.order_id})"
                }
                for order_info in order_infos
            ]
            # 添加一个"返回"按钮
            buttons.append(
                {
                    "title": "返回",
                    "payload": "/SetSlots(order_id='false')"
                }
            )
            dispatcher.utter_message(text="请选择订单",buttons=buttons)
        # 2.3 如果订单数量=0，直接返回消息，告知用户订单不存在。槽order_id=false，打断action_listen动作
        else:
            dispatcher.utter_message(text="未查询到订单")
            event.append(SlotSet("order_id", "false"))
            # 打断action_listen动作
            event.append(ActionExecutionRejected("action_listen"))
        return event

    def get_query_condition(self, tracker):
        # 获取槽 用户id、goto
        user_id = tracker.get_slot("user_id")
        goto = tracker.get_slot("goto")

        # 根据 goto的值，封装不同的过滤条件
        match goto:
            case "action_ask_order_id_shipped":
                # 查询已发货的订单
                return and_(
                    OrderInfo.user_id == user_id,
                    OrderInfo.order_status == "已发货",
                )
            case "action_ask_order_id_shipped_delivered":
                # 查询 已发货、已签收 的订单
                return and_(
                    OrderInfo.user_id == user_id,
                    OrderInfo.order_status.in_(["已发货", "已签收"]),
                )
            case "action_ask_order_id_before_completed_3_days":
                # 查询进行中，或3日内已完成的订单
                return and_(
                    OrderInfo.user_id == user_id,
                    OrderInfo.order_status != "已取消",
                    or_(
                        OrderInfo.order_status != "已完成",
                        OrderInfo.complete_time > datetime.now() - timedelta(days=3),
                    ),
                )
            case "action_ask_order_id_before_delivered":
                # 查询已签收之前状态的订单
                return and_(
                    OrderInfo.user_id == user_id,
                    OrderInfo.order_status != "已取消",
                    OrderStatus.status_code <= 320,
                )
            case "action_ask_order_id_before_shipped":
                # 查询已发货之前状态的订单
                return and_(
                    OrderInfo.user_id == user_id,
                    OrderInfo.order_status != "已取消",
                    OrderStatus.status_code <= 310,
                )
            case "action_ask_order_id_after_delivered":
                # 查询已签收、售后中、已完成的订单
                return and_(
                    OrderInfo.user_id == user_id,
                    OrderInfo.order_status != "已取消",
                    OrderStatus.status_code >= 330,
                )

class GetOrderDetail(Action):
    """
    获取订单详情，注意以下要求：
    1、name()返回要与domain_order中的action名称一致
    """

    def name(self) -> str:
        return "action_get_order_detail"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:

        # 1、根据槽"order_id"获取订单ID
        # 1.1 获取槽"order_id"的值
        order_id = tracker.get_slot("order_id")
        # 1.2 从数据库中查询订单与订单明细、物流、售后等信息，使用joinedload加载相关联的表：order_detail、logistics、receive、order_status_
        with SessionLocal() as session:
            order_info = (
                session.query(OrderInfo)
                .options(joinedload(OrderInfo.order_detail))
                .options(joinedload(OrderInfo.logistics))
                .options(joinedload(OrderInfo.receive))
                .options(joinedload(OrderInfo.order_status_))
                .filter_by(order_id=order_id)
                .first()
            )

        # 2、拼接要返回的信息
        # 2.1 拼接订单信息，标题：订单转态、订单ID，内容：创建时间、支付时间、签收时间、完成时间
        message = [f"- [{order_info.order_status}]**订单ID**：{order_info.order_id}"]
        # 遍历订单时间信息字典，只添加非空的时间字段到消息中
        for k, v in {
            "创建时间": order_info.create_time,
            "支付时间": order_info.payment_time,
            "签收时间": order_info.delivered_time,
            "完成时间": order_info.complete_time,
        }.items():
            # 如果时间字段不为空，则格式化并添加到消息列表中
            if v:
                message.append(f"  - {k}：{v}")
        # 拼接订单明细信息，标题：**订单明细**
        message.append("- **订单明细**：")
        total_total_amount = 0.0  # 订单总金额
        total_discount_amount = 0.0 # 订单优惠金额
        total_final_amount = 0.0 # 订单实付金额
        # 遍历订单明细
        for order_detail in order_info.order_detail:
            # 添加每条订单明细信息，内容：商品名称 × 数量 | 订单金额 - 优惠金额 = 实付金额
            message.append(
                f"  - {order_detail.sku_name} × {order_detail.sku_count} | \
                {order_detail.total_amount}-{order_detail.discount_amount}={order_detail.final_amount}"
            )
            # 计算整个订单的总金额、优惠金额、实付金额
            total_total_amount += float(order_detail.total_amount)
            total_discount_amount += float(order_detail.discount_amount)
            total_final_amount += float(order_detail.final_amount)
        # 添加订单金额合计，内容为：订单总金额 - 优惠总金额 = 实付总金额
        message.append(
            f"  - **合计**：{total_total_amount}-{total_discount_amount}={total_final_amount}"
        )
        # 2.2 拼接收货信息，标题：收货信息，内容：收货人、联系电话、收货地址（省、市、区县、街道详细地址）
        message.extend(
            [
                "- **收货信息**：",
                f"  - 收货人：{order_info.receive.receiver_name}",
                f"  - 联系电话：{order_info.receive.receiver_phone}",
                f"  - 收货地址：{order_info.receive.receive_province}\
                {order_info.receive.receive_city}\
                {order_info.receive.receive_district}\
                {order_info.receive.receive_street_address}",
            ]
        )
        # 2.3 拼接最近物流信息，标题：最近物流信息，内容：物流信息
        logistics = order_info.logistics
        if logistics:
            message.append("- **最近物流信息**：")
            # 对logistics表的logistics_tracking字段取最后一条信息
            message.append(f"  - {logistics[0].logistics_tracking.splitlines()[-1]}")

        # 3、发送拼接结果的message给用户
        dispatcher.utter_message(text="\n".join(message))

        # 4、判断订单是否有售后信息，如果有，则发送售后信息给用户，没有就直接return
        # 4.1 status_code < 400说明不处于售后中，直接 return
        if order_info.order_status_.status_code < 400:
            return []
        # 4.2 有售后信息，发送售后信息
        # 售后表是按照订单详情ID的粒度存储
        # 同一个订单详情，可能有多个售后记录（多次退换货）
        # 每一个售后记录，可能有多条物流信息（纯退货1条物流，退换货2条）

        # 获取所有订单明细ID：
        order_detail_ids = [
            order_detail.order_detail_id for order_detail in order_info.order_detail
        ]
        # 查询每个订单明细最新的售后信息
        with SessionLocal() as session:
            # 子查询：postsale 按 order_detail_id 分组，取最大的 postsale.create_time
            # 因为每个订单详情，可能有多次退换货情况，所以同一个订单详情，可能有多条售后信息，子查询为了找到每个订单详情的最新售后数据
            subquery = (
                session.query(
                    Postsale.order_detail_id,
                    func.max(Postsale.create_time).label("max_time"),
                )
                .filter(Postsale.order_detail_id.in_(order_detail_ids))
                .group_by(Postsale.order_detail_id)
                .subquery()
            )
            # 主查询：通过 order_detail_id 和 create_time 与子查询关联，获取最新的售后记录
            # 其中 c 是 SQLAlchemy 中 subquery 的列属性访问器，用于访问子查询中的列
            postsales = (
                session.query(Postsale)
                .join(
                    subquery,
                    and_(
                        Postsale.order_detail_id == subquery.c.order_detail_id,
                        Postsale.create_time == subquery.c.max_time,
                    ),
                )
                .options(joinedload(Postsale.order_detail)) # 关联 订单详情
                .options(joinedload(Postsale.logistics))    # 关联 物流
                .all()
            )
        # 如果关联后没有售后信息，直接 return
        if not postsales:
            return []
        # 拼接售后信息，遍历postsales
        # 一个详情，一条最新售后，可能有多条物流（退换货2条）
        for postsale in postsales:
            # 拼接标题：订单状态、售后ID
            message = [
                f"- [{postsale.postsale_status}]**售后ID**：{postsale.postsale_id}"
            ]
            # 拼接标题：订单明细
            message.append("- **订单明细**：")
            # 拼接订单明细内容：商品sku名称 × 商品数量
            message.append(
                f"  -{postsale.order_detail.sku_name} × {postsale.order_detail.sku_count}"
            )
            # 拼接退款金额：退款金额：refund_amount
            message.append(f"- **退款金额**：{postsale.refund_amount}")
            # 获取最新的物流信息
            if postsale.logistics:
                # 按物流数据的创建时间倒序。因为如果是换货，会有两条物流数据，一条是换货退货，一条是换货发货
                postsale.logistics = sorted(
                    postsale.logistics, key=lambda x: x.create_time, reverse=True
                )
                # 拼接标题：最新物流信息
                message.append("- **最近物流信息**：")
                # 拼接最新物流信息
                message.append(
                    # 前面已经排序，取索引0即最新的物流信息。然后切分该条物流的tracking，取最后一个信息
                    f"  - {postsale.logistics[0].logistics_tracking.splitlines()[-1]}"
                )
            # 发送拼接好的售后信息
            dispatcher.utter_message(text="\n".join(message))
        return []

class AskReceiveId(Action):
    """
    查询数据库中现有的收货信息，buttons展示给用户选择，包括"修改并新建收货信息"选项。注意以下要求：
    1、name()返回要与domain_order中的action名称一致
    """

    def name(self) -> str:
        return "action_ask_receive_id"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # 1、从槽中获取用户ID和订单ID
        user_id = tracker.get_slot("user_id")
        order_id = tracker.get_slot("order_id")

        # 2、查询用户的所有收货信息、当前订单的收货信息
        # 2.1 根据当前user_id,查询 ReceiveInfo表,获取用户现有收货信息
        with SessionLocal() as session:
            receive_infos = session.query(ReceiveInfo).filter_by(user_id=user_id).all()
            # 2.2 查询当前订单的收货信息
            current_receive_info = (
                session.query(OrderInfo).filter_by(order_id=order_id).first().receive
            )
        buttons = []

        # 3、遍历收货信息，生成按钮
        for receive_info in receive_infos:
            buttons.append(
                {
                    "title": f"收货人姓名：{receive_info.receiver_name} - \
                    联系电话：{receive_info.receiver_phone} - \
                    收货地址：{receive_info.receive_province}\
                    {receive_info.receive_city}\
                    {receive_info.receive_district}\
                    {receive_info.receive_street_address}",
                    "payload": f"/SetSlots(receive_id={receive_info.receive_id})",
                }
            )

        # 4、添加"修改并新建收货信息"的button
        buttons.extend(
            [
                {
                    "title": "修改并新建收货信息",
                    "payload": f"/SetSlots(receive_id=modify)",
                },
                {"title": "取消", "payload": f"/SetSlots(receive_id=false)"},
            ]
        )

        # 5、发送 buttons给用户选择
        dispatcher.utter_message(
            text="请选择现有的收货信息，或修改并新建收货信息", buttons=buttons
        )

        # 6、更新槽值，将当前订单的收货信息更新到对应的槽中
        return [
            SlotSet("receiver_name", current_receive_info.receiver_name),
            SlotSet("receiver_phone", current_receive_info.receiver_phone),
            SlotSet("receive_province", current_receive_info.receive_province),
            SlotSet("receive_city", current_receive_info.receive_city),
            SlotSet("receive_district", current_receive_info.receive_district),
            SlotSet(
                "receive_street_address", current_receive_info.receive_street_address
            ),
        ]


class AskReceiveProvince(Action):
    """
    询问收货省。注意以下要求：
    1、name()返回要与domain_order中的action名称一致
    2、使用 Redis 缓存地区数据，减少数据库查询
    """

    def name(self) -> str:
        return "action_ask_receive_province"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # 带缓存的查询
        provinces = self._get_provinces()

        # 根据得到的省份信息，构造按钮列表
        buttons = [
            {
                "title": province,
                "payload": f"/SetSlots(receive_province={province})",
            }
            for province in provinces
        ]
        # 发送按钮列表给用户
        dispatcher.utter_message(text="请选择省份", buttons=buttons)
        return []

    @cacheable(ttl=86400, key_prefix="regions:provinces")
    def _get_provinces(self):
        """获取省份列表（缓存 24 小时）"""
        with SessionLocal() as session:
            provinces = session.query(Region.province).distinct().all()
        return [p[0] for p in provinces]


class AskReceiveCity(Action):
    """
    询问收货市。注意以下要求：
    1、name()返回要与domain_order中的action名称一致
    """

    def name(self) -> str:
        return "action_ask_receive_city"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # 1、从槽中获取省份
        receive_province = tracker.get_slot("receive_province")

        # 2、从数据库中获取该省份下的市
        with SessionLocal() as session:
            cities = (
                session.query(Region.city)
                .filter(Region.province == receive_province)
                .distinct()
                .all()
            )

        # 3、将市的元组列表转换为按钮列表
        buttons = [
            {"title": city[0], "payload": f"/SetSlots(receive_city={city[0]})"}
            for city in cities
        ]

        # 4、发送按钮列表
        dispatcher.utter_message(text="请选择城市", buttons=buttons)
        return []


class AskReceiveDistrict(Action):
    """
    询问收货区。注意以下要求：
    1、name()返回要与domain_order中的action名称一致
    """

    def name(self) -> str:
        return "action_ask_receive_district"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # 1、从槽中获取收货市
        receive_city = tracker.get_slot("receive_city")

        # 2、从数据库中获取该市下的收货区
        with SessionLocal() as session:
            districts = (
                session.query(Region.district)
                .filter(Region.city == receive_city)
                .distinct()
                .all()
            )

        # 3、构造按钮列表
        buttons = [
            {
                "title": district[0],
                "payload": f"/SetSlots(receive_district={district[0]})",
            }
            for district in districts
        ]

        # 4、发送按钮列表
        dispatcher.utter_message(text="请选择城区", buttons=buttons)
        return []


class AskSetReceiveInfo(Action):
    """
    设置收货信息。注意以下要求：
    1、name()返回要与domain_order中的action名称一致
    """

    def name(self) -> str:
        return "action_ask_set_receive_info"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # 1、从槽中获取 receive_id 和 set_receive_info
        receive_id = tracker.get_slot("receive_id")
        set_receive_info = tracker.get_slot("set_receive_info")

        # 2、根据收货id，获取收货信息
        # 2.1 如果receive_id为"修改"或"已修改"，获取slot中的收货信息
        if receive_id in ("modify", "modified"):
            # 2.1、从槽中获取收货信息
            receive_info = ReceiveInfo(
                receive_id="rec" + uuid4().hex[:16],
                user_id=tracker.get_slot("user_id"),
                receiver_name=tracker.get_slot("receiver_name"),
                receiver_phone=tracker.get_slot("receiver_phone"),
                receive_province=tracker.get_slot("receive_province"),
                receive_city=tracker.get_slot("receive_city"),
                receive_district=tracker.get_slot("receive_district"),
                receive_street_address=tracker.get_slot("receive_street_address"),
            )
        # 2.2 如果receive_id不是修改，从数据库中查询对应收货信息
        else:
            with SessionLocal() as session:
                receive_info = (
                    session.query(ReceiveInfo).filter_by(receive_id=receive_id).first()
                )

        # 3、如果确认修改，进行修改(第二次执行该action，也就是用户选择了"确认修改"，才能进来)
        if set_receive_info:
            # 获取指定order_id的订单信息
            order_id = tracker.get_slot("order_id")
            with SessionLocal() as session:
                order_info = (
                    session.query(OrderInfo).filter_by(order_id=order_id).first()
                )
                # 如果没有使用已有的收货信息，向数据库中添加新的收货信息
                if receive_id in ("modify", "modified"):
                    # 查询收货信息是否已存在
                    old_receive_info = (
                        session.query(ReceiveInfo)
                        .filter(
                            ReceiveInfo.user_id == receive_info.user_id,
                            ReceiveInfo.receiver_name == receive_info.receiver_name,
                            ReceiveInfo.receiver_phone == receive_info.receiver_phone,
                            ReceiveInfo.receive_province
                            == receive_info.receive_province,
                            ReceiveInfo.receive_city == receive_info.receive_city,
                            ReceiveInfo.receive_district
                            == receive_info.receive_district,
                            ReceiveInfo.receive_street_address
                            == receive_info.receive_street_address,
                        )
                        .first()
                    )
                    # old_receive_info不为空，则收货信息已存在
                    if old_receive_info:
                        receive_info = old_receive_info
                        dispatcher.utter_message(
                            text="此收货信息已存在，将不再重复添加"
                        )
                    # old_receive_info为空，则添加新收货信息
                    else:
                        session.add(receive_info)
                        session.flush()

                # 更新订单的收货信息
                order_info.receive_id = receive_info.receive_id
                # 提交事务
                session.commit()
            # 返回结果
            dispatcher.utter_message(text="订单收货信息已修改")
        # 初次执行，展示收货信息，询问是否确认修改
        else:
            # 拼接展示的收货信息
            message = [
                f"- 收货人姓名：{receive_info.receiver_name}",
                f"- 联系电话：{receive_info.receiver_phone}",
                f"- 收货省份：{receive_info.receive_province}",
                f"- 收货城市：{receive_info.receive_city}",
                f"- 收货城区：{receive_info.receive_district}",
                f"- 收货地址：{receive_info.receive_street_address}",
            ]
            # 发送收货信息
            dispatcher.utter_message(text="\n".join(message))
            # 发送确认的button
            dispatcher.utter_message(
                text="是否确认修改？",
                buttons=[
                    {"title": "确认", "payload": "/SetSlots(set_receive_info=true)"},
                    {"title": "取消", "payload": "/SetSlots(set_receive_info=false)"},
                ],
            )
        return []

class CancelOrder(Action):
    """
    取消订单。注意以下要求：
    1、name()返回要与domain_order中的action名称一致
    2、使用分布式锁防止并发取消同一订单
    3、Redis不可用时降级为本地模式
    """

    def name(self) -> str:
        return "action_cancel_order"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # 1、从槽中获取订单ID
        order_id = tracker.get_slot("order_id")

        # 2、获取分布式锁，防止并发取消同一订单
        lock = distributed_lock(f"cancel_order:{order_id}", ttl=10)
        try:
            with lock.guard():
                return self._do_cancel(dispatcher, order_id)
        except Exception as e:
            # 锁获取失败——资源正在被其他实例处理
            dispatcher.utter_message(
                text="该订单正在被其他操作处理中，请稍后重试"
            )
            return []

    def _do_cancel(self, dispatcher, order_id):
        """实际的取消逻辑（在锁保护下执行）"""
        import logging
        logger = logging.getLogger("action_order")

        with get_session() as session:
            order_info = session.query(OrderInfo).filter_by(order_id=order_id).first()

            if order_info is None:
                dispatcher.utter_message(text="订单不存在")
                return []

            # 二次校验：只能取消待支付或待发货的订单
            if order_info.order_status not in ("待支付", "待发货"):
                dispatcher.utter_message(
                    text=f"订单当前状态为「{order_info.order_status}」，无法取消"
                )
                return []

            # 获取当前订单状态
            old_order_status = order_info.order_status
            # 更新订单状态为已取消
            order_info.order_status = "已取消"
            # 更新订单完成时间
            order_info.complete_time = datetime.now()
            # 提交更新（在 with get_session() 内自动 commit）

            logger.info(
                "订单已取消: order_id=%s, old_status=%s, instance=%s",
                order_id, old_order_status, __import__("socket").gethostname()
            )

        # 3、生成回复消息
        message = "订单已取消"
        # 如果订单状态为待发货，则添加退款金额提示
        if old_order_status == "待发货":
            message += "，退款金额将在24小时内返还您的账户"

        # 4、回复消息
        dispatcher.utter_message(text=message)
        return []
