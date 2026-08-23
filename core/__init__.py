"""核心模块导出"""

from .automation import (
    fetch_chat_contacts,
    run_send,
    send_to_contact,
    check_login,
    detect_rate_limit,
    set_paths,
)
from .scheduler import (
    configure,
    apply_schedule,
    next_run_time,
    schedule_retry,
    cancel_retry,
    shutdown,
)
from .runtime import (
    load_runtime,
    set_running,
    record_run,
    record_contacts,
    update_runtime,
    setup_logging,
    recent_logs,
    set_paths as set_runtime_paths,
)
from .extract_cookie import main as extract_cookie_main, get_output_path

__all__ = [
    "fetch_chat_contacts",
    "run_send",
    "send_to_contact",
    "check_login",
    "detect_rate_limit",
    "set_paths",
    "configure",
    "apply_schedule",
    "next_run_time",
    "schedule_retry",
    "cancel_retry",
    "shutdown",
    "load_runtime",
    "set_running",
    "record_run",
    "record_contacts",
    "update_runtime",
    "setup_logging",
    "recent_logs",
    "set_runtime_paths",
    "extract_cookie_main",
    "get_output_path",
]
