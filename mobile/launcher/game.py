"""游戏版本列表、资源安装与启动命令构建"""
import os
import subprocess

import minecraft_launcher_lib as mll


def mc_dir(settings):
    custom = settings.get("game_dir") or ""
    return custom if custom else os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), ".minecraft")


def available_versions(mc_dir):
    """从官方清单获取所有可用版本（含 type / releaseTime）"""
    versions = mll.utils.get_available_versions(mc_dir)
    return [{"id": v["id"],
             "type": v.get("type", "release"),
             "releaseTime": str(v.get("releaseTime", ""))[:10]} for v in versions]


def installed_versions(mc_dir):
    """已安装版本（按发布时间倒序）"""
    try:
        versions = mll.utils.get_installed_versions(mc_dir)
    except Exception:
        return []
    result = [{"id": v["id"], "releaseTime": str(v.get("releaseTime", ""))[:10]}
              for v in versions]
    result.sort(key=lambda x: (x["releaseTime"], x["id"]), reverse=True)
    return result


def is_installed(version_id, mc_dir):
    return os.path.isfile(os.path.join(mc_dir, "versions", version_id,
                                       version_id + ".json"))


class ProgressReporter:
    """把 minecraft-launcher-lib 的回调转成统一 emit(dict) 事件"""

    def __init__(self, emit):
        self._emit = emit

    def setStatus(self, status):
        self._emit({"status": str(status)})

    def setProgress(self, value):
        self._emit({"progress": value})

    def setMax(self, value):
        self._emit({"max": value})


def install(version_id, mc_dir, emit):
    """安装指定版本（客户端 jar / 库 / 资源文件），emit 用于进度上报"""
    reporter = ProgressReporter(emit)
    mll.install.install_minecraft_version(version_id, mc_dir, callback={
        "setStatus": reporter.setStatus,
        "setProgress": reporter.setProgress,
        "setMax": reporter.setMax,
    })


def install_fabric(version_id, mc_dir, emit):
    """为原版版本安装 Fabric（纯 Python 实现，无需 Java）"""
    reporter = ProgressReporter(emit)
    mll.fabric.install_fabric(version_id, mc_dir, callback={
        "setStatus": reporter.setStatus,
        "setProgress": reporter.setProgress,
        "setMax": reporter.setMax,
    })


def install_forge(version_id, mc_dir, emit, java_exe):
    """为原版版本安装 Forge（需要 Java 运行安装器）"""
    reporter = ProgressReporter(emit)
    mll.forge.install_minecraft_version(version_id, mc_dir, callback={
        "setStatus": reporter.setStatus,
        "setProgress": reporter.setProgress,
        "setMax": reporter.setMax,
    }, java=java_exe)


def build_launch_command(version_id, mc_dir, account, settings, java_exe,
                         server=None):
    memory = max(1, int(settings.get("memory_gb", 2)))
    options = {
        "username": account["name"],
        "uuid": account["uuid"],
        "token": "0",
        "executablePath": java_exe,
        "jvmArguments": ["-Xms%dG" % min(memory, 1), "-Xmx%dG" % memory],
        "launcherName": "ZYCSSGXX",
        "launcherVersion": "1.0",
    }
    if settings.get("version_isolation"):
        # 版本隔离：每个版本独立的存档/模组/配置目录
        options["gameDirectory"] = os.path.join(mc_dir, "versions", version_id)
    cmd = mll.command.get_minecraft_command(version_id, mc_dir, options)
    if server and server.get("ip"):
        # 原版参数：启动后自动连接服务器
        cmd += ["--server", server["ip"],
                "--port", str(server.get("port") or 25565)]
    return cmd


def launch(cmd, cwd):
    """启动游戏进程，stdout 合并到管道供日志窗口实时读取"""
    return subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
        bufsize=1)
