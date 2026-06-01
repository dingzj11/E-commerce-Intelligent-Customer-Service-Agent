import torch
from neo4j import GraphDatabase
from transformers import AutoTokenizer

from configs import config
from models.intent_classify_bert import IntentClassifyBert
from models.spell_check_t5 import SpellCheckT5
from runner.Predictor import IntentClassifyBertPredictor, SpellCheckT5Predictor
from uie_predictor import UIEPredictor


class ChatService:
    def __init__(self):
        self.intent_classify_predictor = self.init_intent_classify_predictor()
        self.spell_check_predictor = self.init_spell_check_predictor()
        self.uie_predictor = UIEPredictor(model='uie-base', task_path=config.CHECKPOINT_DIR / 'uie/model_best',
                                          device='gpu', schema=[])
        self.neo4j_driver = GraphDatabase.driver(uri=config.NEO4J_CONFIG["uri"],
                                                 auth=(config.NEO4J_CONFIG["user"], config.NEO4J_CONFIG["password"]))

    @staticmethod
    def init_intent_classify_predictor():
        model = IntentClassifyBert(labels=config.INTENT_LIST)
        model.load_state_dict(torch.load(config.CHECKPOINT_DIR / 'intent_classify' / 'best.pt'))
        tokenizer = AutoTokenizer.from_pretrained(config.PRE_TRAINED_DIR / 'bert-base-chinese')
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        predictor = IntentClassifyBertPredictor(model, tokenizer, device)
        return predictor

    @staticmethod
    def init_spell_check_predictor():
        model = SpellCheckT5()
        model.load_state_dict(torch.load(config.CHECKPOINT_DIR / 'spell_check_t5' / 'best.pt'))
        tokenizer = AutoTokenizer.from_pretrained(config.PRE_TRAINED_DIR / 'mengzi-t5')
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        predictor = SpellCheckT5Predictor(model, tokenizer, device)
        return predictor

    def extract_entity(self, text, schema):
        self.uie_predictor.set_schema(schema)
        result = self.uie_predictor(text)[0]
        for key in result.keys():
            result[key] = [dic['text'] for dic in result[key]]
        return result

    def chat(self, question: str):
        intent = self.intent_classify_predictor.predict(question)
        # question = self.spell_check_predictor.predict(question)
        match intent:
            case '查询某商品的某个属性的属性值':
                schema = ['商品', '商品属性名称']
                result = self.extract_entity(question, schema)
                if len(result.keys()) == len(schema):
                    cypher = """
                        MATCH (spu:SPU{spu_name:$spu_name})<-[:Belong]-(sku:SKU)-[:Have]->(attr:Attr{attr_name:$attr_name}) 
                        RETURN attr.attr_value AS attr_value
                                    """
                    params = {
                        'spu_name': result['商品'][0],
                        'attr_name': result['商品属性名称'][0]
                    }
                    records, _, _ = self.neo4j_driver.execute_query(cypher, parameters_=params)
                    if len(records) > 0:
                        res = [record.data()['attr_value'] for record in records]
                        response = f"{result['商品'][0]}的{result['商品属性名称'][0]}有\n{"\n".join(res)}"
                        return response
            case '查询某商品的所有单品':
                schema = ['商品']
                result = self.extract_entity(question, schema)
                if len(result.keys()) == len(schema):
                    cypher = """
                        MATCH (spu:SPU{spu_name:$spu_name})<-[:Belong]-(sku:SKU) 
                        RETURN sku.sku_name AS sku_name
                                    """
                    params = {
                        'spu_name': result['商品'][0]
                    }
                    records, _, _ = self.neo4j_driver.execute_query(cypher, parameters_=params)
                    if len(records) > 0:
                        res = [record.data()['sku_name'] for record in records]
                        response = f"{result['商品'][0]}有\n{"\n".join(res)}"
                        return response
            case '查询某商品具有某些属性值的单品':
                schema = ['商品', '商品属性值']
                result = self.extract_entity(question, schema)
                if len(result.keys()) == len(schema):
                    cypher = """
                        MATCH (spu:SPU{spu_name:$spu_name})<-[:Belong]-(sku:SKU)-[:Have]->(attr:Attr)
                        WHERE attr.attr_value IN $attr_value_list
                        RETURN DISTINCT sku.sku_name AS sku_name
                    """
                    params = {
                        'spu_name': result['商品'][0],
                        'attr_value_list': result['商品属性值']
                    }
                    records, _, _ = self.neo4j_driver.execute_query(cypher, parameters_=params)
                    if len(records) > 0:
                        res = [record.data()['sku_name'] for record in records]
                        response = f"符合条件的商品有\n{"\n".join(res)}"
                        return response
            case '查询某品牌所有品类':
                pass
            case '查询某品类所有品牌':
                pass
            case '查询某品类所有商品':
                pass
            case '查询某品类某个属性的所有属性值':
                pass
            case '查询某品类某品牌的所有商品':
                pass
            case '查询某品类具有某些属性的单品':
                pass
            case '查询某品类某品牌具有某些属性的单品':
                pass
            case '查询和某商品某个属性具有相同属性值的其他商品':
                pass
            case '查询某商品具有某些属性值的单品的价格':
                pass
            case '查询某品类某价格区间的单品':
                pass
            case '查询某品类某品牌某价格区间的单品':
                pass

        return "请重新输入问题"


if __name__ == '__main__':
    service = ChatService()
    print(service.chat("小米12S Ultra都有哪些版本？"))