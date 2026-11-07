"""启动器自更新。

更新源是一个 manifest.json（可免费托管在 GitHub Pages / Gitee Pages /
GitHub Raw 等）：

    {
      "version": "1.0.1",
      "url": "https://.../minelauncher-1.0.1.zip",
      "notes": "本次更新内容"
    }

zip 内容为项目根目录（main.py、launcher/ 等），允许带或不带顶层文件夹。
纯 Python 脚本在运行中可被覆盖，因此无需外部升级器。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from . import config

_UA = {"User-Agent": "ZYCSSGXX/" + config.APP_VERSION}


def compare_versions(a, b):
    """按数字段比较，a > b 返回 True（如 1.10.0 > 1.9.2）"""

    def parts(v):
        return tuple(int(x) for x in re.findall(r"\d+", v))

    return parts(a) > parts(b)


def check_update(manifest_url, timeout=10):
    """有新版本返回 {"version", "url", "notes"}，否则返回 None"""
    if not manifest_url:
        return None
    req = urllib.request.Request(manifest_url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    latest = str(data.get("version", "")).strip()
    url = str(data.get("url", "")).strip()
    if not latest or not url:
        return None
    if not compare_versions(latest, config.APP_VERSION):
        return None
    return {"version": latest, "url": url, "notes": str(data.get("notes", ""))}


def download_update(zip_url, progress=None):
    """下载更新包到临时目录，返回 zip 路径。progress(cur_bytes, total_bytes)"""
    fd, zip_path = tempfile.mkstemp(prefix="minelauncher-update-", suffix=".zip")
    os.close(fd)

    def hook(count, block, total):
        if progress and total:
            progress(count * block, total)

    try:
        urllib.request.urlretrieve(zip_url, zip_path, reporthook=hook)
    except Exception:
        _remove(zip_path)
        raise
    return zip_path


def apply_update(zip_path, install_dir=None):
    """解压覆盖安装目录（用户数据在 %APPDATA%，不受影响）"""
    install_dir = install_dir or config.INSTALL_DIR
    tmp = tempfile.mkdtemp(prefix="minelauncher-extract-")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        entries = os.listdir(tmp)
        src = tmp
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
            src = os.path.join(tmp, entries[0])
        os.makedirs(install_dir, exist_ok=True)
        for name in os.listdir(src):
            s = os.path.join(src, name)
            d = os.path.join(install_dir, name)
            if os.path.isdir(s):
                if os.path.isdir(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _remove(zip_path)


def restart():
    """以当前解释器重新启动启动器"""
    main_py = os.path.join(config.INSTALL_DIR, "main.py")
    subprocess.Popen([sys.executable, main_py], close_fds=True)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
