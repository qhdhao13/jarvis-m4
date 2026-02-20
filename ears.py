# -*- coding: utf-8 -*-
"""
ears.py - JARVIS 的「耳朵」：ASR 语音识别层
使用 Faster-Whisper 做识别，PyAudio 做麦克风采集，简单 VAD（语音活动检测）节流算力。
Mac 上可配置 device/compute_type 以更好利用 Metal（若 faster-whisper 支持 MPS）。
"""

import asyncio
import io
import os
import struct
import wave
from pathlib import Path

import numpy as np

# 延迟导入，避免未安装时主程序无法启动
try:
    import pyaudio
except ImportError:
    pyaudio = None

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

# 录音参数：16kHz 单声道，与 Whisper 常用输入一致
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 1024
FORMAT = pyaudio.paInt16 if pyaudio else None

# 简单 VAD：基于短时能量（RMS）的阈值（默认偏灵敏，接近 Mac 自带语音输入）
VAD_RMS_THRESHOLD = 280      # 高于此认为有人声；值越低越灵敏，环境吵可调高
VAD_SILENCE_MS = 550         # 持续静音这么久认为一句话结束；越短结束越跟手
VAD_SPEECH_MIN_MS = 300      # 最短语音长度，避免误触
FRAME_MS = 30                # 每帧约 30ms


def _rms(data: bytes) -> float:
    """计算一段 PCM 数据的 RMS（均方根），用于简单 VAD。"""
    if len(data) < 2:
        return 0.0
    n = len(data) // 2
    samples = struct.unpack(f"{n}h", data[: n * 2])
    arr = np.array(samples, dtype=np.float32)
    return float(np.sqrt(np.mean(arr * arr)))


class Ears:
    """耳朵：麦克风 + VAD + Whisper 识别。"""

    def __init__(
        self,
        model_size: str = "tiny",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "zh",
        beam_size: int = 3,
        initial_prompt: str | None = None,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language or None  # None 表示自动检测
        self.beam_size = max(1, min(5, int(beam_size)))  # 1～5，越大越准越慢
        self.initial_prompt = (initial_prompt or "").strip() or None  # 词汇提示，利于识别专名
        self._model = None

    def _get_model(self):
        """懒加载 Whisper 模型（首次识别时加载，避免启动过慢）。"""
        if WhisperModel is None:
            raise RuntimeError("未安装 faster-whisper，请执行: pip install faster-whisper")
        if self._model is None:
            # 国内直连 Hugging Face 常失败，未设置时使用国内镜像以便首次下载 Whisper 模型
            if "HF_ENDPOINT" not in os.environ:
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            # Mac 上 device 通常为 cpu；若 future 版本支持 MPS 可改为 "mps"
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root=None,
            )
        return self._model

    def transcribe_audio_bytes(self, pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
        """
        将一整段 PCM 音频（16bit 单声道）转成文字。
        在 asyncio 中建议用 run_in_executor 调用，避免阻塞事件循环。
        """
        model = self._get_model()
        # faster-whisper 接受文件路径或 numpy array
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=True,
            initial_prompt=self.initial_prompt,
        )
        text = " ".join(s.text.strip() for s in segments if s.text).strip()
        return text or ""

    async def transcribe_async(self, pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
        """异步封装：在线程池中执行转写，不阻塞主循环。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.transcribe_audio_bytes,
            pcm_bytes,
            sample_rate,
        )


def record_until_silence(
    timeout_seconds: float = 10.0,
    silence_duration_ms: float = VAD_SILENCE_MS,
    speech_min_ms: float = VAD_SPEECH_MIN_MS,
    rms_threshold: float = VAD_RMS_THRESHOLD,
) -> bytes:
    """
    从默认麦克风录音，检测到人声后开始保留，持续静音一段时间后停止。
    返回 PCM 数据（16bit 单声道 16kHz）。
    若未安装 PyAudio 或没有麦克风，会抛出异常。
    """
    if pyaudio is None:
        raise RuntimeError("未安装 PyAudio，请执行: pip install PyAudio")

    pa = pyaudio.PyAudio()
    stream = None
    try:
        stream = pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
        frames = []
        in_speech = False
        speech_start_idx = -1
        silence_frames = 0
        speech_min_frames = max(1, int(speech_min_ms / FRAME_MS))
        silence_max_frames = int(silence_duration_ms / FRAME_MS)
        max_frames = int(timeout_seconds * SAMPLE_RATE / (CHUNK * 2))  # 粗略

        for i in range(max_frames):
            data = stream.read(CHUNK, exception_on_overflow=False)
            rms = _rms(data)
            if rms >= rms_threshold:
                if not in_speech:
                    in_speech = True
                    speech_start_idx = len(frames)
                    silence_frames = 0
                frames.append(data)
                silence_frames = 0
            else:
                if in_speech:
                    silence_frames += 1
                    frames.append(data)
                    if silence_frames >= silence_max_frames:
                        # 只保留从 speech_start 开始的段
                        speech_len = len(frames) - (silence_frames - silence_max_frames)
                        if speech_len >= speech_min_frames:
                            frames = frames[:speech_len]
                            break
                        in_speech = False
                        silence_frames = 0
                        frames = []
                else:
                    frames.append(data)
        return b"".join(frames) if frames else b""
    finally:
        if stream:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        pa.terminate()


async def record_until_silence_async(
    timeout_seconds: float = 10.0,
    **kwargs,
) -> bytes:
    """在线程池中执行录音，避免阻塞。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: record_until_silence(timeout_seconds=timeout_seconds, **kwargs),
    )
