# -*- coding: utf-8 -*-
"""
mouth.py - JARVIS 的「嘴巴」：TTS 语音合成与播放
封装 Edge-TTS 的异步调用，用 pygame.mixer 播放音频流，并做简单缓存避免重复合成相同句子。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

# 延迟导入
try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    import pygame
except ImportError:
    pygame = None


def _get_cache_path(cache_dir: str, text: str, voice: str) -> Path:
    """根据文本和音色生成缓存文件路径（相同内容复用）。"""
    key = f"{voice}|{text}"
    name = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] + ".mp3"
    return Path(cache_dir) / name


async def synthesize_to_file(
    text: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    output_path: str | Path | None = None,
) -> str | Path:
    """
    使用 Edge-TTS 将 text 合成为音频并写入文件。
    若未指定 output_path，会写入临时文件并返回路径。
    """
    if edge_tts is None:
        raise RuntimeError("未安装 edge-tts，请执行: pip install edge-tts")
    communicate = edge_tts.Communicate(text, voice)
    if output_path is None:
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        path = Path(path)
    else:
        path = Path(output_path)
    await communicate.save(str(path))
    return path


async def tts_speak(
    text: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    cache_dir: str | None = ".tts_cache",
    use_cache: bool = True,
) -> None:
    """
    说出一段文字：先查缓存，无则调用 Edge-TTS 合成并写入缓存，再播放。
    播放使用 pygame.mixer，会阻塞直到播完。
    """
    if not text.strip():
        return
    if pygame is None:
        raise RuntimeError("未安装 pygame，请执行: pip install pygame")

    path = None
    if use_cache and cache_dir:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        path = _get_cache_path(cache_dir, text, voice)
        if path.exists():
            pass  # 直接播放
        else:
            await synthesize_to_file(text, voice=voice, output_path=path)
    else:
        path = await synthesize_to_file(text, voice=voice)

    path = str(path)
    if not os.path.exists(path):
        print("[错误] 音频文件不存在:", path)
        return
    # macOS 优先用系统 afplay 播放，通常比 pygame 更稳定、不易无声
    def _play():
        import subprocess
        import sys
        if sys.platform == "darwin":
            try:
                subprocess.run(["afplay", path], check=True, capture_output=True, timeout=120)
                return
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                if isinstance(e, subprocess.TimeoutExpired):
                    print("[警告] 播放超时")
                # 回退到 pygame
        try:
            pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=2048)
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            clock = pygame.time.Clock()
            wait_sec = 0
            while pygame.mixer.music.get_busy() and wait_sec < 120:
                clock.tick(10)
                wait_sec += 0.01
            if wait_sec >= 120:
                print("[警告] 播放超时，请检查系统音量与音频设备")
        except Exception as e:
            print("[错误] 播放失败:", e)
        finally:
            try:
                pygame.mixer.quit()
            except Exception:
                pass

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _play)


async def speak_sentence(sentence: str, voice: str = "zh-CN-XiaoxiaoNeural", cache_dir: str = ".tts_cache") -> None:
    """对外接口：说一句话（带缓存）。"""
    await tts_speak(sentence, voice=voice, cache_dir=cache_dir)
