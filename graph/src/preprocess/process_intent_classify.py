from datasets import load_dataset, ClassLabel
from transformers import AutoTokenizer

from configs import config


def process_data():
    # 读取数据
    dataset = load_dataset("csv", data_files=str(config.DATA_DIR / 'intent_classify' / 'raw' / 'data.csv'))[
        "train"]

    # 划分数据集
    all_labels = dataset.unique('intent')
    dataset = dataset.cast_column('intent', ClassLabel(names=all_labels))
    print(all_labels)

    dataset_dict = dataset.train_test_split(train_size=0.8, stratify_by_column='intent')
    dataset_dict['valid'], dataset_dict['test'] = dataset_dict['test'].train_test_split(test_size=0.5,
                                                                                        stratify_by_column='intent').values()

    # 编码器数据
    tokenizer = AutoTokenizer.from_pretrained(config.PRE_TRAINED_DIR / 'bert-base-chinese')

    def map_func(batch):
        inputs = tokenizer(batch['text'], truncation=True, padding='max_length', max_length=32)
        input_ids = inputs['input_ids']
        attention_mask = inputs['attention_mask']
        return {
            'input_ids': input_ids,
            'attention_mask': attention_mask,
            'labels': batch['intent']
        }

    dataset_dict = dataset_dict.map(map_func, batched=True, remove_columns=['text', 'intent'])

    dataset_dict.save_to_disk(config.DATA_DIR / 'intent_classify' / 'processed')


if __name__ == '__main__':
    process_data()
