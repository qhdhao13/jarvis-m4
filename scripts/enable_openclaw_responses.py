#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 OpenClaw Gateway 配置中开启 responses 端点，并重启 Gateway 服务。
配置路径：~/.openclaw/openclaw.json
"""
import json
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"
# 本机 Gateway 的 launchd 服务名（launchctl list 中可见）
GATEWAY_SERVICE = "ai.openclaw.gateway"


def main():
    if not CONFIG_PATH.exists():
        print(f"未找到配置文件: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    # 读取并解析配置
    raw = CONFIG_PATH.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"配置不是合法 JSON: {e}", file=sys.stderr)
        sys.exit(1)

    gateway = data.setdefault("gateway", {})
    gateway.setdefault("http", {})
    gateway["http"].setdefault("endpoints", {})
    gateway["http"]["endpoints"].setdefault("responses", {})
    gateway["http"]["endpoints"]["responses"]["enabled"] = True

    # 写回（保留缩进便于后续手工编辑）
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已启用 responses 端点并保存: {CONFIG_PATH}")

    # 重启 Gateway（launchd 按用户维度，用 gui/$UID）
    uid = subprocess.run(["id", "-u"], capture_output=True, text=True, check=True).stdout.strip()
    label = f"gui/{uid}/{GATEWAY_SERVICE}"
    r = subprocess.run(
        ["launchctl", "kickstart", "-k", label],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        print(f"已重启 Gateway 服务: {label}")
    else:
        print(f"重启 Gateway 失败 (exit {r.returncode}): {r.stderr or r.stdout}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
