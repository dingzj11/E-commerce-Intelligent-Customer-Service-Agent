from typing import Optional
import datetime
import decimal

from sqlalchemy import BigInteger, Column, DECIMAL, Enum, ForeignKeyConstraint, Index, Integer, String, TIMESTAMP, Table, text
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class Logistics(Base):
    __tablename__ = 'logistics'
    __table_args__ = {'comment': '物流表'}

    logistics_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment='物流ID')
    create_time: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, comment='创建时间')
    delivered_time: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, comment='签收时间')
    logistics_tracking: Mapped[Optional[str]] = mapped_column(String(500), comment='物流明细')
    logistics_category: Mapped[Optional[str]] = mapped_column(Enum('退货', '换货退货', '换货发货'), comment='物流类别')

    order: Mapped[list['OrderInfo']] = relationship('OrderInfo', secondary='order_logistics', back_populates='logistics')
    postsale: Mapped[list['Postsale']] = relationship('Postsale', secondary='postsale_logistics', back_populates='logistics')
    logistics_complaints_record: Mapped[list['LogisticsComplaintsRecord']] = relationship('LogisticsComplaintsRecord', back_populates='logistics')


class LogisticsCompany(Base):
    __tablename__ = 'logistics_company'
    __table_args__ = {'comment': '物流公司表'}

    company_name: Mapped[str] = mapped_column(String(20), primary_key=True, comment='物流公司名称')


class LogisticsComplaint(Base):
    __tablename__ = 'logistics_complaint'
    __table_args__ = {'comment': '物流投诉内容对照表'}

    logistics_status: Mapped[str] = mapped_column(String(20), primary_key=True, comment='物流状态')
    logistics_complaint: Mapped[str] = mapped_column(String(100), primary_key=True, comment='物流投诉内容')


class OrderStatus(Base):
    __tablename__ = 'order_status'
    __table_args__ = {'comment': '订单状态表'}

    order_status: Mapped[str] = mapped_column(String(20), primary_key=True, comment='订单状态')
    status_code: Mapped[Optional[int]] = mapped_column(Integer, comment='状态码')

    order_info: Mapped[list['OrderInfo']] = relationship('OrderInfo', back_populates='order_status_')


class PostsaleStatus(Base):
    __tablename__ = 'postsale_status'
    __table_args__ = {'comment': '售后状态表'}

    postsale_status: Mapped[str] = mapped_column(String(20), primary_key=True, comment='售后状态')
    is_refund: Mapped[int] = mapped_column(TINYINT(1), nullable=False, comment='是否退款')
    is_return: Mapped[int] = mapped_column(TINYINT(1), nullable=False, comment='是否退货')
    is_exchange: Mapped[int] = mapped_column(TINYINT(1), nullable=False, comment='是否换货')
    status_code: Mapped[Optional[int]] = mapped_column(Integer, comment='状态码')

    postsale: Mapped[list['Postsale']] = relationship('Postsale', back_populates='postsale_status_')


class ProductCategory(Base):
    __tablename__ = 'product_category'
    __table_args__ = {'comment': '商品类别表'}

    product_category: Mapped[str] = mapped_column(String(20), primary_key=True, comment='商品类别')

    postsale_reason: Mapped[list['PostsaleReason']] = relationship('PostsaleReason', back_populates='product_category_')
    sku_info: Mapped[list['SkuInfo']] = relationship('SkuInfo', back_populates='product_category')


class Region(Base):
    __tablename__ = 'region'
    __table_args__ = {'comment': '区域表'}

    province: Mapped[str] = mapped_column(String(20), primary_key=True, comment='省')
    city: Mapped[str] = mapped_column(String(20), primary_key=True, comment='市')
    district: Mapped[str] = mapped_column(String(20), primary_key=True, comment='区')

    receive_info: Mapped[list['ReceiveInfo']] = relationship('ReceiveInfo', back_populates='region')


class UserInfo(Base):
    __tablename__ = 'user_info'
    __table_args__ = {'comment': '用户信息表'}

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment='用户ID')

    logistics_complaints_record: Mapped[list['LogisticsComplaintsRecord']] = relationship('LogisticsComplaintsRecord', back_populates='user')
    receive_info: Mapped[list['ReceiveInfo']] = relationship('ReceiveInfo', back_populates='user')
    order_info: Mapped[list['OrderInfo']] = relationship('OrderInfo', back_populates='user')


