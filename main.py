"""抖音续火花助手 - AstrBot 插件主入口"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from astrbot.api import AstrBotConfig
from astrbot.core.star import Star, StarTools
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.permission import PermissionType, PermissionTypeFilter
from astrbot.core.star.register.star_handler import register_custom_filter
from astrbot.api.web import json_response, error_response, request

from .core import (
    fetch_chat_contacts,
    run_send,
    configure,
    apply_schedule,
    next_run_time,
    schedule_retry,
    cancel_retry,
    shutdown,
    load_runtime,
    set_running,
    record_run,
    record_contacts,
    update_runtime,
    setup_logging,
    recent_logs,
    set_runtime_paths,
    extract_cookie_main,
)

if TYPE_CHECKING:
    from astrbot.core.star.context import Context
    from astrbot.core.platform.astr_message_event import AstrMessageEvent

PLUGIN_NAME = "douyin_spark"


class DouyinSparkPlugin(Star):
    """抖音续火花助手插件

    功能：
    - 每日定时自动给指定好友发送私信，维持聊天火花
    - 支持干跑测试、自动补发、限流熔断
    - 提供 Web 管理界面配置好友、消息模板、发送时间
    - 登录态本地获取、服务器复用，避免异地登录风控
    """

    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context, config)

        # 插件数据目录
        self.data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 状态文件路径
        self.state_path = self.data_dir / "state.json"
        self.runtime_path = self.data_dir / "runtime.json"
        self.log_dir = self.data_dir / "logs"
        self.screenshot_path = self.data_dir / "last_error.png"

        # 设置核心模块路径
        set_runtime_paths(self.runtime_path, self.log_dir)
        from .core.automation import set_paths as set_auto_paths
        set_auto_paths(self.state_path, self.screenshot_path)

        # 初始化日志
        self.logger = setup_logging(self.log_dir)

        # 配置
        self._config: dict = {}
        self._load_config()

        # 运行锁
        self._run_lock = threading.Lock()
        self._contacts_fetching = False

        # 注册 Web API (供前端页面调用)
        self._register_web_apis()

        # 初始化调度器
        configure(self._run_send_wrapper)
        apply_schedule(self)

        self.logger.info("抖音续火花助手插件已加载")

    def _register_web_apis(self) -> None:
        """注册 Web API 端点"""
        base = f"/{PLUGIN_NAME}"
        self.context.register_web_api(f"{base}/web/status", self.web_status, ["GET"], "Get plugin status")
        self.context.register_web_api(f"{base}/web/config", self.web_config, ["GET"], "Get plugin config")
        self.context.register_web_api(f"{base}/web/save-config", self.web_save_config, ["POST"], "Save plugin config")
        self.context.register_web_api(f"{base}/web/contacts", self.web_contacts, ["GET"], "Get contacts")
        self.context.register_web_api(f"{base}/web/fetch-contacts", self.web_fetch_contacts, ["POST"], "Fetch contacts")
        self.context.register_web_api(f"{base}/web/run", self.web_run, ["POST"], "Run send task")
        self.context.register_web_api(f"{base}/web/upload-state", self.web_upload_state, ["POST"], "Upload state")
        self.context.register_web_api(f"{base}/web/logs", self.web_logs, ["GET"], "Get logs")
        self.context.register_web_api(f"{base}/web/extract-cookie", self.web_extract_cookie, ["POST"], "Extract cookie")
        self.context.register_web_api(f"{base}/web/qr-login", self.web_qr_login, ["POST"], "QR code login")
        self.context.register_web_api(f"{base}/web/qr-login-status", self.web_qr_login_status, ["GET"], "QR code login status")

    def _load_config(self) -> None:
        """加载插件配置"""
        if self.config:
            # 从 AstrBotConfig 获取配置
            self._config = dict(self.config)
        else:
            self._config = {}

        # 设置默认值
        defaults = {
            "schedule_time": "21:00",
            "jitter_minutes": 30,
            "send_gap_min": 6,
            "send_gap_max": 12,
            "max_friends_per_run": 20,
            "friends": [],
            "messages": ["🔥 续火花", "晚安，明天见", "今天也要开心哦"],
            "auto_retry": True,
            "headless": True,
            "browser_args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        }
        for key, value in defaults.items():
            if key not in self._config:
                self._config[key] = value

    @property
    def config(self) -> dict:
        return self._config

    def get_state_path(self) -> Path:
        return self.state_path

    def get_runtime_path(self) -> Path:
        return self.runtime_path

    def _run_send_wrapper(self, dry_run: bool = False, only_names: list[str] | None = None) -> None:
        """包装 run_send 以支持线程锁和回调"""
        if not self._run_lock.acquire(blocking=False):
            self.logger.warning("已有任务在运行，跳过本次发送")
            return

        def worker() -> None:
            try:
                set_running(True)
                try:
                    result = run_send(self, dry_run=dry_run, only_names=only_names)
                    record_run(result)
                    self.logger.info(
                        "本次发送完成：成功 %s 人，失败 %s 人，dry=%s",
                        len(result.get("ok", [])),
                        len(result.get("failed", [])),
                        dry_run,
                    )

                    # 处理自动补发
                    if not dry_run and result.get("failed") and not result.get("logged_out"):
                        failed_names = [
                            f["name"]
                            for f in result.get("failed", [])
                            if isinstance(f, dict)
                            and isinstance(f.get("name"), str)
                            and f["name"] != "_system"
                        ]
                        if failed_names and self.config.get("auto_retry", True):
                            rt = load_runtime()
                            today = datetime.now().date().isoformat()
                            if rt.get("retry_date") != today:
                                update_runtime(retry_date=today)
                                schedule_retry(self, failed_names=failed_names)
                        elif not failed_names:
                            cancel_retry()
                    elif not dry_run:
                        cancel_retry()
                finally:
                    set_running(False)
            finally:
                self._run_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    async def initialize(self) -> None:
        """插件激活时调用"""
        self.logger.info("插件初始化完成")
        apply_schedule(self)

    async def terminate(self) -> None:
        """插件禁用/重载时调用"""
        self.logger.info("插件正在关闭...")
        shutdown()

    # ==================== Web API 处理器 ====================

    async def web_status(self):
        rt = load_runtime()
        return json_response({
            "state_file_exists": self.state_path.exists(),
            "session_status": rt.get("session_status", "unknown"),
            "running": rt.get("running", False),
            "last_run": rt.get("last_run"),
            "next_run": next_run_time(),
            "history_count": len(rt.get("history", [])),
            "auth_required": True,
        })

    async def web_config(self):
        return json_response(self.config)

    async def web_save_config(self):
        try:
            payload = await request.json(default={})
            merged = dict(self.config)
            merged.update(payload)

            # 清理列表
            merged["friends"] = [str(x).strip() for x in merged.get("friends", []) if str(x).strip()]
            merged["messages"] = [str(x) for x in merged.get("messages", []) if str(x).strip()]
            if not merged["messages"]:
                merged["messages"] = ["🔥"]

            # 验证时间格式
            schedule = str(merged.get("schedule_time", "21:00"))
            try:
                hh, mm = schedule.split(":")
                if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                    raise ValueError
                merged["schedule_time"] = f"{int(hh):02d}:{int(mm):02d}"
            except Exception:
                return error_response("schedule_time 必须是 HH:MM 格式")

            # 验证数值
            for key in ("jitter_minutes", "send_gap_min", "send_gap_max", "max_friends_per_run"):
                try:
                    merged[key] = max(0, int(merged.get(key, self.config[key])))
                except (TypeError, ValueError):
                    return error_response(f"{key} 必须是整数")

            if merged["send_gap_max"] < merged["send_gap_min"]:
                merged["send_gap_max"] = merged["send_gap_min"]

            self._config = merged
            # 持久化到 AstrBot 配置系统
            if hasattr(self.context, "config_manager"):
                await self.context.config_manager.update_plugin_config(PLUGIN_NAME, merged)

            apply_schedule(self)
            return json_response({"ok": True, "config": merged})
        except Exception as e:
            return error_response(str(e))

    async def web_contacts(self):
        rt = load_runtime()
        return json_response({
            "contacts": rt.get("contacts", []),
            "contacts_at": rt.get("contacts_at"),
            "contacts_error": rt.get("contacts_error"),
            "fetching": self._contacts_fetching,
        })

    async def web_fetch_contacts(self):
        if self._run_lock.locked():
            return error_response("已有任务在运行")
        self._contacts_fetching = True

        def worker() -> None:
            try:
                result = fetch_chat_contacts(self)
                record_contacts(result)
            finally:
                self._contacts_fetching = False

        threading.Thread(target=worker, daemon=True).start()
        return json_response({"ok": True, "started": True})

    async def web_run(self):
        try:
            payload = await request.json(default={})
            dry = bool(payload.get("dry", False))
        except Exception:
            dry = False

        if self._run_lock.locked():
            return error_response("已有任务在运行")
        self._run_send_wrapper(dry_run=dry)
        return json_response({"ok": True, "started": True})

    async def web_upload_state(self):
        try:
            files = await request.files()
            upload = files.get("file")
            if not upload:
                return error_response("缺少文件")

            content = await upload.read()
            if len(content) > 5 * 1024 * 1024:
                return error_response("文件过大")

            data = json.loads(content.decode("utf-8"))
            if not isinstance(data.get("cookies"), list) or not data["cookies"]:
                return error_response("缺少 cookies 字段，请确认是 Playwright 导出的登录态文件")

            self.state_path.write_bytes(content)
            self.logger.info("已更新登录态 state.json（%s 字节）", len(content))
            return json_response({"ok": True, "size": len(content)})
        except json.JSONDecodeError:
            return error_response("不是合法的 JSON 文件")
        except Exception as e:
            return error_response(str(e))

    async def web_logs(self):
        try:
            n = int(request.query.get("n", 300))
        except Exception:
            n = 300
        return json_response({"logs": "\n".join(recent_logs(max(10, min(n, 600))))})

    async def web_extract_cookie(self):
        try:
            extract_cookie_main(self.data_dir)
            return json_response({"ok": True, "message": "登录态已保存，请上传到插件"})
        except Exception as e:
            return error_response(str(e))

    async def web_qr_login(self):
        """启动二维码登录流程（服务端执行，需图形界面或 Xvfb）"""
        if self._run_lock.locked():
            return error_response("已有任务在运行")
        
        def worker() -> None:
            try:
                from .core.extract_cookie import main as extract_main
                extract_main(self.data_dir)
                self.logger.info("二维码登录流程完成，state.json 已生成")
            except Exception as e:
                self.logger.error("二维码登录失败: %s", e)
        
        threading.Thread(target=worker, daemon=True).start()
        return json_response({"ok": True, "message": "二维码登录已启动，请查看服务器桌面或 VNC 窗口扫码"})

    async def web_qr_login_status(self):
        """获取二维码登录状态"""
        return json_response({
            "state_exists": self.state_path.exists(),
            "state_size": self.state_path.stat().st_size if self.state_path.exists() else 0,
        })

    # ==================== 命令处理 ====================

    @register_custom_filter(PermissionTypeFilter, PermissionType.ADMIN)
    @CommandFilter("续火花扫码登录", alias={"spark_qr_login", "扫码登录"})
    async def cmd_qr_login(self, event: AstrMessageEvent) -> None:
        """启动二维码登录（需服务器有图形界面或 Xvfb）"""
        if self._run_lock.locked():
            await event.reply("⚠️ 已有任务在运行中，请稍后再试")
            return

        await event.reply(
            "🔐 启动扫码登录流程...\n"
            "⚠️ 注意：此功能需要服务器有图形界面（桌面环境）或配置 Xvfb 虚拟显示器。\n"
            "如果服务器是无头模式，请改用本地电脑运行提取脚本后上传 state.json。\n"
            "\n"
            "登录成功后会自动保存 state.json 到插件数据目录。"
        )

        def worker() -> None:
            try:
                from .core.extract_cookie import main as extract_main
                extract_main(self.data_dir)
                self.logger.info("二维码登录流程完成，state.json 已生成")
            except Exception as e:
                self.logger.error("二维码登录失败: %s", e)

        threading.Thread(target=worker, daemon=True).start()

    @register_custom_filter(PermissionTypeFilter, PermissionType.ADMIN)
    @CommandFilter("续火花状态", alias={"spark_status", "火花状态"})
    async def cmd_status(self, event: AstrMessageEvent) -> None:
        """查看续火花运行状态"""
        rt = load_runtime()
        state_exists = self.state_path.exists()
        next_run = next_run_time()

        msg = [
            "🔥 抖音续火花助手 - 运行状态",
            f"📁 登录态文件: {'✅ 已上传' if state_exists else '❌ 未上传'}",
            f"🟢 会话状态: {rt.get('session_status', 'unknown')}",
            f"⚙️ 运行中: {'是' if rt.get('running') else '否'}",
            f"⏰ 下次自动发送: {next_run or '未设置'}",
            f"📊 历史执行次数: {len(rt.get('history', []))}",
        ]

        last_run = rt.get("last_run")
        if last_run:
            at = last_run.get("at", "未知")
            ok_count = len(last_run.get("ok", []))
            failed_count = len(last_run.get("failed", []))
            dry = " (干跑)" if last_run.get("dry_run") else ""
            msg.append(f"\n📝 上次执行 ({at}{dry}):")
            msg.append(f"  ✅ 成功: {ok_count} 人")
            if failed_count > 0:
                failed_names = [f["name"] for f in last_run.get("failed", []) if isinstance(f, dict)]
                msg.append(f"  ❌ 失败: {failed_count} 人 - {', '.join(failed_names[:5])}")
                if len(failed_names) > 5:
                    msg.append(f"    ... 等 {len(failed_names)} 人")
            if last_run.get("logged_out"):
                msg.append("  ⚠️ 登录态已过期，请重新上传")
            if last_run.get("rate_limited"):
                msg.append("  ⚠️ 疑似触发限流")

        await event.reply("\n".join(msg))

    @register_custom_filter(PermissionTypeFilter, PermissionType.ADMIN)
    @CommandFilter("续火花发送", alias={"spark_send", "发送火花"})
    async def cmd_send(self, event: AstrMessageEvent) -> None:
        """立即发送续火花消息"""
        if self._run_lock.locked():
            await event.reply("⚠️ 已有任务在运行中，请稍后再试")
            return

        await event.reply("🚀 启动发送任务...")
        self._run_send_wrapper(dry_run=False)

    @register_custom_filter(PermissionTypeFilter, PermissionType.ADMIN)
    @CommandFilter("续火花测试", alias={"spark_dry", "干跑测试"})
    async def cmd_dry_run(self, event: AstrMessageEvent) -> None:
        """干跑测试（不真实发送）"""
        if self._run_lock.locked():
            await event.reply("⚠️ 已有任务在运行中，请稍后再试")
            return

        await event.reply("🧪 启动干跑测试...")
        self._run_send_wrapper(dry_run=True)

    @register_custom_filter(PermissionTypeFilter, PermissionType.ADMIN)
    @CommandFilter("续火花获取好友", alias={"spark_fetch", "获取好友列表"})
    async def cmd_fetch_contacts(self, event: AstrMessageEvent) -> None:
        """从抖音获取聊天列表好友"""
        if not self.state_path.exists():
            await event.reply("❌ 尚未上传登录态 state.json，请先上传")
            return

        if self._run_lock.locked():
            await event.reply("⚠️ 已有任务在运行中，请稍后再试")
            return

        self._contacts_fetching = True
        await event.reply("📥 正在读取聊天列表，可能需要半分钟左右...")

        def worker() -> None:
            try:
                result = fetch_chat_contacts(self)
                record_contacts(result)
                if result.get("error"):
                    self.logger.error("获取好友列表失败: %s", result["error"])
                else:
                    names = result.get("names", [])
                    self.logger.info("获取到 %s 个联系人", len(names))
            finally:
                self._contacts_fetching = False

        threading.Thread(target=worker, daemon=True).start()

    @register_custom_filter(PermissionTypeFilter, PermissionType.ADMIN)
    @CommandFilter("续火花好友", alias={"spark_friends", "火花好友"})
    async def cmd_list_friends(self, event: AstrMessageEvent) -> None:
        """查看已配置的续火花好友"""
        rt = load_runtime()
        contacts = rt.get("contacts", [])
        friends = self.config.get("friends", [])

        msg = ["👥 续火花好友列表:"]
        if contacts:
            msg.append("\n📋 从抖音获取的聊天列表:")
            for c in contacts[:20]:
                streak = f" 🔥{c.get('streak', '')}" if c.get("streak") else ""
                msg.append(f"  • {c['name']}{streak}")
            if len(contacts) > 20:
                msg.append(f"  ... 共 {len(contacts)} 个")
        else:
            msg.append("\n📋 从抖音获取的聊天列表: 暂无，请先点击「获取好友列表」")

        if friends:
            msg.append("\n✅ 已勾选的续火花好友:")
            for f in friends:
                msg.append(f"  • {f}")
        else:
            msg.append("\n✅ 已勾选的续火花好友: 暂无")

        await event.reply("\n".join(msg))

    @register_custom_filter(PermissionTypeFilter, PermissionType.ADMIN)
    @CommandFilter("续火花设置", alias={"spark_config", "火花设置"})
    async def cmd_config(self, event: AstrMessageEvent) -> None:
        """查看当前配置"""
        cfg = self.config
        msg = [
            "⚙️ 当前配置:",
            f"  ⏰ 发送时间: {cfg.get('schedule_time', '21:00')}",
            f"  🎲 抖动窗口: {cfg.get('jitter_minutes', 30)} 分钟",
            f"  ⏱️ 好友间隔: {cfg.get('send_gap_min', 6)}-{cfg.get('send_gap_max', 12)} 秒",
            f"  👥 最大发送数: {cfg.get('max_friends_per_run', 20)}",
            f"  🔁 自动补发: {'开启' if cfg.get('auto_retry') else '关闭'}",
            f"  🌐 无头模式: {'开启' if cfg.get('headless') else '关闭'}",
            f"  📝 消息模板: {len(cfg.get('messages', []))} 条",
            f"  👥 续火花好友: {len(cfg.get('friends', []))} 人",
        ]
        await event.reply("\n".join(msg))

    @register_custom_filter(PermissionTypeFilter, PermissionType.ADMIN)
    @CommandFilter("续火花上传登录态", alias={"spark_upload", "上传state"})
    async def cmd_upload_state(self, event: AstrMessageEvent) -> None:
        """上传登录态 (请在网页配置页面操作)"""
        await event.reply(
            "📤 请在 AstrBot WebUI 管理面板中操作：\n"
            "1. 进入插件配置页面\n"
            "2. 点击「上传登录态」选择 state.json 文件\n"
            "3. 或使用命令：/续火花上传 state.json (需配合文件上传)"
        )

    @register_custom_filter(PermissionTypeFilter, PermissionType.ADMIN)
    @CommandFilter("续火花帮助", alias={"spark_help", "火花帮助"})
    async def cmd_help(self, event: AstrMessageEvent) -> None:
        """显示帮助信息"""
        msg = [
            "🔥 抖音续火花助手 - 命令帮助",
            "",
            "📋 基础命令:",
            "  /续火花状态 - 查看运行状态",
            "  /续火花发送 - 立即发送续火花",
            "  /续火花测试 - 干跑测试（不真实发送）",
            "  /续火花获取好友 - 从抖音获取聊天列表",
            "  /续火花好友 - 查看已配置的好友",
            "  /续火花设置 - 查看当前配置",
            "  /续火花帮助 - 显示此帮助",
            "",
            "⚙️ 详细配置请在 WebUI 管理面板中进行：",
            "  - 好友列表勾选",
            "  - 消息模板编辑",
            "  - 定时时间设置",
            "  - 登录态上传",
            "",
            "⚠️ 注意事项:",
            "  - 仅限个人低频自用，批量/多账号必封",
            "  - 登录态过期需在本地运行提取脚本并重新上传",
            "  - 建议国内同城机房服务器，海外 IP 易触发验证码",
        ]
        await event.reply("\n".join(msg))


# 导出插件类
__all__ = ["DouyinSparkPlugin"]
