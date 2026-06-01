import torch
from torch import nn, tensor
from transformers import AutoModel

from configs import config


class SpellCheckBert(nn.Module):
    def __init__(self):
        super().__init__()
        self.bert = AutoModel.from_pretrained(config.PRE_TRAINED_DIR / 'bert-base-chinese')
        self.linear = nn.Linear(self.bert.config.hidden_size, self.bert.config.vocab_size)
        self.loss_func = nn.CrossEntropyLoss(ignore_index=self.bert.config.pad_token_id)

    def forward(self, input_ids, attention_mask, labels=None):
        outputs = self.bert(input_ids, attention_mask)
        last_hidden_state = outputs.last_hidden_state
        logits = self.linear(last_hidden_state)
        # logits.shape: [batch_size,seq_len,vocab_size]
        predictions = torch.argmax(logits, dim=-1)
        # predictions.shape: [batch_size,seq_len]

        # torch.cat([torch.full((batch_size, 1), 0),attention_mask[:,2:],torch.full((batch_size, 1), 0)])
        # predictions.shape: [batch_size,seq_len]
        predictions = predictions.masked_fill(attention_mask == 0, self.bert.config.pad_token_id)

        result = {'predictions': predictions}
        if labels is not None:
            loss = self.loss_func(logits.reshape(-1, logits.shape[-1]), labels.reshape(-1))
            result['loss'] = loss
        return result
