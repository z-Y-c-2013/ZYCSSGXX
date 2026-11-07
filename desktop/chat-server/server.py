"""ZYCSSGXX 聊天后端服务器（带 SQLite 持久化）。

极简实现：FastAPI + WebSocket + SQLite，支持：
- 账号注册（通过 HTTP POST 校验唯一性，与启动器本地账号名同步）
- 好友添加（双方互加后成为好友）
- 一对一聊天（WebSocket 消息中转）
- 离线消息存储（SQLite 持久化，重启不丢）

部署：Render.com 免费层（https://render.com）
  1. 把 chat-server 目录推到 GitHub
  2. Render → New + Web Service → 选仓库 → Build Command: pip install -r requirements.txt
     Start Command: uvicorn server:app --host 0.0.0.0 --port $PORT
  3. 拿到 URL 后填到启动器设置 → 聊天服务器地址

本地运行：
  pip install -r requirements.txt
  python server.py
  然后启动器设置 → 聊天服务器地址填 ws://localhost:8000/ws
"""
import asyncio
import json
import os
import sqlite3
import time
import uuid as uuidlib
from contextlib import contextmanager
from typing import Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="ZYCSSGXX Chat Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.environ.get("CHAT_DB", "chat.db")

# ---- 数据库 ----
def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn

def _init_db():
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                name TEXT PRIMARY KEY,
                uuid TEXT,
                created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS friendships (
                a TEXT NOT NULL,
                b TEXT NOT NULL,
                created_at INTEGER,
                PRIMARY KEY (a, b)
            );
            CREATE TABLE IF NOT EXISTS friend_requests (
                from_name TEXT NOT NULL,
                to_name TEXT NOT NULL,
                time INTEGER,
                PRIMARY KEY (from_name, to_name)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_name TEXT NOT NULL,
                to_name TEXT NOT NULL,
                content TEXT NOT NULL,
                time INTEGER NOT NULL,
                delivered INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_name, delivered);
        """)
        conn.commit()
    finally:
        conn.close()

_init_db()

# ---- 活跃连接 ----
connections: Dict[str, WebSocket] = {}


# ---- 工具 ----
def _account_exists(name):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT name FROM accounts WHERE name=?", (name,)).fetchone()
        return row is not None
    finally:
        conn.close()

def _create_account(name, uuid=""):
    conn = _get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO accounts (name, uuid, created_at) VALUES (?,?,?)",
                     (name, uuid or str(uuidlib.uuid4()), int(time.time())))
        conn.commit()
    finally:
        conn.close()

def _get_friends(name):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT CASE WHEN a=? THEN b ELSE a END as friend FROM friendships WHERE a=? OR b=?",
            (name, name, name)).fetchall()
        return [r["friend"] for r in rows]
    finally:
        conn.close()

def _are_friends(a, b):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM friendships WHERE (a=? AND b=?) OR (a=? AND b=?)",
            (a, b, b, a)).fetchone()
        return row is not None
    finally:
        conn.close()

def _add_friend(a, b):
    conn = _get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO friendships (a, b, created_at) VALUES (?,?,?)",
                     (min(a, b), max(a, b), int(time.time())))
        conn.execute("DELETE FROM friend_requests WHERE (from_name=? AND to_name=?) OR (from_name=? AND to_name=?)",
                     (a, b, b, a))
        conn.commit()
    finally:
        conn.close()

def _get_requests(to):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT from_name, time FROM friend_requests WHERE to_name=? ORDER BY time DESC LIMIT 50",
            (to,)).fetchall()
        return [{"from": r["from_name"], "time": r["time"]} for r in rows]
    finally:
        conn.close()

def _add_request(from_, to):
    conn = _get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO friend_requests (from_name, to_name, time) VALUES (?,?,?)",
                     (from_, to, int(time.time())))
        conn.commit()
    finally:
        conn.close()

def _undelivered_messages(to):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT from_name, content, time FROM messages WHERE to_name=? AND delivered=0 ORDER BY time ASC LIMIT 200",
            (to,)).fetchall()
        conn.execute("UPDATE messages SET delivered=1 WHERE to_name=? AND delivered=0", (to,))
        conn.commit()
        return [{"from": r["from_name"], "content": r["content"], "time": r["time"]} for r in rows]
    finally:
        conn.close()

def _save_message(from_, to, content):
    conn = _get_conn()
    try:
        conn.execute("INSERT INTO messages (from_name, to_name, content, time, delivered) VALUES (?,?,?,?,0)",
                     (from_, to, content[:2000], int(time.time())))
        conn.commit()
    finally:
        conn.close()


# ---- FastAPI Models ----
class RegisterRequest(BaseModel):
    name: str
    uuid: str = ""


# ---- HTTP API ----
@app.post("/api/register")
async def register(req: RegisterRequest):
    name = req.name.strip().lower()
    if not name:
        raise HTTPException(400, "用户名不能为空")
    _create_account(name, req.uuid)
    return {"ok": True, "account": {"name": name}}


@app.get("/api/friend/add")
async def add_friend_get(self: str = "", to: str = ""):
    self, to = self.strip().lower(), to.strip().lower()
    if not self or not to:
        raise HTTPException(400, "参数缺失")
    if self == to:
        raise HTTPException(400, "不能加自己为好友")
    if not _account_exists(to):
        raise HTTPException(404, "对方账号不存在")
    if _are_friends(self, to):
        return {"ok": True, "message": "已经是好友了"}
    _add_request(self, to)
    return {"ok": True, "message": "好友请求已发送"}


@app.get("/api/friend/accept")
async def accept_friend(self: str = "", from_: str = ""):
    self, from_ = self.strip().lower(), from_.strip().lower()
    if not self or not from_:
        raise HTTPException(400, "参数缺失")
    if _account_exists(from_):
        _create_account(from_)
    _add_friend(self, from_)
    return {"ok": True, "friends": _get_friends(self)}


@app.get("/api/friends")
async def list_friends(self: str = ""):
    self = self.strip().lower()
    if self and not _account_exists(self):
        _create_account(self)
    result = []
    for fname in _get_friends(self):
        result.append({"name": fname, "online": fname in connections})
    return {"ok": True, "friends": result}


@app.get("/api/friend/requests")
async def list_requests(self: str = ""):
    self = self.strip().lower()
    return {"ok": True, "requests": _get_requests(self)}


@app.get("/api/search")
async def search_user(q: str = ""):
    q = q.strip().lower()
    if not q:
        return {"ok": True, "results": []}
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT name FROM accounts WHERE name LIKE ? LIMIT 20",
            ("%" + q + "%",)).fetchall()
        return {"ok": True, "results": [{"name": r["name"]} for r in rows]}
    finally:
        conn.close()


# ---- WebSocket ----
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user: str = ""):
    user = user.strip().lower()
    if not user:
        await websocket.close(code=4001, reason="no username")
        return
    _create_account(user)

    await websocket.accept()
    connections[user] = websocket

    try:
        # 登录确认
        await websocket.send_json({
            "type": "login_ok",
            "friends": _get_friends(user),
            "requests": _get_requests(user),
        })
        # 离线消息
        msgs = _undelivered_messages(user)
        if msgs:
            await websocket.send_json({"type": "offline_msgs", "messages": msgs})

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type", "")
            if mtype == "chat":
                target = msg.get("to", "").strip().lower()
                content = msg.get("content", "")
                if not target or not content:
                    continue
                payload = {
                    "type": "chat",
                    "from": user,
                    "to": target,
                    "content": content[:2000],
                    "time": int(time.time()),
                }
                # 存库
                _save_message(user, target, content)
                # 在线转发
                if target in connections:
                    await connections[target].send_json(payload)
            elif mtype == "ping":
                await websocket.send_json({"type": "pong"})
            elif mtype == "friend_add":
                to = msg.get("to", "").strip().lower()
                if to and to != user and _account_exists(to):
                    if not _are_friends(user, to) and not any(
                            r["from"] == user for r in _get_requests(to)):
                        _add_request(user, to)
                        if to in connections:
                            await connections[to].send_json({
                                "type": "friend_request", "from": user, "time": int(time.time())})
                        await websocket.send_json({"type": "friend_add_ok", "to": to})
            elif mtype == "friend_accept":
                from_ = msg.get("from", "").strip().lower()
                if from_ and _account_exists(from_):
                    if not _are_friends(user, from_):
                        _add_friend(user, from_)
                        if from_ in connections:
                            await connections[from_].send_json({"type": "friend_accept", "from": user})
                        await websocket.send_json({"type": "friend_accept_ok", "from": from_})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        connections.pop(user, None)


@app.get("/")
async def root():
    return {"ok": True, "service": "ZYCSSGXX Chat",
            "accounts": None, "online": len(connections),
            "db": DB_PATH}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
