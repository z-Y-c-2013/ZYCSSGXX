"""Java 运行时：本机检测、版本匹配、Adoptium (Temurin JRE) 自动下载"""
import glob
import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile

JAVA_SCAN_PATTERNS = [
    r"C:\Program Files\Java\*\bin\java.exe",
    r"C:\Program Files (x86)\Java\*\bin\java.exe",
    r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
    r"C:\Program Files (x86)\Eclipse Adoptium\*\bin\java.exe",
    r"C:\Program Files\Microsoft\jdk*\bin\java.exe",
    r"C:\Program Files\Zulu\zulu-*\bin\java.exe",
    r"C:\Program Files\Amazon Corretto\*\bin\java.exe",
    r"C:\Program Files\BellSoft\*\bin\java.exe",
    r"C:\Program Files\Alibaba\dragonwell-*\bin\java.exe",
]

ADOPTIUM_API = ("https://api.adoptium.net/v3/assets/latest/{major}/hotspot"
                "?architecture=x64&image_type=jre&os=windows&vendor=eclipse")


def find_javas():
    """扫描本机常见位置，返回 java.exe 路径列表"""
    found, seen = [], set()

    def _add(path):
        if path and os.path.isfile(path) and path.lower() not in seen:
            found.append(path)
            seen.add(path.lower())

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        _add(os.path.join(java_home, "bin", "java.exe"))
    which = shutil.which("java")
    if which:
        _add(which)
    for pattern in JAVA_SCAN_PATTERNS:
        for path in glob.glob(pattern):
            _add(path)
    return found


def java_major(java_path):
    """读取 Java 主版本号（1.8 → 8），失败返回 0"""
    try:
        out = subprocess.run([java_path, "-version"], capture_output=True, timeout=20)
        text = (out.stderr or b"").decode("utf-8", "replace") + (out.stdout or b"").decode("utf-8", "replace")
        m = re.search(r'version "(\d+)(?:\.(\d+))?[^"]*"', text)
        if not m:
            return 0
        major = int(m.group(1))
        if major == 1 and m.group(2):
            return int(m.group(2))
        return major
    except Exception:
        return 0


def required_java_major(version_id):
    """根据游戏版本推断所需 Java 大版本"""
    m = re.match(r"^1\.(\d+)(?:\.(\d+))?", version_id)
    if m:
        minor, patch = int(m.group(1)), int(m.group(2) or 0)
        if minor >= 21:
            return 21
        if minor == 20 and patch >= 5:
            return 21
        if minor == 17:
            return 16
        if minor >= 18:
            return 17
        return 8
    m = re.match(r"^(\d\d)w", version_id)  # 快照，如 24w14a
    if m:
        return 21 if int(m.group(1)) >= 24 else 8
    return 8


def pick_java(required, custom_path=""):
    """在所有候选 Java 中选出版本达标且最接近要求的一个；无达标返回 None"""
    candidates = []
    if custom_path and os.path.isfile(custom_path):
        candidates.append(custom_path)
    candidates += find_javas()
    best, best_major = None, 0
    for path in candidates:
        major = java_major(path)
        if major >= required and (best is None or major < best_major):
            best, best_major = path, major
    return best


def download_java(major, dest_dir, progress=None):
    """从 Adoptium 下载 Temurin JRE 并解压，返回 java.exe 路径。

    progress(cur_bytes, total_bytes) 可为 None。
    """
    os.makedirs(dest_dir, exist_ok=True)
    url = ADOPTIUM_API.format(major=major)
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    link = None
    for item in data:
        pkg = item.get("binary", {}).get("package", {})
        if str(pkg.get("link", "")).endswith(".zip"):
            link = pkg["link"]
            break
    if not link:
        raise RuntimeError("未找到可用的 Java %d 下载链接" % major)

    zip_path = os.path.join(dest_dir, "temurin-%d.zip" % major)

    def hook(count, block, total):
        if progress and total:
            progress(count * block, total)

    urllib.request.urlretrieve(link, zip_path, reporthook=hook)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
    try:
        os.remove(zip_path)
    except OSError:
        pass

    for sub in sorted(os.listdir(dest_dir)):
        exe = os.path.join(dest_dir, sub, "bin", "java.exe")
        if os.path.isfile(exe):
            return exe
    raise RuntimeError("Java 下载完成但解压失败，请重试")
