from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent

DATA_DIR = ROOT_DIR / "data"
PRE_TRAINED_DIR = ROOT_DIR / "pretrained"
CHECKPOINT_DIR = ROOT_DIR / "checkpoint"
EXTERNAL_LIB_DIR = ROOT_DIR / "external_lib"
WEB_STATIC_DIR = ROOT_DIR / "src" / "web" / "static"

# Mysql数据库相关配置
MYSQL_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': 'gmall',
    'charset': 'utf8mb4',
}

# Neo4J数据库相关配置
NEO4J_CONFIG = {
    'uri': 'neo4j://localhost:7687',
    'user': 'neo4j',
    'password': 'Atguigu.123',
}

INTENT_LIST = ['查询某商品的某个属性的属性值',
               '查询某商品的所有单品',
               '查询某商品具有某些属性值的单品',
               '查询某品牌所有品类',
               '查询某品类所有品牌',
               '查询某品类所有商品',
               '查询某品类某个属性的所有属性值',
               '查询某品类某品牌的所有商品',
               '查询某品类具有某些属性的单品',
               '查询某品类某品牌具有某些属性的单品',
               '查询和某商品某个属性具有相同属性值的其他商品',
               '查询某商品具有某些属性值的单品的价格',
               '查询某品类某价格区间的单品',
               '查询某品类某品牌某价格区间的单品']
