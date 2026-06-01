#!/bin/bash
# ==================== 模型下载脚本 ====================
# 下载项目所需的预训练模型权重
#
# 使用方法:
#   bash scripts/download_models.sh
#
# 模型列表:
#   1. BGE-base-zh-v1.5 — 中文嵌入模型 (约 400MB)
#      HuggingFace: BAAI/bge-base-zh-v1.5
#   2. 其他模型请参考 README.md 中的说明

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MODELS_DIR="$PROJECT_DIR/models"

echo "=== 下载预训练模型 ==="
echo "项目目录: $PROJECT_DIR"
echo ""

# ---- BGE-base-zh-v1.5 (中文嵌入模型) ----
echo "[1/1] 下载 BGE-base-zh-v1.5..."
BGE_DIR="$MODELS_DIR/bge-base-zh-v1.5"

if [ -d "$BGE_DIR" ] && [ -f "$BGE_DIR/config.json" ]; then
    echo "  BGE-base-zh-v1.5 配置文件已存在，跳过下载。"
    echo "  如需下载权重文件，请运行:"
    echo "    pip install huggingface_hub"
    echo "    huggingface-cli download BAAI/bge-base-zh-v1.5 --local-dir $BGE_DIR"
else
    echo "  请使用以下命令下载 BGE 模型权重:"
    echo "    pip install huggingface_hub"
    echo "    huggingface-cli download BAAI/bge-base-zh-v1.5 --local-dir $BGE_DIR"
fi

echo ""
echo "=== 下载完成 ==="
echo ""
echo "提示: Rasa 训练模型 (*.tar.gz) 需要通过 Rasa CLI 自行训练:"
echo "  rasa train"
