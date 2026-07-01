#!/usr/bin/env bash
# 下载 OpenCV 人脸识别模型（YuNet + SFace）
set -e
cd "$(dirname "$0")/.."
DIR="models/face"
mkdir -p "$DIR"
BASE="https://github.com/opencv/opencv_zoo/raw/main/models"
MIRROR="https://ghproxy.net/$BASE"
download_one() {
  local rel="$1"
  local out="$DIR/$(basename "$rel")"
  if [ -f "$out" ]; then echo "已有 $(basename "$rel")"; return 0; fi
  echo "下载 $rel ..."
  curl --connect-timeout 15 --max-time 300 -L -f -o "$out" "$MIRROR/$rel" \
    || curl --connect-timeout 15 --max-time 300 -L -f -o "$out" "$BASE/$rel"
}
download_one "face_detection_yunet/face_detection_yunet_2023mar.onnx"
download_one "face_recognition_sface/face_recognition_sface_2021dec.onnx"
echo "完成: $DIR"
ls -la "$DIR"
