# -*- coding: utf-8 -*-
"""
jarvis_icon.py - 状态动画图标
随贾维斯状态（IDLE / LISTENING / PROCESSING / SPEAKING）显示不同动画，需与 main.py 同时运行。
从程序坞启动时若 tkinter 崩溃，主程序会改为仅后台运行并弹窗提示。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 项目根目录：优先用环境变量（app 启动时传入），否则用本文件所在目录
ROOT = Path(os.environ.get("JARVIS_PROJECT_ROOT", Path(__file__).resolve().parent))
STATE_FILE = ROOT / ".jarvis_state"
SIZE = 140
BG = "#1a1a2e"
COLORS = {
    "IDLE": "#4a4a6a",
    "LISTENING": "#3d8bfd",
    "PROCESSING": "#ffc107",
    "SPEAKING": "#00c853",
}


def read_state() -> str:
    try:
        if STATE_FILE.exists():
            return STATE_FILE.read_text(encoding="utf-8").strip().upper() or "IDLE"
    except Exception:
        pass
    return "IDLE"


def main():
    # 从程序坞/无终端环境启动时，避免 stdout/stderr 写导致异常
    try:
        devnull = open(os.devnull, "w")
        sys.stdout = devnull
        sys.stderr = devnull
    except Exception:
        pass
    try:
        import tkinter as tk
    except ImportError:
        sys.exit(1)
    import math
    state = read_state()
    pulse = 0.0

    def on_tick():
        nonlocal pulse
        try:
            s = read_state()
            pulse = (pulse + 0.08) % (2 * math.pi)
            scale = 0.85 + 0.15 * (1 + math.sin(pulse))
            if s == "LISTENING":
                scale *= 0.9 + 0.2 * (1 + math.sin(pulse * 2))
            elif s == "SPEAKING":
                scale *= 0.92 + 0.18 * (1 + math.sin(pulse * 1.5))
            r = int(SIZE * 0.35 * scale)
            color = COLORS.get(s, COLORS["IDLE"])
            canvas.delete("all")
            canvas.create_oval(SIZE // 2 - r, SIZE // 2 - r, SIZE // 2 + r, SIZE // 2 + r, fill=color, outline=color)
        except Exception:
            pass
        try:
            root.after(80, on_tick)
        except Exception:
            pass

    try:
        root = tk.Tk()
        root.title("JARVIS")
        root.geometry(f"{SIZE}x{SIZE}+50+50")
        root.configure(bg=BG)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", 0.95)
        except Exception:
            pass
        canvas = tk.Canvas(root, width=SIZE, height=SIZE, bg=BG, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        on_tick()
        root.mainloop()
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
