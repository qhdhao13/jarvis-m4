#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 OpenClaw HTTP 结果回传：模拟贾维斯调用 openclaw_send，看是否能拿到执行结果。
运行前请设置环境变量（或先 export）：
  OPENCLAW_USE_HTTP=1
  OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
  OPENCLAW_GATEWAY_TOKEN=你的token
并确保本机 OpenClaw.app 已运行、Gateway 已开启 responses 端点。
"""
import asyncio
import os
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import brain


async def main():
    test_message = "你好，请用一句话介绍你自己。"
    print("测试指令:", test_message)
    print("环境: OPENCLAW_USE_HTTP=%s, GATEWAY_URL=%s, TOKEN=%s"
          % (os.getenv("OPENCLAW_USE_HTTP"), os.getenv("OPENCLAW_GATEWAY_URL"),
             "已设置" if os.getenv("OPENCLAW_GATEWAY_TOKEN") or os.getenv("OPENCLAW_GATEWAY_PASSWORD") else "未设置"))
    print("-" * 50)
    result = await brain.openclaw_send(test_message)
    print("openclaw_send 返回:")
    print(result)
    print("-" * 50)
    if "OpenClaw 执行结果：" in result:
        print("[通过] 已从 Gateway 拿到执行结果，贾维斯可据此做语音播报。")
    elif "已发送给 OpenClaw" in result:
        print("[未走 HTTP] 当前为深度链接模式；若需结果回传，请设置 OPENCLAW_USE_HTTP=1 与 OPENCLAW_GATEWAY_TOKEN。")
    else:
        print("[需排查] 可能是 Gateway 未开 responses、认证失败或网络问题，请根据上文提示检查。")


if __name__ == "__main__":
    asyncio.run(main())
