# -*- coding: utf-8 -*-
"""
main.py - JARVIS-M4 主程序：异步主循环与状态机
流程：等待触发 -> 拾音 -> ASR -> LLM -> TTS -> 播放，然后回到等待。
状态：IDLE（等待唤醒/按键）-> LISTENING（拾音中）-> PROCESSING（思考中）-> SPEAKING（说话中）
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# 将项目根目录加入路径，便于同目录下 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml

import brain
import ears
import jarvis_logging
import mouth

# 唤醒词：可选依赖 openwakeword，未安装时仍使用「按 Enter」触发
try:
    import numpy as np
    from openwakeword.model import Model as WakeWordModel
    _OPENWAKEWORD_AVAILABLE = True
except ImportError:
    _OPENWAKEWORD_AVAILABLE = False

# 本模块 logger（在 main() 内 init_logging 之后才有输出）
logger = logging.getLogger("jarvis.main")

# 状态机状态
STATE_IDLE = "IDLE"
STATE_LISTENING = "LISTENING"
STATE_PROCESSING = "PROCESSING"
STATE_SPEAKING = "SPEAKING"


def load_config(config_path: str = "config.yaml") -> dict:
    """加载 config.yaml，若不存在则返回默认字典。"""
    p = Path(config_path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_icon_state(state: str, config: dict) -> None:
    """写入当前状态到文件，供状态动画图标脚本读取（IDLE/LISTENING/PROCESSING/SPEAKING）。"""
    path = (config.get("icon_state_file") or "").strip()
    if not path:
        return
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    try:
        p.write_text(state.strip(), encoding="utf-8")
    except Exception:
        pass


def _wake_word_loop_blocking(wake_cfg: dict):
    """
    在后台线程中运行：打开麦克风，用 openWakeWord 检测唤醒词；
    检测到后关闭麦克风并返回，主流程接着录音。
    """
    import pyaudio
    # openWakeWord 常用参数：16kHz，chunk 1280
    RATE, CHUNK = 16000, 1280
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    threshold = float(wake_cfg.get("threshold", 0.5))
    model_path = (wake_cfg.get("model_path") or "").strip()
    # macOS 上通常用 onnx；未指定时根据系统选择
    inference_framework = wake_cfg.get("inference_framework") or ("onnx" if sys.platform == "darwin" else "tflite")

    pa = pyaudio.PyAudio()
    stream = None
    try:
        if model_path and Path(model_path).exists():
            oww = WakeWordModel(wakeword_models=[model_path], inference_framework=inference_framework)
        else:
            oww = WakeWordModel(inference_framework=inference_framework)
        stream = pa.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio = np.frombuffer(data, dtype=np.int16)
            oww.predict(audio)
            # 分数在 prediction_buffer 中：每个模型对应一个分数列表，取最新一项
            for model_name, scores in (getattr(oww, "prediction_buffer", None) or {}).items():
                if scores and len(scores) > 0 and float(scores[-1]) > threshold:
                    return  # 检测到唤醒词，退出并释放麦克风
    except Exception:
        pass
    finally:
        if stream:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        pa.terminate()


def _try_create_wake_word_model(wake_cfg: dict) -> bool:
    """尝试创建唤醒词模型（用于启动时检测模型是否已下载）。成功返回 True。"""
    try:
        model_path = (wake_cfg.get("model_path") or "").strip()
        inference_framework = wake_cfg.get("inference_framework") or ("onnx" if sys.platform == "darwin" else "tflite")
        if model_path and Path(model_path).exists():
            WakeWordModel(wakeword_models=[model_path], inference_framework=inference_framework)
        else:
            WakeWordModel(inference_framework=inference_framework)
        return True
    except Exception:
        return False


async def wait_for_wake_word_async(config: dict):
    """等待唤醒词被检测到（在线程中跑 openWakeWord，检测到后返回）。"""
    wake_cfg = config.get("wake_word") or {}
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _wake_word_loop_blocking, wake_cfg)


def _wait_enter_blocking():
    """阻塞直到用户按 Enter（用于「按 Enter」触发模式）。"""
    input("按 Enter 开始说话（或 Ctrl+C 退出）... ")


def _wait_key_blocking():
    """阻塞直到用户按任意键（空格/Enter 等），无需再按回车。"""
    import sys
    if sys.platform == "darwin" or sys.platform.startswith("linux"):
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    else:
        input("按任意键开始说话... ")


async def wait_for_trigger(config: dict):
    """
    根据 config 的 trigger 选择触发方式：enter（按 Enter）、key（按任意键）。
    从程序坞点开时没有终端，用「自动等几秒后开始听」代替按键，无需回车。
    """
    # 无终端（如从程序坞启动）时不等回车，等 2 秒后直接开始听
    if not sys.stdin.isatty():
        await asyncio.sleep(2)
        return
    trigger = (config.get("trigger") or "enter").strip().lower()
    loop = asyncio.get_event_loop()
    if trigger == "key":
        await loop.run_in_executor(None, _wait_key_blocking)
    else:
        await loop.run_in_executor(None, _wait_enter_blocking)


async def run_once(config: dict, conversation_history: list) -> list:
    """
    执行一轮：拾音 -> ASR -> LLM -> TTS -> 播放，并返回更新后的对话历史。
    LLM 根据 config 的 llm.backend 选择 Ollama 或 Kimi。
    """
    llm_cfg = config.get("llm") or {}
    backend = (llm_cfg.get("backend") or "ollama").strip().lower()
    ollama_cfg = config.get("ollama") or {}
    kimi_cfg = config.get("kimi") or {}
    whisper_cfg = config.get("whisper") or {}
    tts_cfg = config.get("tts") or {}
    prompt_path = config.get("system_prompt_path") or "prompts/system.txt"

    system_prompt = None
    if Path(prompt_path).exists():
        system_prompt = Path(prompt_path).read_text(encoding="utf-8").strip()

    # 1) 根据 backend 检查对应服务
    if backend == "kimi":
        api_key = brain._get_kimi_api_key()
        kimi_base = kimi_cfg.get("base_url", "https://api.moonshot.cn/v1")
        if not api_key:
            logger.error("使用 Kimi 需设置环境变量: export KIMI_API_KEY=sk-xxx")
            return conversation_history
        if not await brain.check_kimi(api_key, kimi_base):
            logger.error("Kimi API 不可用（请检查 Key 与网络）。")
            return conversation_history
    else:
        base_url = ollama_cfg.get("base_url", "http://localhost:11434")
        if not await brain.check_ollama(base_url):
            logger.error("Ollama 未启动或不可达，请先启动 Ollama（如运行 ollama serve）。")
            return conversation_history

    # 2) 拾音
    _write_icon_state(STATE_LISTENING, config)
    logger.info("[LISTENING] 正在听...")
    # 从 config.ears 读取 VAD 参数，使听觉灵敏度可调（接近 mini 语音输入水平）
    ears_cfg = config.get("ears") or {}
    try:
        pcm = await ears.record_until_silence_async(
            timeout_seconds=float(ears_cfg.get("timeout_seconds", 15.0)),
            silence_duration_ms=float(ears_cfg.get("silence_duration_ms", ears.VAD_SILENCE_MS)),
            speech_min_ms=float(ears_cfg.get("speech_min_ms", ears.VAD_SPEECH_MIN_MS)),
            rms_threshold=float(ears_cfg.get("rms_threshold", ears.VAD_RMS_THRESHOLD)),
        )
    except Exception as e:
        logger.exception("录音失败: %s", e)
        return conversation_history
    if len(pcm) < 16000 * 2:  # 少于约 1 秒
        logger.info("未检测到有效语音，跳过")
        return conversation_history

    # 3) ASR
    _write_icon_state(STATE_PROCESSING, config)
    logger.info("[PROCESSING] 识别中...")
    ears_impl = ears.Ears(
        model_size=whisper_cfg.get("model_size", "tiny"),
        device=whisper_cfg.get("device", "cpu"),
        compute_type=whisper_cfg.get("compute_type", "int8"),
        language=whisper_cfg.get("language") or None,
        beam_size=whisper_cfg.get("beam_size", 3),
        initial_prompt=whisper_cfg.get("initial_prompt") or None,
    )
    user_text = await ears_impl.transcribe_async(pcm)
    if not user_text.strip():
        logger.info("未识别到文字，跳过")
        return conversation_history
    logger.info("[用户] %s", user_text)

    # 4) LLM
    logger.info("[PROCESSING] 思考中...")
    if backend == "kimi":
        reply = await brain.chat_simple_kimi(
            user_text,
            history=conversation_history,
            system_prompt=system_prompt,
            base_url=kimi_cfg.get("base_url", "https://api.moonshot.cn/v1"),
            model=kimi_cfg.get("model", "moonshot-v1-8k"),
            timeout=kimi_cfg.get("timeout_seconds", 60),
        )
    else:
        reply = await brain.chat_simple(
            user_text,
            history=conversation_history,
            system_prompt=system_prompt,
            base_url=ollama_cfg.get("base_url", "http://localhost:11434"),
            model=ollama_cfg.get("model", "qwen2.5:7b-instruct"),
        )
    conversation_history.append({"role": "user", "content": user_text})
    conversation_history.append({"role": "assistant", "content": reply})

    # 对话摘要/记忆：达到阈值时用 LLM 压缩旧对话为一条摘要，再截断
    memory_cfg = config.get("memory") or {}
    max_before_summary = memory_cfg.get("max_rounds_before_summary", 8)
    summary_every = memory_cfg.get("summary_every_rounds", 4)
    if len(conversation_history) >= max_before_summary and summary_every > 0:
        try:
            summary = await brain.summarize_conversation(conversation_history[:max_before_summary], config)
            if summary:
                summary_msg = {"role": "user", "content": "[此前对话摘要]\n" + summary}
                conversation_history = [summary_msg] + conversation_history[max_before_summary:]
                logger.info("已生成对话摘要并压缩历史")
        except Exception as e:
            logger.warning("生成对话摘要失败，仅截断: %s", e)
            conversation_history = conversation_history[-max_before_summary:]
    # 总条数上限，避免上下文过长
    if len(conversation_history) > 10:
        conversation_history = conversation_history[-10:]

    # 5) TTS + 播放
    _write_icon_state(STATE_SPEAKING, config)
    logger.info("[SPEAKING] 贾维斯正在说...")
    voice = tts_cfg.get("voice", "zh-CN-XiaoxiaoNeural")
    cache_dir = tts_cfg.get("cache_dir", ".tts_cache")
    try:
        await mouth.speak_sentence(reply, voice=voice, cache_dir=cache_dir)
    except Exception as e:
        logger.exception("播放失败: %s", e)

    _write_icon_state(STATE_IDLE, config)
    return conversation_history


async def main():
    config = load_config()
    # 统一日志：控制台 + 可选文件（config.log.file）
    jarvis_logging.init_logging(config)
    # 可覆盖系统提示词路径
    if config.get("system_prompt_path"):
        os.environ["JARVIS_SYSTEM_PROMPT"] = config["system_prompt_path"]
    # exec_shell 白名单：从 config 注入，供 brain.exec_shell 校验
    exec_shell_cfg = config.get("exec_shell") or {}
    brain.set_exec_shell_policy(
        allow_all=bool(exec_shell_cfg.get("allow_all")),
        whitelist=exec_shell_cfg.get("whitelist") or [],
    )
    # OpenClaw 执行结果语音回传：从 config 注入环境变量，供 brain.openclaw_send 使用
    openclaw_cfg = config.get("openclaw") or {}
    if openclaw_cfg.get("use_http"):
        os.environ["OPENCLAW_USE_HTTP"] = "1"
        if openclaw_cfg.get("gateway_url"):
            os.environ["OPENCLAW_GATEWAY_URL"] = str(openclaw_cfg["gateway_url"]).strip().rstrip("/")
        if openclaw_cfg.get("timeout_seconds") is not None:
            os.environ["OPENCLAW_TIMEOUT_SECONDS"] = str(openclaw_cfg["timeout_seconds"])
        # 认证：优先 token；Gateway 若为 password 模式可用 password（建议用环境变量，勿在 config 明文）
        if openclaw_cfg.get("token"):
            os.environ["OPENCLAW_GATEWAY_TOKEN"] = str(openclaw_cfg["token"])
        if openclaw_cfg.get("password"):
            os.environ["OPENCLAW_GATEWAY_PASSWORD"] = str(openclaw_cfg["password"])

    wake_cfg = config.get("wake_word") or {}
    use_wake_word = wake_cfg.get("enabled") and _OPENWAKEWORD_AVAILABLE
    wake_fallback_msg = False  # 是否已打印「改用按 Enter」类提示，避免重复
    # 若启用唤醒词，启动时检测模型是否存在（预训练模型需先下载）
    if use_wake_word:
        loop = asyncio.get_event_loop()
        model_ok = await loop.run_in_executor(None, _try_create_wake_word_model, wake_cfg)
        if not model_ok:
            use_wake_word = False
            wake_fallback_msg = True
            logger.info("JARVIS-M4 已就绪。唤醒词模型未就绪，本次使用「按 Enter 后录音」。")
            logger.info("  首次使用唤醒词请先下载模型（需联网）: python3 -c \"import openwakeword; openwakeword.utils.download_models()\"")
    if use_wake_word:
        logger.info("JARVIS-M4 已就绪。当前为「唤醒词」模式，说出唤醒词（如 Hey Jarvis）后开始录音。")
    elif not wake_fallback_msg:
        if wake_cfg.get("enabled") and not _OPENWAKEWORD_AVAILABLE:
            logger.info("JARVIS-M4 已就绪。config 已启用唤醒词但未安装 openwakeword，使用按键触发。")
            logger.info("  安装唤醒词依赖: pip3 install openwakeword")
        else:
            if not sys.stdin.isatty():
                logger.info("JARVIS-M4 已就绪。当前为「程序坞」模式，约 2 秒后开始听，直接说话即可。")
            else:
                trigger = (config.get("trigger") or "enter").strip().lower()
                if trigger == "key":
                    logger.info("JARVIS-M4 已就绪。当前为「按任意键」模式，按空格或 Enter 后开始录音。")
                else:
                    logger.info("JARVIS-M4 已就绪。当前为「按 Enter」模式，按 Enter 后开始录音。")
    conversation_history = []
    _write_icon_state(STATE_IDLE, config)

    while True:
        try:
            if use_wake_word:
                await wait_for_wake_word_async(config)
                logger.info("[唤醒] 已检测到，请说话...")
            else:
                await wait_for_trigger(config)
            conversation_history = await run_once(config, conversation_history)
        except KeyboardInterrupt:
            logger.info("再见。")
            # 直接退出，避免等待 run_in_executor 里的线程（input/录音/播放）导致退出时报错
            os._exit(0)
        except Exception as e:
            logger.exception("主循环异常: %s", e)
            conversation_history = conversation_history  # 保持历史继续下一轮


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见。")
        os._exit(0)
