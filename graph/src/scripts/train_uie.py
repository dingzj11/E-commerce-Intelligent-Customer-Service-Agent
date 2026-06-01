import sys

from configs import config

# 保证在命令行中执行代码时，可以导入外部依赖uie_pytorch
sys.path.insert(0, str(config.EXTERNAL_LIB_DIR / 'uie_pytorch'))

from uie_predictor import UIEPredictor
from pprint import pprint

# 实体抽取
schema = ['商品', '颜色']  # Define the schema for entity extraction
ie = UIEPredictor(model='uie-base', task_path=config.CHECKPOINT_DIR / 'uie/model_best', schema=schema)
pprint(
    ie("小米12S Ultra 骁龙8+旗舰处理器 徕卡光学镜头 2K超视感屏 120Hz高刷 67W快充 8GB+128GB 冷杉绿 5G手机"))  # Better print results using pprint

# 关系抽取
# schema = {'竞赛名称': ['主办方', '承办方', '已举办次数']}  # Define the schema for relation extraction
# ie = UIEPredictor(model='uie-base', task_path=config.PRE_TRAINED_DIR / 'uie_base_pytorch', schema=schema)
# pprint(
#     ie('2022语言与智能技术竞赛由中国中文信息学会和中国计算机学会联合主办，百度公司、中国中文信息学会评测工作委员会和中国计算机学会自然语言处理专委会承办，已连续举办4届，成为全球最热门的中文NLP赛事之一。'))
