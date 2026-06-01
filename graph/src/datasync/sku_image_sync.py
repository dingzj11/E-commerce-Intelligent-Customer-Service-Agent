import sys

import easyocr
import pymysql
import torch
from neo4j import GraphDatabase
from pymysql.cursors import DictCursor
from transformers import AutoTokenizer

from configs import config
from models.spell_check_bert import SpellCheckBert
from runner.Predictor import SpellCheckBertPredictor

sys.path.insert(0, str(config.EXTERNAL_LIB_DIR / 'uie_pytorch'))
from uie_predictor import UIEPredictor


def get_sku_image_url():
    with pymysql.connect(**config.MYSQL_CONFIG) as connection:
        with connection.cursor(cursor=DictCursor) as cursor:
            cursor.execute("""
                select
                    sku_id,
                    img_url
                from sku_image
                where img_url like '/data%'
            """)
            return cursor.fetchall()


def get_sku_image_text(sku_image_url):
    sku_image_text = {'sku_id': [], 'image_text': []}
    reader = easyocr.Reader(['ch_sim', 'en'])
    for item in sku_image_url:
        # {'sku_id': 36, 'img_url': '/data/images/36/1.jpg'}
        url = config.ROOT_DIR / item['img_url'][1:]
        result = reader.readtext(str(url), detail=0)
        image_text = "".join(result)

        sku_image_text['sku_id'].append(item['sku_id'])
        sku_image_text['image_text'].append(image_text)
    return sku_image_text


def check_sku_image_text(sku_image_text):
    model = SpellCheckBert()
    model.load_state_dict(torch.load(config.CHECKPOINT_DIR / 'spell_check_bert' / 'best.pt'))

    tokenizer = AutoTokenizer.from_pretrained(config.PRE_TRAINED_DIR / 'bert-base-chinese')

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    predictor = SpellCheckBertPredictor(model, tokenizer, device)

    sku_image_text['image_text'] = predictor.predict(sku_image_text['image_text'])
    return sku_image_text


def get_sku_desc():
    sku_desc = {'sku_id': [], 'sku_desc': []}
    with pymysql.connect(**config.MYSQL_CONFIG) as connection:
        with connection.cursor(cursor=DictCursor) as cursor:
            cursor.execute("""
                select
                    id sku_id,
                    sku_desc
                from sku_info
            """)
            result = cursor.fetchall()
    for item in result:
        sku_desc['sku_id'].append(item['sku_id'])
        sku_desc['sku_desc'].append(item['sku_desc'])
    return sku_desc


def get_sku_entity(sku_text, schema):
    sku_entity = []
    sku_ids = sku_text['sku_id']
    ie = UIEPredictor(model='uie-base', task_path=config.CHECKPOINT_DIR / 'uie/model_best', schema=schema, device='gpu')
    result = ie(sku_text['sku_text'])
    for index, item in enumerate(result):
        # {'商品': [{'end': 11,
        #            'probability': np.float32(0.9996733),
        #            'start': 0,
        #            'text': '小米12S Ultra'}],
        #  '颜色': [{'end': 63,
        #            'probability': np.float32(0.999913),
        #            'start': 60,
        #            'text': '冷杉绿'}
        for key, value in item.items():
            sku_id = sku_ids[index]
            attr_name = key
            attr_value = value[0]['text']
            sku_entity.append({
                'sku_id': sku_id,
                'attr_name': attr_name,
                'attr_value': attr_value
            })
    return sku_entity


def write_sku_entity(sku_entity):
    with GraphDatabase.driver(uri=config.NEO4J_CONFIG["uri"],
                              auth=(config.NEO4J_CONFIG["user"], config.NEO4J_CONFIG["password"])) as driver:
        for entity in sku_entity:
            # {'sku_id': 1, 'attr_name': '颜色', 'attr_value': '绿色'}
            driver.execute_query("""
                MATCH (sku:SKU {sku_id:$sku_id})
                OPTIONAL MATCH (sku)-[:Have]->(attr_exist:Attr{attr_name:$attr_name})
                WITH sku,attr_exist
                WHERE attr_exist is null
                MERGE (attr:Attr {attr_name:$attr_name, attr_value:$attr_value})
                MERGE (sku)-[:Have]->(attr)
        """, parameters_=entity)


if __name__ == '__main__':
    # 1.获取商品的image_url
    sku_image_url = get_sku_image_url()
    # 2.识别商品图片中的文字
    sku_image_text = get_sku_image_text(sku_image_url)
    # 3.对识别结果进行纠错
    checked_sku_image_text = check_sku_image_text(sku_image_text)
    # 4.获取sku_info中的商品描述
    sku_desc = get_sku_desc()
    # 5.合并商品描述和图片中的文本
    sku_text = {
        'sku_id': sku_desc['sku_id'] + checked_sku_image_text['sku_id'],
        'sku_text': sku_desc['sku_desc'] + checked_sku_image_text['image_text']
    }
    # 6.对（图片中的文本+商品描述）进行实体抽取
    schema = [
    "尺码",
    "观看距离",
    "分辨率",
    "屏幕尺寸",
    "电视类型",
    "版本",
    "颜色",
    "机身内存",
    "运行内存",
    "处理器或内存",
    "内存",
    "硬盘",
    "显卡",
    "处理器",
    "类别",
    "分类",
    "是否有机",
    "粮食调味",
    "面部护肤",
    "香水彩妆",
    "功效",
    "香调",
    "电池容量",
    "摄像头像素",
    "散热方式",
    "解锁方式",
]
    sku_entity = get_sku_entity(sku_text, schema)

    # 7.将结果写入图数据库
    write_sku_entity(sku_entity)
