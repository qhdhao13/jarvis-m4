# -*- coding: utf-8 -*-
"""
vision.py - 贾维斯的「眼睛」：实时摄像头视觉
后台线程持续采集画面，周期性调用 Ollama 视觉模型（如 minicpm-v）更新场景描述，
供对话时注入上下文，让贾维斯能「看到」用户。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

logger = logging.getLogger("jarvis.vision")

# OpenCV 可选：未安装时视觉模块不可用
try:
    import cv2
    import numpy as np

    _CV2_AVAILABLE = True
except ImportError:
    cv2 = None  # type: ignore
    np = None  # type: ignore
    _CV2_AVAILABLE = False


# 用户话里若含这些词，触发「即时看图」再分析一帧（比后台缓存更准）
_VISION_QUERY_KEYWORDS = (
    "看到", "看见", "瞧瞧", "看一下", "看看", "识别", "谁在", "什么颜色",
    "穿什么", "在做什么", "在干嘛", "在干什么", "画面", "摄像头", "镜头",
    "see", "look", "watch", "camera",
)


@dataclass
class VisionState:
    """线程安全的视觉状态快照。"""

    description: str = ""
    updated_at: float = 0.0
    frame_jpeg_base64: str = ""
    camera_ok: bool = False
    last_error: str = ""
    analyzing: bool = False


class VisionWatcher:
    """
    实时视觉监视器：
    - 采集线程：以 capture_fps 从摄像头读帧，保留最新一帧
    - 分析协程：每 analyze_interval_seconds 调用视觉模型更新场景描述
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.device_index = int(cfg.get("device_index", 0))
        self.capture_fps = float(cfg.get("capture_fps", 5.0))
        self.analyze_interval = float(cfg.get("analyze_interval_seconds", 3.0))
        self.jpeg_quality = int(cfg.get("jpeg_quality", 70))
        self.max_width = int(cfg.get("max_width", 640))
        self.model = str(cfg.get("model", "minicpm-v:latest"))
        self.base_url = str(cfg.get("base_url", "http://localhost:11434")).rstrip("/")
        self.analyze_prompt = str(
            cfg.get(
                "analyze_prompt",
                "你是贾维斯的眼睛。用一两句中文简要描述摄像头画面："
                "是否有人、大致动作、主要物体与场景。不要编造看不见的内容。",
            )
        )
        self.inject_context = bool(cfg.get("inject_context", True))

        self._lock = threading.Lock()
        self._state = VisionState()
        self._latest_frame: Any = None
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._analyze_task: asyncio.Task | None = None

    def start(self) -> bool:
        """启动摄像头采集线程；分析协程由 main 在 asyncio 中调用 start_analyze_loop。"""
        if not self.enabled:
            return False
        if not _CV2_AVAILABLE:
            self._set_error("未安装 opencv-python-headless，请执行: pip install opencv-python-headless")
            logger.warning("[视觉] %s", self._state.last_error)
            return False
        if self._capture_thread and self._capture_thread.is_alive():
            return True

        self._stop_event.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, name="jarvis-vision-capture", daemon=True)
        self._capture_thread.start()
        logger.info("[视觉] 摄像头采集已启动（设备 %s）", self.device_index)
        return True

    async def start_analyze_loop(self) -> None:
        """在 asyncio 主循环中周期性分析最新帧。"""
        if not self.enabled:
            return
        while not self._stop_event.is_set():
            try:
                await self._analyze_latest_frame()
            except Exception as e:
                self._set_error(f"视觉分析异常: {e}")
                logger.warning("[视觉] %s", e)
            await asyncio.sleep(self.analyze_interval)

    def stop(self) -> None:
        """停止采集与分析。"""
        self._stop_event.set()
        if self._analyze_task and not self._analyze_task.done():
            self._analyze_task.cancel()
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)

    def get_latest_frame_bgr(self) -> Any:
        """返回最新一帧 BGR 图像副本（供主人人脸识别等使用）。"""
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def get_context(self) -> str:
        """返回可注入 LLM 的当前画面描述（无有效描述时返回空字符串）。"""
        with self._lock:
            if not self._state.description:
                if self._state.last_error:
                    return f"[摄像头] {self._state.last_error}"
                return ""
            age = time.time() - self._state.updated_at
            return f"[当前摄像头画面（约 {int(age)} 秒前更新）]\n{self._state.description}"

    def is_ready(self) -> bool:
        with self._lock:
            return self._state.camera_ok and bool(self._state.description)

    @staticmethod
    def user_wants_vision(user_text: str) -> bool:
        """判断用户是否在明确询问「看到了什么」类问题。"""
        text = (user_text or "").lower()
        return any(kw in text for kw in _VISION_QUERY_KEYWORDS)

    async def analyze_now(self, question: str | None = None) -> str:
        """即时分析最新一帧（用户主动问「你看到什么」时用）。"""
        b64 = self._get_latest_jpeg_base64()
        if not b64:
            return "摄像头暂无画面，请检查是否已授权「终端/Python」使用相机（系统设置 → 隐私与安全性 → 相机）。"
        prompt = question or "请用一两句中文描述你在这张图里看到的内容。"
        return await self._call_vision_model(b64, prompt)

    def _capture_loop(self) -> None:
        """后台线程：持续读取摄像头，保留最新帧。"""
        cap = cv2.VideoCapture(self.device_index)
        if not cap.isOpened():
            self._set_error(
                "无法打开摄像头。请在「系统设置 → 隐私与安全性 → 相机」中允许终端/Python 访问。"
            )
            logger.warning("[视觉] %s", self._state.last_error)
            return

        with self._lock:
            self._state.camera_ok = True
            self._state.last_error = ""

        interval = 1.0 / max(self.capture_fps, 1.0)
        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if ret and frame is not None:
                frame = self._resize_frame(frame)
                with self._lock:
                    self._latest_frame = frame.copy()
            else:
                self._set_error("摄像头读帧失败")
            time.sleep(interval)

        cap.release()
        with self._lock:
            self._state.camera_ok = False

    def _resize_frame(self, frame: Any) -> Any:
        """缩小分辨率，加快视觉模型推理。"""
        h, w = frame.shape[:2]
        if w <= self.max_width:
            return frame
        scale = self.max_width / float(w)
        new_h = max(1, int(h * scale))
        return cv2.resize(frame, (self.max_width, new_h), interpolation=cv2.INTER_AREA)

    def _get_latest_jpeg_base64(self) -> str:
        with self._lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()
        if frame is None:
            return ""
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            return ""
        return base64.b64encode(buf).decode("ascii")

    async def _analyze_latest_frame(self) -> None:
        """用视觉模型分析最新帧并更新场景描述。"""
        b64 = self._get_latest_jpeg_base64()
        if not b64:
            return
        with self._lock:
            if self._state.analyzing:
                return
            self._state.analyzing = True
        try:
            desc = await self._call_vision_model(b64, self.analyze_prompt)
            if desc.strip():
                with self._lock:
                    self._state.description = desc.strip()
                    self._state.updated_at = time.time()
                    self._state.frame_jpeg_base64 = b64
                    self._state.last_error = ""
                logger.debug("[视觉] 场景更新: %s", desc[:80])
        finally:
            with self._lock:
                self._state.analyzing = False

    async def _call_vision_model(self, image_b64: str, prompt: str) -> str:
        """调用 Ollama 视觉模型（/api/chat，messages 中带 images）。"""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
            "stream": False,
        }
        timeout = aiohttp.ClientTimeout(total=120)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=timeout) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        self._set_error(f"视觉模型请求失败 ({resp.status}): {text[:120]}")
                        return ""
                    data = await resp.json()
                    return ((data.get("message") or {}).get("content") or "").strip()
        except asyncio.TimeoutError:
            self._set_error("视觉模型响应超时")
            return ""
        except Exception as e:
            self._set_error(str(e))
            return ""

    def _set_error(self, msg: str) -> None:
        with self._lock:
            self._state.last_error = msg
