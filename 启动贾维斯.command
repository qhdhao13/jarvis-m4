#!/bin/bash
# 双击此文件即可启动贾维斯 + 状态动画图标（关掉图标窗口会同时结束贾维斯）
cd "$(dirname "$0")"
echo "正在启动贾维斯…"
python3 main.py &
MAIN_PID=$!
sleep 1
python3 jarvis_icon.py
kill $MAIN_PID 2>/dev/null
echo "贾维斯已退出。"
