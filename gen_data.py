import os
from actions.db_table_class import *
import random
from uuid import uuid4
from faker import Faker
from datetime import datetime, timedelta
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import Session, joinedload
from dotenv import load_dotenv

load_dotenv()

# 从环境变量读取数据库配置
db_host = os.getenv("MYSQL_HOST", "localhost")
db_port = int(os.getenv("MYSQL_PORT", "3306"))
db_name = os.getenv("MYSQL_DATABASE", "ecs")
db_user_name = os.getenv("MYSQL_USER", "root")
db_password = os.getenv("MYSQL_PASSWORD", "")
url = f"mysql+pymysql://{db_user_name}:{db_password}@{db_host}:{db_port}/{db_name}?charset=utf8"
engine = create_engine(url)

fake = Faker("zh_CN")

with Session(engine) as session:
    regions = session.query(Region).all()


def gen_new_time(this_time: datetime | None, delta_seconds: int) -> datetime | None:
    """生成处于[this_time, this_time+delta_seconds)，且不超过当前时间的新时间"""
    if this_time is None:
        return None
    delta_seconds = int(
        min(delta_seconds, (datetime.now() - this_time).total_seconds())
    )
    return this_time + timedelta(seconds=random.randint(0, delta_seconds))


def import_receive_info(nums=50):
    """导入收货信息"""
    if nums == 0:
        return
    region = random.choices(regions, k=nums)
    with Session(engine) as session:
        user_infos = session.query(UserInfo).all()
        receive_infos = [
            ReceiveInfo(
                receive_id="rec" + uuid4().hex[:16],
                user_id=random.choice(user_infos).user_id,
                receiver_name=fake.name(),
                receiver_phone=fake.phone_number(),
                receive_province=region[i].province,
                receive_city=region[i].city,
                receive_district=region[i].district,
                receive_street_address=fake.street_address(),
            )
            for i in range(nums)
        ]
        session.add_all(receive_infos)
        session.commit()


def import_order_info(nums=50):
    """导入订单信息"""
    if nums == 0:
        return
    with Session(engine) as session:
        user_infos = (
            session.query(UserInfo)
            .options(joinedload(UserInfo.receive_info))
            .filter(UserInfo.receive_info.any())
            .all()
        )
    if not user_infos:
        raise Exception("缺少收货信息")
    order_infos = [gen_order_info(random.choice(user_infos)) for _ in range(nums)]
    with Session(engine) as session:
        session.add_all(order_infos)
        session.commit()


def gen_logistics_tracking(
    create_time: datetime,
    shipping_info: ReceiveInfo,
    receive_info: ReceiveInfo,
    delivered: bool,
):
    """生成物流轨迹"""
    tracking = []
    this_time = gen_new_time(create_time, 6 * 60 * 60)
    this_address = (
        shipping_info.receive_province
        + shipping_info.receive_city
        + shipping_info.receive_district
    )
    tracking.append(
        this_time.strftime("%Y-%m-%d %H:%M:%S") + " " + this_address + " " + "已揽收"
    )
    for _ in range(random.randint(1, 3)):
        this_time = gen_new_time(this_time, 1 * 60 * 60)
        pre_address = this_address
        region = random.choice(regions)
        this_address = region.province + region.city
        tracking.append(
            this_time.strftime("%Y-%m-%d %H:%M:%S")
            + " 离开 "
            + pre_address
            + "，发往 "
            + this_address
        )
        this_time = gen_new_time(this_time, 6 * 60 * 60)
        tracking.append(
            this_time.strftime("%Y-%m-%d %H:%M:%S") + " 到达 " + this_address
        )
    this_time = gen_new_time(this_time, 1 * 60 * 60)
    pre_address = this_address
    this_address = receive_info.receive_province + receive_info.receive_city
    tracking.append(
        this_time.strftime("%Y-%m-%d %H:%M:%S")
        + " 离开 "
        + pre_address
        + "，发往 "
        + this_address
    )
    this_time = gen_new_time(this_time, 6 * 60 * 60)
    this_address += receive_info.receive_district
    tracking.append(this_time.strftime("%Y-%m-%d %H:%M:%S") + " 到达 " + this_address)
    this_time = gen_new_time(this_time, 3 * 60 * 60)
    this_address += receive_info.receive_street_address
    tracking.append(
        this_time.strftime("%Y-%m-%d %H:%M:%S")
        + " "
        + this_address
        + " "
        + fake.name()
        + fake.phone_number()
        + " 派送中"
    )
    delivered_time = gen_new_time(this_time, 3 * 60 * 60)
    tracking.append(
        delivered_time.strftime("%Y-%m-%d %H:%M:%S") + " " + this_address + " 已签收"
    )
    if delivered:
        return "\n".join(tracking), delivered_time
    else:
        return "\n".join(tracking[0 : random.randint(1, len(tracking) - 1)]), None


