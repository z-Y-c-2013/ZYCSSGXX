"""ZYCSSGXX 聊天客户端（WebSocket + HTTP）。

用法：
    from . import chat as chatlib
    client = chatlib.ChatClient(settings, username, ui_queue)
    client.start()          # 启动后台连接线程
    client.send_chat(to, content)
    client.add_friend(to_name)
    # 后台通过 ui_queue 推送事件：chat_message / friend_list / login_ok / ...
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from . import config

_UA = {"User-Agent": "ZYCSSGXX-chat/" + config.APP_VERSION}


class ChatClient:
    """聊天客户端：后台线程维护 WebSocket 连接 + HTTP API 调用"""

    def __init__(self, settings, username, ui_queue):
        self.settings = settings
        self.username = username.strip().lower()
        self.ui_queue = ui_queue
        self.ws = None
        self.running = False
        self._thread = None
        self._friends = []
        self._pending_requests = []
        # 本地消息缓存（最近1000条）：{friend_name: [msg dict]}
        self._history = {}

    # ---------- URL 构造 ----------
    def _base_http(self):
        """HTTP API 基地址"""
        url = (self.settings.get("chat_server") or "").strip()
        if not url:
            return ""
        # ws://host → http://host, wss://host → https://host
        if url.startswith("ws://"):
            return "http://" + url[5:]
        if url.startswith("wss://"):
            return "https://" + url[6:]
        return url.rstrip("/")

    def _ws_url(self):
        base = (self.settings.get("chat_server") or "").strip()
        if not base:
            return ""
        base = base.rstrip("/")
        return "%s/ws?user=%s" % (base, urllib.parse.quote(self.username))

    # ---------- 启动/停止 ----------
    def start(self):
        if not self.username:
            return
        if self._thread and self._thread.is_alive():
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    # ---------- HTTP API ----------
    def _http_get(self, path):
        base = self._base_http()
        if not base:
            return None
        url = base + path
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.load(resp)
        except Exception:
            return None

    def register_account(self, name, uuid=""):
        """通过 HTTP 注册（启动器创建账号时调用）"""
        base = self._base_http()
        if not base:
            return True  # 没有服务端，跳过
        url = base + "/api/register"
        try:
            data = json.dumps({"name": name, "uuid": uuid}).encode()
            req = urllib.request.Request(url, data=data, headers={
                "Content-Type": "application/json", **_UA}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.load(resp)
        except Exception:
            return None

    def search_user(self, q):
        q = q.strip()
        if not q:
            return []
        result = self._http_get("/api/search?q=" + urllib.parse.quote(q))
        if result and result.get("ok"):
            return result.get("results", [])
        return []

    def get_friends(self):
        result = self._http_get("/api/friends?self=" + urllib.parse.quote(self.username))
        if result and result.get("ok"):
            self._friends = result.get("friends", [])
            return self._friends
        return []

    def get_requests(self):
        result = self._http_get("/api/friend/requests?self=" + urllib.parse.quote(self.username))
        if result and result.get("ok"):
            self._pending_requests = result.get("requests", [])
            return self._pending_requests
        return []

    # ---------- WebSocket ----------
    def _run(self):
        """后台线程：连接 + 接收消息，断线自动重连"""
        try:
            import websocket as ws_lib
        except ImportError:
            # 没装 websocket-client，跳过 WebSocket
            # 用长轮询替代
            self._polling_loop()
            return

        reconnect_delay = 2
        while self.running:
            url = self._ws_url()
            if not url:
                break
            try:
                self.ws = ws_lib.create_connection(url, timeout=30)
                reconnect_delay = 2  # 成功后重置
                self.ui_queue.put({"chat_connected": True})
                # 接收循环
                while self.running:
                    data = self.ws.recv()
                    if not data:
                        break
                    self._on_server_message(json.loads(data))
            except Exception as exc:
                self.ui_queue.put({"chat_error": str(exc)[:100]})
            finally:
                self.ws = None
                if self.running:
                    self.ui_queue.put({"chat_connected": False})
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)

    def _polling_loop(self):
        """无 websocket 库时的降级方案：长轮询"""
        last_check = 0
        while self.running:
            time.sleep(3)
            now = time.time()
            if now - last_check > 10:
                self.ui_queue.put({"chat_status": "长轮询模式（未安装 websocket-client）"})
                last_check = now

    def _on_server_message(self, msg):
        mtype = msg.get("type", "")
        if mtype == "login_ok":
            self._friends = msg.get("friends", [])
            self._pending_requests = msg.get("requests", [])
            self.ui_queue.put({"chat_login_ok": {
                "friends": self._friends,
                "requests": self._pending_requests,
            }})
        elif mtype == "offline_msgs":
            for m in msg.get("messages", []):
                friend = m.get("from", "unknown")
                self._history.setdefault(friend, []).append(m)
            self.ui_queue.put({"chat_offline": msg.get("messages", [])})
        elif mtype == "chat":
            friend = msg.get("from", "unknown")
            self._history.setdefault(friend, []).append(msg)
            self.ui_queue.put({"chat_message": msg})
        elif mtype == "friend_request":
            self.ui_queue.put({"chat_friend_request": msg})
        elif mtype == "friend_accept":
            self.ui_queue.put({"chat_friend_accept": msg})
        elif mtype == "friend_add_ok":
            self.ui_queue.put({"chat_friend_add_ok": msg})
        elif mtype == "friend_accept_ok":
            self.ui_queue.put({"chat_friend_accept_ok": msg})

    # ---------- 发送 ----------
    def _ws_send(self, payload):
        if not self.ws:
            return False
        try:
            self.ws.send(json.dumps(payload))
            return True
        except Exception:
            return False

    def send_chat(self, to, content):
        to = to.strip().lower()
        content = content.strip()
        if not to or not content:
            return False
        payload = {"type": "chat", "to": to, "content": content}
        ok = self._ws_send(payload)
        if ok:
            msg = dict(payload)
            msg["from"] = self.username
            msg["time"] = int(time.time())
            self._history.setdefault(to, []).append(msg)
            self.ui_queue.put({"chat_sent": msg})
        return ok

    def add_friend(self, to_name):
        to_name = to_name.strip().lower()
        if not to_name or to_name == self.username:
            return False
        if self.ws:
            return self._ws_send({"type": "friend_add", "to": to_name})
        # 降级 HTTP
        base = self._base_http()
        if not base:
            return False
        url = "%s/api/friend/add?self=%s&to=%s" % (
            base, urllib.parse.quote(self.username), urllib.parse.quote(to_name))
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return True
        except Exception:
            return False

    def accept_friend(self, from_name):
        from_name = from_name.strip().lower()
        if self.ws:
            return self._ws_send({"type": "friend_accept", "from": from_name})
        base = self._base_http()
        if not base:
            return False
        url = "%s/api/friend/accept?self=%s&from=%s" % (
            base, urllib.parse.quote(self.username), urllib.parse.quote(from_name))
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return True
        except Exception:
            return False

    # ---------- 本地历史 ----------
    def get_history(self, friend):
        return self._history.get(friend, [])

    def friends(self):
        return self._friends
