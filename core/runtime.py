"""运行状态与日志。运行结果持久化到 data/runtime.json，日志同时写文件与内存环形缓冲。"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main import DouyinSparkPlugin

_lock = threading.Lock()
_ring: deque[str] = deque(maxlen=600)

RUNTIME_PATH: Path | None = None
LOG_DIR: Path | None = None


def _default() -> dict:
    return {
        "session_status": "unknown",
        "running": False,
        "last_run": None,
        "history": [],
        "contacts": [],
        "contacts_at": None,
        "contacts_error": None,
        "retry_date": None,
    }


def load_runtime() -> dict:
    rt = _default()
    if RUNTIME_PATH and RUNTIME_PATH.exists():
        try:
            data = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rt.update(data)
        except Exception:
            pass
    return rt


def _save(rt: dict) -> None:
    if not RUNTIME_PATH:
        return
    with _lock:
        RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_PATH.write_text(json.dumps(rt, ensure_ascii=False, indent=2), encoding="utf-8")


def set_running(value: bool) -> None:
    rt = load_runtime()
    rt["running"] = bool(value)
    _save(rt)


def record_run(result: dict) -> None:
    rt = load_runtime()
    rt["last_run"] = result
    history = rt.get("history", [])
    history.insert(0, result)
    rt["history"] = history[:30]

    if result.get("logged_out"):
        rt["session_status"] = "expired"
    elif result.get("ok") and not result.get("failed"):
        rt["session_status"] = "ok"
    elif result.get("ok"):
        rt["session_status"] = "partial"
    elif not result.get("failed"):
        rt["session_status"] = "ok"
    else:
        rt["session_status"] = "failed"
    _save(rt)


def record_contacts(data: dict) -> None:
    rt = load_runtime()
    rt["contacts"] = data.get("names", [])
    rt["contacts_at"] = data.get("at")
    rt["contacts_error"] = data.get("error")
    _save(rt)


def update_runtime(**fields) -> None:
    rt = load_runtime()
    rt.update(fields)
    _save(rt)


class RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _ring.append(self.format(record))
        except Exception:
            pass


def setup_logging(log_dir: Path) -> logging.Logger:
    logger = logging.getLogger("astrbot.plugins.douyin_spark")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    global LOG_DIR
    LOG_DIR = log_dir
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    rh = RingHandler()
    rh.setFormatter(fmt)
    logger.addHandler(rh)
    return logger


def recent_logs(n: int = 300) -> list[str]:
    return list(_ring)[-n:]


def set_paths(runtime_path: Path, log_dir: Path):
    global RUNTIME_PATH, LOG_DIR
    RUNTIME_PATH = runtime_path
    LOG_DIR = log_dir
