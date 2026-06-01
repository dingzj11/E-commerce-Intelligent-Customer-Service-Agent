import os
from dataclasses import dataclass
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm


@dataclass
class TrainingConfig:
    # 训练参数
    epochs: int = 3
    train_batch_size: int = 32
    valid_batch_size: int = 32
    test_batch_size: int = 32
    lr: float = 5e-5
    enable_amp: bool = True

    # 路径相关
    output_dir: Path = Path('./checkpoint')
    logs_dir: Path = Path('./logs')

    # 早停相关
    early_stop_patience: int = 3
    early_stop_metric: str = 'loss'

    # step相关
    log_steps: int = 50
    save_steps: int = 100
    eval_steps: int = 200


class Trainer:
    def __init__(self,
                 model,
                 train_dataset,
                 valid_dataset,
                 test_dataset,
                 training_config,
                 compute_metrics=None,
                 optimizer=None):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = model.to(self.device)
        self.train_dataset = train_dataset
        self.valid_dataset = valid_dataset
        self.test_dataset = test_dataset
        self.config = training_config
        self.compute_metrics = compute_metrics
        self.optimizer = optimizer if optimizer else torch.optim.Adam(self.model.parameters(), lr=self.config.lr)
        # 创建目录
        os.makedirs(self.config.output_dir, exist_ok=True)

        # 全局step
        self.global_step = 1

        # tensorboard
        self.writer = SummaryWriter(log_dir=self.config.logs_dir)

        # 早停相关
        self.early_stop_best_score = -float('inf')
        self.early_stop_counter = 0

        # amp相关
        self.scaler = torch.amp.GradScaler(device=self.device.type, enabled=self.config.enable_amp)

    def train(self):
        # 加载checkpoint
        self._load_checkpoint()

        # 获取数据集
        dataloader = self._get_dataloader(dtype='train')
        # 训练
        for epoch in range(1, 1 + self.config.epochs):
            for batch_id, batch in enumerate(tqdm(dataloader, desc=f"Epoch {epoch}")):
                # 处理断点续训
                current_step = (epoch - 1) * len(dataloader) + batch_id
                if current_step < self.global_step:
                    continue

                # 训练一个batch
                loss = self._train_step(batch)

                # 判断是否要保存日志
                if self.global_step % self.config.log_steps == 0:
                    self.writer.add_scalar('loss', loss, self.global_step)
                    # [Epoch:1|step:100] Train Loss:4.3
                    tqdm.write(f'[Epoch:{epoch}|step:{self.global_step}] Train Loss:{loss:.4f}')

                # 判断是否要保存checkpoint
                if self.global_step % self.config.save_steps == 0:
                    self._save_checkpoint()

                # 判断是否要进行评估（早停）
                if self.global_step % self.config.eval_steps == 0:
                    # 验证模型
                    metrics = self.evaluate(dtype='valid')
                    # loss:0.01 | accuracy:0.98 | f1:0.98
                    metrics_str = "|".join([f'{k}:{v:.4f}' for k, v in metrics.items()])
                    tqdm.write(f'[Epoch:{epoch}|step:{self.global_step}] Valid {metrics_str}')

                    # 早停判断
                    if self._should_early_stop(metrics):
                        tqdm.write('early stop')
                        return

                self.global_step += 1

    def _train_step(self, batch):
        self.model.train()
        input_ids = batch['input_ids'].to(self.device)
        attention_mask = batch['attention_mask'].to(self.device)
        labels = batch['labels'].to(self.device)
        # 前向传播
        with torch.autocast(device_type=self.device.type, dtype=torch.float16, enabled=self.config.enable_amp):
            outputs = self.model(input_ids, attention_mask, labels)
            loss = outputs['loss']
        # 反向传播
        self.scaler.scale(loss).backward()
        self.scaler.step(self.optimizer)
        self.scaler.update()
        self.optimizer.zero_grad()
        return loss.item()

    def evaluate(self, dtype='test'):
        total_loss = 0
        all_predictions = []
        all_labels = []
        dataloader = self._get_dataloader(dtype)
        self.model.eval()
        with torch.no_grad():
            for batch in tqdm(dataloader, desc=dtype):
                outputs = self._evaluate_step(batch)
                total_loss += outputs['loss'].item()

                # 收集预测结果和标签
                if self.compute_metrics is not None:
                    predictions = outputs['predictions']
                    all_predictions.extend(predictions.tolist())
                    all_labels.extend(batch['labels'].tolist())

        # 统计评估结果
        if self.compute_metrics is not None:
            metrics = self.compute_metrics(all_predictions, all_labels)
        else:
            metrics = {}
        metrics['loss'] = total_loss / len(dataloader)
        return metrics

    def _evaluate_step(self, batch):
        input_ids = batch['input_ids'].to(self.device)
        attention_mask = batch['attention_mask'].to(self.device)
        labels = batch['labels'].to(self.device)
        outputs = self.model(input_ids, attention_mask, labels)
        return outputs

    def _get_dataloader(self, dtype='train'):
        if dtype == 'train':
            dataset = self.train_dataset
            batch_size = self.config.train_batch_size
        elif dtype == 'valid':
            dataset = self.valid_dataset
            batch_size = self.config.valid_batch_size
        elif dtype == 'test':
            dataset = self.test_dataset
            batch_size = self.config.test_batch_size
        else:
            raise ValueError('Invalid dtype')

        dataset.set_format(type='torch')
        return DataLoader(dataset, batch_size=batch_size, shuffle=True)

    def _save_checkpoint(self):
        checkpoint = {
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'scaler_state_dict': self.scaler.state_dict(),
            'global_step': self.global_step,
            'early_stop_best_score': self.early_stop_best_score,
            'early_stop_counter': self.early_stop_counter
        }
        torch.save(checkpoint, self.config.output_dir / 'checkpoint.pt')

    def _load_checkpoint(self):
        checkpoint_path = self.config.output_dir / 'checkpoint.pt'
        if checkpoint_path.exists():
            print("检查点存在，开始加载")
            checkpoint = torch.load(checkpoint_path)
            self.model.load_state_dict(checkpoint['model_state_dict'])
            self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
            self.scaler.load_state_dict(checkpoint['scaler_state_dict'])
            self.global_step = checkpoint['global_step']
            self.early_stop_best_score = checkpoint['early_stop_best_score']
            self.early_stop_counter = checkpoint['early_stop_counter']
        else:
            print("检查不存在，从头训练")

    def _should_early_stop(self, metrics):
        score = metrics[self.config.early_stop_metric]
        if self.config.early_stop_metric == 'loss':
            score = -score

        if score > self.early_stop_best_score:
            self.early_stop_best_score = score
            self.early_stop_counter = 0
            torch.save(self.model.state_dict(), self.config.output_dir / 'best.pt')
            return False
        else:
            self.early_stop_counter += 1
            if self.early_stop_counter >= self.config.early_stop_patience:
                return True
            else:
                return False


class Seq2SeqTrainer(Trainer):
    def _evaluate_step(self, batch):
        # 从模型的forward方法中获取loss
        input_ids = batch['input_ids'].to(self.device)
        attention_mask = batch['attention_mask'].to(self.device)
        labels = batch['labels'].to(self.device)

        outputs = self.model(input_ids, attention_mask, labels)
        loss = outputs['loss']

        result = {'loss': loss}
        # 从模型的generate方法中获取predictions
        if self.compute_metrics is not None:
            predictions = self.model.generate(input_ids, attention_mask)
            # predictions.shape = (batch_size, seq_len)

            result['predictions'] = predictions
        return result
