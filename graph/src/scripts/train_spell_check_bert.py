from pathlib import Path

from datasets import load_from_disk
from transformers import AutoTokenizer

from configs import config
from models.spell_check_bert import SpellCheckBert
from runner.Trainer import TrainingConfig, Trainer

model = SpellCheckBert()
dataset_dict = load_from_disk(str(config.DATA_DIR / 'spell_check/processed/bert'))
training_config = TrainingConfig(output_dir=config.CHECKPOINT_DIR / 'spell_check_bert',
                                 logs_dir=Path('/root/tf-logs/spell_check_bert'),
                                 log_steps=50,
                                 save_steps=1000,
                                 eval_steps=500,
                                 epochs=30
                                 )

tokenizer = AutoTokenizer.from_pretrained(config.PRE_TRAINED_DIR / 'bert-base-chinese')


def compute_metrics(predictions, labels):
    # predictions : [[1,3,5],[2,3,6],[1,2,3],[7,0,9]]
    # labels :[[1,3,5],[2,4,6],[1,2,3],[7,8,9]]
    total_count = 0
    correct_count = 0
    predictions = tokenizer.batch_decode(predictions, skip_special_tokens=True)
    labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
    for pred, label in zip(predictions, labels):
        if pred == label:
            correct_count += 1
        total_count += 1
    return {'accuracy': correct_count / total_count}


trainer = Trainer(model,
                  dataset_dict['train'],
                  dataset_dict['valid'],
                  dataset_dict['test'],
                  training_config,
                  compute_metrics)
trainer.train()
