"""
实现思路：
    先确定查询知识图谱的入口节点，根据入口节点和用户意图生成Cypher语句进行查询
    1.LLM根据用户输入，确定需要的入口节点类型以及实体
    2.根据提供的入口节点类型和实体，使用混合检索获取候选入口节点信息
    3.LLM根据用户输入和入口节点信息生成Cypher查询语句
    4.LLM验证生成的Cypher语法、逻辑是否正确，罗列出错误信息
    5.LLM根据用户输入、入口节点、错误信息、先前Cypher语句来生成更正后的Cypher语句
    6.执行Cypher查询，返回查询结果
工作流程:
    用户提问：用户输入查询问题
    标签路由：LLM识别问题涉及的节点类型和实体
    节点检索：使用混合检索找到候选入口节点
    Cypher生成：LLM根据入口节点和问题生成Cypher查询语句
    语句验证：验证Cypher语句的正确性
    语句校正：如有错误则进行校正
    执行查询：在Neo4j中执行Cypher查询
    返回结果：将查询结果返回给用户
"""

import os
import re
import json
import dotenv
import jieba
import logging
import asyncio
from typing import Any, Text
from neo4j import GraphDatabase
from pydantic import BaseModel, Field
from langchain_core.documents import Document
from neo4j.exceptions import CypherSyntaxError
from rasa.utils.endpoints import EndpointConfig
from neo4j_graphrag.retrievers import HybridRetriever
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.graphs.neo4j_graph import Neo4jGraph
from neo4j_graphrag.retrievers.text2cypher import extract_cypher
from rasa.core.information_retrieval import SearchResultList, InformationRetrieval
from langchain_community.chains.graph_qa.cypher import CypherQueryCorrector, Schema
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