class LogisticsComplaintsRecord(Base):
    __tablename__ = 'logistics_complaints_record'
    __table_args__ = (
        ForeignKeyConstraint(['logistics_id'], ['logistics.logistics_id'], name='logistics_complaints_record_ibfk_2'),
        ForeignKeyConstraint(['user_id'], ['user_info.user_id'], name='logistics_complaints_record_ibfk_1'),
        Index('logistics_id', 'logistics_id'),
        Index('user_id', 'user_id'),
        {'comment': '物流投诉记录表'}
    )

    record_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment='投诉记录ID')
    logistics_id: Mapped[str] = mapped_column(String(50), nullable=False, comment='物流ID')
    logistics_complaint: Mapped[str] = mapped_column(String(500), nullable=False, comment='物流投诉内容')
    complaint_time: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, comment='投诉时间')
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, comment='用户ID')

    logistics: Mapped['Logistics'] = relationship('Logistics', back_populates='logistics_complaints_record')
    user: Mapped['UserInfo'] = relationship('UserInfo', back_populates='logistics_complaints_record')


class PostsaleReason(Base):
    __tablename__ = 'postsale_reason'
    __table_args__ = (
        ForeignKeyConstraint(['product_category'], ['product_category.product_category'], name='postsale_reason_ibfk_1'),
        Index('product_category', 'product_category'),
        {'comment': '售后原因表'}
    )

    postsale_reason: Mapped[str] = mapped_column(String(100), primary_key=True, comment='售后原因')
    product_category: Mapped[Optional[str]] = mapped_column(String(20), comment='商品类别')

    product_category_: Mapped[Optional['ProductCategory']] = relationship('ProductCategory', back_populates='postsale_reason')


class ReceiveInfo(Base):
    __tablename__ = 'receive_info'
    __table_args__ = (
        ForeignKeyConstraint(['receive_province', 'receive_city', 'receive_district'], ['region.province', 'region.city', 'region.district'], name='receive_info_ibfk_2'),
        ForeignKeyConstraint(['user_id'], ['user_info.user_id'], name='receive_info_ibfk_1'),
        Index('receive_province', 'receive_province', 'receive_city', 'receive_district'),
        Index('user_id', 'user_id', 'receiver_name', 'receiver_phone', 'receive_province', 'receive_city', 'receive_district', 'receive_street_address', unique=True),
        {'comment': '收货信息表'}
    )

    receive_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment='收货信息ID')
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, comment='用户ID')
    receiver_name: Mapped[str] = mapped_column(String(50), nullable=False, comment='收货人姓名')
    receiver_phone: Mapped[str] = mapped_column(String(50), nullable=False, comment='收货人电话')
    receive_province: Mapped[str] = mapped_column(String(50), nullable=False, comment='收货省')
    receive_city: Mapped[str] = mapped_column(String(50), nullable=False, comment='收货市')
    receive_district: Mapped[str] = mapped_column(String(50), nullable=False, comment='收货区')
    receive_street_address: Mapped[str] = mapped_column(String(50), nullable=False, comment='收货详细地址')

    region: Mapped['Region'] = relationship('Region', back_populates='receive_info')
    user: Mapped['UserInfo'] = relationship('UserInfo', back_populates='receive_info')
    order_info: Mapped[list['OrderInfo']] = relationship('OrderInfo', back_populates='receive')
    postsale: Mapped[list['Postsale']] = relationship('Postsale', back_populates='receive')


class SkuInfo(Base):
    __tablename__ = 'sku_info'
    __table_args__ = (
        ForeignKeyConstraint(['sku_category'], ['product_category.product_category'], name='sku_info_ibfk_1'),
        Index('sku_category', 'sku_category'),
        {'comment': '商品信息表'}
    )

    sku_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment='商品ID')
    sku_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='商品名称')
    sku_price: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), nullable=False, comment='商品单价')
    sku_category: Mapped[str] = mapped_column(String(20), nullable=False, comment='商品类别')
    sku_count: Mapped[int] = mapped_column(Integer, nullable=False, comment='商品库存')

    product_category: Mapped['ProductCategory'] = relationship('ProductCategory', back_populates='sku_info')
    order_detail: Mapped[list['OrderDetail']] = relationship('OrderDetail', back_populates='sku')


class OrderInfo(Base):
    __tablename__ = 'order_info'
    __table_args__ = (
        ForeignKeyConstraint(['order_status'], ['order_status.order_status'], name='order_info_ibfk_3'),
        ForeignKeyConstraint(['receive_id'], ['receive_info.receive_id'], name='order_info_ibfk_2'),
        ForeignKeyConstraint(['user_id'], ['user_info.user_id'], name='order_info_ibfk_1'),
        Index('order_status', 'order_status'),
        Index('receive_id', 'receive_id'),
        Index('user_id', 'user_id'),
        {'comment': '订单表'}
    )

    order_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment='订单ID')
    create_time: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, comment='创建时间')
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, comment='用户ID')
    receive_id: Mapped[str] = mapped_column(String(50), nullable=False, comment='收货信息ID')
    order_status: Mapped[str] = mapped_column(String(20), nullable=False, comment='订单状态')
    payment_time: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, comment='支付时间')
    delivered_time: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, comment='签收时间')
    complete_time: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, comment='完成时间')

    logistics: Mapped[list['Logistics']] = relationship('Logistics', secondary='order_logistics', back_populates='order')
    order_status_: Mapped['OrderStatus'] = relationship('OrderStatus', back_populates='order_info')
    receive: Mapped['ReceiveInfo'] = relationship('ReceiveInfo', back_populates='order_info')
    user: Mapped['UserInfo'] = relationship('UserInfo', back_populates='order_info')
    order_detail: Mapped[list['OrderDetail']] = relationship('OrderDetail', back_populates='order')


