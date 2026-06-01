from torch import nn
from transformers import AutoModel

from configs import config


class IntentClassifyBert(nn.Module):
    def __init__(self, labels):
        super().__init__()
        self.labels = labels
        self.bert = AutoModel.from_pretrained(config.PRE_TRAINED_DIR / 'bert-base-chinese')
        self.linear = nn.Linear(self.bert.config.hidden_size, len(labels))
        self.loss_func = nn.CrossEntropyLoss()

    def forward(self, input_ids, attention_mask, labels=None):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        cls_hidden_state = outputs.last_hidden_state[:, 0, :]
        logits = self.linear(cls_hidden_state)
        # logits.shape = [batch_size, num_labels]
        predictions = logits.argmax(dim=-1)
        # predictions = [batch_size]
        result = {"predictions": predictions}
        if labels is not None:
            loss = self.loss_func(logits, labels)
            result['loss'] = loss
        return result
