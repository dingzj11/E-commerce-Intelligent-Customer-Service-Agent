"""提供嵌入模型服务接口，方便 rasa 中调用该 Embedding模型"""

import os
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

# 加载模型
model = SentenceTransformer("../models/bge-base-zh-v1.5")


# 请求格式
class EmbeddingRequest(BaseModel):
    model: str
    input: str | list[str]


app = FastAPI()


@app.post("/embeddings")
def embed(request: EmbeddingRequest):
    embed_batch_size = 64 # 每次处理64个句子
    # 统一转成list
    texts = [request.input] if isinstance(request.input, str) else request.input
    # 使用模型对文本进行编码，批量大小为64，同时进行向量归一化
    embeddings = model.encode(
        texts, batch_size=embed_batch_size, normalize_embeddings=True
    )
    embeddings = embeddings.tolist()

    # 按照OpenAI Embedding API的格式返回结果
    return {
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "embedding": embed,
                "index": i,
            }
            for i, embed in enumerate(embeddings)
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=10010)
