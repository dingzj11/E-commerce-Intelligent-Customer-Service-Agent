# 电商智能客服 Agent (E-commerce Intelligent Customer Service Agent)

[English](#english) | [中文](#chinese)

---

<a name="english"></a>

## Overview

A production-grade **e-commerce intelligent customer service chatbot** built on **Rasa Pro (CALM)** with **GraphRAG** knowledge retrieval and enterprise-level **Redis distributed infrastructure**. The system handles the full customer service lifecycle: order management, logistics tracking, after-sales (returns/refunds/exchanges), and knowledge-based product Q&A.

> **Highlight**: Designed specifically to demonstrate **backend engineering depth** in AI agent systems — covering NLP pipeline, dialogue management, knowledge graph, distributed systems patterns, and LLM integration.

## Key Features

### Conversational AI
| Feature | Tech |
|---------|------|
| **Flow-based Dialogue** | Rasa Pro CALM (Conversational AI with Language Models) |
| **Multi-intent NLU** | LLM-powered command generator (Qwen-Plus) |
| **Contextual Rephrasing** | NLG response rephraser for natural language generation |
| **Multi-turn Slot Filling** | Custom actions for structured data collection |

### Knowledge Retrieval (GraphRAG)
| Feature | Tech |
|---------|------|
| **Hybrid Retrieval** | Vector similarity + Full-text search via Neo4j |
| **Text-to-Cypher** | LLM generates, validates, and corrects Cypher queries |
| **Chinese Embedding** | BGE-base-zh-v1.5 with FastAPI serving |
| **Entity Linking** | Automatic label routing + entity extraction |

### Distributed Systems (Redis)
| Feature | Description |
|---------|-------------|
| **Distributed Lock** | SET NX + Lua atomic release + Watchdog renewal + Redlock (multi-instance) |
| **Cache Strategies** | 3-layer protection: penetration (null cache), breakdown (mutex), avalanche (TTL jitter) |
| **Rate Limiter** | Sliding window counter per user / IP / global |
| **Idempotency** | Request de-duplication via Redis SET NX |
| **Distributed ID** | Snowflake-like ID generator |
| **Bloom Filter** | Cache penetration prevention |
| **Delay Queue** | Redis ZSET-based delayed task execution |
| **Stream Processing** | Redis Stream for event-driven architecture |

### Business Actions
- **Order Management**: Query, cancel, modify shipping address
- **Logistics Tracking**: Real-time tracking, carrier listing, complaint filing
- **After-Sales**: Refund/return/exchange with auto-approval (7-day policy)
- **Data Generation**: Faker-based test data with realistic distributions

### NLP Models (graph/)
- Intent Classification (BERT-based)
- Spell Checking (BERT + T5)
- Information Extraction (UIE — Universal Information Extraction)

## Architecture

```
                     ┌──────────────────────────┐
                     │     User (WebSocket/      │
                     │     REST/WeChat)          │
                     └────────────┬─────────────┘
                                  │
                     ┌────────────▼─────────────┐
                     │    Rasa Pro Server        │
                     │  ┌─────────────────────┐  │
                     │  │  NLU Pipeline        │  │
                     │  │  (LLM Command Gen)   │  │
                     │  ├─────────────────────┤  │
                     │  │  Dialogue Policies   │  │
                     │  │  (FlowPolicy +       │  │
                     │  │   EnterpriseSearch)  │  │
                     │  └─────────────────────┘  │
                     └──┬──────────┬──────────┬──┘
                        │          │          │
          ┌─────────────▼──┐  ┌───▼────┐  ┌─▼──────────────┐
          │  Custom Actions │  │ Redis  │  │  GraphRAG       │
          │  (Order/Log/    │  │ (Lock/ │  │  (Neo4j + LLM)  │
          │   Postsale)     │  │ Cache/ │  │                  │
          └───────┬─────────┘  │ Rate/  │  └─────┬────────────┘
                  │            │ Stream)│        │
          ┌───────▼─────────┐  └───────┘  ┌─────▼────────────┐
          │  MySQL           │             │  Embedding       │
          │  (Orders/Users/  │             │  Service         │
          │   Products)      │             │  (FastAPI/BGE)   │
          └─────────────────┘             └──────────────────┘
```

## Project Structure

```
Smart-Service-Online/
├── actions/                     # Rasa Custom Actions
│   ├── db.py                    #   Database connection pool
│   ├── db_table_class.py        #   SQLAlchemy ORM models
│   ├── action_order.py          #   Order management actions
│   ├── action_logistics.py      #   Logistics tracking actions
│   └── action_postsale.py       #   After-sales service actions
│
├── core/                        # Redis Distributed Infrastructure
│   ├── config.py                #   Centralized configuration (dataclass)
│   ├── redis_client.py          #   Redis client (Pipeline/Lua/HLL/BitMap/GEO)
│   ├── distributed_lock.py      #   Distributed lock + Redlock
│   ├── distributed_id.py        #   Snowflake-like ID generator
│   ├── cache_decorator.py       #   Cache decorators (@cacheable)
│   ├── rate_limiter.py          #   Sliding window rate limiter
│   ├── idempotency.py           #   Request idempotency
│   ├── redis_bloom.py           #   Bloom filter
│   ├── redis_delay_queue.py     #   Delayed task queue
│   ├── redis_stream.py          #   Event stream
│   └── redis_transaction.py     #   Redis transactions
│
├── addons/                      # Rasa Extensions
│   ├── information_retrieval.py #   GraphRAG knowledge retrieval
│   ├── embed_service.py         #   Embedding model HTTP API
│   └── create_indexing.py       #   Neo4j index creation
│
├── data/flows/                  # Dialogue flow definitions
├── domain/                      # Domain (intents, entities, slots, responses)
├── graph/src/                   # NLP model training/inference code
├── e2e_tests/                   # End-to-end conversation tests
├── examples/                    # Usage examples
├── scripts/                     # Utility scripts
├── gen_data.py                  # Test data generator
├── config.yml                   # Rasa NLU pipeline & policies
├── endpoints.yml                # External services configuration
├── credentials.yml              # Channel credentials
└── requirements.txt             # Python dependencies
```

## Quick Start

### Prerequisites

- Python 3.10+
- Redis 7.0+
- MySQL 8.0+
- Neo4j 5.x+
- [Rasa Pro License](https://rasa.com/rasa-pro/) (free for development)

### Setup

```bash
# 1. Clone
git clone https://github.com/dingzj11/E-commerce-Intelligent-Customer-Service-Agent.git
cd E-commerce-Intelligent-Customer-Service-Agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys and database credentials

# 4. Download embedding model weights
bash scripts/download_models.sh

# 5. Set up databases (MySQL, Neo4j, Redis)

# 6. Generate test data (optional)
python gen_data.py

# 7. Start embedding service
cd addons && python embed_service.py &

# 8. Train and run Rasa
rasa train
rasa run --enable-api
```

## Technology Stack

| Category | Technologies |
|----------|-------------|
| **Dialogue Framework** | Rasa Pro 3.10+ (CALM) |
| **LLM** | Qwen-Plus / Qwen3-8B (with LoRA fine-tuning) |
| **Embedding** | BGE-base-zh-v1.5 (Sentence Transformers) |
| **Graph Database** | Neo4j 5.x |
| **Relational DB** | MySQL 8.0 + SQLAlchemy 2.0 |
| **Cache/Lock/Queue** | Redis 7.0 (Standalone / Sentinel / Cluster) |
| **Web Framework** | FastAPI + Uvicorn |
| **NLP** | Transformers, jieba |
| **Test Data** | Faker |

## Interview Knowledge Points (面试知识点)

If you're using this project on your resume, here are the key concepts to be familiar with:

### Redis
- **Cache Penetration, Breakdown, Avalanche** (缓存穿透/击穿/雪崩) — all three protections implemented
- **Distributed Lock**: `SET NX EX` atomic operation, Lua script release, Watchdog auto-renewal
- **Redlock Algorithm**: multi-instance majority-vote lock (antirez proposal + Martin Kleppmann critique)
- **Optimistic Locking (WATCH/MULTI/EXEC)** vs **Pessimistic Locking (Distributed Lock)**
- **Redis Data Structures**: HyperLogLog (UV), BitMap (sign-in), GEO (nearby stores)
- **Pipeline**: reduce RTT, not the same as MULTI/EXEC transaction

### AI Agent
- **CALM**: Conversational AI with Language Models — flow-based dialogue
- **GraphRAG**: hybrid retrieval (vector + full-text) + LLM Text-to-Cypher
- **LLM Fine-tuning**: Qwen3-8B LoRA PEFT
- **Embedding**: dense retrieval with bi-encoder models
- **Multi-turn Dialogue**: slot filling, intent classification, entity extraction

### System Design
- **Distributed ID Generation**: Snowflake algorithm
- **Rate Limiting**: sliding window counter pattern
- **Idempotency**: request de-duplication in distributed systems
- **Connection Pool**: SQLAlchemy QueuePool configuration
- **Configuration Management**: environment-variable-driven, 12-factor app compliant

---

<a name="chinese"></a>

## 项目简介

基于 **Rasa Pro (CALM)** 构建的生产级**电商智能客服聊天机器人**，集成了 **GraphRAG 知识检索** 和企业级 **Redis 分布式基础设施**。系统涵盖客服全流程：订单管理、物流追踪、售后服务（退款/退货/换货）以及知识型商品问答。

> **核心价值**: 展示 AI Agent 系统中的**后端工程深度** — NLP 管线、对话管理、知识图谱、分布式系统模式、LLM 集成。

## 核心亮点

### 对话 AI
- **Flow 流程对话**: Rasa Pro CALM 多轮对话管理
- **LLM 意图识别**: Qwen-Plus 驱动的命令生成器
- **上下文重述**: NLG 自然语言响应生成
- **多轮槽位填充**: 结构化数据采集的自定义 Action

### 知识检索 (GraphRAG)
- **混合检索**: Neo4j 向量相似度 + 全文搜索
- **Text-to-Cypher**: LLM 生成→验证→校正 Cypher 查询
- **中文嵌入**: BGE-base-zh-v1.5 + FastAPI 服务
- **实体链接**: 自动标签路由 + 实体抽取

### 分布式系统 (Redis)
| 功能模块 | 技术实现 |
|---------|---------|
| 分布式锁 | Redis SET NX + Lua 原子释放 + 看门狗续期 + Redlock 多实例 |
| 缓存策略 | 三防：穿透(空值缓存)、击穿(互斥锁)、雪崩(TTL 随机化) |
| 限流器 | 滑动窗口计数器 (用户/IP/全局三级) |
| 幂等性 | Redis SET NX 请求去重 |
| 分布式 ID | Snowflake 雪花算法 |
| 布隆过滤器 | 缓存穿透前置防护 |
| 延迟队列 | Redis ZSET 实现延迟任务 |
| Stream | 事件驱动消息流 |

### 业务功能
- 订单管理：查询、取消、修改收货地址
- 物流追踪：实时轨迹、快递公司列表、投诉
- 售后服务：退款/退货/换货（含 7 天无理由自动审核）
- 数据生成：Faker 模拟真实分布的测试数据

### NLP 模型 (graph/)
- 意图分类 (BERT)
- 拼写纠错 (BERT + T5)
- 通用信息抽取 (UIE)

## 快速开始

### 环境要求

- Python 3.10+
- Redis 7.0+
- MySQL 8.0+
- Neo4j 5.x+
- [Rasa Pro License](https://rasa.com/rasa-pro/) (开发环境免费)

### 安装步骤

```bash
git clone https://github.com/dingzj11/E-commerce-Intelligent-Customer-Service-Agent.git
cd E-commerce-Intelligent-Customer-Service-Agent
pip install -r requirements.txt
cp .env.example .env  # 编辑 .env 填入 API Key 和数据库配置
bash scripts/download_models.sh  # 下载模型权重

# 启动嵌入模型服务
cd addons && python embed_service.py &

# 训练并启动 Rasa
rasa train
rasa run --enable-api
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 对话框架 | Rasa Pro 3.10+ (CALM) |
| 大语言模型 | Qwen-Plus / Qwen3-8B (LoRA 微调) |
| 嵌入模型 | BGE-base-zh-v1.5 |
| 图数据库 | Neo4j 5.x |
| 关系数据库 | MySQL 8.0 + SQLAlchemy 2.0 |
| 缓存/锁/队列 | Redis 7.0 (单机/哨兵/集群) |
| Web 框架 | FastAPI + Uvicorn |
| NLP | Transformers, jieba |

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

> **Note**: Rasa Pro requires a separate license. This project only includes the configuration and custom code built on top of Rasa Pro.
