# JARVIS-M4

> **小白用语音可以控制龙虾啦。**

在 Mac（Apple Silicon M4）上运行的本地语音助手：说句话就能让**龙虾（OpenClaw）**截屏、开灯、执行指令——**耳朵（ASR）→ 大脑（LLM）→ 嘴巴（TTS）**，支持中英文、工具调用、对话记忆，零门槛用语音控制 OpenClaw。

---

## 作者与版权

- **开发者**：祖蛙  
- **联系方式**：微信 v：qhdhao | 邮箱：qhdhao@126.com  
- **知识产权**：归本人（qhdhao）所有。  
- **说明**：本项目全部由 AI 辅助完成。

### 使用与许可

- **个人使用**：免费使用、复刻与扩展，欢迎 Fork 与二次开发。  
- **商业用途**：须事先与我联系并征得同意后方可使用。  
- **祖蛙名字与形象**：任何公开使用（含商业与衍生项目）均须征得本人同意。  

详见仓库内 [LICENSE](LICENSE) 文件。

---

## 功能概览

| 功能 | 说明 |
|------|------|
| **🎤 语音控制龙虾（OpenClaw）** | **核心卖点**：说「让龙虾截屏」「打开灯」「查一下」等，贾维斯立刻转发给本机 OpenClaw，小白也能零门槛用语音操控。可选 HTTP 结果语音回传。 |
| **语音输入** | 按 Enter 或唤醒词开始录音，说完自动识别（Faster-Whisper），灵敏度可调、接近 Mac 自带语音输入 |
| **大脑** | 本地 Ollama 或云端 Kimi，支持工具调用（天气、开应用、锁屏、查时间、打开网址、关屏、系统信息等） |
| **语音输出** | Edge-TTS 合成 + 本地缓存，中文女声 |
| **对话记忆** | 多轮对话保留历史，并自动摘要压缩，贾维斯能结合上文理解「刚才」「之前说的」 |
| **安全** | `exec_shell` 白名单限制，统一 logging，配置驱动 |

### 能说多久？能记住吗？理解了吗？

- **单次说话时长**：默认最长约 **15 秒**（`config.yaml` 中 `ears.timeout_seconds` 可改为 20～30）。说完后静音约 0.5 秒自动结束并识别。  
- **能记住**：同一轮会话保留对话历史，多轮后自动摘要压缩，最多约 10 条消息 + 摘要；关闭程序后会话清空（当前未持久化）。  
- **能理解**：每次回复都会带上「系统提示词 + 对话历史（含摘要）」，能结合你之前说的话理解指代，回复连贯。

---

## 环境要求

- macOS（建议 Apple Silicon，如 M4）
- Python 3.11+
- [Ollama](https://ollama.com) 已安装并拉取模型（如 `ollama pull qwen2.5:3b`）  
- 语音控制 OpenClaw 需本机已安装并运行 **OpenClaw.app**

---

## 快速开始

```bash
# 1. 克隆
git clone git@github.com:qhdhao13/jarvis-m4.git
cd jarvis-m4

# 2. 使用项目虚拟环境（推荐，避免系统 Python 限制）
./run.sh
# 首次会创建 .venv 并在依赖缺失时提示安装

# 或手动：创建虚拟环境并安装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. 启动 Ollama（若未在运行）
# 打开 Ollama 应用或终端执行 ollama serve

# 4. 运行
./run.sh
# 或：.venv/bin/python main.py
```

按 Enter 开始录音，说完自动识别 → LLM 思考 → 语音播放；若配置唤醒词则说出唤醒词即可开始。

---

## 配置说明

主要编辑 **`config.yaml`**：

- **大脑**：`llm.backend` 选 `ollama`（本地）或 `kimi`（云端）。用 Kimi 时设置环境变量 `KIMI_API_KEY`，勿写入配置文件。  
- **听觉**：`ears` 中可调 `timeout_seconds`（单次最长录音秒数）、`rms_threshold`（灵敏度）、`silence_duration_ms`（静音多久结束一句）。  
- **Whisper**：`whisper.model_size`（tiny/base/small）、`language: zh` 等。  
- **TTS**：`tts.voice`、`tts.cache_dir`。  
- **OpenClaw**：`openclaw.use_http`、`openclaw.gateway_url`；认证建议用环境变量 `OPENCLAW_GATEWAY_TOKEN` 或 `OPENCLAW_GATEWAY_PASSWORD`。  
- **对话记忆**：`memory.summary_every_rounds`、`memory.max_rounds_before_summary`。  
- **安全**：`exec_shell.allow_all`、`exec_shell.whitelist` 控制 shell 白名单。

更多细节见 **`进阶说明.md`**（唤醒词、记忆/RAG、控制电脑、状态图标、OpenClaw、双击启动等）。

---

## 项目结构

| 路径 | 说明 |
|------|------|
| `main.py` | 主循环与状态机：IDLE → LISTENING → PROCESSING → SPEAKING |
| `brain.py` | LLM 调用、工具调用（含 openclaw_send）、对话摘要 |
| `ears.py` | 麦克风 + VAD + Faster-Whisper 识别 |
| `mouth.py` | Edge-TTS 合成 + 缓存 + pygame 播放 |
| `jarvis_logging.py` | 统一日志配置 |
| `config.yaml` | 所有可调参数 |
| `prompts/system.txt` | 贾维斯人设与能力说明（可编辑） |
| `run.sh` | 检查虚拟环境与 Ollama 后启动主程序 |
| `启动贾维斯.command` | 双击启动主程序 + 状态图标（关图标即退出） |
| `进阶说明.md` | 唤醒词、记忆、OpenClaw、脚本与 config 等说明 |
| `scripts/` | 唤醒词模型下载、OpenClaw Gateway 开启、测试等脚本 |

---

## 语音控制 OpenClaw（小白用语音控制龙虾）

- **一句话**：本机开着 OpenClaw，对着贾维斯说「让龙虾截屏」「打开灯」——小白也能用语音控制龙虾，无需记命令。  
- 本机需已运行 **OpenClaw.app**（菜单栏），Gateway 已连接。  
- 说 **「让龙虾截屏」**、**「让 OpenClaw 打开灯」**、**「叫龙虾查一下天气」** 等，贾维斯会调用 `openclaw_send` 将指令发给 OpenClaw。  
- 「龙虾」为 OpenClaw 别称，已在系统提示中约定。  
- 若在 OpenClaw Gateway 中开启 responses 并配置认证，并在本项目中设置 `openclaw.use_http: true` 及环境变量 Token/Password，贾维斯会用语音播报 OpenClaw 的执行结果。

---

## 许可证与免责

- 本项目为开源项目，个人可免费使用、复刻与扩展。  
- 商业使用及对「祖蛙」名字与形象的使用，须事先联系本人并征得同意。  
- 知识产权归本人所有。  
- 详见 [LICENSE](LICENSE)。

---

## 致谢

本项目全部由 AI 完成；感谢所有开源依赖（Ollama、Faster-Whisper、Edge-TTS、LangChain 等）。
