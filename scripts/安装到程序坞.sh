#!/bin/bash
# 将贾维斯.app 安装到「应用程序」目录，便于从启动台打开或拖到程序坞
DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${HOME}/Applications"
mkdir -p "$APP_DIR"
cp -R "$DIR/JARVIS.app" "$APP_DIR/"
echo "已安装到: $APP_DIR/JARVIS.app"
echo "添加到程序坞：打开「启动台」找到「JARVIS」，拖到程序坞即可固定。"
