import pymysql
from pymysql.cursors import DictCursor

from configs import config
from neo4j import GraphDatabase


def read_sku_base_info(cursor):
    cursor.execute("""
        select ski.id     sku_id,
               ski.sku_name,
               spi.spu_name,
               bc3.name   category3_name,
               bc2.name   category2_name,
               bc1.name   category1_name,
               bt.tm_name trademark_name
        from sku_info ski
                 left join spu_info spi on ski.spu_id = spi.id
                 left join base_category3 bc3 on spi.category3_id = bc3.id
                 left join base_category2 bc2 on bc3.category2_id = bc2.id
                 left join base_category1 bc1 on bc2.category1_id = bc1.id
                 left join base_trademark bt on spi.tm_id = bt.id
    """)
    return cursor.fetchall()


def read_sku_attr_info(cursor):
    cursor.execute("""
        select sku_id,
               attr_name,
               value_name attr_value
        from sku_attr_value
        union all
        select sku_id,
               sale_attr_name,
               sale_attr_value_name
        from sku_sale_attr_value
    """)
    return cursor.fetchall()


def write_sku_base_info(driver, sku_base_info):
    for sku in sku_base_info:
        # {'sku_id': 1,
        #  'sku_name': '小米12S Ultra 骁龙8+旗舰处理器 徕卡光学镜头 2K超视感屏 120Hz高刷 67W快充 8GB+128GB 冷杉绿 5G手机',
        #  'spu_name': '小米12S Ultra', 'category3_name': '手机', 'category2_name': '手机通讯', 'category1_name': '手机',
        #  'trademark_name': 'Redmi'}
        driver.execute_query("""
            MERGE (sku:SKU{sku_id:$sku_id,sku_name:$sku_name})
            MERGE (spu:SPU{spu_name:$spu_name})
            MERGE (cate3:Category3{category3_name:$category3_name})
            MERGE (cate2:Category2{category2_name:$category2_name})
            MERGE (cate1:Category1{category1_name:$category1_name})
            MERGE (tm:Trademark{trademark_name:$trademark_name})
            MERGE (sku)-[:Belong]->(spu)
            MERGE (spu)-[:Belong]->(cate3)
            MERGE (cate3)-[:Belong]->(cate2)
            MERGE (cate2)-[:Belong]->(cate1)
            MERGE (spu)-[:Belong]->(tm)
        """, parameters_=sku)


def write_sku_attr_info(driver, sku_attr_info):
    for attr in sku_attr_info:
        # {'sku_id': 1, 'attr_name': '手机一级1', 'attr_value': '安卓手机'}
        driver.execute_query("""
            MATCH (sku:SKU {sku_id:$sku_id})
            MERGE (attr:Attr {attr_name:$attr_name, attr_value:$attr_value})
            MERGE (sku)-[:Have]->(attr)
        """, parameters_=attr)


if __name__ == '__main__':
    # 读取Mysql数据
    with pymysql.connect(**config.MYSQL_CONFIG) as connection:
        with connection.cursor(cursor=DictCursor) as cursor:
            sku_base_info = read_sku_base_info(cursor)
            sku_attr_info = read_sku_attr_info(cursor)

    # 将数据写入Neo4j
    with GraphDatabase.driver(uri=config.NEO4J_CONFIG["uri"],
                              auth=(config.NEO4J_CONFIG["user"], config.NEO4J_CONFIG["password"])) as driver:
        write_sku_base_info(driver, sku_base_info)
        write_sku_attr_info(driver, sku_attr_info)