# 配置控制台日志
logger = logging.getLogger("retrieval")
logger.setLevel(logging.INFO)
if not logger.handlers:
    formatter = logging.Formatter("[%(levelname)s]%(asctime)s: %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# 路由输出定义,使用Pydantic定义数据模型
class RouteItem(BaseModel):
    label: str = Field(..., description="节点类型，比如“SKU”")
    entity: str = Field(..., description="实体文本")


class RouteOutput(BaseModel):
    outputs: list[RouteItem]


def get_chat_history(tracker_state: dict[str, Any], user_id) -> dict[str]:
    """从 tracker state 中提取聊天历史"""
    chat_history = []
    if not tracker_state.get("events"):
        return chat_history
    for event in tracker_state.get("events"):
        if event.get("event") == "user":
            role = "user_id=" + user_id if user_id else "user"#如果有user_id则为"user_id=xxx"，否则为"user"
            chat_history.append(f"{role}:{event.get('text').strip()}")
        elif event.get("event") == "bot":
            chat_history.append(f"bot:{event.get('text').strip()}")

    #返回最近5条聊天记录，用换行符连接成一个字符串。（奇数条，最后一条为用户最后的提问，前面是成对的问答）
    return "\n".join(chat_history[-5:])


class GraphRAG(InformationRetrieval):
    """继承了 Rasa 的 InformationRetrieval"""

    def __init__(self, embeddings):
        super().__init__(embeddings)
        # 入口节点可选标签
        self.optional_label = (
            "- Category1:   一级分类，如“食品饮料”、“家用电器”、“手机”"
            "- Category2:   二级分类，如“大家电”、“香水彩妆”"
            "- Category3:   三级分类，如“手机”、“香水”、“笔记本”"
            "- Trademark:   品牌，如“华为”、“索芙特”、“金沙河”"
            "- SPU:         商品名称，如“华为Mate 40 pro”"
            "- SKU:         单品名称，如“联想（Lenovo） 拯救者Y9000P 2022 16英寸游戏笔记本电脑 i9-12900H RTX3070Ti 钛晶灰”"
            "- Attr:        商品属性值，如“70英寸”、“蓝色”、“非有机食品”"
            "- User:        用户ID，如“176”"
        )
        # 节点标签路由 prompt
        # PromptTemplate是基础的提示模板类，用于传统的文本生成场景：
        # ChatPromptTemplate是专为聊天模型设计的提示模板类（系统消息、用户消息、AI消息等，适合多轮对话）
        self.route_label_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    "你是一个智能检索路由Agent。"
                    "现在根据用户输入判断最可能需要的一个或多个标签以及每个标签对应的实体，作为后续Neo4j查询的入口节点\n"
                    "**注意：如果查询与用户相关，需要将用户信息加入入口节点**\n"
                    '以严格JSON格式输出结果，比如“[{{"label": "SPU", "entity": "iPhone 16 Pro"}}]”。'
                    "可选节点类型:\n{optional_label}"
                ),
                HumanMessagePromptTemplate.from_template("{query}"),
            ]
        )
        # Cypher 生成 prompt
        self.generate_cypher_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    "你是一个Cypher专家，正在根据入口节点信息和用户输入，参照schema生成准确无误的Cypher查询语句。"
                    "**注意：查询结果中不可以包含嵌入向量等多余属性**\n"
                    "仅返回Cypher语句。\n"
                    "schema:\n{schema}"
                ),
                HumanMessagePromptTemplate.from_template(
                    "入口节点:\n{entry_nodes}\n\n用户输入:\n{query}\n\nCypher语句:"
                ),
            ]
        )
        # Cypher 验证 prompt
        self.validate_cypher_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    "你是一位Cypher专家，正在审查一位初级开发人员编写的Cypher语句。你需要根据schema和用户输入，检查如下内容：\n"
                    "* Cypher语句中是否需要包含用户信息作为过滤条件？\n"
                    "* Cypher语句中是否有任何语法错误？\n"
                    "* Cypher语句中的关系方向是否符合schema中的定义？\n"
                    "* Cypher语句中是否漏定义了变量或使用了未定义的变量？\n"
                    "* Cypher语句检索出的内容能否用于回答用户的问题？\n"
                    '以严格列表格式输出错误信息，比如“["错误1", "错误2"]”，始终解释schema与Cypher语句之间的差异。'
                    "如果确认没有问题，返回空内容即可。\n"
                    "schema:\n{schema}"
                ),
                HumanMessagePromptTemplate.from_template(
                    "入口节点:\n{entry_nodes}\n\n"
                    "用户输入:\n{query}\n\n"
                    "待验证的Cypher语句:\n{cypher}"
                ),
            ]
        )
        # Cypher 校正 prompt
        self.correct_cypher_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    "你是一位Cypher专家，正在审查一位初级开发人员编写的Cypher语句。你需要根据schema以及提供的错误信息更正Cypher语句。"
                    "仅返回Cypher语句。\n"
                    "schema:\n{schema}"
                ),
                HumanMessagePromptTemplate.from_template(
                    "入口节点:\n{entry_nodes}\n\n"
                    "用户输入:\n{query}\n\n"
                    "错误信息:\n{errors}\n\n"
                    "待更正的Cypher语句:\n{cypher}\n\n"
                    "更正后的Cypher语句:"
                ),
            ]
        )

    def connect(self, config: EndpointConfig) -> None:
        """连接检索系统：连接到Neo4j数据库并初始化相关组件"""

        # 1、创建Neo4j驱动程序
        # 获取 endpoints.yml 下 vector_store 中的配置信息(rasa的api)
        neo4j_url = config.kwargs["neo4j_url"]
        neo4j_auth = tuple(config.kwargs["neo4j_auth"])  # 元组(用户名，密码)
        # Neo4j 驱动
        self.driver = GraphDatabase.driver(neo4j_url, auth=neo4j_auth)

        # 2、获取图数据库schema
        # Neo4j Graph 包装器
        neo4j_graph = Neo4jGraph(
            neo4j_url,
            neo4j_auth[0],  # 连接Neo4j数据库的用户名
            neo4j_auth[1],  # 连接Neo4j数据库的密码
            enhanced_schema=True  # 是否使用增强的schema信息，设为True 提供更详细的schema信息，包括节点标签、关系类型和属性等
        )
        # Neo4j schema
        self.neo4j_schema = neo4j_graph.schema
        # Neo4j 关系列表
        corrector_schema = [
            Schema(el["start"], el["type"], el["end"])
            for el in neo4j_graph.structured_schema.get("relationships")
        ]

        # 3、初始化 Cypher查询校正器（langchain提供的api）
        self.cypher_corrector = CypherQueryCorrector(corrector_schema)

        # 4、配置 LLM（使用coder模型，对语法处理效果更好）
        # model_name = "qwen3-coder-plus-2025-07-22"
        model_name = "qwen3-coder-480b-a35b-instruct"
        # model_name = "Moonshot-Kimi-K2-Instruct"
        dotenv.load_dotenv("../.env")
        model_api_key = os.getenv("API_KEY")
        # Tongyi：使用简单的字符串作为输入
        # ChatTongyi：使用消息对象列表，支持SystemMessage、HumanMessage、AIMessage等
        self.llm = ChatTongyi(model=model_name, api_key=model_api_key)

    async def route_label(self, query):
        """
        路由标签识别：识别标签，抽取实体
        使用LLM识别用户查询中涉及的节点类型和实体
        """

        # 1、填充prompt中的变量
        prompt = self.route_label_prompt.format_prompt(
            optional_label=self.optional_label, query=query
        )

        # 2、调用LLM，获得输出结果
        # with_structured_output方法：输出遵循指定的数据结构（指定的RouteOutput类）
        # 依赖于 function calling 或 tool calling 机制，LangChain 会将数据模型（如 RouteOutput）转换为工具定义（tool definition）
        llm_output = await self.llm.with_structured_output(RouteOutput).ainvoke(prompt)
        outputs = llm_output.outputs
        # 如果模型不支持 tool call，使用下面的方式
        # llm_output = await self.llm.ainvoke(prompt)
        # outputs = [RouteItem(**item) for item in json.loads(llm_output.content)]

        logger.info("入口节点标签与实体:%s", outputs)
        return outputs

    async def node_retrieval(self, route_res, top_k):
        """
        节点检索：根据标签和实体，检索入口节点
        对于用户节点直接通过Cypher查询获取，对于其他类型的节点则使用混合检索（向量+全文）进行检索
            route_res: 路由结果，包含标签和实体信息
            top_k: 检索返回的节点数量上限
        """
        pairs = []  # 用于存储需要检索的标签-实体对
        retrieved_nodes = {}  # 用于存储检索到的节点结果，以标签为键

        for i in route_res:
            if not i.entity:  # 遍历路由结果中的每一项，如果实体为空则跳过当前项
                continue
            if i.label == "User":  # 如果标签是"User"，则直接使用Cypher查询在数据库中查找用户节点。
                user_node = self.driver.execute_query(
                    "match (u:User) where u.user_id = $user_id return u;",
                    {"user_id": int(i.entity)},
                )
                retrieved_nodes.setdefault(i.label, []).append(user_node)  # 将结果添加到retrieved_nodes字典中
            else:  # 如果不是用户节点，则将标签和实体作为一个元组添加到pairs列表中，供后续检索使用
                pairs.append((i.label, i.entity))

        if not pairs:  # 如果没有需要检索的标签-实体对，直接返回已找到的节点（通常是用户节点）
            return retrieved_nodes

        # 将标签-实体对分离成两个独立的列表：labels和entities
        labels, entities = zip(*pairs)
        labels, entities = list(labels), list(entities)

        # 对每个实体进行中文分词处理，只保留中英文和数字字符，用" OR "连接，生成全文检索查询文本
        query_texts = [
            " OR ".join(
                [
                    word.strip()
                    for word in jieba.lcut(entity)
                    if re.fullmatch(r"[a-zA-Z0-9\u4e00-\u9fa5]+", word.strip())
                ]
            )
            for entity in entities
        ]
        # 对实体进行向量化处理，生成向量表示，用于向量检索
        query_vectors = self.embeddings.embed_documents(entities)

        # 为每个标签创建混合检索任务：
        # ，指定驱动程序和索引名称（和）
        tasks = []
        for label, query_text, query_vector in zip(labels, query_texts, query_vectors):
            # 创建HybridRetriever实例（neo4j_graphrag库）
            retriever = HybridRetriever(
                self.driver,
                vector_index_name=label.lower() + "_vector",  # 向量索引名称
                fulltext_index_name=label.lower() + "_fulltext",  # 全文索引名称
            )
            tasks.append(
                # 将同步的检索操作包装为异步任务，以支持并发执行
                asyncio.to_thread(
                    retriever.get_search_results,
                    query_text,
                    query_vector,
                    top_k,
                    effective_search_ratio=2,
                )
            )
        # 并发执行所有检索任务，并等待所有结果返回。
        results = await asyncio.gather(*tasks)

        # 处理检索结果
        for (label, _), result in zip(pairs, results): #遍历每一对标签和对应的检索结果
            # 根据标签类型构建结果格式，提取节点名称/值和得分，添加到retrieved_nodes字典中
            retrieved_nodes.setdefault(label, []).extend(
                # 对于非"Attr"标签，使用{标签名}_name作为键
                [
                    {
                        f"{label.lower()}_name": i["node"][f"{label.lower()}_name"],
                        "score": i["score"],
                    }
                    for i in result.records
                ]
                if label != "Attr"
                # 对于"Attr"标签，使用{标签名}_value作为键
                else [
                    {
                        f"{label.lower()}_value": i["node"][f"{label.lower()}_value"],
                        "score": i["score"],
                    }
                    for i in result.records
                ]
            )
        logger.info("入口节点:%s", retrieved_nodes)
        return retrieved_nodes

    async def generate_cypher(self, query, entry_nodes):
        """
        Cypher语句生成：生成 Cypher 语句
        用LLM根据入口节点和用户查询生成Cypher查询语句
        """

        # 1、填充prompt中的变量
        prompt = self.generate_cypher_prompt.format_prompt(
            schema=self.neo4j_schema, query=query, entry_nodes=entry_nodes
        )

        # 2、调用LLM
        # llm_output = self.llm.invoke(prompt)
        llm_output = await self.llm.ainvoke(prompt)

        # 3、使用neo4j_graphrag库的extract_cypher函数提取Cypher语句
        cypher = extract_cypher(llm_output.content)

        logger.info("Cypher生成:%s", cypher)
        return cypher

    async def validate_cypher(self, query, entry_nodes, cypher):
        """
        Cypher语句验证：验证 Cypher 语句
        使用 LLM 验证生成的Cypher语句的语法和逻辑正确性
        """

        # 1、验证 Cypher 语法
        errors = [] #错误列表，用于收集验证过程中发现的错误
        try:
            self.driver.execute_query(f"explain {cypher}") #通过explain关键字只检查语法而不实际执行
        except CypherSyntaxError as e: # 捕获语法错误并添加到错误列表中
            errors.append(e)

        # 2、验证 Cypher 逻辑是否符合用户查询意图
        prompt = self.validate_cypher_prompt.format_prompt(
            schema=self.neo4j_schema,
            query=query,
            cypher=cypher,
            entry_nodes=entry_nodes,
        )
        llm_output = await self.llm.ainvoke(prompt)

        errors.extend(json.loads(llm_output.content))
        logger.info("Cypher验证:%s", errors)
        return errors

    async def correct_cypher(self, query, entry_nodes, cypher, errors):
        """
        Cypher语句校正：校正 Cypher 语句
        使用 LLM 进行校正：如果验证失败，则根据错误信息校正Cypher语句。
        """

        # 1、填充prompt中的变量
        prompt = self.correct_cypher_prompt.format_prompt(
            schema=self.neo4j_schema,
            query=query,
            cypher=cypher,
            entry_nodes=entry_nodes,
            errors=errors,
        )

        # 2、调用LLM
        llm_output = await self.llm.ainvoke(prompt)

        # 3、使用neo4j_graphrag库的extract_cypher函数提取Cypher语句
        cypher = extract_cypher(llm_output.content)

        return cypher

    async def search(
            self, query: Text, tracker_state: dict[Text, Any], threshold: float = 0.8
    ) -> SearchResultList:
        """
        执行查询
        整个检索流程的主入口，按顺序执行各步骤并返回结果。
        """

        #如果查询为空，则返回一个包含"空"文档的搜索结果列
        query = (query or "").strip()
        if not query:
            return SearchResultList.from_document_list([Document("空")])
        # 获取用户ID
        user_id = tracker_state.get("slots", {}).get("user_id")
        # 获取聊天历史
        chat_history = get_chat_history(tracker_state, user_id)
        # 获取入口节点标签
        route_res = await self.route_label(chat_history)
        # 检索入口节点
        entry_nodes = await self.node_retrieval(route_res, 10)
        # 生成 Cypher 语句
        cypher = await self.generate_cypher(query, entry_nodes)
        # 验证 Cyoher 语句
        errors = await self.validate_cypher(query, entry_nodes, cypher)
        # 校正 Cyoher 语句
        if errors:
            cypher = await self.correct_cypher(query, entry_nodes, cypher, errors)
        # 校正关系方向。如果某个关系和其反向关系都不合法，会返回空字符串
        cypher = self.cypher_corrector(cypher)
        logger.info("Cypher校正:%s", cypher)
        # 执行 Cypher 语句
        # SearchResultList：rasa中一个专门用于存储搜索结果的类
        res = SearchResultList.from_document_list([Document("空")])
        try:
            records = self.driver.execute_query(cypher).records
            docs = [Document(str(dict(rec))) for rec in records]
            res = SearchResultList.from_document_list(docs)
        except Exception as e:
            logger.warning("执行Cypher语句异常: %s", e)
        logger.info("检索结果: %s", res)
        return res


