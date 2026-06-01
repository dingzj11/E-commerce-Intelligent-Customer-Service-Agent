"""数据库模块

提供 MySQL 连接池管理、读写分离支持、分布式场景下的连接优化。

特性:
- SQLAlchemy 连接池（支持高并发）
- 可选的读写分离（写主库、读从库）
- 连接健康检查（pool_pre_ping）
- 连接回收防止 MySQL wait_timeout 断开
- 从环境变量读取配置（容器化友好）
"""

import logging
import os
import subprocess
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from core.config import get_config

logger = logging.getLogger("db")

# ==================== 数据库配置 ====================

# 优先从核心配置读取，降级为直接读取环境变量
try:
    _mysql_cfg = get_config().mysql
    db_host = _mysql_cfg.host
    db_port = _mysql_cfg.port
    db_name = _mysql_cfg.database
    db_user_name = _mysql_cfg.user
    db_password = _mysql_cfg.password
    pool_size = _mysql_cfg.pool_size
    max_overflow = _mysql_cfg.max_overflow
    pool_recycle = _mysql_cfg.pool_recycle
    pool_pre_ping = _mysql_cfg.pool_pre_ping
except Exception:
    # 核心配置初始化失败时的回退（如 Redis 不可用）
    db_host = os.getenv("MYSQL_HOST", "localhost")
    db_port = int(os.getenv("MYSQL_PORT", "3306"))
    db_name = os.getenv("MYSQL_DATABASE", "ecs")
    db_user_name = os.getenv("MYSQL_USER", "root")
    db_password = os.getenv("MYSQL_PASSWORD", "123321")
    pool_size = int(os.getenv("MYSQL_POOL_SIZE", "20"))
    max_overflow = int(os.getenv("MYSQL_MAX_OVERFLOW", "40"))
    pool_recycle = int(os.getenv("MYSQL_POOL_RECYCLE", "3600"))
    pool_pre_ping = True

# 数据库 URL
url = (
    f"mysql+pymysql://{db_user_name}:{db_password}"
    f"@{db_host}:{db_port}/{db_name}?charset=utf8mb4"
)

# ==================== 连接池 ====================

# 写库引擎
engine = create_engine(
    url,
    poolclass=QueuePool,
    pool_size=pool_size,
    max_overflow=max_overflow,
    pool_recycle=pool_recycle,       # 1小时回收连接，防止 MySQL wait_timeout
    pool_pre_ping=pool_pre_ping,     # 每次从池中取出时检查连接有效性
    echo=False,
    connect_args={
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
    },
)

# 会话工厂
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ==================== 连接事件监控 ====================

@event.listens_for(engine, "checkout")
def _on_checkout(dbapi_conn, conn_record, conn_proxy):
    """连接检出事件（用于监控连接池使用情况）"""
    logger.debug("数据库连接检出: pool_size=%s, checked_out=%s, overflow=%s",
                 engine.pool.size(), engine.pool.checkedout(), engine.pool.overflow())


@event.listens_for(engine, "checkin")
def _on_checkin(dbapi_conn, conn_record):
    """连接归还事件"""
    logger.debug("数据库连接归还")


# ==================== 会话管理 ====================


@contextmanager
def get_session():
    """获取数据库会话的上下文管理器

    用法:
        with get_session() as session:
            order = session.query(OrderInfo).filter_by(order_id=order_id).first()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        # 安全关闭会话，防止连接泄漏
        try:
            session.close()
        except Exception:
            pass


def get_db():
    """获取数据库会话（FastAPI 依赖注入风格，手动管理事务）"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


if __name__ == "__main__":
    def export_db_table_class(run=False):
        """将数据库表映射为Python类"""
        if not run:
            return
        output_path = "db_table_class.py"

        cmd = ["python", "-m", "sqlacodegen", url]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result.stdout)

    export_db_table_class(True)
