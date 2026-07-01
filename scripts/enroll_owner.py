#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
录入主人人脸：对着摄像头按提示完成录入，数据保存在 .owner/
用法: .venv/bin/python3 scripts/enroll_owner.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
from owner_face import OwnerRecognizer


def main() -> None:
    owner_dir = ROOT / ".owner"
    models_dir = ROOT / "models" / "face"
    yunet = models_dir / "face_detection_yunet_2023mar.onnx"
    if not yunet.exists():
        print("请先下载人脸模型: bash scripts/download_face_models.sh")
        sys.exit(1)

    print("=" * 50)
    print("  贾维斯 — 主人人脸录入")
    print("  请正对摄像头，保持光线充足、面部清晰")
    print("  3 秒后开始采集…")
    print("=" * 50)
    time.sleep(3)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("无法打开摄像头，请检查权限：系统设置 → 隐私 → 相机")
        sys.exit(1)

    ok = False
    for attempt in range(30):
        ret, frame = cap.read()
        if not ret:
            continue
        if OwnerRecognizer.enroll_from_frame(frame, owner_dir, models_dir):
            ok = True
            print(f"\n录入成功！已保存到 {owner_dir}/")
            print("  owner_feature.npy  — 人脸特征")
            print("  owner_preview.jpg — 预览图")
            print("\n重启贾维斯后，见到你会说：你好主人，需要我做什么？")
            break
        time.sleep(0.2)

    cap.release()
    if not ok:
        print("\n录入失败：未检测到清晰人脸。请调整角度、光线后重试。")
        sys.exit(1)


if __name__ == "__main__":
    main()
