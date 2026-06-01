知识图谱项目目录结构
./
├── data/                               # 数据存储目录
│   ├── gmall.sql                       # MySQL 数据库数据
│   ├── images/                         # 图片存储目录
│   ├── intent_classify/                # 意图分类模型训练数据
│   ├── spell_check/                    # 拼写纠错模型训练数据
│   └── uie/                            # UIE 模型训练数据
├── uie_pytorch/                        # UIE 模型微调代码
├── templates/                          # 网页样式
├── pretrained/                         # 预训练模型目录
├── models/                             # 模型参数文件目录
└── src/
   ├── models_def/                      # 模型定义
   ├── preprocess/                      # 数据预处理
   ├── runner/                          # 模型训练评估
   ├── config.py                        # 配置文件
   ├── main.py                          # 模型训练流程
   ├── data_prepare.py                  # MySQL 与 Neo4j 数据准备
   ├── dialog_process.py                # 对话处理流程
   ├── intent_recognize_rule_base.py    # 基于规则意图识别
   ├── entity_extractor_rule_base.py    # 基于规则实体抽取
   ├── entity_extractor_model_base.py   # 基于模型的实体抽取
   └── app.py                           # Web 服务
