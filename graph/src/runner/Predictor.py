import torch
from datasets import ClassLabel
from transformers import AutoTokenizer

from configs import config
from models.intent_classify_bert import IntentClassifyBert
from models.spell_check_bert import SpellCheckBert
from models.spell_check_t5 import SpellCheckT5


class BasePredictor:
    def __init__(self, model, tokenizer, device):
        self.device = device
        self.model = model.to(self.device)
        self.tokenizer = tokenizer

    def predict(self, inputs: list[str] | str, batch_size=16):
        pass


class SpellCheckBertPredictor(BasePredictor):

    def predict(self, inputs: list[str] | str, batch_size=16):
        is_str = isinstance(inputs, str)
        if is_str:
            inputs = [inputs]

        # 处理输入数据
        inputs = self.tokenizer(inputs,
                                truncation=True,
                                padding='max_length',
                                max_length=64,
                                return_tensors='pt')
        input_ids = inputs['input_ids'].to(self.device)
        attention_mask = inputs['attention_mask'].to(self.device)

        # 批量预测
        predictions = []
        for i in range(0, input_ids.shape[0], batch_size):
            batch_input_ids = input_ids[i:i + batch_size]
            batch_attention_mask = attention_mask[i:i + batch_size]
            batch_outputs = self.model(batch_input_ids, batch_attention_mask)
            batch_predictions = batch_outputs['predictions']
            predictions.extend(batch_predictions)

        result: list[str] = self.tokenizer.batch_decode(predictions, skip_special_tokens=True)
        result = [text.replace(' ', '') for text in result]
        if is_str:
            return result[0]
        return result


class SpellCheckT5Predictor(BasePredictor):

    def predict(self, inputs: list[str] | str, batch_size=16):
        is_str = isinstance(inputs, str)
        if is_str:
            inputs = [inputs]

        # 处理输入数据
        inputs = self.tokenizer(inputs,
                                truncation=True,
                                padding='max_length',
                                max_length=64,
                                return_tensors='pt')
        input_ids = inputs['input_ids'].to(self.device)
        attention_mask = inputs['attention_mask'].to(self.device)

        # 批量预测
        predictions = []
        for i in range(0, input_ids.shape[0], batch_size):
            batch_input_ids = input_ids[i:i + batch_size]
            batch_attention_mask = attention_mask[i:i + batch_size]
            batch_predictions = self.model.generate(batch_input_ids, batch_attention_mask)
            predictions.extend(batch_predictions)

        result: list[str] = self.tokenizer.batch_decode(predictions, skip_special_tokens=True)
        result = [text.replace(' ', '') for text in result]
        if is_str:
            return result[0]
        return result


class IntentClassifyBertPredictor(BasePredictor):
    def predict(self, inputs: list[str] | str, batch_size=16):
        is_str = isinstance(inputs, str)
        if is_str:
            inputs = [inputs]
        encoded = self.tokenizer(inputs, padding=True, return_tensors='pt')
        input_ids = encoded['input_ids'].to(self.device)
        attention_mask = encoded['attention_mask'].to(self.device)

        predictions = []
        for i in range(0, input_ids.shape[0], batch_size):
            batch_input_ids = input_ids[i:i + batch_size]
            batch_attention_mask = attention_mask[i:i + batch_size]
            batch_outputs = self.model(batch_input_ids, batch_attention_mask)
            batch_predictions = batch_outputs['predictions']
            predictions.extend(batch_predictions)

        result = [self.model.labels[prediction] for prediction in predictions]
        if is_str:
            return result[0]
        return result


if __name__ == '__main__':
    # 测试SpellCheckBert
    model = SpellCheckBert()
    model.load_state_dict(torch.load(config.CHECKPOINT_DIR / 'spell_check_bert' / 'best.pt'))

    tokenizer = AutoTokenizer.from_pretrained(config.PRE_TRAINED_DIR / 'bert-base-chinese')

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    predictor = SpellCheckBertPredictor(model, tokenizer, device)

    print(predictor.predict(
        ["我今天箱吃樱跳",
         "我喜焕你",
         "时报指出,波顿的演讲稿中说,「在九月十一日之前,荀些国家可能必免这总作法",
         "我很杯伤，我很想要哭琪",
         "安照孙阳自已的画说",
         "中国拼叮请美国部要「助长」台独分裂活动。",
         "藤森今天队她是否将茌亚洲寻求庇护或返回秘鲁,保持沉默。",
         "小红和小明是南女朋友关系，但是今天小红跟小明吵了一架，然后向小明剔出了分首。"
         "他必需完成作业",
         "这是全球有市以来首次子灾难发生候这么短一段时间内,就筹集到这么高的金饿。"
         ]
    ))

    # 测试SpellCheckT5
    # model = SpellCheckT5()
    # model.load_state_dict(torch.load(config.CHECKPOINT_DIR / 'spell_check_t5' / 'best.pt'))
    #
    # tokenizer = AutoTokenizer.from_pretrained(config.PRE_TRAINED_DIR / 'mengzi-t5')
    #
    # device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    #
    # predictor = SpellCheckT5Predictor(model, tokenizer, device)
    #
    # print(predictor.predict(
    #     ['再加上在工作的地方有机会见面别的人，也可以学习新的文，最后经验越来越多。职业女生会增加她们的新智。',
    #      '我喜你。']))

    # 测试IntentClassifyBert
    # model = IntentClassifyBert(labels=config.INTENT_LIST)
    # model.load_state_dict(torch.load(config.CHECKPOINT_DIR / 'intent_classify' / 'best.pt'))
    # tokenizer = AutoTokenizer.from_pretrained(config.PRE_TRAINED_DIR / 'bert-base-chinese')
    # device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    # predictor = IntentClassifyBertPredictor(model, tokenizer, device)
    # print(predictor.predict('小米12S Ultra都有哪些版本？'))
