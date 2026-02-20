# -*- coding: utf-8 -*-
"""
jarvis_logging.py - JARVIS 统一日志配置
在 main 启动时调用 init_logging(config)，之后各模块使用 logging.getLogger(__name__) 输出日志。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path


def init_logging(config: dict) -> None:
    """
    根据 config 初始化日志：控制台 INFO；若 config.log 指定 file 则同时写入文件。
    config 示例：
      log:
        level: "INFO"    # 可选：DEBUG / INFO / WARNING / ERROR
        file: "logs/jarvis.log"  # 可选：不设则仅控制台
    """
    log_cfg = config.get("log") or {}
    level_name = (log_cfg.get("level") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = (log_cfg.get("file") or "").strip()

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger("jarvis")
    root.setLevel(level)
    # 避免重复添加 handler（多次调用 init_logging 时）
    if not root.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(level)
        console.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
        root.addHandler(console)

        if log_file:
            log_path = Path(log_file)
            if not log_path.is_absolute():
                log_path = Path(__file__).resolve().parent / log_path
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setLevel(level)
            fh.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
            root.addHandler(fh)

    # 让各子模块使用 jarvis.xxx 的 logger，便于过滤
    logging.getLogger("jarvis.main").setLevel(level)
    logging.getLogger("jarvis.brain").setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """获取带 jarvis 前缀的 logger，供 main/brain 等使用。"""
    if name.startswith("jarvis."):
        return logging.getLogger(name)
    return logging.getLogger("jarvis." + name)