def gen_logistics(
    create_time: datetime,
    receive_info: ReceiveInfo,
    logistics_category: str,
    delivered: bool,
) -> Logistics:
    """生成物流信息"""
    if logistics_category not in [None, "退货", "换货退货", "换货发货"]:
        raise ValueError(
            "logistics_category must in [None, '退货', '换货退货','换货发货']"
        )
    region = random.choice(regions)
    # 发货信息
    shipping_info = ReceiveInfo(
        receive_id=None,
        user_id=None,
        receiver_name=None,
        receiver_phone=None,
        receive_province=region.province,
        receive_city=region.city,
        receive_district=region.district,
        receive_street_address=fake.street_address(),
    )
    create_time = gen_new_time(create_time, 6 * 60 * 60)
    if logistics_category in ["退货", "换货退货"]:
        # 调换发货信息和收货信息
        shipping_info, receive_info = receive_info, shipping_info
    logistics_tracking, delivered_time = gen_logistics_tracking(
        create_time, shipping_info, receive_info, delivered
    )
    return Logistics(
        logistics_id="lgt" + uuid4().hex[:16],
        create_time=create_time,
        delivered_time=delivered_time,
        logistics_tracking=logistics_tracking,
        logistics_category=logistics_category,
    )


def gen_postsale(
    create_time: datetime,
    order_detail: OrderDetail,
    receive_info: ReceiveInfo,
    postsale_type,
    postsale_status: PostsaleStatus,
) -> Postsale:
    """订单明细关联售后信息"""
    create_time = gen_new_time(create_time, 6 * 60 * 60)
    # 订单明细->商品信息->商品分类->售后原因
    with Session(engine) as session:
        sku_info = (
            session.query(SkuInfo).filter(SkuInfo.sku_id == order_detail.sku_id).first()
        )
        product_category = sku_info.sku_category
        postsale_reasons = (
            session.query(PostsaleReason)
            .filter(
                or_(
                    PostsaleReason.product_category == product_category,
                    PostsaleReason.product_category.is_(None),
                )
            )
            .all()
        )
    # 生成售后信息
    postsale = Postsale(
        postsale_id="pts" + uuid4().hex[:16],
        create_time=create_time,
        order_detail_id=order_detail.order_detail_id,
        postsale_reason=random.choice(postsale_reasons).postsale_reason,
        postsale_status=postsale_status.postsale_status,
        complete_time=None,
        refund_amount=order_detail.final_amount,
        postsale_type=postsale_type,
        receive_id=receive_info.receive_id,
    )
    if postsale_status.status_code <= 420:
        pass
    elif postsale_status.status_code >= 900 and postsale_status.status_code <= 920:
        # 生成完成时间
        postsale.complete_time = gen_new_time(create_time, 24 * 60 * 60)
    elif postsale_type == "退货":
        # 生成完成时间和退货物流信息
        logistics = gen_logistics(
            create_time, receive_info, "退货", postsale_status.status_code >= 900
        )
        postsale.logistics.append(logistics)
        postsale.complete_time = gen_new_time(logistics.delivered_time, 12 * 60 * 60)
    elif postsale_type == "换货":
        postsale.refund_amount = None
        # 生成完成时间和换货物流信息
        logistics = gen_logistics(
            create_time,
            receive_info,
            "换货退货",
            random.choice([True, False])
            or postsale_status.status_code >= 900
            or postsale_status.postsale_status == "换发货",
        )
        postsale.logistics.append(logistics)
        if (
            logistics.delivered_time is not None
            and postsale_status.postsale_status != "换退货"
        ):
            logistics = gen_logistics(
                logistics.delivered_time,
                receive_info,
                "换货发货",
                postsale_status.status_code >= 900,
            )
            postsale.logistics.append(logistics)
            postsale.complete_time = gen_new_time(logistics.delivered_time, 6 * 60 * 60)
    order_detail.postsale.append(postsale)
    return postsale


