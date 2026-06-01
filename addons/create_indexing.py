# neo4j-admin database load --from-path="neo4j.dump文件所在目录" --overwrite-destination=true neo4j --verbose
import os
import re
import jieba
import logging
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from neo4j_graphrag.indexes import (
    create_vector_index,
    upsert_vectors,
    create_fulltext_index,
)

# 配置控制台日志
logger = logging.getLogger("indexing")
logger.setLevel(logging.INFO)
if not logger.handlers:
    formatter = logging.Formatter("[%(levelname)s]%(asctime)s: %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

vector_dim = 768  # 嵌入向量维度
embed_batch_size = 64  # 嵌入向量计算批次大小


def drop_constraint(driver):
    """删除所有约束"""
    records = driver.execute_query("show constraints").records
    for record in records:
        driver.execute_query(f"drop constraint {record['name']} if exists")


def drop_index_without_constraint(driver):
    """删除所有没有约束的索引"""
    records = driver.execute_query("show index").records
    for record in records:
        if not record["owningConstraint"]:
            driver.execute_query(f"drop index {record['name']} if exists")


# --------- 创建向量索引 ---------
embed_model = SentenceTransformer("../models/bge-base-zh-v1.5")


def vector_indexing(driver, label, property="name"):
    """创建向量索引，并添加嵌入向量"""

    # 创建向量索引
    create_vector_index(
        driver,
        name=f"{label.lower()}_vector",  # 索引的唯一名称
        label=label,  # 要索引的节点标签
        embedding_property="embedding",  # 包含嵌入向量值的节点属性键
        dimensions=vector_dim,  # 向量嵌入维度，768与使用的 bge-base-zh-v1.5 嵌入模型一致
        similarity_fn="cosine",  # 向量相似度函数，可选值为 "euclidean"（欧几里得距离）或 "cosine"（余弦相似度）
    )

    # 查询 embedding 为 null 的节点，获取 elementId 和 指定属性
    record_list = driver.execute_query(
        f"""match (n:{label}) where n.embedding is null
            return elementId(n) as id, n.{property} as text""",
    ).records
    record_tuple_list = [(r["id"], r["text"]) for r in record_list]
    if not record_tuple_list:
        logger.info(f"{label} 所有节点皆存在嵌入向量")
        return
    # [('id1', 'text1'), ('id2', 'text2')] =》 zip(('id1', 'text1'), ('id2', 'text2'))=>[('id1', 'id2'), ('text1', 'text2')]
    ids, texts = zip(*record_tuple_list)
    ids = list(ids)
    texts = list(texts)

    # 计算文本的嵌入向量
    logger.info(f"计算 {label} ({len(record_list)}) 的嵌入向量")
    embeddings = embed_model.encode(
        texts, batch_size=embed_batch_size, normalize_embeddings=True
    )

    # 按 elementId 添加嵌入向量属性
    logger.info(f"写入 {label} ({len(record_list)}) 的嵌入向量")
    upsert_vectors(
        driver,
        ids=ids,
        embedding_property="embedding",
        embeddings=embeddings,
    )


# --------- 创建全文索引 ---------
def fulltext_indexing(driver, label, property="name"):
    """创建全文索引，并添加节点属性"""

    # 创建全文索引
    create_fulltext_index(
        driver,
        name=f"{label.lower()}_fulltext",  # 索引的唯一名称
        label=label,  # 要创建索引的节点标签
        node_properties=["fulltext"],  # 要创建全文索引的节点属性列表
    )

    # 查询 fulltext 为 null 的节点，获取 elementId 和 指定属性
    record_list = driver.execute_query(
        f"""match (n:{label}) where n.fulltext is null
            return elementId(n) as id, n.{property} as text""",
    ).records
    record_tuple_list = [(r["id"], r["text"]) for r in record_list]
    if not record_tuple_list:
        logger.info(f"{label} 所有节点皆存在全文索引属性")
        return

    # 文本分词，作为全文索引属性
    logger.info(f"计算 {label} ({len(record_list)}) 的全文索引")
    pattern = re.compile(r"[a-zA-Z0-9\u4e00-\u9fa5]+") #匹配英文字母、数字和中文字符
    fulltext_tuple_list = [
        (
            id_,
            " ".join(
                [
                    word.strip()
                    for word in jieba.lcut(text)
                    if pattern.fullmatch(word.strip())#过滤掉不符合正则表达式的词汇
                ]
            ),
        )
        for id_, text in record_tuple_list
    ]
    ids, fulltexts = zip(*fulltext_tuple_list)
    ids = list(ids)
    fulltexts = list(fulltexts)

    # 按 elementId 添加全文索引属性
    logger.info(f"写入 {label} ({len(fulltexts)}) 的全文索引")
    insert_batch_size = 1000
    for i in range(0, len(record_tuple_list), insert_batch_size):
        batch_rows = [
            {"id": id_, "fulltext": ft}
            for id_, ft in zip(
                ids[i: i + insert_batch_size],
                fulltexts[i: i + insert_batch_size],
            )
        ]

        # UNWIND：将列表数据展开为多行记录

        driver.execute_query(
            "UNWIND $rows AS row " #将传入的rows列表（通过参数传递）展开，每一项作为一行数据，命名为row
            "MATCH (n) "
            "WHERE elementId(n) = row.id "
            "SET n.fulltext = row.fulltext ",
            {"rows": batch_rows},
        )


if __name__ == "__main__":
    neo4j_url = "neo4j://127.0.0.1"
    neo4j_auth = ("neo4j", "12345678")
    with GraphDatabase.driver(neo4j_url, auth=neo4j_auth) as driver:
        # 1、清空处理：确保所有索引和约束都被清理干净，为后续重新创建索引做好准备
        # 清空所有约束。约束会自动创建索引，删除约束同时会删除对应的索引
        drop_constraint(driver)
        # 清空所有没有约束的索引
        drop_index_without_constraint(driver)

        # 2、清空并创建向量索引
        # 清空所有嵌入向量
        driver.execute_query("match (n) remove n.embedding")
        # 创建向量索引
        vector_indexing(driver, "Category1", "category1_name")
        vector_indexing(driver, "Category2", "category2_name")
        vector_indexing(driver, "Category3", "category3_name")
        vector_indexing(driver, "Trademark", "trademark_name")
        vector_indexing(driver, "SPU", "spu_name")
        vector_indexing(driver, "SKU", "sku_name")
        vector_indexing(driver, "Attr", "attr_value")

        # 3、清空并创建全文索引
        # 清空所有节点全文索引属性
        driver.execute_query("match (n) remove n.fulltext")
        # 创建全文索引
        fulltext_indexing(driver, "Category1", "category1_name")
        fulltext_indexing(driver, "Category2", "category2_name")
        fulltext_indexing(driver, "Category3", "category3_name")
        fulltext_indexing(driver, "Trademark", "trademark_name")
        fulltext_indexing(driver, "SPU", "spu_name")
        fulltext_indexing(driver, "SKU", "sku_name")
        fulltext_indexing(driver, "Attr", "attr_value")
