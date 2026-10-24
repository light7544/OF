"""Centralized structured logging system for DexT3 Engine."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

DATA_DIR = Path(os.getenv("DATA_DIR", "C:\\bot_data"))
LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def setup_loggers():
    """Configure file and console handlers for bot runtime, browser debug, capture, and signals."""
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers
    if not root_logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)

    # Helper to add file handler if not already present
    def _add_file_handler(logger_name: str, filename: str):
        lg = logging.getLogger(logger_name)
        log_path = LOGS_DIR / filename
        # Check if handler already attached
        for h in lg.handlers:
            if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_path.resolve():
                return lg
        fh = logging.FileHandler(str(log_path), encoding="utf-8")
        fh.setFormatter(formatter)
        fh.setLevel(logging.DEBUG)
        lg.addHandler(fh)
        return lg

    _add_file_handler("bot", "bot_runtime.log")
    _add_file_handler("browser", "browser_debug.log")
    _add_file_handler("browser_session", "browser_debug.log")
    _add_file_handler("browser_capture", "capture_debug.log")
    _add_file_handler("capture", "capture_debug.log")
    _add_file_handler("signal_engine", "signal_debug.log")
    _add_file_handler("signals", "signal_debug.log")
    _add_file_handler("pipeline", "bot_runtime.log")


class StageLogger:
    """Helper to emit standard sequence tags across console and file logs."""

    @staticmethod
    def log(stage: str, message: str, logger_name: str = "pipeline"):
        lg = logging.getLogger(logger_name)
        msg = f"[{stage.upper()}] {message}"
        lg.info(msg)
