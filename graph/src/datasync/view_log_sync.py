import pymysql
from neo4j import GraphDatabase
from pymysql.cursors import DictCursor

from configs import config


def read_user_view_log():
    with pymysql.connect(**config.MYSQL_CONFIG) as connection:
        with connection.cursor(cursor=DictCursor) as cursor:
            cursor.execute("""
                select
                    user_id,
                    sku_id,
                    view_time
                from user_view_log
            """)
            return cursor.fetchall()


def write_user_view_log(user_view_log):
    with GraphDatabase.driver(uri=config.NEO4J_CONFIG["uri"],
                              auth=(config.NEO4J_CONFIG["user"], config.NEO4J_CONFIG["password"])) as driver:
        for item in user_view_log:
            driver.execute_query("""
                MATCH (sku:SKU{sku_id:$sku_id})
                MERGE (user:User{user_id:$user_id})
                MERGE (user)-[:View{view_time:$view_time}]->(sku)
            """, item)


if __name__ == '__main__':
    # 1.读取用户行为日志
    user_view_log = read_user_view_log()
    # 2.将日志数据写入neo4j
    write_user_view_log(user_view_log)
