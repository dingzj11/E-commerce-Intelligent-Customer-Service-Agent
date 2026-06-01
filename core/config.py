"""集中化配置管理

支持环境变量覆盖，便于容器化部署（Docker/K8s）。
配置优先级：环境变量 > .env 文件 > 默认值
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import dotenv

# 加载 .env 文件（项目根目录）
dotenv.load_dotenv(Path(__file__).parent.parent / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    return int(val) if val else default


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes")


@dataclass
class MySQLConfig:
    host: str = _env("MYSQL_HOST", "localhost")
    port: int = _env_int("MYSQL_PORT", 3306)
    user: str = _env("MYSQL_USER", "root")
    password: str = _env("MYSQL_PASSWORD", "123321")
    database: str = _env("MYSQL_DATABASE", "ecs")
    charset: str = "utf8mb4"

    # 连接池配置
    pool_size: int = _env_int("MYSQL_POOL_SIZE", 20)
    max_overflow: int = _env_int("MYSQL_MAX_OVERFLOW", 40)
    pool_recycle: int = _env_int("MYSQL_POOL_RECYCLE", 3600)  # 1小时回收连接
    pool_pre_ping: bool = True  # 连接前检查可用性

    # 读写分离（可选）
    read_host: Optional[str] = _env("MYSQL_READ_HOST") or None
    read_port: int = _env_int("MYSQL_READ_PORT", 3306)

    @property
    def url(self) -> str:
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}?charset={self.charset}"
        )

    @property
    def read_url(self) -> Optional[str]:
        if not self.read_host:
            return None
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.read_host}:{self.read_port}/{self.database}?charset={self.charset}"
        )


@dataclass
class RedisConfig:
    host: str = _env("REDIS_HOST", "localhost")
    port: int = _env_int("REDIS_PORT", 6379)
    password: str = _env("REDIS_PASSWORD", "")
    db: int = _env_int("REDIS_DB", 0)
    use_ssl: bool = _env_bool("REDIS_SSL", False)

    # 连接池配置
    max_connections: int = _env_int("REDIS_MAX_CONNECTIONS", 50)
    socket_timeout: int = _env_int("REDIS_SOCKET_TIMEOUT", 5)
    socket_connect_timeout: int = _env_int("REDIS_CONNECT_TIMEOUT", 5)

    # Key 前缀（用于多环境隔离）
    key_prefix: str = _env("REDIS_KEY_PREFIX", "rasa_ecs:")

    # 高可用模式: "standalone" | "sentinel" | "cluster"
    mode: str = _env("REDIS_MODE", "standalone")

    # Sentinel 配置
    sentinel_master_name: str = _env("REDIS_SENTINEL_MASTER", "mymaster")
    sentinel_hosts: str = _env("REDIS_SENTINEL_HOSTS", "")  # "host1:26379,host2:26379"

    # Redlock 多实例配置（多个独立 Redis 节点）
    redlock_hosts: str = _env("REDIS_REDLOCK_HOSTS", "")  # "host1:6379,host2:6379,..."

    @property
    def url(self) -> str:
        protocol = "rediss" if self.use_ssl else "redis"
        if self.password:
            return f"{protocol}://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"{protocol}://{self.host}:{self.port}/{self.db}"


@dataclass
class Neo4jConfig:
    uri: str = _env("NEO4J_URI", "neo4j://127.0.0.1:7687")
    user: str = _env("NEO4J_USER", "neo4j")
    password: str = _env("NEO4J_PASSWORD", "12345678")
    max_connection_lifetime: int = _env_int("NEO4J_MAX_CONN_LIFETIME", 3600)
    max_connection_pool_size: int = _env_int("NEO4J_POOL_SIZE", 50)


@dataclass
class LLMConfig:
    api_key: str = _env("API_KEY", "")
    qwen_model: str = "qwen-plus-2025-07-28"
    qwen_coder_model: str = "qwen3-coder-480b-a35b-instruct"
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class CacheTTL:
    """缓存过期时间配置（秒）"""
    regions: int = _env_int("CACHE_TTL_REGIONS", 86400)       # 地区数据 24h
    logistics_companies: int = _env_int("CACHE_TTL_LOGISTICS", 86400)  # 物流公司 24h
    product_category: int = _env_int("CACHE_TTL_CATEGORY", 3600)  # 产品分类 1h
    order_detail: int = _env_int("CACHE_TTL_ORDER", 300)       # 订单详情 5min
    postsale_reasons: int = _env_int("CACHE_TTL_REASONS", 3600)  # 售后原因 1h
    embedding: int = _env_int("CACHE_TTL_EMBEDDING", 86400)   # 嵌入结果 24h


@dataclass
class RateLimitConfig:
    """限流配置"""
    global_per_second: int = _env_int("RATE_LIMIT_GLOBAL", 100)
    per_user_per_second: int = _env_int("RATE_LIMIT_USER", 10)
    per_ip_per_second: int = _env_int("RATE_LIMIT_IP", 30)
    postsale_per_user_per_minute: int = _env_int("RATE_LIMIT_POSTSALE", 5)  # 售后频率限制


@dataclass
class AppConfig:
    """应用全局配置"""
    mysql: MySQLConfig = field(default_factory=MySQLConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    neo4j: Neo4jConfig = field(default_factory=Neo4jConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    cache_ttl: CacheTTL = field(default_factory=CacheTTL)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)

    # 应用配置
    app_name: str = "rasa-ecs-agent"
    env: str = _env("APP_ENV", "development")  # development/testing/production
    debug: bool = _env_bool("DEBUG", False)
    api_key: str = _env("API_KEY", "")

    # 分布式配置
    instance_id: str = field(default_factory=lambda: _env("INSTANCE_ID", ""))
    max_retry_on_lock: int = _env_int("LOCK_MAX_RETRY", 3)
    lock_timeout: int = _env_int("LOCK_TIMEOUT", 10)  # 分布式锁超时（秒）


# 全局单例
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """获取全局配置单例"""
    global _config
    if _config is None:
        _config = AppConfig()
    return _config
