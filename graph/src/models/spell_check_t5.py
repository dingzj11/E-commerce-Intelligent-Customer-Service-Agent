import torch
from torch import nn
from transformers import AutoModel

from configs import config


class SpellCheckT5(nn.Module):
    def __init__(self):
        super().__init__()
        self.t5 = AutoModel.from_pretrained(config.PRE_TRAINED_DIR / 'mengzi-t5')
        self.linear = nn.Linear(self.t5.config.hidden_size, self.t5.config.vocab_size)
        self.loss_func = nn.CrossEntropyLoss(ignore_index=self.t5.config.pad_token_id)

    def forward(self, input_ids, attention_mask, labels):
        """
        前向传播
        :param input_ids: 原始序列
        :param attention_mask:  原始序列的mask
        :param labels: 目标序列
        :return:
        """
        # 处理解码器的输入
        decoder_input_ids = self.t5._shift_right(labels)

        outputs = self.t5(input_ids=input_ids,
                          attention_mask=attention_mask,
                          decoder_input_ids=decoder_input_ids)

        last_hidden_state = outputs.last_hidden_state
        # last_hidden_state.shape = [batch_size, seq_len, hidden_size]
        logits = self.linear(last_hidden_state)
        # logits.shape = [batch_size, seq_len, vocab_size]
        predictions = logits.argmax(dim=-1)

        loss = self.loss_func(logits.reshape(-1, logits.shape[-1]), labels.reshape(-1))

        return {'loss': loss, 'predictions': predictions}

    def generate(self, input_ids, attention_mask, num_beams=3, max_length=64):
        # input_ids.shape = [batch_size, seq_len]
        # attention_mask.shape = [batch_size, seq_len]

        # 所需参数
        batch_size = input_ids.shape[0]
        device = input_ids.device
        example_offset = torch.arange(batch_size, device=device) * num_beams
        vocab_size = self.t5.config.vocab_size

        # 编码
        encoder_outputs = self.t5.encoder(input_ids, attention_mask)
        last_hidden_state = encoder_outputs.last_hidden_state
        # last_hidden_state.shape = [batch_size, seq_len, hidden_size]

        # 处理编码器的输出( [batch_size*num_beams, seq_len, hidden_size] )
        encoder_hidden_states = last_hidden_state.repeat_interleave(num_beams, dim=0)
        encoder_attention_mask = attention_mask.repeat_interleave(num_beams, dim=0)

        # 解码
        # 各beam是否已经完成
        is_finish = torch.zeros([batch_size * num_beams], dtype=torch.bool, device=device)

        # 各个beam的分数
        beam_scores = torch.full([batch_size * num_beams, 1], -float('inf'), device=device)
        beam_scores[example_offset, 0] = 0

        # 准备第一步的输入
        decoder_input_ids = torch.full([batch_size * num_beams, 1],
                                       self.t5.config.decoder_start_token_id,
                                       device=device)
        for t in range(max_length):
            decoder_outputs = self.t5.decoder(input_ids=decoder_input_ids,
                                              encoder_hidden_states=encoder_hidden_states,
                                              encoder_attention_mask=encoder_attention_mask)
            last_hidden_state = decoder_outputs.last_hidden_state
            logits = self.linear(last_hidden_state)
            # logits.shape = [batch_size*num_beams, seq_len, vocab_size]

            # 最后一个位置的logits
            next_token_logits = logits[:, -1, :]
            # next_token_logits.shape = [batch_size*num_beams, vocab_size]

            # 转为概率分布
            next_token_scores = torch.log_softmax(next_token_logits, dim=-1)
            # next_token_scores.shape = [batch_size*num_beams, vocab_size]

            # 处理已经完成的Beam的下一个token的得分
            if is_finish.any():
                next_token_scores[is_finish, :] = -float('inf')
                next_token_scores[is_finish, self.t5.config.eos_token_id] = 0

            total_scores = beam_scores + next_token_scores

            # 对total_scores进行变形，方便获取全局topk
            total_scores = total_scores.reshape(batch_size, -1)
            # total_scores.shape = [batch_size, num_beams*vocab_size]

            # 获取topk([batch_size, num_beams]])
            topk_values, topk_indices = torch.topk(total_scores, k=num_beams, dim=-1)

            # 处理beam_scores
            beam_scores = topk_values.reshape(-1, 1)

            # 处理下一步的decoder_input_ids
            # 获取下一个token的id
            topk_indices = topk_indices.reshape(-1, 1)
            next_token_ids = topk_indices % vocab_size
            # next_token_ids.shape = [batch_size*num_beams, 1]

            # 获取历史beam
            beam_indices = (topk_indices // vocab_size).reshape(-1) + example_offset.repeat_interleave(num_beams, dim=0)

            # 判断是否已经生成完毕
            is_finish = is_finish[beam_indices] | (next_token_ids.reshape(-1) == self.t5.config.eos_token_id)
            if is_finish.all():
                break

            # 拼接得到下一步的decoder_input_ids
            decoder_input_ids = torch.cat([decoder_input_ids[beam_indices], next_token_ids], dim=-1)

        # 选择每个样本的分值最高的beam
        beam_scores = beam_scores.reshape(batch_size, num_beams)
        best_beam_indices = beam_scores.argmax(dim=-1) + example_offset
        return decoder_input_ids[best_beam_indices]