def gen_order_detail(order_id) -> OrderDetail:
    """生成不包含售后信息的订单明细信息"""
    with Session(engine) as session:
        # 选择商品信息
        sku_info = random.choice(session.query(SkuInfo).all())
    # 选择商品数量
    sku_count = random.choices([1, 2, 3, 4, 5, 6], weights=[70, 10, 5, 5, 5, 5])[0]
    total_amount = sku_info.sku_price * sku_count
    discount_amount = random.uniform(0, float(total_amount))
    final_amount = float(total_amount) - discount_amount
    order_detail = OrderDetail(
        order_detail_id="ordd" + uuid4().hex[:16],
        order_id=order_id,
        sku_id=sku_info.sku_id,
        sku_name=sku_info.sku_name,
        sku_count=sku_count,
        total_amount=total_amount,
        final_amount=final_amount,
        discount_amount=discount_amount,
    )
    return order_detail


def gen_order_info(user_info: UserInfo) -> OrderInfo:
    """生成订单信息"""
    # 选择收货信息
    receive_info = random.choice(user_info.receive_info)
    # 选择订单状态
    with Session(engine) as session:
        order_status = random.choice(session.query(OrderStatus).all())
    # 创建时间：当前时间2-14天之前
    create_time = datetime.now() - timedelta(
        seconds=random.randint(2 * 24 * 60 * 60, 14 * 24 * 60 * 60)
    )
    # 生成订单信息
    order_info = OrderInfo(
        order_id="ord" + uuid4().hex[:16],
        create_time=create_time,
        user_id=user_info.user_id,
        receive_id=receive_info.receive_id,
        order_status=order_status.order_status,
        payment_time=None,
        delivered_time=None,
        complete_time=None,
    )
    # 生成订单明细信息
    nums = random.choices([1, 2, 3], weights=[80, 18, 2])[0]
    order_details = [gen_order_detail(order_info.order_id) for _ in range(nums)]
    order_info.order_detail = order_details
    # 根据状态生成并调整其他信息
    if order_status.order_status == "待支付":
        return order_info
    # 生成支付时间
    order_info.payment_time = gen_new_time(create_time, 15 * 60)
    if order_status.order_status == "已取消":
        # 生成完成时间
        order_info.complete_time = gen_new_time(create_time, 6 * 60 * 60)
        # 可能在支付前取消
        if random.choice([True, False]):
            # 删除支付时间
            order_info.complete_time = order_info.payment_time
            order_info.payment_time = None
        return order_info
    if order_status.order_status == "待发货":
        return order_info
    # 生成物流信息
    delivered = True if order_status.status_code >= 330 else False
    logistics = gen_logistics(order_info.payment_time, receive_info, None, delivered)
    order_info.logistics = [logistics]
    order_info.delivered_time = logistics.delivered_time
    if order_status.status_code < 400:
        return order_info
    have_postsale = random.choices([True, False], weights=[20, 80])[0]
    # 如果已完成且没有售后记录，不生成售后信息
    if not have_postsale and order_status.order_status != "售后中":
        # 生成完成时间
        order_info.complete_time = gen_new_time(order_info.delivered_time, 6 * 60 * 60)
        return order_info
    # 确定售后类型和售后状态
    postsale_type = random.choice(["退款", "退货", "换货"])
    type_condition = {
        "退款": PostsaleStatus.is_refund == True,
        "退货": PostsaleStatus.is_return == True,
        "换货": PostsaleStatus.is_exchange == True,
    }
    status_condition = (
        PostsaleStatus.status_code >= 900
        if order_status.order_status == "已完成"
        else PostsaleStatus.status_code <= 499
    )
    with Session(engine) as session:
        postsale_status = random.choice(
            session.query(PostsaleStatus)
            .filter(
                type_condition[postsale_type],
                (status_condition),
            )
            .all()
        )
    # 选择若干个订单明细关联售后信息
    order_details = random.choices(
        order_info.order_detail,
        k=random.randint(1, len(order_info.order_detail)),
    )
    postsales = [
        gen_postsale(
            order_info.delivered_time,
            order_detail,
            receive_info,
            postsale_type,
            postsale_status,
        )
        for order_detail in order_details
    ]
    if order_status.order_status == "售后中":
        return order_info
    # 生成完成时间
    order_info.complete_time = max([postsale.complete_time for postsale in postsales])
    return order_info


def clear_tables(run=False):
    """清空生成的数据"""
    tables = [
        LogisticsComplaintsRecord,
        t_postsale_logistics,
        t_order_logistics,
        Logistics,
        Postsale,
        OrderDetail,
        OrderInfo,
        ReceiveInfo,
    ]

    with Session(engine) as session:
        try:
            for table in tables:
                session.query(table).delete()
            session.commit()
            print("已清空先前生成的数据")
        except Exception as e:
            session.rollback()
            print(f"清空失败: {e}")


if __name__ == "__main__":
    clear_tables(True)  # 清空先前生成的数据
    import_receive_info(30)  # 导入收货信息
    import_order_info(200)  # 导入订单信息
