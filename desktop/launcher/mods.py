"""模组管理：Modrinth 搜索 / 下载 / 已装列表（免费开放 API）"""
import json
import os
import urllib.parse
import urllib.request

API = "https://api.modrinth.com/v2"
_UA = {"User-Agent": "ZYCSSGXX/1.0 (Minecraft launcher)"}
LOADERS = ("fabric", "forge", "quilt", "neoforge")


def _get(url):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def mods_dir(mc_dir):
    return os.path.join(mc_dir, "mods")


def search(query, loader, game_version, limit=20):
    """按关键词 + 加载器 + 游戏版本搜索模组"""
    facets = [["project_type:mod"]]
    if loader in LOADERS:
        facets.append(["categories:" + loader])
    if game_version:
        facets.append(["versions:" + game_version])
    url = API + "/search?" + urllib.parse.urlencode({
        "query": query or "", "limit": limit, "facets": json.dumps(facets)})
    return _get(url).get("hits", [])


def latest_file(project_id, loader, game_version):
    """取模组在指定版本/加载器下的最新文件 (url, filename)"""
    url = API + "/project/%s/version?%s" % (project_id, urllib.parse.urlencode({
        "game_versions": json.dumps([game_version]) if game_version else "[]",
        "loaders": json.dumps([loader]) if loader in LOADERS else "[]"}))
    versions = _get(url)
    if not versions:
        return None, None
    for f in versions[0].get("files", []):
        if f.get("primary"):
            return f["url"], f["filename"]
    files = versions[0].get("files", [])
    if files:
        return files[0]["url"], files[0]["filename"]
    return None, None


def download(url, filename, mc_dir, progress=None):
    """下载模组 jar 到 mods 目录，返回完整路径"""
    d = mods_dir(mc_dir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, filename)

    def hook(count, block, total):
        if progress and total:
            progress(count * block, total)

    urllib.request.urlretrieve(url, path, reporthook=hook)
    return path


def list_mods(mc_dir):
    """已安装模组 [(文件名, 大小KB)]"""
    d = mods_dir(mc_dir)
    if not os.path.isdir(d):
        return []
    out = []
    for name in os.listdir(d):
        if name.lower().endswith(".jar"):
            p = os.path.join(d, name)
            try:
                out.append((name, os.path.getsize(p) // 1024))
            except OSError:
                pass
    return sorted(out)


def delete_mod(mc_dir, name):
    try:
        os.remove(os.path.join(mods_dir(mc_dir), name))
        return True
    except OSError:
        return False
