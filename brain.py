# -*- coding: utf-8 -*-
"""
brain.py - JARVIS 的「大脑」：LLM 交互层
封装 Ollama 调用，支持流式输出（边说边返回），并实现简单的 Function Calling。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import aiohttp

# 默认配置，可由 main 注入
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
SYSTEM_PROMPT_PATH = os.getenv("JARVIS_SYSTEM_PROMPT", "prompts/system.txt")


def _load_system_prompt(path: str) -> str:
    """从文件加载系统提示词，若文件不存在则返回默认贾维斯人设。"""
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return (
        "你是贾维斯（JARVIS），用户的智能助手。"
        "当前系统运行在 Apple M4 芯片上，神经网络连接正常。"
        "回复简洁、专业，支持中英文。"
    )


# ---------- 工具定义：供 LLM 在回复中声明调用 ----------
# 这里用「自然语言 + 约定 JSON」的方式，让 Qwen/Llama 输出如：
#   {"tool": "get_weather", "args": {"city": "北京"}}
# 或纯对话无 tool 时直接返回文本。

TOOL_DESCRIPTIONS = """
你是这台 Mac mini 的语音助手，可使用以下工具（需要时在回复中单独输出一行 JSON，不要夹杂其他文字）：
- get_weather(city): 查询天气，参数 city 为城市名。
- mac_volume(level): 设置系统音量，level 为 0～100 的整数。
- mac_open_app(app_name): 打开应用，app_name 如 Safari、备忘录、日历、音乐、邮件、抖音。
- mac_lock_screen(): 锁定屏幕（无参数）。
- mac_get_time(): 获取当前日期时间（无参数）。
- mac_open_url(url): 在浏览器打开网址，url 如 https://www.baidu.com；找抖音上某内容可打开 https://www.douyin.com/search/关键词（关键词需 URL 编码或英文）。
- mac_sleep_display(): 关闭显示器（无参数）。
- mac_system_info(): 查看本机运行时间、磁盘信息（无参数）。
- openclaw_send(message): 向本机 OpenClaw（用户也称「龙虾」）发送一条指令，message 为自然语言指令（如「打开灯」「截屏」）。用户说「让龙虾做xxx」时即用此工具。
- exec_shell(cmd): 执行 shell 命令；仅允许 config 中白名单内的命令前缀（如 open -a、osascript、date），否则拒绝执行。
输出格式示例：{"tool": "mac_open_app", "args": {"app_name": "Safari"}}
若不需要调用工具，直接回复自然语言即可。
"""


async def get_weather(city: str) -> str:
    """查询城市天气（wttr.in 免费接口，支持中文城市名如秦皇岛）。"""
    city = (city or "").strip()
    if not city:
        return "请告诉我要查哪座城市。"
    try:
        from urllib.parse import quote

        headers = {"User-Agent": "curl/7.64.1", "Accept-Language": "zh-CN,zh;q=0.9"}
        q = quote(city)
        async with aiohttp.ClientSession() as session:
            # 优先 JSON 详情（wttr.in 返回 text/plain，需手动 json.loads）
            url_j1 = f"https://wttr.in/{q}?format=j1&lang=zh"
            async with session.get(url_j1, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    raw = await resp.text()
                    data = json.loads(raw)
                    cur = (data.get("current_condition") or [{}])[0]
                    area = (data.get("nearest_area") or [{}])[0]
                    name = city
                    if area.get("areaName") and not any("\u4e00" <= c <= "\u9fff" for c in city):
                        name = area["areaName"][0].get("value", city)
                    temp = cur.get("temp_C", "?")
                    feels = cur.get("FeelsLikeC", "")
                    desc = ""
                    if cur.get("lang_zh"):
                        desc = cur["lang_zh"][0].get("value", "")
                    elif cur.get("weatherDesc"):
                        desc = cur["weatherDesc"][0].get("value", "")
                    humid = cur.get("humidity", "")
                    wind = cur.get("windspeedKmph", "")
                    parts = [f"{name}现在{desc}，气温 {temp} 摄氏度"]
                    if feels:
                        parts.append(f"体感 {feels} 度")
                    if humid:
                        parts.append(f"湿度 {humid}%")
                    if wind:
                        parts.append(f"风速约 {wind} 公里每小时")
                    return "，".join(parts) + "。"
            # 回退：一行简讯
            url3 = f"https://wttr.in/{q}?format=3&lang=zh"
            async with session.get(url3, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    line = (await resp.text()).strip()
                    if line:
                        return line.replace(":", "，") + "。"
        return f"{city}天气查询失败，请稍后再试。"
    except asyncio.TimeoutError:
        return f"{city}天气查询超时，请稍后再试。"
    except Exception as e:
        return f"{city}天气查询失败：{e}"


# exec_shell 白名单：由 main 在加载 config 后调用 set_exec_shell_policy 注入
_exec_shell_allow_all = False
_exec_shell_whitelist: list[str] = []


def set_exec_shell_policy(allow_all: bool = False, whitelist: list[str] | None = None) -> None:
    """设置 exec_shell 的执行策略（白名单）。main 加载 config 后调用。"""
    global _exec_shell_allow_all, _exec_shell_whitelist
    _exec_shell_allow_all = allow_all
    _exec_shell_whitelist = list(whitelist or [])


def _exec_shell_allowed(cmd: str) -> bool:
    """判断命令是否在白名单内（命令需以某条白名单前缀开头）。"""
    if _exec_shell_allow_all:
        return True
    cmd = cmd.strip()
    for prefix in _exec_shell_whitelist:
        # 支持前缀匹配（前缀去尾随空格后与 cmd 前段一致即可）
        p = prefix.rstrip()
        if cmd.startswith(p) or (p and cmd == p):
            return True
    return False


async def exec_shell(cmd: str) -> str:
    """在本地执行 shell 命令；受白名单限制，仅允许配置中的命令前缀。"""
    cmd = cmd.strip()
    if not cmd:
        return "未提供命令。"
    if not _exec_shell_allowed(cmd):
        return "拒绝执行：该命令不在白名单中。请使用其他已支持的工具（如 mac_open_app、mac_open_url、mac_volume 等）。"
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        out = (stdout or b"").decode("utf-8", errors="replace").strip()
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        if err:
            return f"stdout:\n{out}\nstderr:\n{err}"
        return out or "(无输出)"
    except Exception as e:
        return f"执行失败: {e}"


# ---------- Mac 本机能力（让贾维斯成为这台 Mac mini 的一部分）----------

async def _run_cmd(cmd: str, timeout: float = 10.0) -> str:
    """执行一条 shell 命令，返回标准输出或错误信息。"""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = (stdout or b"").decode("utf-8", errors="replace").strip()
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        return out if out else (err or "已执行")
    except asyncio.TimeoutError:
        return "执行超时"
    except Exception as e:
        return f"执行失败: {e}"


async def mac_volume(level: int) -> str:
    """设置系统音量，level 为 0～100 的整数。"""
    level = max(0, min(100, int(level)))
    return await _run_cmd(f'osascript -e "set volume output volume {level}"')


async def mac_open_app(app_name: str) -> str:
    """打开 Mac 上的应用，app_name 为应用名（如 Safari、备忘录、日历）。"""
    app = app_name.strip().replace('"', '\\"')
    return await _run_cmd(f'open -a "{app}"', timeout=5.0)


async def mac_lock_screen() -> str:
    """锁定当前 Mac 屏幕（等同于 控制+命令+Q）。"""
    return await _run_cmd('osascript -e \'tell application "System Events" to keystroke "q" using {control down, command down}\'', timeout=3.0)


async def mac_get_time() -> str:
    """获取本机当前日期和时间。"""
    return await _run_cmd('date "+%Y年%m月%d日 %H:%M"')


async def mac_open_url(url: str) -> str:
    """在默认浏览器中打开网址。"""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return await _run_cmd(f'open "{url}"', timeout=5.0)


async def mac_sleep_display() -> str:
    """关闭显示器（进入睡眠）。"""
    return await _run_cmd("pmset displaysleepnow", timeout=3.0)


async def mac_system_info() -> str:
    """获取本机简要信息：运行时间、磁盘空间。"""
    uptime = await _run_cmd("uptime")
    disk = await _run_cmd("df -h / | tail -1")
    return f"运行时间: {uptime}\n磁盘: {disk}"


def _parse_openclaw_response(data: dict) -> str | None:
    """
    解析 OpenClaw Gateway /v1/responses 返回的 JSON（OpenResponses 格式），
    提取助理回复文本，供贾维斯用语音播报。
    """
    output = data.get("output") or []
    for item in output:
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            texts = []
            for part in content:
                if part.get("type") == "output_text" and part.get("text"):
                    texts.append(part["text"])
            if texts:
                return "\n".join(texts).strip()
    return None


async def openclaw_send(message: str) -> str:
    """
    向本机 OpenClaw 发送指令。若配置了 HTTP（OPENCLAW_USE_HTTP + Gateway URL + Token），
    则通过 Gateway /v1/responses 发送并等待执行结果，返回结果文本供贾维斯语音播报；
    否则通过深度链接发送，仅能语音确认「已发送，请在 OpenClaw 界面查看结果」。
    """
    msg = message.strip()
    if not msg:
        return "请提供要发给 OpenClaw 的指令内容。"

    use_http = os.getenv("OPENCLAW_USE_HTTP", "").strip().lower() in ("1", "true", "yes")
    gateway_url = (os.getenv("OPENCLAW_GATEWAY_URL") or "").strip().rstrip("/")
    # Token 优先；Gateway 若为 password 模式，可用 OPENCLAW_GATEWAY_PASSWORD 作为 Bearer
    token = (os.getenv("OPENCLAW_GATEWAY_TOKEN") or os.getenv("OPENCLAW_GATEWAY_PASSWORD") or "").strip()

    if use_http and gateway_url and token:
        api_url = f"{gateway_url}/v1/responses"
        payload = {"model": "openclaw", "input": msg}
        timeout_sec = float(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "90"))
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-openclaw-agent-id": "main",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout_sec)
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        return f"OpenClaw 请求失败（{resp.status}），已改为仅发送指令。请在其界面查看。若需语音播报结果，请确认 Gateway 已开启 responses 端点并配置认证。"
                    data = await resp.json()
            text = _parse_openclaw_response(data)
            if text:
                return f"OpenClaw 执行结果：{text}"
            return "OpenClaw 已收到指令并执行，但未返回可播报的文本结果。请在其界面查看。"
        except asyncio.TimeoutError:
            return "OpenClaw 执行超时，请在其界面查看是否已完成。"
        except Exception as e:
            return f"无法通过 Gateway 获取结果（{e}），已改为仅发送指令。请在其界面查看。若需语音播报结果，请确认 Gateway 已开启 responses 并配置 OPENCLAW_GATEWAY_TOKEN。"

    # 未配置 HTTP 或未配 Token：使用深度链接，仅发送指令
    from urllib.parse import quote
    quoted = quote(msg)
    url = f"openclaw://agent?message={quoted}"
    await _run_cmd(f'open "{url}"', timeout=5.0)
    return "已发送给 OpenClaw，请在其界面查看执行结果。"


TOOLS = {
    "get_weather": get_weather,
    "exec_shell": exec_shell,
    "mac_volume": mac_volume,
    "mac_open_app": mac_open_app,
    "mac_lock_screen": mac_lock_screen,
    "mac_get_time": mac_get_time,
    "mac_open_url": mac_open_url,
    "mac_sleep_display": mac_sleep_display,
    "mac_system_info": mac_system_info,
    "openclaw_send": openclaw_send,
}


def _parse_tool_call(text: str) -> dict | None:
    """从模型输出中解析 JSON 工具调用（支持嵌套 args、markdown 代码块）。"""
    text = (text or "").strip()
    if not text:
        return None
    # 去掉 markdown 代码块包裹
    if "```" in text:
        for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE):
            text = block.strip()
            break
    candidates: list[str] = [text]
    # 扫描所有平衡花括号的 JSON 片段（修复 nested args 导致旧正则匹配失败的问题）
    i = 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        for j in range(i, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[i : j + 1])
                    i = j + 1
                    break
        else:
            break
    for cand in candidates:
        cand = cand.strip()
        if not cand.startswith("{"):
            continue
        try:
            obj = json.loads(cand)
            if isinstance(obj.get("tool"), str) and isinstance(obj.get("args"), dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _sanitize_speech_text(text: str) -> str:
    """去掉不应朗读给用户的工具 JSON / 代码块，避免把命令当语音播放。"""
    t = (text or "").strip()
    if not t:
        return t
    if _parse_tool_call(t):
        return ""
    if t.startswith("{") and t.endswith("}"):
        try:
            json.loads(t)
            return ""
        except json.JSONDecodeError:
            pass
    return t


async def _call_tool(tool_name: str, args: dict) -> str:
    """根据名称和参数执行工具，返回字符串结果。"""
    fn = TOOLS.get(tool_name)
    if not fn:
        return f"未知工具: {tool_name}"
    try:
        return await fn(**args)
    except TypeError as e:
        return f"参数错误: {e}"
    except Exception as e:
        return f"执行异常: {e}"


async def summarize_conversation(messages: list[dict], config: dict) -> str:
    """
    用 LLM 将一段对话压缩成 2～3 句话的摘要，用于后续上下文。
    config 需包含 llm.backend、ollama/kimi 的 base_url、model 等。
    """
    if not messages:
        return ""
    llm_cfg = config.get("llm") or {}
    backend = (llm_cfg.get("backend") or "ollama").strip().lower()
    prompt = "请用 2～3 句话总结以下对话的关键信息与用户意图，用于后续对话上下文。不要列举具体命令，只提炼要点。\n\n"
    for m in messages:
        role = (m.get("role") or "").strip()
        content = (m.get("content") or "").strip()
        if role == "user":
            prompt += f"用户：{content}\n"
        elif role == "assistant":
            prompt += f"助手：{content}\n"
    prompt = prompt.strip()

    if backend == "kimi":
        api_key = _get_kimi_api_key()
        kimi_cfg = config.get("kimi") or {}
        base_url = kimi_cfg.get("base_url", "https://api.moonshot.cn/v1")
        model = kimi_cfg.get("model", "moonshot-v1-8k")
        timeout = kimi_cfg.get("timeout_seconds", 60)
        if not api_key:
            return ""
        summary_messages = [{"role": "user", "content": prompt}]
        out = await _one_round_kimi(summary_messages, api_key, base_url, model, timeout)
        return (out or "").strip()
    else:
        ollama_cfg = config.get("ollama") or {}
        base_url = ollama_cfg.get("base_url", OLLAMA_BASE).rstrip("/")
        model = ollama_cfg.get("model", OLLAMA_MODEL)
        url = f"{base_url}/api/chat"
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return ""
                    data = await resp.json()
                    content = (data.get("message") or {}).get("content") or ""
                    return content.strip()
        except Exception:
            return ""


async def check_ollama(base_url: str = OLLAMA_BASE) -> bool:
    """检查 Ollama 服务是否可用（用于启动时重试逻辑）。"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url.rstrip('/')}/api/tags", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                return resp.status == 200
    except Exception:
        return False


