"""在本地电脑（有界面的 Windows/macOS）或服务器（配置 Xvfb）运行：打开浏览器扫码登录抖音，导出登录态。

用法：
    playwright install chromium
    python -m astrbot_plugin_douyin_spark.core.extract_cookie

生成 state.json 后，通过插件配置页面上传即可。

服务器无头模式下需安装 Xvfb:
    apt-get install -y xvfb
    xvfb-run -a python -m astrbot_plugin_douyin_spark.core.extract_cookie
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def get_output_path(plugin_data_dir: Path) -> Path:
    return plugin_data_dir / "state.json"


def _has_display() -> bool:
    """检查是否有可用的显示环境"""
    return bool(os.environ.get("DISPLAY")) or sys.platform == "darwin" or sys.platform == "win32"


def _try_xvfb() -> bool:
    """尝试使用 Xvfb 启动虚拟显示器"""
    if shutil.which("xvfb-run"):
        return True
    return False


def main(plugin_data_dir: Path, force_headless: bool = False) -> None:
    out_path = get_output_path(plugin_data_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 判断运行模式
    use_headless = force_headless or not _has_display()
    
    if use_headless:
        if not _try_xvfb():
            print("❌ 无图形界面环境，且未检测到 xvfb-run。")
            print("   请安装 Xvfb: apt-get install -y xvfb")
            print("   然后使用: xvfb-run -a python -m astrbot_plugin_douyin_spark.core.extract_cookie")
            print("   或在本地有界面的电脑上运行此脚本。")
            sys.exit(1)
        print("🖥️  检测到无头环境，将使用 Xvfb 虚拟显示器...")
    else:
        print("🖥️  检测到图形界面环境，将打开浏览器窗口...")

    print("正在启动浏览器，请在弹出的窗口里用手机抖音 App 扫码登录…")

    with sync_playwright() as p:
        if use_headless:
            # 使用 Xvfb 时仍需 headless=False，由 xvfb-run 提供虚拟显示
            browser = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-setuid-sandbox"])
        else:
            browser = p.chromium.launch(headless=False)
        
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=60000)

        deadline = time.time() + 300
        while time.time() < deadline:
            cookies = context.cookies()
            if any(c["name"].startswith("sessionid") for c in cookies):
                time.sleep(2)
                context.storage_state(path=str(out_path))
                print(f"\n✅ 登录态已保存到: {out_path}")
                browser.close()
                return
            time.sleep(2)

        print("\n⏰ 超时：5 分钟内未完成扫码登录，请重新运行。")
        browser.close()
        sys.exit(1)


if __name__ == "__main__":
    # When run directly, use current directory
    import argparse
    parser = argparse.ArgumentParser(description="抖音扫码登录态提取工具")
    parser.add_argument("--force-headless", action="store_true", help="强制使用无头模式（配合 Xvfb）")
    parser.add_argument("--data-dir", type=Path, default=Path.cwd() / "data", help="插件数据目录")
    args = parser.parse_args()
    main(args.data_dir, force_headless=args.force_headless)
