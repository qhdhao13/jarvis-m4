#!/usr/bin/env bash
# 使用系统 curl 下载 openWakeWord 模型，绕过 Python requests 的 SSL 问题（如 macOS LibreSSL）
# 用法：./scripts/download_openwakeword_models.sh
# 无法连 GitHub 时：可设置代理 export HTTPS_PROXY=http://127.0.0.1:7890 或使用镜像（脚本会自动尝试）

set -e
BASE="https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
# 国内 GitHub 加速镜像（按顺序尝试；阿里/清华镜像是 git 克隆用，不代理 release 文件，故用下列代理站）
MIRRORS=("https://ghproxy.net" "https://ghproxy.com" "https://mirror.ghproxy.com")
# 模型目录：与 openwakeword 包内 resources/models 一致
DIR="$(python3 -c "
import sys, os
try:
    import openwakeword
    d = os.path.join(os.path.dirname(openwakeword.__file__), 'resources', 'models')
    print(d)
except Exception as e:
    print('ERROR:', e, file=sys.stderr)
    sys.exit(1)
" 2>/dev/null)"
mkdir -p "$DIR"
cd "$DIR"

FILES=(
  embedding_model.tflite embedding_model.onnx
  melspectrogram.tflite melspectrogram.onnx
  silero_vad.onnx
  alexa_v0.1.tflite alexa_v0.1.onnx
  hey_mycroft_v0.1.tflite hey_mycroft_v0.1.onnx
  hey_jarvis_v0.1.tflite hey_jarvis_v0.1.onnx
  hey_rhasspy_v0.1.tflite hey_rhasspy_v0.1.onnx
  timer_v0.1.tflite timer_v0.1.onnx
  weather_v0.1.tflite weather_v0.1.onnx
)

# 下载单个文件：先直连，失败则依次尝试各镜像（设了 HTTPS_PROXY 时 curl 会走代理）
download_one() {
  local f="$1"
  local url="$BASE/$f"
  if curl --http1.1 -sSL -f -o "$f" "$url" 2>/dev/null; then
    return 0
  fi
  for M in "${MIRRORS[@]}"; do
    echo "直连失败，尝试镜像 $M ..."
    if curl --http1.1 -sSL -f -o "$f" "$M/$url" 2>/dev/null; then
      return 0
    fi
  done
  return 1
}

echo "下载目录: $DIR"
[ -n "$HTTPS_PROXY" ] || [ -n "$https_proxy" ] && echo "使用代理: ${HTTPS_PROXY:-$https_proxy}"
for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then
    echo "已有 $f，跳过"
  else
    echo "下载 $f ..."
    if ! download_one "$f"; then
      echo "失败: $f"
      echo "建议: 1) 设置代理后重试: export HTTPS_PROXY=http://127.0.0.1:7890"
      echo "      2) 或在本机用浏览器/能访问 GitHub 的网络下载 v0.5.1 的 release 文件，放到: $DIR"
      exit 1
    fi
  fi
done
echo "完成。可运行 python3 main.py 使用唤醒词。"
