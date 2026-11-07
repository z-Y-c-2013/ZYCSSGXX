"""联机模块：局域网房间发现（Minecraft 官方组播协议）+ 本机 IP + 日志端口嗅探。

Minecraft 对局域网开放后会向 224.0.2.60:4445 组播：
    [MOTD]房间名[/MOTD][AD]192.168.1.5:54321[/AD]
"""
import re
import socket
import struct
import threading
import time

MC_MULTICAST_GROUP = "224.0.2.60"
MC_MULTICAST_PORT = 4445
ROOM_TTL = 6.0  # 房间广播约 1.5 秒一次，超时视为关闭

_RE_MOTD = re.compile(r"\[MOTD\](.*?)\[/MOTD\]", re.S)
_RE_AD = re.compile(r"\[AD\](.*?)\[/AD\]", re.S)
_RE_LOG_LAN_PORT = re.compile(
    r"(?:对局域网开放|LAN|Opened to LAN|Serving).{0,80}?(\d{4,5})", re.I)


class LanRoomScanner:
    """后台线程持续监听局域网房间广播"""

    def __init__(self):
        self._rooms = {}          # (ip, port) -> {"motd","ip","port","seen"}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _listen(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", MC_MULTICAST_PORT))
            mreq = struct.pack("4sl", socket.inet_aton(MC_MULTICAST_GROUP),
                               socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(1.0)
        except OSError:
            return
        while not self._stop.is_set():
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            text = data.decode("utf-8", "replace")
            ad = _RE_AD.search(text)
            if not ad:
                continue
            ipport = ad.group(1).strip().lstrip("/")
            ip, _, port = ipport.rpartition(":")
            if not ip or not port.isdigit():
                continue
            motd = _RE_MOTD.search(text)
            with self._lock:
                self._rooms[(ip, int(port))] = {
                    "motd": motd.group(1).strip() if motd else "Minecraft 房间",
                    "ip": ip, "port": int(port), "seen": time.time()}
        try:
            sock.close()
        except OSError:
            pass

    def snapshot(self):
        """返回当前可见房间列表（剔除过期）"""
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._rooms.items() if now - v["seen"] > ROOM_TTL]
            for k in expired:
                del self._rooms[k]
            rooms = sorted(self._rooms.values(),
                           key=lambda r: (r["ip"], r["port"]))
        return [{"motd": r["motd"], "ip": r["ip"], "port": r["port"]}
                for r in rooms]


def local_ips():
    """本机内网 IP 列表（用于告诉朋友连接地址）"""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def parse_lan_port(log_line):
    """从游戏日志行嗅探『对局域网开放』的端口，未命中返回 None"""
    m = _RE_LOG_LAN_PORT.search(log_line)
    if m:
        return int(m.group(1))
    return None
