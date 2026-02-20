#!/usr/bin/env bash
# JARVIS-M4 启动脚本
# 用途：使用项目虚拟环境 .venv，避免系统 Python 的「externally-managed-environment」限制；检查 Ollama；运行主程序

set -e
cd "$(dirname "$0")"

# 确保使用虚拟环境：不存在则创建，然后统一用 .venv 里的 Python
if [ ! -d ".venv" ]; then
  echo "正在创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi
PYTHON=".venv/bin/python3"

# ---------- 1. 依赖（可选：首次运行或依赖缺失时安装到 .venv）----------
if ! "$PYTHON" -c "import aiohttp, yaml" 2>/dev/null; then
  echo "建议在虚拟环境中安装依赖: $PYTHON -m pip install -r requirements.txt"
  read -p "是否现在安装? [y/N] " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    "$PYTHON" -m pip install -r requirements.txt
  fi
fi

# ---------- 2. LLM 服务：根据 config.yaml 的 llm.backend 决定是否检查 Ollama -----------
NEED_OLLAMA="yes"
if [ -f config.yaml ]; then
  BACKEND=$("$PYTHON" -c "
import yaml
try:
    c = yaml.safe_load(open('config.yaml')) or {}
    b = (c.get('llm') or {}).get('backend') or 'ollama'
    print(b.strip().lower())
except Exception:
    print('ollama')
" 2>/dev/null || echo "ollama")
  if [ "$BACKEND" = "kimi" ] && [ -n "$KIMI_API_KEY" ]; then
    NEED_OLLAMA="no"
  fi
fi
if [ "$NEED_OLLAMA" = "yes" ]; then
  OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
  if ! curl -s -f "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    echo "未检测到 Ollama 服务（$OLLAMA_URL）。"
    echo "请先安装并启动 Ollama: https://ollama.com"
    echo "或使用 Kimi：在 config.yaml 中设置 llm.backend 为 kimi，并 export KIMI_API_KEY=sk-xxx"
    echo ""
    read -p "启动后按 Enter 继续..."
  fi
fi

# ---------- 3. 运行主程序 ----------
# 首次运行会从 Hugging Face 下载 Whisper 模型；国内若报错可设置镜像：export HF_ENDPOINT=https://hf-mirror.com
echo "正在启动 JARVIS-M4..."
exec "$PYTHON" main.py
