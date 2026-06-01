from pathlib import Path

import torch
from datasets import load_from_disk
from transformers import AutoTokenizer

from configs import config
from models.spell_check_t5 import SpellCheckT5
from runner.Trainer import TrainingConfig, Trainer, Seq2SeqTrainer

model = SpellCheckT5()
model.load_state_dict(torch.load(config.CHECKPOINT_DIR / 'spell_check_t5' / 'best.pt'))

dataset_dict = load_from_disk(str(config.DATA_DIR / 'spell_check/processed/t5'))
training_config = TrainingConfig(output_dir=config.CHECKPOINT_DIR / 'spell_check_t5',
                                 logs_dir=Path('/root/tf-logs/spell_check_t5'),
                                 log_steps=50,
                                 save_steps=1000,
                                 eval_steps=500,
                                 epochs=30
                                 )

tokenizer = AutoTokenizer.from_pretrained(config.PRE_TRAINED_DIR / 'mengzi-t5')


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


trainer = Seq2SeqTrainer(model,
                         dataset_dict['train'],
                         dataset_dict['valid'],
                         dataset_dict['test'].select(range(10000)),
                         training_config,
                         compute_metrics)
print(trainer.evaluate())
