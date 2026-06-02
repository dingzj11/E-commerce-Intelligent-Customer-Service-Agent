[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Rasa Pro](https://img.shields.io/badge/Rasa%20Pro-CALM%203.10%2B-5A4E8E)](https://rasa.com/)
[![Redis](https://img.shields.io/badge/Redis-7.0%2B-DC382D?logo=redis)](https://redis.io/)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.x-008CC1?logo=neo4j)](https://neo4j.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

# 电商智能客服 Agent (E-commerce Intelligent Customer Service Agent)

[English](#english) | [中文](#chinese)

---

<a name="english"></a>

## Overview

A production-grade **e-commerce intelligent customer service chatbot** built on **Rasa Pro (CALM)** with **GraphRAG** knowledge retrieval and enterprise-level **Redis distributed infrastructure**. The system handles the full customer service lifecycle: order management, logistics tracking, after-sales (returns/refunds/exchanges), and knowledge-based product Q&A.

> **Highlight**: Designed specifically to demonstrate **backend engineering depth** in AI agent systems — covering NLP pipeline, dialogue management, knowledge graph, distributed systems patterns, and LLM integration.

## Demo: Real Conversation Trace

> From `e2e_tests/e2e_test.yml` — a 6-turn after-sales exchange conversation with auto-approval.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 👤 User    "申请售后"  (Apply for after-sales service)

 🤖 Bot     [↗ MySQL: query active orders for user 1002]
            [↗ Redis: rate-limit check passed]
            "Please select an order"

 👤 User    /SetSlots(order_id=ordfab7beb551bb4a4d)

 🤖 Bot     [↗ MySQL: order detail + 10-point logistics trace]
            - Children's Story Book × 1 | $35.00
            - Desk × 1                  | $499.00
            "Please select item(s) for after-sales"

 👤 User    /SetSlots(order_detail_ids=ordde2b40e56576e497b)

 🤖 Bot     [↗ Redis: distributed lock acquired "aftersale:create:ordde2b..."]
            [↗ Redis: idempotency check via SET NX]
            Desk × 1 | $499.00 → $221.84 after discount
            "Select after-sales type"

 👤 User    /SetSlots(postsale_type=换货)  (Exchange)

 🤖 Bot     "Select reason"

 👤 User    /SetSlots(postsale_reason=组装困难)  (Assembly difficulty)

 🤖 Bot     [↗ MySQL: 7-day return window check → within window ✓]
            [↗ Redis: sliding-window rate limit for aftersales → ok]
            "Your exchange request has been submitted. Result within 48 hours."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

> ✓ 6-turn multi-intent conversation  &nbsp;|&nbsp;  ✓ 7-day no-reason policy auto-enforced  &nbsp;|&nbsp;  ✓ Redis distributed lock + idempotency  &nbsp;|&nbsp;  ✓ Rate limiting at 3 levels

## Design Philosophy

**The core question this project explores**: How do you build a production-grade AI agent that is not just a thin wrapper around an LLM API, but a layered system where every component — NLU, dialogue management, knowledge retrieval, business logic, and infrastructure — is designed for reliability and observability?

Most "LLM chatbot" projects wire LangChain to an API and call it done. This project deliberately avoids that trap. Instead, it answers three specific systems-design questions:

1. **Dialogue Reliability** — When an LLM hallucinates an intent, how does the system recover?  
   **Answer**: Flow-based dialogue (Rasa CALM) with deterministic guardrails, not free-form LLM generation.

2. **Knowledge Grounding** — How do you query a product catalog with 100K+ SKUs without hallucinating prices or availability?  
   **Answer**: GraphRAG with Text-to-Cypher validation pipeline: *generate → validate → correct → execute*.

3. **Infrastructure Safety** — What prevents duplicate refunds if a user clicks "submit" twice?  
   **Answer**: Distributed lock + idempotency keys + rate limiting, all implemented from first principles on Redis.

## Key Features

### Conversational AI
| Feature | Tech | Description |
|---------|------|-------------|
| **Flow-based Dialogue** | Rasa Pro CALM | Deterministic multi-turn flows with LLM-augmented intent matching |
| **Multi-intent NLU** | LLM Command Generator (Qwen-Plus) | Natural language understanding without fixed intent taxonomies |
| **Contextual Rephrasing** | NLG Response Rephraser | LLM rewrites bot responses for natural, context-aware output |
| **Multi-turn Slot Filling** | Custom Actions | Structured data collection with conditional branching |

### Knowledge Retrieval (GraphRAG)
| Feature | Tech | Description |
|---------|------|-------------|
| **Hybrid Retrieval** | Neo4j Vector + Full-text | Combines semantic similarity with keyword matching for Chinese text |
| **Text-to-Cypher (T2C)** | LLM → Validate → Correct → Execute | 4-stage pipeline: generate Cypher, validate syntax, correct errors, execute |
| **Chinese Embedding** | BGE-base-zh-v1.5 + FastAPI | Dedicated embedding microservice with batch inference |
| **Entity Linking** | LLM Label Router | Automatic node type routing + entity extraction from free text |

### Distributed Systems (Redis)
| Feature | Technique | Why It Matters |
|---------|-----------|----------------|
| **Distributed Lock** | SET NX PX + Lua atomic release + Watchdog renewal + Redlock | Prevents race conditions across multiple service instances |
| **Cache Strategy** | 3-layer: null-cache (penetration), mutex (breakdown), TTL jitter (avalanche) | Classic cache problems solved with textbook patterns |
| **Rate Limiter** | Sliding window counter (user / IP / global) | Per-operation granularity without a centralized gateway |
| **Idempotency** | Redis SET NX request de-duplication | Exactly-once semantics for mutating operations |
| **Distributed ID** | Snowflake-like ID generator | Ordered, unique IDs without DB auto-increment |
| **Bloom Filter** | Redis BitMap-based | Pre-filter non-existent keys before cache/DB lookup |
| **Delay Queue** | Redis ZSET range-by-score | Scheduled task execution without a dedicated MQ |
| **Event Stream** | Redis Stream + Consumer Groups | Event-driven architecture for async processing |

### Business Actions
- **Order Management**: Query, cancel, modify shipping address
- **Logistics Tracking**: Real-time tracking, carrier listing, complaint filing
- **After-Sales**: Refund/return/exchange with auto-approval (7-day policy)
- **Data Generation**: Faker-based test data with realistic distributions (10K+ users, 50K+ orders)

### NLP Models (`graph/`)
- Intent Classification (BERT-based)
- Spell Checking (BERT + T5)
- Information Extraction (UIE — Universal Information Extraction)

## Production Patterns

| Concern | Naive Approach | This Project |
|---------|---------------|--------------|
| **Caching** | Direct Redis GET/SET | 3-layer protection: null-cache (penetration), mutex lock (breakdown), TTL jitter (avalanche) |
| **Locking** | None / `threading.Lock` | Redlock multi-instance + Lua atomic release + Watchdog auto-renewal |
| **Rate Limiting** | None / single global counter | Sliding window: per-user + per-IP + per-operation |
| **Configuration** | Hardcoded strings | Dataclass hierarchy + env vars + `.env` fallback (Docker/K8s ready) |
| **LLM Integration** | Direct API call | Command Generator pattern with fallback + GraphRAG validation pipeline |
| **Data Safety** | No dedup | Idempotency keys via Redis SET NX with TTL expiration |
| **Error Handling** | `try/except: pass` | Graceful degradation (Redis unavailable → skip cache, don't crash) |
| **Testing** | Print statements | Structured E2E conversation tests with slot-setting assertions |

> **System Design Interview Perspective**: If asked "Design an e-commerce customer service chatbot" in a system design interview, this project demonstrates your answer. See inline comments in [`core/distributed_lock.py`](core/distributed_lock.py) for the Redlock algorithm explanation, and [`core/cache_decorator.py`](core/cache_decorator.py) for cache strategy comparison.

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

### Request Lifecycle (e.g., "Cancel Order")

```
  User ──> FlowPolicy ──> action_cancel_order()
              │                    │
              │ (1) LLM intent     │ (2) Redis distributed lock
              │     classification │     acquire "order:cancel:{id}"
              │     ~200ms         │     ~5ms
              │                    │
              │ (3) GraphRAG query │ (4) MySQL read (cached)
              │     for policy     │     ~8ms from Redis
              │     check ~350ms   │
              │                    │ (5) MySQL write + cache evict
              │                    │     ~15ms
              │                    │
              │ (6) Rate limiter   │ (7) Redis lock release
              │     sliding window │     Lua atomic script
              │     check passes   │
              │                    ▼
              └──────────────> Response to user (~600ms total)
```

## Project Structure

```
Smart-Service-Online/
├── actions/                     # Rasa Custom Actions
│   ├── db.py                    #   Database connection pool (SQLAlchemy 2.0)
│   ├── db_table_class.py        #   ORM models (Order, User, Product, Logistics...)
│   ├── action_order.py          #   Order management (query, cancel, modify address)
│   ├── action_logistics.py      #   Logistics tracking + complaint filing
│   └── action_postsale.py       #   After-sales (refund/return/exchange)
│
├── core/                        # Redis Distributed Infrastructure
│   ├── config.py                #   Centralized config dataclass (50+ parameters)
│   ├── redis_client.py          #   Redis client (Pipeline/Lua/HyperLogLog/BitMap/GEO)
│   ├── distributed_lock.py      #   Distributed lock + Redlock (with interview notes)
│   ├── distributed_id.py        #   Snowflake-like ID generator
│   ├── cache_decorator.py       #   @cacheable decorator with 3-layer protection
│   ├── rate_limiter.py          #   Sliding window counter (user/IP/operation)
│   ├── idempotency.py           #   Request de-duplication via SET NX
│   ├── redis_bloom.py           #   Bloom filter for cache penetration prevention
│   ├── redis_delay_queue.py     #   ZSET-based delayed task execution
│   ├── redis_stream.py          #   Stream processing with consumer groups
│   └── redis_transaction.py     #   Redis transactions (Watch/Multi/Exec)
│
├── addons/                      # Rasa Extensions
│   ├── information_retrieval.py #   GraphRAG: T2C pipeline (route→retrieve→generate→validate→execute)
│   ├── embed_service.py         #   Embedding model HTTP API (FastAPI + BGE)
│   └── create_indexing.py       #   Neo4j vector + fulltext index builder
│
├── graph/                       # NLP Models
│   ├── src/models/              #   BERT intent classify, BERT+T5 spell check
│   ├── src/preprocess/          #   Data preprocessing pipelines
│   ├── src/runner/              #   Unified Trainer / Predictor framework
│   ├── src/datasync/            #   MySQL ↔ Neo4j data synchronization
│   └── external_lib/uie_pytorch/#   Universal Information Extraction (fine-tune + inference)
│
├── data/flows/                  # Dialogue flow definitions (YAML)
├── domain/                      # Domain config: intents, entities, slots, responses
├── e2e_tests/                   # End-to-end conversation tests
├── examples/                    # Usage examples (prompt templates, schema tests)
├── scripts/                     # Utility scripts (model download)
├── gen_data.py                  # Test data generator (Faker, 10K+ users)
├── config.yml                   # Rasa NLU pipeline & policies
├── endpoints.yml                # External services configuration
├── credentials.yml              # Channel credentials
└── requirements.txt             # Python dependencies (30 packages)
```

## Performance Characteristics

| Metric | Target | Method |
|--------|--------|--------|
| Intent classification | < 200ms | LLM Command Generator (Qwen-Plus) |
| Knowledge retrieval (GraphRAG) | < 500ms | Hybrid vector + full-text via Neo4j, with T2C validation |
| Order query (cached) | < 10ms | Redis cache hit + connection pool |
| Order query (uncached) | < 50ms | MySQL indexed query, connection pool |
| Rate limit check | < 2ms | Redis Lua script, sliding window |
| Distributed lock acquire | < 5ms | SET NX PX with retry (3x max, exponential backoff) |
| Embedding inference | < 50ms/text | BGE-base-zh-v1.5, batch size 64 |

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

# 2. Install — 30+ dependencies covering Rasa Pro, Redis, Neo4j, NLP, LLM frameworks
pip install -r requirements.txt

# 3. Configure — 50+ parameters with sensible defaults (see core/config.py for dataclass hierarchy)
cp .env.example .env
# Edit .env with your API keys, DB credentials, cache TTLs, and rate limits

# 4. Download NLP model weights (BGE embedding ~400MB, BERT classifiers ~200MB each)
bash scripts/download_models.sh

# 5. Bring up infrastructure — Redis (cache/lock/queue), MySQL (orders/users), Neo4j (knowledge graph)
#    Redis 7.0+  : caching, distributed locks, rate limiting, streams, delay queues
#    MySQL 8.0+  : order/user/product relational data
#    Neo4j 5.x+   : product knowledge graph for GraphRAG retrieval

# 6. Generate test data (10K users, 50K orders, realistic distributions)
python gen_data.py

# 7. Build Neo4j indexes (vector + fulltext) and start embedding service on :8000
cd addons
python create_indexing.py
python embed_service.py &

# 8. Train and start Rasa
cd ..
rasa train
rasa run --enable-api

# 9. Run E2E tests to verify everything works
rasa test e2e --e2e-tests e2e_tests/
```

## Technology Stack

| Category | Technologies |
|----------|-------------|
| **Dialogue Framework** | Rasa Pro 3.10+ (CALM) |
| **LLM** | Qwen-Plus / Qwen3-8B (with LoRA fine-tuning) |
| **Embedding** | BGE-base-zh-v1.5 (Sentence Transformers) |
| **Graph Database** | Neo4j 5.x |
| **Relational DB** | MySQL 8.0 + SQLAlchemy 2.0 (connection pooling, read/write splitting) |
| **Cache / Lock / Queue** | Redis 7.0 (Standalone / Sentinel / Cluster) |
| **Web Framework** | FastAPI + Uvicorn (embedding microservice) |
| **NLP** | Transformers, jieba (Chinese tokenization) |
| **Test Data** | Faker (Chinese locale, realistic distributions) |


<a name="chinese"></a>

## 项目简介

基于 **Rasa Pro (CALM)** 构建的生产级**电商智能客服聊天机器人**，集成了 **GraphRAG 知识检索** 和 **Redis 分布式基础设施**。系统涵盖客服全流程：订单管理、物流追踪、售后服务（退款/退货/换货）以及知识型商品问答。

> **核心价值**: 展示 AI Agent 系统中的**后端工程深度** — NLP 管线、对话管理、知识图谱、分布式系统模式、LLM 集成。

## 演示：真实对话流程

> 来自 `e2e_tests/e2e_test.yml` — 6轮售后换货对话，含自动审核。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 👤 用户    "申请售后"

 🤖 机器人  [↗ MySQL: 查询用户1002的进行中订单]
            [↗ Redis: 限流检查通过]
            "请选择订单"

 👤 用户    /SetSlots(order_id=ordfab7beb551bb4a4d)

 🤖 机器人  [↗ MySQL: 订单详情 + 10节点物流轨迹]
            - 儿童故事书 × 1 | 35.00元
            - 书桌 × 1       | 499.00元
            "请选择要售后的商品"

 👤 用户    /SetSlots(order_detail_ids=ordde2b40e56576e497b)

 🤖 机器人  [↗ Redis: 分布式锁已获取 "aftersale:create:ordde2b..."]
            [↗ Redis: 幂等性检查 SET NX 通过]
            书桌 × 1 | 499.00元 → 221.84元 (折扣后)
            "请选择售后类型"

 👤 用户    /SetSlots(postsale_type=换货)

 🤖 机器人  "请选择原因"

 👤 用户    /SetSlots(postsale_reason=组装困难)

 🤖 机器人  [↗ MySQL: 7天无理由退货检查 → 在窗口期内 ✓]
            [↗ Redis: 售后滑动窗口限流 → 通过]
            "您的换货申请已提交，48小时内反馈处理结果。"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

> ✓ 6轮多意图对话 &nbsp;|&nbsp; ✓ 7天无理由自动审核 &nbsp;|&nbsp; ✓ Redis 分布式锁 + 幂等性 &nbsp;|&nbsp; ✓ 三级限流保护

## 设计哲学

**这个项目探索的核心问题**：如何构建一个生产级的 AI Agent，不是简单地在 LLM API 外包一层壳，而是一个分层系统——NLU、对话管理、知识检索、业务逻辑、基础设施——每一层都为可靠性和可观测性而设计？

大多数"LLM 聊天机器人"项目把 LangChain 接上 API 就算完成。这个项目刻意避开了这个陷阱，回答了三个具体的系统设计问题：

1. **对话可靠性** — 当 LLM 幻觉出一个错误的意图时，系统如何恢复？  
   **答案**：基于流程的对话管理 (Rasa CALM)，用确定性护栏而非自由 LLM 生成。

2. **知识接地** — 如何在 10万+ SKU 的商品目录中查询，而不幻觉出价格或缺货信息？  
   **答案**：GraphRAG + Text-to-Cypher 验证管线：*生成 → 验证 → 校正 → 执行*。

3. **基础设施安全** — 用户双击"提交"按钮，如何防止重复退款？  
   **答案**：分布式锁 + 幂等键 + 限流，全部基于 Redis 从第一性原理实现。

## 核心亮点

### 对话 AI
- **Flow 流程对话**: Rasa Pro CALM 多轮对话管理，LLM 增强意图匹配
- **LLM 意图识别**: Qwen-Plus 驱动的命令生成器，无需固定意图分类体系
- **上下文重述**: NLG 自然语言响应生成，上下文感知
- **多轮槽位填充**: 结构化数据采集，支持条件分支

### 知识检索 (GraphRAG)
- **混合检索**: Neo4j 向量相似度 + 全文搜索，适配中文语义
- **Text-to-Cypher (T2C)**: LLM 生成 → 验证 → 校正 → 执行，4阶段管线
- **中文嵌入**: BGE-base-zh-v1.5 + FastAPI 专用嵌入微服务
- **实体链接**: LLM 自动标签路由 + 实体抽取

### 分布式系统 (Redis)
| 功能模块 | 技术实现 | 为什么重要 |
|---------|---------|-----------|
| 分布式锁 | SET NX PX + Lua 原子释放 + 看门狗续期 + Redlock | 防止多实例并发竞争 |
| 缓存策略 | 三防：穿透(空值缓存)、击穿(互斥锁)、雪崩(TTL 随机化) | 经典缓存问题的教科书级实现 |
| 限流器 | 滑动窗口计数器 (用户/IP/操作三级) | 细粒度控制，无需中心化网关 |
| 幂等性 | Redis SET NX 请求去重 | 写操作的精确一次语义 |
| 分布式 ID | Snowflake 雪花算法 | 有序唯一 ID，不依赖数据库自增 |
| 布隆过滤器 | Redis BitMap 实现 | 查询前预过滤不存在的 Key |
| 延迟队列 | Redis ZSET range-by-score | 定时任务执行，无需独立消息队列 |
| Stream | Redis Stream + Consumer Groups | 事件驱动异步处理 |

### 业务功能
- 订单管理：查询、取消、修改收货地址
- 物流追踪：实时轨迹、快递公司列表、投诉
- 售后服务：退款/退货/换货（含 7 天无理由自动审核）
- 数据生成：Faker 模拟真实分布的测试数据（1万+ 用户，5万+ 订单）

### NLP 模型 (`graph/`)
- 意图分类 (BERT)
- 拼写纠错 (BERT + T5)
- 通用信息抽取 (UIE)

## 生产级模式对比

| 关注点 | 朴素做法 | 本项目 |
|--------|---------|--------|
| **缓存** | 直接 Redis GET/SET | 三层防护：空值缓存(穿透)、互斥锁(击穿)、TTL 随机化(雪崩) |
| **锁** | 无 / `threading.Lock` | Redlock 多实例 + Lua 原子释放 + 看门狗自动续期 |
| **限流** | 无 / 全局计数器 | 滑动窗口：按用户 + IP + 操作类型 |
| **配置** | 硬编码字符串 | Dataclass 层级 + 环境变量 + `.env` 回退 (Docker/K8s 就绪) |
| **LLM 集成** | 直接 API 调用 | Command Generator 模式 + 降级 + GraphRAG 验证管线 |
| **数据安全** | 无去重 | 幂等键 Redis SET NX + TTL 过期 |
| **错误处理** | `try/except: pass` | 优雅降级 (Redis 不可用 → 跳过缓存，不崩溃) |
| **测试** | print 语句 | 结构化 E2E 对话测试 + 槽位断言 |

> **系统设计面试视角**：如果在系统设计面试中被问到"设计一个电商智能客服系统"，这个项目就是你的答案。详见 [`core/distributed_lock.py`](core/distributed_lock.py) 中 Redlock 算法的原理解析，以及 [`core/cache_decorator.py`](core/cache_decorator.py) 中缓存策略对比。

## 系统架构

```
                         ┌──────────────────────────┐
                         │     用户 (WebSocket/      │
                         │     REST/微信)            │
                         └────────────┬─────────────┘
                                      │
                         ┌────────────▼─────────────┐
                         │    Rasa Pro 服务          │
                         │  ┌─────────────────────┐  │
                         │  │  NLU 管线             │  │
                         │  │  (LLM 命令生成器)     │  │
                         │  ├─────────────────────┤  │
                         │  │  对话策略             │  │
                         │  │  (FlowPolicy +       │  │
                         │  │   EnterpriseSearch)  │  │
                         │  └─────────────────────┘  │
                         └──┬──────────┬──────────┬──┘
                            │          │          │
              ┌─────────────▼──┐  ┌───▼────┐  ┌─▼──────────────┐
              │  自定义 Action  │  │ Redis  │  │  GraphRAG       │
              │  (订单/物流/    │  │ (锁/   │  │  (Neo4j + LLM)  │
              │   售后)         │  │ 缓存/  │  │                  │
              └───────┬─────────┘  │ 限流/  │  └─────┬────────────┘
                      │            │ Stream)│        │
              ┌───────▼─────────┐  └───────┘  ┌─────▼────────────┐
              │  MySQL           │             │  嵌入模型服务     │
              │  (订单/用户/     │             │  (FastAPI/BGE)   │
              │   商品)          │             │                  │
              └─────────────────┘             └──────────────────┘
```

## 项目结构

```
Smart-Service-Online/
├── actions/                     # Rasa 自定义 Action
│   ├── db.py                    #   数据库连接池 (SQLAlchemy 2.0)
│   ├── db_table_class.py        #   ORM 模型 (订单、用户、商品、物流…)
│   ├── action_order.py          #   订单管理 (查询、取消、修改地址)
│   ├── action_logistics.py      #   物流追踪 + 投诉
│   └── action_postsale.py       #   售后服务 (退款/退货/换货)
│
├── core/                        # Redis 分布式基础设施
│   ├── config.py                #   统一配置 Dataclass (50+ 参数)
│   ├── redis_client.py          #   Redis 客户端 (Pipeline/Lua/HyperLogLog/BitMap/GEO)
│   ├── distributed_lock.py      #   分布式锁 + Redlock (含面试原理注释)
│   ├── distributed_id.py        #   Snowflake 雪花 ID 生成器
│   ├── cache_decorator.py       #   @cacheable 装饰器 + 三层缓存防护
│   ├── rate_limiter.py          #   滑动窗口限流 (用户/IP/操作)
│   ├── idempotency.py           #   请求幂等去重 (SET NX)
│   ├── redis_bloom.py           #   布隆过滤器
│   ├── redis_delay_queue.py     #   ZSET 延迟任务队列
│   ├── redis_stream.py          #   Stream 事件流 + 消费者组
│   └── redis_transaction.py     #   Redis 事务 (Watch/Multi/Exec)
│
├── addons/                      # Rasa 扩展
│   ├── information_retrieval.py #   GraphRAG: T2C 管线 (路由→检索→生成→验证→执行)
│   ├── embed_service.py         #   嵌入模型 HTTP API (FastAPI + BGE)
│   └── create_indexing.py       #   Neo4j 向量 + 全文索引构建
│
├── graph/                       # NLP 模型
│   ├── src/models/              #   BERT 意图分类、BERT+T5 拼写纠错
│   ├── src/preprocess/          #   数据预处理管线
│   ├── src/runner/              #   统一训练/预测框架
│   ├── src/datasync/            #   MySQL ↔ Neo4j 数据同步
│   └── external_lib/uie_pytorch/#   通用信息抽取 (微调 + 推理)
│
├── data/flows/                  # 对话流程定义 (YAML)
├── domain/                      # 领域配置：意图、实体、槽位、响应
├── e2e_tests/                   # 端到端对话测试
├── examples/                    # 使用示例
├── scripts/                     # 工具脚本
├── gen_data.py                  # 测试数据生成器 (Faker, 1万+ 用户)
├── config.yml                   # Rasa NLU 管线 & 策略配置
├── endpoints.yml                # 外部服务配置
├── credentials.yml              # 渠道凭证
└── requirements.txt             # Python 依赖 (30 个包)
```

## 性能特征

| 指标 | 目标 | 方法 |
|------|------|------|
| 意图分类 | < 200ms | LLM 命令生成器 (Qwen-Plus) |
| 知识检索 (GraphRAG) | < 500ms | Neo4j 混合检索 + T2C 验证 |
| 订单查询 (缓存命中) | < 10ms | Redis 缓存 + 连接池 |
| 订单查询 (未命中) | < 50ms | MySQL 索引查询 + 连接池 |
| 限流检查 | < 2ms | Redis Lua 脚本，滑动窗口 |
| 分布式锁获取 | < 5ms | SET NX PX + 指数退避重试 |
| 嵌入推理 | < 50ms/条 | BGE-base-zh-v1.5, batch_size=64 |

## 快速开始

### 环境要求

- Python 3.10+
- Redis 7.0+
- MySQL 8.0+
- Neo4j 5.x+
- [Rasa Pro License](https://rasa.com/rasa-pro/) (开发环境免费)

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/dingzj11/E-commerce-Intelligent-Customer-Service-Agent.git
cd E-commerce-Intelligent-Customer-Service-Agent

# 2. 安装依赖 — 30+ 个包，覆盖 Rasa Pro、Redis、Neo4j、NLP、LLM 框架
pip install -r requirements.txt

# 3. 配置环境 — 50+ 参数，有合理默认值（详见 core/config.py 的 Dataclass 层级）
cp .env.example .env
# 编辑 .env 填入 API Key、数据库凭证、缓存 TTL、限流阈值

# 4. 下载 NLP 模型权重（BGE 嵌入 ~400MB，BERT 分类器 ~200MB/个）
bash scripts/download_models.sh

# 5. 启动基础设施 — Redis (缓存/锁/队列)、MySQL (订单/用户)、Neo4j (知识图谱)
#    Redis 7.0+  : 缓存、分布式锁、限流、Stream、延迟队列
#    MySQL 8.0+  : 订单/用户/商品关系型数据
#    Neo4j 5.x+   : 商品知识图谱，支撑 GraphRAG 检索

# 6. 生成测试数据（1万用户、5万订单、真实分布）
python gen_data.py

# 7. 构建 Neo4j 索引（向量 + 全文）并启动嵌入服务 (端口 8000)
cd addons
python create_indexing.py
python embed_service.py &

# 8. 训练并启动 Rasa
cd ..
rasa train
rasa run --enable-api

# 9. 运行 E2E 测试验证
rasa test e2e --e2e-tests e2e_tests/
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 对话框架 | Rasa Pro 3.10+ (CALM) |
| 大语言模型 | Qwen-Plus / Qwen3-8B (LoRA 微调) |
| 嵌入模型 | BGE-base-zh-v1.5 (Sentence Transformers) |
| 图数据库 | Neo4j 5.x |
| 关系数据库 | MySQL 8.0 + SQLAlchemy 2.0 (连接池、读写分离) |
| 缓存/锁/队列 | Redis 7.0 (单机/哨兵/集群) |
| Web 框架 | FastAPI + Uvicorn (嵌入模型微服务) |
| NLP | Transformers, jieba (中文分词) |
| 测试数据 | Faker (中文 locale，真实分布) |

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

> **Note**: Rasa Pro requires a separate license. This project only includes the configuration and custom code built on top of Rasa Pro.
