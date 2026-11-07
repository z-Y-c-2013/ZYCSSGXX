"""全局配置与路径管理"""
import json
import os
import shutil
import sys

APP_NAME = "ZYCSSGXX"
APP_VERSION = "1.4.0"
# 启动器安装目录（launcher/ 的上级，即 main.py 所在目录）
INSTALL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 资源目录（PyInstaller 打包后从 _MEIPASS 读取）
if getattr(sys, "frozen", False):
    ASSETS_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "assets")
else:
    ASSETS_DIR = os.path.join(INSTALL_DIR, "assets")
ICON_FILE = os.path.join(ASSETS_DIR, "zycssgxx.ico")

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
ACCOUNTS_FILE = os.path.join(APP_DIR, "accounts.json")
JAVA_DIR = os.path.join(APP_DIR, "runtime")


def _migrate_old_data():
    """旧版数据目录 MineLauncher → ZYCSSGXX 一次性迁移（同盘移动，瞬间完成）"""
    old = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MineLauncher")
    if os.path.isdir(old) and not os.path.exists(APP_DIR):
        try:
            shutil.move(old, APP_DIR)
        except OSError:
            pass


_migrate_old_data()

DEFAULT_SETTINGS = {
    "game_dir": "",   # 空 = %APPDATA%\.minecraft
    "memory_gb": 2,
    "java_path": "",  # 空 = 自动检测
    "update_manifest_url": "",  # 更新源 manifest.json 地址，空 = 不检查
    "terracotta_path": "",      # 陶瓦联机程序路径，空 = 未设置
    "chat_server": "",          # 聊天服务器地址（ws://xxx 或 wss://xxx），空 = 不使用聊天
    # --- 管理员推送（只有作者本人解锁）---
    "admin_token": "",          # 管理员密钥，有值才显示推送面板
    "push_provider": "github",  # github 或 gitee
    "push_repo": "",            # owner/repo 格式
    "push_url": "",             # manifest.json 的远程 raw 地址
}


def default_game_dir():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), ".minecraft")


def load_settings():
    os.makedirs(APP_DIR, exist_ok=True)
    settings = dict(DEFAULT_SETTINGS)
    try:
        if os.path.isfile(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings.update(json.load(f))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    os.makedirs(APP_DIR, exist_ok=True)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
