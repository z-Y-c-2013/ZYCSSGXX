"""离线账号管理。

规则：账号名唯一（不区分大小写），不允许添加重复账号。
UUID 按 Minecraft 离线模式标准算法（MD5 of "OfflinePlayer:<name>"）生成。
"""
import hashlib
import json
import os
import re
import threading
import uuid as uuidlib

_lock = threading.Lock()

NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{1,16}$")


def offline_uuid(name):
    digest = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30  # UUID version 3
    digest[8] = (digest[8] & 0x3F) | 0x80  # IETF variant
    return str(uuidlib.UUID(bytes=bytes(digest)))


class AccountStore:
    def __init__(self, path):
        self.path = path
        self.accounts = []   # [{name, uuid, type}]
        self.current = ""
        self._load()

    def _load(self):
        try:
            if os.path.isfile(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.accounts = data.get("accounts", [])
                self.current = data.get("current", "")
        except (OSError, ValueError):
            self.accounts, self.current = [], ""

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"accounts": self.accounts, "current": self.current},
                      f, ensure_ascii=False, indent=2)

    def names(self):
        return [a["name"] for a in self.accounts]

    def add(self, name):
        name = name.strip()
        if not name:
            raise ValueError("用户名不能为空")
        if not NAME_PATTERN.match(name):
            raise ValueError("用户名限 1-16 位，只能是字母、数字、下划线或中文")
        with _lock:
            for acc in self.accounts:
                if acc["name"].lower() == name.lower():
                    raise ValueError("账号「%s」已存在，不允许重复账号" % acc["name"])
            self.accounts.append({"name": name, "uuid": offline_uuid(name), "type": "offline"})
            if not self.current:
                self.current = name
            self._save()
        return name

    def remove(self, name):
        with _lock:
            self.accounts = [a for a in self.accounts if a["name"] != name]
            if self.current == name:
                self.current = self.accounts[0]["name"] if self.accounts else ""
            self._save()

    def set_current(self, name):
        with _lock:
            if name in self.names():
                self.current = name
                self._save()

    def current_account(self):
        for a in self.accounts:
            if a["name"] == self.current:
                return a
        return None