def _get_kimi_api_key() -> str:
    """从环境变量读取 Kimi API Key，不要写在代码或配置里。"""
    return (os.getenv("KIMI_API_KEY") or "").strip()


async def check_kimi(api_key: str | None = None, base_url: str = "https://api.moonshot.cn/v1") -> bool:
    """检查 Kimi API 是否可用（有 Key 且能连上）。"""
    key = (api_key or _get_kimi_api_key())
    if not key:
        return False
    try:
        async with aiohttp.ClientSession() as session:
            # 发一个最小请求验证 key
            url = base_url.rstrip("/") + "/chat/completions"
            payload = {"model": "moonshot-v1-8k", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
    except Exception:
        return False


async def _one_round_kimi(
    messages: list[dict],
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = 60,
) -> str:
    """Kimi 单轮对话（OpenAI 兼容接口），返回助手回复内容。"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "max_tokens": 2048}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status != 200:
                text = await resp.text()
                return f"[Kimi API 错误 {resp.status}] {text[:200]}"
            data = await resp.json()
            choice = (data.get("choices") or [None])[0]
            if not choice:
                return ""
            return (choice.get("message") or {}).get("content") or ""


def _append_vision_context(system: str, vision_context: str | None) -> str:
    """将实时摄像头场景描述追加到系统提示词（若有）。"""
    ctx = (vision_context or "").strip()
    if not ctx:
        return system
    return system.strip() + "\n\n" + ctx


async def chat(
    user_message: str,
    history: list[dict],
    system_prompt: str | None = None,
    base_url: str = OLLAMA_BASE,
    model: str = OLLAMA_MODEL,
    stream: bool = True,
    vision_context: str | None = None,
):
    """
    与 Ollama 对话：先发一轮对话；若模型返回中包含工具调用则执行工具，
    再把工具结果作为新一条用户消息追问一轮（最多执行一次工具），最后流式返回最终回复。

    history: 列表，每项为 {"role": "user"|"assistant", "content": "..."}
    stream: 是否流式返回最终助手回复（逐 token 通过 async generator 产出）。
    """
    base_url = base_url.rstrip("/")
    system = system_prompt or _load_system_prompt(SYSTEM_PROMPT_PATH)
    system = _append_vision_context(system.strip() + "\n\n" + TOOL_DESCRIPTIONS.strip(), vision_context)

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    async with aiohttp.ClientSession() as session:
        payload = {"model": model, "messages": messages, "stream": False}
        url = f"{base_url}/api/chat"

        # 第一轮：获取完整回复，用于解析工具调用
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                text = await resp.text()
                yield f"[Ollama 错误 {resp.status}] {text[:200]}"
                return
            data = await resp.json()
            assistant_message = (data.get("message") or {}).get("content") or ""

        # 解析工具调用
        tool_call = _parse_tool_call(assistant_message)
        if tool_call:
            tool_name = tool_call.get("tool", "")
            tool_args = tool_call.get("args") or {}
            result = await _call_tool(tool_name, tool_args)
            # 用工具结果作为新用户消息再问一轮
            follow_up = f"[工具 {tool_name} 返回]\n{result}\n请根据以上结果用简短自然语言回复用户。"
            messages.append({"role": "assistant", "content": assistant_message})
            messages.append({"role": "user", "content": follow_up})
            payload["messages"] = messages
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    yield f"[Ollama 追问失败 {resp.status}]"
                    return
                data = await resp.json()
                assistant_message = (data.get("message") or {}).get("content") or ""

        # 流式输出最终回复（这里用「整句一次性」模拟流式，避免再请求一次 stream=True）
        if stream:
            for chunk in (assistant_message[i : i + 2] for i in range(0, len(assistant_message), 2)):
                yield chunk
        else:
            yield assistant_message


async def chat_simple(
    user_message: str,
    history: list[dict] | None = None,
    system_prompt: str | None = None,
    base_url: str = OLLAMA_BASE,
    model: str = OLLAMA_MODEL,
    vision_context: str | None = None,
) -> str:
    """非流式、一次性返回完整回复（Ollama 后端）。"""
    history = history or []
    full = []
    async for chunk in chat(
        user_message,
        history,
        system_prompt=system_prompt,
        base_url=base_url,
        model=model,
        stream=False,
        vision_context=vision_context,
    ):
        full.append(chunk)
    result = "".join(full)
    return _sanitize_speech_text(result) or result


async def chat_simple_kimi(
    user_message: str,
    history: list[dict] | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    base_url: str = "https://api.moonshot.cn/v1",
    model: str = "moonshot-v1-8k",
    timeout: int = 60,
) -> str:
    """
    使用 Kimi（月之暗面）API 做一轮对话，支持工具调用。
    API Key 未传时从环境变量 KIMI_API_KEY 读取。
    """
    key = (api_key or _get_kimi_api_key()).strip()
    if not key:
        return "[错误] 未设置 KIMI_API_KEY，请 export KIMI_API_KEY=sk-xxx"

    system = system_prompt or _load_system_prompt(SYSTEM_PROMPT_PATH)
    system = system.strip() + "\n\n" + TOOL_DESCRIPTIONS.strip()
    messages = [{"role": "system", "content": system}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_message})

    assistant_message = await _one_round_kimi(messages, key, base_url, model, timeout)
    tool_call = _parse_tool_call(assistant_message)
    if tool_call:
        tool_name = tool_call.get("tool", "")
        tool_args = tool_call.get("args") or {}
        result = await _call_tool(tool_name, tool_args)
        follow_up = f"[工具 {tool_name} 返回]\n{result}\n请根据以上结果用简短自然语言回复用户。"
        messages.append({"role": "assistant", "content": assistant_message})
        messages.append({"role": "user", "content": follow_up})
        assistant_message = await _one_round_kimi(messages, key, base_url, model, timeout)
    spoken = _sanitize_speech_text(assistant_message)
    if spoken:
        return spoken
    if _parse_tool_call(assistant_message):
        return "请求已收到，但生成语音回复时出错，请再说一次。"
    return assistant_message
