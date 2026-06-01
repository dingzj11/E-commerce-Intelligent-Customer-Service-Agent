from pathlib import Path

from datasets import load_from_disk

from configs import config
from models.intent_classify_bert import IntentClassifyBert
from runner.Trainer import Trainer, TrainingConfig

if __name__ == '__main__':
    model = IntentClassifyBert(config.INTENT_LIST)

    dataset_dict = load_from_disk(config.DATA_DIR / 'intent_classify' / 'processed')
    train_dataset = dataset_dict['train']
    valid_dataset = dataset_dict['valid']
    test_dataset = dataset_dict['test']

    training_config = TrainingConfig(
        lr=5e-6,
        early_stop_metric='accuracy',
        early_stop_patience=5,
        logs_dir=Path('/root/tf-logs/intent_classify_bert'),
        output_dir=config.CHECKPOINT_DIR / 'intent_classify',
        train_batch_size=4,
        valid_batch_size=4,
        enable_amp=True,
        eval_steps=100,
        save_steps=100,
        log_steps=20
    )


    def compute_metrics(predictions, labels):
        total_count = 0
        correct_count = 0
        for pred, label in zip(predictions, labels):
            if pred == label:
                correct_count += 1
            total_count += 1
        return {'accuracy': correct_count / total_count}


    trainer = Trainer(model, train_dataset, test_dataset, valid_dataset, training_config, compute_metrics)
    trainer.train()
