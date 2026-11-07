"""Minecraft 独立服务器管理：官方 server.jar 下载 + eula/properties + 启停控制。

创建的服务器保存在 %APPDATA%/ZYCSSGXX/servers/<版本id>/，
默认 online-mode=false 以支持离线账号联机。
"""
import json
import os
import subprocess
import urllib.request

_UA = {"User-Agent": "ZYCSSGXX/1.0 (Minecraft launcher)"}
MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

SERVER_PROPERTIES = """# ZYCSSGXX 服务器配置
online-mode=false
server-port=25565
motd=ZYCSSGXX \u8054\u673a\u670d\u52a1\u5668
max-players=10
view-distance=8
spawn-protection=0
enable-command-block=false
difficulty=easy
gamemode=survival
white-list=false
"""


def servers_dir(app_dir):
    d = os.path.join(app_dir, "servers")
    os.makedirs(d, exist_ok=True)
    return d


def server_dir(app_dir, version_id):
    return os.path.join(servers_dir(app_dir), version_id)


def list_servers(app_dir):
    """已创建的服务器 [版本id]（判定依据：目录内有 server.jar）"""
    root = servers_dir(app_dir)
    out = []
    for name in sorted(os.listdir(root)):
        if os.path.isfile(os.path.join(root, name, "server.jar")):
            out.append(name)
    return out


def server_download_url(version_id):
    """从 Mojang 官方 manifest 取服务器 jar 下载地址（远古版本可能没有）"""
    req = urllib.request.Request(MANIFEST, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        manifest = json.load(resp)
    for v in manifest["versions"]:
        if v["id"] == version_id:
            with urllib.request.urlopen(v["url"], timeout=20) as resp:
                detail = json.load(resp)
            dl = detail.get("downloads", {}).get("server")
            if not dl:
                raise RuntimeError("官方没有提供 %s 的服务器端" % version_id)
            return dl["url"]
    raise RuntimeError("版本 %s 不存在" % version_id)


def create_server(version_id, app_dir, progress=None):
    """下载官方服务器 jar 并写好 eula / 配置，返回服务器目录"""
    url = server_download_url(version_id)
    d = server_dir(app_dir, version_id)
    os.makedirs(d, exist_ok=True)
    jar = os.path.join(d, "server.jar")

    def hook(count, block, total):
        if progress and total:
            progress(count * block, total)

    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as resp, open(jar, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            hook(done, 1, total)

    eula = os.path.join(d, "eula.txt")
    if not os.path.isfile(eula):
        with open(eula, "w", encoding="utf-8") as f:
            f.write("# 已由 ZYCSSGXX 记录你在创建时的同意选择\neula=true\n")
    props = os.path.join(d, "server.properties")
    if not os.path.isfile(props):
        with open(props, "w", encoding="utf-8") as f:
            f.write(SERVER_PROPERTIES)
    return d


def launch_command(server_dir_, java_exe, memory_gb=2):
    """服务器启动命令（stdin 发 stop 可优雅关服）"""
    return [
        java_exe,
        "-Xms%dM" % min(memory_gb * 1024 // 2, 1024),
        "-Xmx%dM" % (memory_gb * 1024),
        "-jar", "server.jar", "nogui",
    ]


def launch(server_dir_, java_exe, memory_gb=2):
    """在服务器目录启动，stdin/stdout 接管供控制台读写"""
    return subprocess.Popen(
        launch_command(server_dir_, java_exe, memory_gb),
        cwd=server_dir_,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def send_command(proc, cmd):
    """向服务器控制台发送命令（如 stop / list / op xxx）"""
    try:
        proc.stdin.write(cmd + "\n")
        proc.stdin.flush()
        return True
    except (OSError, ValueError):
        return False
