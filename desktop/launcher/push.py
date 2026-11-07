"""管理员推送启动器更新。

只有设置了 admin_token 的启动器才有此功能（作者本人）。
推送流程：
1. 打包 launcher 目录为 zip
2. 上传到 GitHub/Gitee Release（用 token 调 API）
3. 更新 manifest.json 到 GitHub/Gitee Pages

需要在设置页配置：
- admin_token：管理员密钥（用于解锁推送按钮）
- push_url：manifest.json 的远程地址（GitHub Raw / Gitee Pages 等）
- release_url：Release API 地址（可选，为空则只更新 manifest）
"""
import json
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile

from . import config

_UA = {"User-Agent": "ZYCSSGXX-push/" + config.APP_VERSION}


def compare_versions(a, b):
    """按数字段比较，a > b 返回 True"""
    def parts(v):
        return tuple(int(x) for x in re.findall(r"\d+", v))
    return parts(a) > parts(b)


def is_admin(settings):
    """是否已解锁管理员功能"""
    token = (settings.get("admin_token") or "").strip()
    return bool(token)


def package_launcher(source_dir=None):
    """打包启动器源码目录为 zip，返回 zip 路径"""
    source_dir = source_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fd, zip_path = tempfile.mkstemp(prefix="zycssgxx-push-", suffix=".zip")
    os.close(fd)
    skip_dirs = ("__pycache__", "dist", ".git", "chat-server", ".vscode")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if f.endswith(".spec"):
                    continue
                if f.startswith("."):
                    continue
                full = os.path.join(root, f)
                arcname = os.path.relpath(full, source_dir)
                zf.write(full, arcname)
    return zip_path


def build_manifest(version, url, notes=""):
    """构建 manifest.json 内容（dict）"""
    return {
        "version": version,
        "url": url,
        "notes": notes,
        "built_at": "",
    }


