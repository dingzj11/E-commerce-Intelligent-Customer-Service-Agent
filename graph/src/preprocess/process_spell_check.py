from datasets import load_dataset
from transformers import AutoTokenizer

from configs import config


def process_data(model, save_path):
    """
    数据处理
    :param model: 模型
    :param save_path: 保存路径
    """

    # 获取数据
    dataset = load_dataset('csv', data_files=str(config.DATA_DIR / 'spell_check' / 'raw' / 'data.txt'),
                           delimiter=' ', header=None, column_names=['text', 'label'])['train']

    # 划分数据集
    dataset_dict = dataset.train_test_split(test_size=0.2)
    dataset_dict['valid'], dataset_dict['test'] = dataset_dict['test'].train_test_split(test_size=0.5).values()
    print(dataset_dict)

    # 数据编码
    tokenizer = AutoTokenizer.from_pretrained(model)

    def map_func(batch):
        # 处理text
        encoded = tokenizer(batch['text'], truncation=True, padding='max_length', max_length=64)
        input_ids = encoded['input_ids']
        attention_mask = encoded['attention_mask']

        # 处理label
        encoded = tokenizer(batch['label'], truncation=True, padding='max_length', max_length=64)
        labels = encoded['input_ids']

        return {
            'input_ids': input_ids,
            'attention_mask': attention_mask,
            'labels': labels
        }

    dataset_dict = dataset_dict.map(map_func, batched=True, remove_columns=['text', 'label'])

    # 保存数据集
    dataset_dict.save_to_disk(save_path)


if __name__ == '__main__':
    # process_data(config.PRE_TRAINED_DIR / 'bert-base-chinese', config.DATA_DIR / 'spell_check' / 'processed' / 'bert')
    process_data(config.PRE_TRAINED_DIR / 'mengzi-t5', config.DATA_DIR / 'spell_check' / 'processed' / 't5')