if __name__ == "__main__":
    # 检索测试
    import os
    from langchain_core.embeddings import Embeddings
    from sentence_transformers import SentenceTransformer

    neo4j_url = "neo4j://127.0.0.1"
    neo4j_auth = ("neo4j", "12345678")


    class BgeEmbedding(Embeddings):
        """定义嵌入模型"""

        def __init__(self):
            self.model = SentenceTransformer("../models/bge-base-zh-v1.5")

        def embed_query(self, text: str) -> list[float]:
            return self.embed_documents([text])[0]

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            embeddings = self.model.encode(
                texts, batch_size=64, normalize_embeddings=True
            )
            return [list(map(float, emb)) for emb in embeddings]


    async def test_retrieval(query):
        """测试检索过程"""
        retrieval_config = EndpointConfig(
            neo4j_url=neo4j_url,
            neo4j_auth=neo4j_auth,
        )
        graphrag = GraphRAG(BgeEmbedding())
        graphrag.connect(retrieval_config)
        await graphrag.search(
            query,
            {
                "slots": {"user_id": "25"},
                "events": [{"event": "user", "text": query}],
            },
        )


    query = "手机有哪些商品？"
    query = "白色256GB的手机有哪些？"
    query = "非有机的大米有哪些，都是什么品牌的？"
    query = "我想找一款16英寸左右，32G内存2TB硬盘的笔记本，屏幕要求2.5K以上"
    query = "我之前看到过一款平板电视还不错，我记得是70多寸8K的，能帮我找下是哪个吗"  # 切换用户17
    query = "有没有带保湿功能的润唇膏，都是什么品牌的，帮我详细介绍下"
    query = "帮我推荐oppo的手机"
    asyncio.run(test_retrieval(query))