def upload_to_github_release(zip_path, tag, repo, token):
    """上传 zip 到 GitHub Release，返回下载 URL。
    repo 格式：owner/repo （如 zycssg/launcher）
    """
    import urllib.parse

    api = "https://api.github.com"

    # 1. 创建 release
    data = json.dumps({
        "tag_name": tag,
        "name": "ZYCSSGXX v" + tag,
        "body": "更新内容：\n" + tag,
        "draft": False,
        "prerelease": False,
    }).encode()
    req = urllib.request.Request(
        "%s/repos/%s/releases" % (api, repo),
        data=data, headers={
            "Authorization": "token " + token,
            "Content-Type": "application/json",
            **_UA,
        }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.load(resp)

    upload_url = release["upload_url"].split("{")[0]
    release_id = release["id"]

    # 2. 上传 asset
    filename = os.path.basename(zip_path)
    file_size = os.path.getsize(zip_path)
    with open(zip_path, "rb") as f:
        req = urllib.request.Request(
            "%s?name=%s" % (upload_url, urllib.parse.quote(filename)),
            data=f.read(), headers={
                "Authorization": "token " + token,
                "Content-Type": "application/zip",
                "Content-Length": str(file_size),
                **_UA,
            }, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            asset = json.load(resp)

    # 3. 获取下载 URL
    return asset["browser_download_url"]


def upload_to_gitee_release(zip_path, tag, repo, token):
    """上传 zip 到 Gitee Release，返回下载 URL。
    repo 格式：owner/repo
    """
    import urllib.parse
    api = "https://gitee.com/api/v5"

    # 1. 创建 release
    data = json.dumps({
        "access_token": token,
        "tag_name": tag,
        "name": "ZYCSSGXX v" + tag,
        "body": "更新内容：\n" + tag,
        "target_commitish": "master",
    }).encode()
    req = urllib.request.Request(
        "%s/repos/%s/releases" % (api, repo),
        data=data, headers={
            "Content-Type": "application/json",
            **_UA,
        }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.load(resp)

    release_id = release["id"]

    # 2. 上传 asset
    filename = os.path.basename(zip_path)
    file_size = os.path.getsize(zip_path)
    with open(zip_path, "rb") as f:
        import http.client
        boundary = "----ZycssgxxBoundary"
        # Gitee multipart 比较特殊，直接用 requests-like 的简单方式
        body = b"--" + boundary.encode() + b"\r\n"
        body += b'Content-Disposition: form-data; name="file"; filename="' + filename.encode() + b'"\r\n'
        body += b"Content-Type: application/zip\r\n\r\n"
        body += f.read() + b"\r\n"
        body += b"--" + boundary.encode() + b"--\r\n"
        conn = http.client.HTTPSConnection("gitee.com", timeout=120)
        conn.request("POST", "/api/v5/repos/%s/releases/%d/attach_files?access_token=%s"
                     % (urllib.parse.quote(repo), release_id, token),
                     body, {
                         "Content-Type": "multipart/form-data; boundary=" + boundary,
                         **_UA,
                     })
        with conn.getresponse() as resp:
            asset = json.loads(resp.read().decode())
        conn.close()

    for a in asset if isinstance(asset, list) else [asset]:
        if a.get("name") == filename:
            return a.get("browser_download_url", "")
    return asset.get("browser_download_url", "")


def write_manifest_to_raw(manifest, raw_url, token):
    """通过 GitHub/Gitee API 直接写 manifest.json 到仓库文件。
    raw_url 示例：https://raw.githubusercontent.com/owner/repo/branch/path/manifest.json
                  https://gitee.com/owner/repo/raw/branch/path/manifest.json
    返回 True 表示成功。
    """
    import base64 as b64
    import urllib.parse

    data_json = json.dumps(manifest, ensure_ascii=False, indent=2)

    if "github" in raw_url:
        # GitHub Raw → GitHub Contents API
        # raw: https://raw.githubusercontent.com/owner/repo/branch/path/manifest.json
        parts = raw_url.replace("https://raw.githubusercontent.com/", "").split("/", 3)
        owner, repo, branch, path = parts
        api = "https://api.github.com"
        # 先获取现有文件的 sha（用于更新）
        try:
            req = urllib.request.Request(
                "%s/repos/%s/%s/contents/%s?ref=%s" % (api, owner, repo, path, branch),
                headers={"Authorization": "token " + token, **_UA})
            with urllib.request.urlopen(req, timeout=10) as resp:
                existing = json.load(resp)
                sha = existing.get("sha")
        except urllib.error.HTTPError:
            sha = None

        body = json.dumps({
            "message": "update manifest for v%s" % manifest.get("version"),
            "content": b64.b64encode(data_json.encode("utf-8")).decode(),
            "branch": branch,
        } | ({"sha": sha} if sha else {})).encode()
        req = urllib.request.Request(
            "%s/repos/%s/%s/contents/%s" % (api, owner, repo, path),
            data=body, headers={
                "Authorization": "token " + token,
                "Content-Type": "application/json",
                **_UA,
            }, method="PUT")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True

    if "gitee" in raw_url:
        # Gitee Raw → Gitee Contents API
        # raw: https://gitee.com/owner/repo/raw/branch/path/manifest.json
        parts = raw_url.replace("https://gitee.com/", "").split("/", 3)
        owner, repo, rest = parts[0], parts[1], parts[2]
        # 去掉 raw/ 前缀
        path_parts = rest.split("/", 1)
        if path_parts[0] == "raw":
            inner = path_parts[1] if len(path_parts) > 1 else ""
            inner_parts = inner.split("/", 1)
            branch = inner_parts[0]
            path = inner_parts[1] if len(inner_parts) > 1 else ""
        else:
            # 可能是直接的 API 路径
            return False

        api = "https://gitee.com/api/v5"
        # 先获取 sha
        try:
            req = urllib.request.Request(
                "%s/repos/%s/%s/contents/%s?access_token=%s&ref=%s"
                % (api, owner, repo, path, token, branch),
                headers=_UA)
            with urllib.request.urlopen(req, timeout=10) as resp:
                existing = json.load(resp)
                sha = existing.get("sha")
        except urllib.error.HTTPError:
            sha = None

        body_data = {
            "access_token": token,
            "message": "update manifest for v%s" % manifest.get("version"),
            "content": b64.b64encode(data_json.encode("utf-8")).decode(),
            "branch": branch,
        }
        if sha:
            body_data["sha"] = sha
        body = urllib.parse.urlencode(body_data).encode()
        req = urllib.request.Request(
            "%s/repos/%s/%s/contents/%s" % (api, owner, repo, path),
            data=body, headers=_UA, method="PUT")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True

    return False


def do_push(settings, version, notes=""):
    """一键推送：打包 → 上传 Release → 更新 manifest。
    返回 (success, message, manifest_url)
    """
    token = (settings.get("admin_token") or "").strip()
    if not token:
        return False, "未设置管理员 token", ""

    push_url = (settings.get("push_url") or settings.get("update_manifest_url") or "").strip()
    provider = (settings.get("push_provider") or "github").lower()
    repo = (settings.get("push_repo") or "").strip()

    if not push_url:
        return False, "未配置 manifest.json 远程地址", ""
    if not repo:
        return False, "未配置仓库地址（owner/repo）", ""

    # 1. 打包
    zip_path = package_launcher()
    try:
        # 2. 上传 Release
        url = ""
        try:
            if provider == "gitee":
                url = upload_to_gitee_release(zip_path, version, repo, token)
            else:
                url = upload_to_github_release(zip_path, version, repo, token)
            if not url:
                return False, "上传 Release 成功但未拿到下载 URL", ""
        except Exception as exc:
            return False, "上传 Release 失败：%s" % exc, ""

        # 3. 更新 manifest
        manifest = build_manifest(version, url, notes)
        try:
            ok = write_manifest_to_raw(manifest, push_url, token)
            if not ok:
                return False, "manifest.json 写入失败", ""
        except Exception as exc:
            return False, "manifest.json 写入失败：%s" % exc, ""

        return True, "推送完成：v%s → %s" % (version, url), url
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass
