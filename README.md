# ZYCSSGXX 🐉

一款**纯离线**、**免费**、**免正版验证**的 Minecraft 启动器。
作者为自己和朋友打造，现已开源。

> 方块世界的小龙使者。在方块里造世界，在代码里造启动器。

---

## ✨ 功能亮点

### 🏠 核心启动
- **完全离线** — 不需要正版账号，注册即用
- **自动管理 Java** — 启动时自动下载适配版本的 OpenJDK
- **版本管理** — 原版、Fabric、Forge、NeoForge 全支持，一键下载/切换
- **自定义皮肤** — 皮肤绘制器 64×64 像素手绘，也能直接导入图片
- **联机可见皮肤** — 自动集成 CustomSkinLoader Mod，联机皮肤别人也能看到

### 🌐 三种联机模式
| 模式 | 说明 |
|------|------|
| 联机大厅 | 局域网多播自动发现房间，点击直连 |
| 官方服务器 | 一键下载 mojang 官方 server.jar，自带控制台，关正版验证 |
| 陶瓦联机 | 集成 EasyTier P2P 跨网联机工具 |

### 💬 内置聊天
- 只有 ZYCSSGXX 启动器账号之间能聊
- 加好友 → 一对一私聊（气泡界面）
- 离线消息自动补发
- 服务端开源，Render 免费部署

### 📦 模组管理
- Fabric / Forge / NeoForge 全支持
- 热门模组自动加载，支持搜索、一键安装
- Modrinth 源，安全可靠

### 🎨 高端白色主题
- 白底 + 翠绿 `#2fd582` + 金色 `#f2c23e` 点缀
- 所有文字黑色系，干净清爽
- 启动 5 秒闪屏（小龙图标 + Logo 并排）

### 🚀 管理员一键推送（作者专属）
- 内置管理员密钥，只有你能解锁推送面板
- 一键打包 → 上传 Release → 更新 manifest
- 朋友们的启动器自动静默更新

---

## 📥 下载安装

### 普通用户
1. 到 [Releases 页面](https://github.com/z-Y-c-2013/ZYCSSGXX/releases) 下载最新 zip
2. 解压后双击 `安装到桌面.bat`
3. 自动安装到 `%LOCALAPPDATA%\ZYCSSGXX` 并创建桌面快捷方式

### 从源码运行
```bash
# 需要 Python 3.11+
pip install -r requirements.txt
python main.py
```

### 打包成 exe
```bash
pyinstaller ZYCSSGXX.spec --noconfirm
# 产物在 dist/ZYCSSGXX.exe
```

---

## 🔧 目录结构

```
ZYCSSGXX/
├── main.py              # 入口
├── launcher/
│   ├── ui.py            # 图形界面（customtkinter）
│   ├── game.py          # 版本下载 + 启动游戏
│   ├── java_runtime.py  # Java 自动下载
│   ├── accounts.py      # 本地账号管理
│   ├── mods.py          # Modrinth API 模组搜索
│   ├── netgame.py       # 局域网发现 + 陶瓦联机
│   ├── server.py        # 官方服务器管理
│   ├── chat.py          # WebSocket 聊天客户端
│   ├── skin.py          # 皮肤替换（含联机自定义皮肤）
│   ├── push.py          # 管理员 Release 推送
│   ├── updater.py       # 自更新检查
│   └── config.py        # 全局配置
├── chat-server/         # 聊天服务器（FastAPI + SQLite）
├── assets/              # 图标、Logo 等资源
└── update/
    └── manifest.json    # 自更新清单
```

---

## 🖥️ 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11（64位） |
| Minecraft 版本 | 1.17+（自动下载 Java 17/21） |
| 内存 | 建议 ≥ 4 GB |
| 磁盘 | 首次启动需下载 Java + MC 版本 |

> Linux / macOS 理论支持（纯 Python），但未实机测试。

---

## 🔐 关于正版

本启动器**不绕过** Minecraft EULA。
- 如果你是正版玩家：可以在设置里填正版账号，一样能用
- 如果你没有正版：用离线模式也能玩（单人 / 局域网）
- 想进 Hypixel 等正版服务器？需要正版账号，这是 MC 官方要求

---

## 🚢 聊天服务器部署

聊天服务器基于 FastAPI，Render.com 免费部署：

```bash
# 克隆 chat-server/ 到 GitHub
# Render → New Web Service → 选仓库
# Build Command: pip install -r requirements.txt
# Start Command: uvicorn server:app --host 0.0.0.0 --port $PORT
```

拿到 URL（如 `wss://xxx.onrender.com`）后，在启动器设置页填"聊天服务器地址"即可。

---

## 🛠️ 技术栈

- **Python 3.13** + [customtkinter](https://github.com/TomSchimansky/CustomTkinter)（GUI）
- [minecraft-launcher-lib](https://github.com/jakubknee/minecraft-launcher-lib)（版本/下载逻辑）
- [Modrinth API](https://docs.modrinth.com/)（模组搜索）
- FastAPI + SQLite（聊天服务端）
- PyInstaller（打包）

---

## 📝 许可

本项目仅供学习和个人使用。Minecraft 是 Mojang Studios 的商标。

---

**作者：** z-Y-c-2013  
**GitHub：** [github.com/z-Y-c-2013/ZYCSSGXX](https://github.com/z-Y-c-2013/ZYCSSGXX)  
**版本：** v1.4.0