class OrderDetail(Base):
    __tablename__ = 'order_detail'
    __table_args__ = (
        ForeignKeyConstraint(['order_id'], ['order_info.order_id'], name='order_detail_ibfk_2'),
        ForeignKeyConstraint(['sku_id'], ['sku_info.sku_id'], name='order_detail_ibfk_1'),
        Index('order_id', 'order_id'),
        Index('sku_id', 'sku_id'),
        {'comment': '订单明细表'}
    )

    order_detail_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment='订单明细ID')
    order_id: Mapped[str] = mapped_column(String(50), nullable=False, comment='订单ID')
    sku_id: Mapped[str] = mapped_column(String(50), nullable=False, comment='商品ID')
    sku_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='商品名称')
    sku_count: Mapped[int] = mapped_column(Integer, nullable=False, comment='商品数量')
    total_amount: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), nullable=False, comment='总计金额')
    final_amount: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), nullable=False, comment='实付金额')
    discount_amount: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 2), server_default=text("'0.00'"), comment='优惠金额')

    order: Mapped['OrderInfo'] = relationship('OrderInfo', back_populates='order_detail')
    sku: Mapped['SkuInfo'] = relationship('SkuInfo', back_populates='order_detail')
    postsale: Mapped[list['Postsale']] = relationship('Postsale', back_populates='order_detail')


t_order_logistics = Table(
    'order_logistics', Base.metadata,
    Column('order_id', String(50), primary_key=True, comment='订单ID'),
    Column('logistics_id', String(50), primary_key=True, comment='物流ID'),
    ForeignKeyConstraint(['logistics_id'], ['logistics.logistics_id'], name='order_logistics_ibfk_2'),
    ForeignKeyConstraint(['order_id'], ['order_info.order_id'], name='order_logistics_ibfk_1'),
    Index('logistics_id', 'logistics_id'),
    comment='订单与物流关联表'
)


class Postsale(Base):
    __tablename__ = 'postsale'
    __table_args__ = (
        ForeignKeyConstraint(['order_detail_id'], ['order_detail.order_detail_id'], name='postsale_ibfk_2'),
        ForeignKeyConstraint(['postsale_status'], ['postsale_status.postsale_status'], name='postsale_ibfk_3'),
        ForeignKeyConstraint(['receive_id'], ['receive_info.receive_id'], name='postsale_ibfk_1'),
        Index('order_detail_id', 'order_detail_id'),
        Index('postsale_status', 'postsale_status'),
        Index('receive_id', 'receive_id'),
        {'comment': '售后表'}
    )

    postsale_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment='售后ID')
    create_time: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, comment='创建时间')
    order_detail_id: Mapped[str] = mapped_column(String(50), nullable=False, comment='订单明细ID')
    postsale_reason: Mapped[str] = mapped_column(String(500), nullable=False, comment='售后原因')
    postsale_status: Mapped[str] = mapped_column(String(20), nullable=False, comment='售后状态')
    receive_id: Mapped[str] = mapped_column(String(50), nullable=False, comment='收货信息ID')
    complete_time: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, comment='完成时间')
    refund_amount: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 2), server_default=text("'0.00'"), comment='退款金额')
    postsale_type: Mapped[Optional[str]] = mapped_column(Enum('退款', '退货', '换货'), comment='售后类型')

    logistics: Mapped[list['Logistics']] = relationship('Logistics', secondary='postsale_logistics', back_populates='postsale')
    order_detail: Mapped['OrderDetail'] = relationship('OrderDetail', back_populates='postsale')
    postsale_status_: Mapped['PostsaleStatus'] = relationship('PostsaleStatus', back_populates='postsale')
    receive: Mapped['ReceiveInfo'] = relationship('ReceiveInfo', back_populates='postsale')


t_postsale_logistics = Table(
    'postsale_logistics', Base.metadata,
    Column('postsale_id', String(50), primary_key=True, comment='售后ID'),
    Column('logistics_id', String(50), primary_key=True, comment='物流ID'),
    ForeignKeyConstraint(['logistics_id'], ['logistics.logistics_id'], name='postsale_logistics_ibfk_2'),
    ForeignKeyConstraint(['postsale_id'], ['postsale.postsale_id'], name='postsale_logistics_ibfk_1'),
    Index('logistics_id', 'logistics_id'),
    comment='售后与物流关联表'
)
