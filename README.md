[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Rasa Pro](https://img.shields.io/badge/Rasa%20Pro-CALM%203.10%2B-5A4E8E)](https://rasa.com/)
[![Redis](https://img.shields.io/badge/Redis-7.0%2B-DC382D?logo=redis)](https://redis.io/)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.x-008CC1?logo=neo4j)](https://neo4j.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

# 电商智能客服 Agent

## 项目简介

基于 **Rasa Pro (CALM)** 构建的生产级**电商智能客服聊天机器人**，集成了 **GraphRAG 知识检索** 和 **Redis 分布式基础设施**。系统涵盖客服全流程：订单管理、物流追踪、售后服务（退款/退货/换货）以及知识型商品问答。

> **核心价值**: 展示 AI Agent 系统中的**后端工程深度** — NLU 管线、对话管理、知识图谱、分布式系统模式、LLM 集成。

## 功能展示

### 订单管理

**查询订单** — 列出进行中和3日内完成的订单，查看详情

![查询订单](images/查询订单.png)

**取消订单** — 取消待支付或待发货的订单，二次确认防止误操作

![取消订单](images/取消订单.png)

**修改订单收货信息** — 支持选择已有地址或新建地址，分步收集省/市/区/街道

![修改收货信息-步骤1](images/修改订单收货信息-1.png)

![修改收货信息-步骤2](images/修改订单收货信息-2.png)

### 物流服务

**查询物流信息** — 查看订单实时物流轨迹

![查询物流信息](images/查询物流信息.png)

**投诉物流** — 选择问题类型提交物流投诉

![投诉物流](images/投诉物流.png)

### 售后服务

**申请售后** — 支持退货/退款/换货，7天无理由自动审核

![申请售后](images/申请售后.png)

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
| 功能 | 技术 | 说明 |
|------|------|------|
| **Flow 流程对话** | Rasa Pro CALM | 确定性多轮对话管理，LLM 增强意图匹配 |
| **LLM 意图识别** | Qwen-Plus 命令生成器 | 无需固定意图分类体系，自然语言理解 |
| **上下文重述** | NLG 响应重述器 | LLM 重写机器人回复，上下文感知 |
| **多轮槽位填充** | 自定义 Action | 结构化数据采集，条件分支 |

### 知识检索 (GraphRAG)
| 功能 | 技术 | 说明 |
|------|------|------|
| **混合检索** | Neo4j 向量 + 全文搜索 | 语义相似度 + 关键词匹配，适配中文 |
| **Text-to-Cypher** | LLM → 验证 → 校正 → 执行 | 4阶段管线生成和校验 Cypher 查询 |
| **中文嵌入** | BGE-base-zh-v1.5 + FastAPI | 专用嵌入微服务，批量推理 |
| **实体链接** | LLM 标签路由 | 自动识别节点类型 + 实体抽取 |

### 分布式系统 (Redis)
| 功能模块 | 技术实现 | 为什么重要 |
|---------|---------|-----------|
| 分布式锁 | SET NX PX + Lua 原子释放 + 看门狗续期 + Redlock | 防止多实例并发竞争 |
| 缓存策略 | 三防：穿透(空值缓存)、击穿(互斥锁)、雪崩(TTL 随机化) | 经典缓存问题的教科书级实现 |
| 限流器 | 滑动窗口计数器 (用户/IP/操作三级) | 细粒度控制，无需中心化网关 |
| 幂等性 | Redis SET NX 请求去重 | 写操作的精确一次语义 |
| 分布式 ID | Snowflake 雪花算法 | 有序唯一 ID，不依赖数据库自增 |
| 布隆过滤器 | Redis BitMap 实现 | 查询前预过滤不存在的 Key |
| 延迟队列 | Redis ZSET range-by-score | 定时任务，无需独立消息队列 |
| Stream | Redis Stream + Consumer Groups | 事件驱动异步处理 |

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

### 请求生命周期（以"取消订单"为例）

```
  用户 ──> FlowPolicy ──> action_cancel_order()
               │                    │
               │ (1) LLM 意图分类   │ (2) Redis 分布式锁
               │     ~200ms         │     获取 "order:cancel:{id}"
               │                    │     ~5ms
               │ (3) GraphRAG 查询  │ (4) MySQL 读取（缓存命中）
               │     政策检查       │     ~8ms
               │     ~350ms         │
               │                    │ (5) MySQL 写入 + 缓存失效
               │                    │     ~15ms
               │ (6) 限流器         │ (7) Redis 释放锁
               │     滑动窗口检查   │     Lua 原子脚本
               │                    │
               └──────────────> 响应用户 (~600ms)
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
├── images/                      # 功能截图展示
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

本项目基于 MIT License 开源。详见 [LICENSE](LICENSE) 文件。

> **注意**: Rasa Pro 需要单独授权。本项目仅包含基于 Rasa Pro 构建的配置和自定义代码。
