# -*- coding: utf-8 -*-
"""
owner_face.py - 主人人脸识别与见面打招呼
使用 OpenCV YuNet 检测人脸 + SFace 提取特征，与录入的主人特征比对。
全部在本地运行，人脸数据保存在 .owner/ 目录。
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("jarvis.owner")

try:
    import cv2

    _CV2_AVAILABLE = True
except ImportError:
    cv2 = None  # type: ignore
    _CV2_AVAILABLE = False

# OpenCV 余弦相似度阈值：高于此认为同一人（官方示例约 0.363）
DEFAULT_MATCH_THRESHOLD = 0.36


class OwnerRecognizer:
    """主人人脸：录入、比对、见面打招呼。"""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.greeting = str(cfg.get("greeting", "你好主人，需要我做什么？"))
        self.cooldown_seconds = float(cfg.get("cooldown_seconds", 300))
        self.check_interval = float(cfg.get("check_interval_seconds", 2.0))
        self.match_threshold = float(cfg.get("match_threshold", DEFAULT_MATCH_THRESHOLD))
        self.owner_dir = Path(cfg.get("owner_dir", ".owner"))
        self.models_dir = Path(cfg.get("models_dir", "models/face"))
        self._owner_feature: np.ndarray | None = None
        self._detector = None
        self._recognizer = None
        self._last_greet_at = 0.0
        self._greeting_lock = asyncio.Lock()
        self._models_ready = False

    def load(self) -> bool:
        """加载人脸模型与主人特征；成功返回 True。"""
        if not self.enabled or not _CV2_AVAILABLE:
            return False
        if not self._load_models():
            return False
        feat_path = self.owner_dir / "owner_feature.npy"
        if not feat_path.exists():
            logger.warning(
                "[主人] 尚未录入人脸，请运行: .venv/bin/python3 scripts/enroll_owner.py"
            )
            return False
        self._owner_feature = np.load(str(feat_path))
        logger.info("[主人] 已加载主人人脸特征，见面将主动打招呼")
        return True

    def _load_models(self) -> bool:
        if self._models_ready:
            return True
        yunet = self.models_dir / "face_detection_yunet_2023mar.onnx"
        sface = self.models_dir / "face_recognition_sface_2021dec.onnx"
        if not yunet.exists() or not sface.exists():
            logger.warning(
                "[主人] 人脸模型缺失，请运行: bash scripts/download_face_models.sh"
            )
            return False
        try:
            self._detector = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), 0.6, 0.3, 5000)
            self._recognizer = cv2.FaceRecognizerSF.create(str(sface), "")
            self._models_ready = True
            return True
        except Exception as e:
            logger.warning("[主人] 加载人脸模型失败: %s", e)
            return False

    def _extract_face_feature(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        """从 BGR 画面中提取最大人脸的特征向量。"""
        if self._detector is None or self._recognizer is None or frame_bgr is None:
            return None
        h, w = frame_bgr.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(frame_bgr)
        if faces is None or len(faces) == 0:
            return None
        # 取面积最大的人脸
        best = max(faces, key=lambda f: float(f[2]) * float(f[3]))
        aligned = self._recognizer.alignCrop(frame_bgr, best)
        return self._recognizer.feature(aligned)

    def is_owner_in_frame(self, frame_bgr: np.ndarray) -> bool:
        """判断当前画面是否为主人。"""
        if self._owner_feature is None:
            return False
        feat = self._extract_face_feature(frame_bgr)
        if feat is None:
            return False
        score = self._recognizer.match(
            self._owner_feature, feat, cv2.FaceRecognizerSF_FR_COSINE
        )
        return float(score) >= self.match_threshold

    @staticmethod
    def enroll_from_frame(frame_bgr: np.ndarray, owner_dir: Path, models_dir: Path) -> bool:
        """从一帧画面录入主人人脸并保存特征（供 enroll 脚本调用）。"""
        if not _CV2_AVAILABLE:
            return False
        rec = OwnerRecognizer({"enabled": True, "owner_dir": str(owner_dir), "models_dir": str(models_dir)})
        if not rec._load_models():
            return False
        feat = rec._extract_face_feature(frame_bgr)
        if feat is None:
            return False
        owner_dir.mkdir(parents=True, exist_ok=True)
        np.save(str(owner_dir / "owner_feature.npy"), feat)
        cv2.imwrite(str(owner_dir / "owner_preview.jpg"), frame_bgr)
        return True

    async def greeting_loop(
        self,
        vision_watcher: Any,
        get_state_fn,
        speak_fn,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """
        后台协程：周期性检查摄像头，认出主人且冷却结束后语音打招呼。
        get_state_fn: 返回当前状态 IDLE/LISTENING/...
        speak_fn: async (text) -> None 语音播放
        """
        if not self.enabled or self._owner_feature is None:
            return
        logger.info("[主人] 见面打招呼已开启（冷却 %.0f 秒）", self.cooldown_seconds)
        while stop_event is None or not stop_event.is_set():
            try:
                await asyncio.sleep(self.check_interval)
                if get_state_fn() != "IDLE":
                    continue
                frame = vision_watcher.get_latest_frame_bgr() if vision_watcher else None
                if frame is None:
                    continue
                loop = asyncio.get_event_loop()
                is_owner = await loop.run_in_executor(None, self.is_owner_in_frame, frame)
                if not is_owner:
                    continue
                now = time.time()
                if now - self._last_greet_at < self.cooldown_seconds:
                    continue
                async with self._greeting_lock:
                    if get_state_fn() != "IDLE":
                        continue
                    if now - self._last_greet_at < self.cooldown_seconds:
                        continue
                    self._last_greet_at = now
                    logger.info("[主人] 认出主人，打招呼")
                    await speak_fn(self.greeting)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("[主人] 打招呼循环: %s", e)
