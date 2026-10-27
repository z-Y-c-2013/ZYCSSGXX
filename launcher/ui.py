"""ZYCSSGXX 图形界面（customtkinter）"""
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from . import chat as chatlib
from . import config
from . import game
from . import java_runtime
from . import mods as mr
from . import netgame
from . import push as pushlib
from . import server
from . import skin as skinlib
from . import updater
from .accounts import AccountStore

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

FONT = "Microsoft YaHei UI"
TYPE_NAMES = {"release": "正式版", "snapshot": "快照",
              "old_beta": "远古Beta", "old_alpha": "远古Alpha"}
NAV_ITEMS = [("home", "主页"), ("download", "下载"), ("mods", "模组"),
             ("netgame", "联机"), ("chat", "聊天"), ("skin", "皮肤"),
             ("accounts", "账号"), ("settings", "设置")]

# ---- 配色体系（高端白色 + GXX 翠绿/金色点缀）----
C_BG = "#f3f4f7"
C_CARD = "#ffffff"
C_CARD2 = "#eef1f5"
C_BTN = "#e4e8ed"
C_BTN_HOVER = "#d5dae2"
C_ACCENT = "#2fd582"
C_ACCENT_HOVER = "#26b26c"
C_GOLD = "#f2c23e"
C_DANGER = "#e0524e"
C_DANGER_HOVER = "#c23c38"
C_SUB = "#8a97aa"
C_TEXT = "#1a1f2b"
C_TEXT2 = "#4a5262"
C_BORDER = "#dce1ea"


def base_version(vid):
    """从版本 id 提取原版游戏版本：fabric-loader-0.16.9-1.20.4 / 1.20.4-forge-47.3.0 → 1.20.4"""
    if vid.startswith("fabric-loader-"):
        return vid.rsplit("-", 1)[-1]
    return vid.split("-")[0]


def loader_of(vid):
    v = vid.lower()
    for name in ("fabric", "quilt", "neoforge", "forge"):
        if name in v:
            return name
    return "vanilla"


def format_downloads(n):
    if n >= 1000000:
        return "%.1fM" % (n / 1000000)
    if n >= 1000:
        return "%.1fK" % (n / 1000)
    return str(n)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ZYCSSGXX — 我的世界启动器")
        self.geometry("1120x700")
        self.minsize(960, 620)
        self.configure(fg_color=C_BG)
        self._apply_window_icon()

        self.settings = config.load_settings()
        self.store = AccountStore(config.ACCOUNTS_FILE)

        self.ui_queue = queue.Queue()
        self.busy = False
        self.server_proc = None
        self.proc = None
        self.all_versions = []
        self.dl_buttons = {}
        self.lan_scanner = netgame.LanRoomScanner()
        self.lan_scanner.start()
        self.lan_port = None
        self._pending_after_java = None
        self._worker_thread = None
        self.mod_hits = []
        self._room_keys = ()

        self._build_fonts()
        self._build_sidebar()
        self._build_pages()
        self._refresh_accounts_ui()
        self._refresh_home_versions()
        self.switch_page("home")
        self.after(80, self._process_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._load_versions_async)
        self.after(600, self._check_update_async, True)  # 启动时静默检查更新
        self.after(1000, self._poll_rooms)
        # 初始化聊天客户端
        self.chat_client = None
        self.chat_current_friend = None
        self.after(1500, self._chat_init)

    # ---------- 基础布局 ----------
    def _apply_window_icon(self):
        try:
            if os.path.isfile(config.ICON_FILE):
                self.iconbitmap(config.ICON_FILE)
        except Exception:
            pass

    def _build_fonts(self):
        self.f_title = ctk.CTkFont(FONT, 21, "bold")
        self.f_section = ctk.CTkFont(FONT, 16, "bold")
        self.f_text = ctk.CTkFont(FONT, 13)
        self.f_small = ctk.CTkFont(FONT, 11)
        self.f_button = ctk.CTkFont(FONT, 13, "bold")
        self.f_big = ctk.CTkFont(FONT, 17, "bold")

    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, width=190, corner_radius=0, fg_color="#ffffff")
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)

        logo_row = ctk.CTkFrame(bar, fg_color="transparent")
        logo_row.pack(fill="x", pady=(24, 0))
        self._logo_img = None
        if os.path.isfile(config.ICON_FILE):
            try:
                logo = Image.open(config.ICON_FILE).convert("RGBA").resize((72, 72))
                self._logo_img = ctk.CTkImage(light_image=logo, dark_image=logo,
                                              size=(36, 36))
                ctk.CTkLabel(logo_row, image=self._logo_img, text="").pack(
                    side="left", padx=(16, 8))
            except Exception:
                pass
        ctk.CTkLabel(logo_row, text="ZYCSSGXX", font=self.f_title,
                     text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(bar, text="我的世界启动器", font=self.f_small,
                     text_color=C_SUB).pack(pady=(4, 20))

        self.nav_buttons = {}
        for key, label in NAV_ITEMS:
            btn = ctk.CTkButton(
                bar, text="  " + label, font=self.f_text, height=42, corner_radius=10,
                anchor="w", fg_color="transparent",
                text_color="#5a6577",
                hover_color="#f0f3f7",
                command=lambda k=key: self.switch_page(k))
            btn.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = btn

        bottom = ctk.CTkFrame(bar, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=14, pady=12)
        self.lbl_status_side = ctk.CTkLabel(
            bottom, text="空闲", font=self.f_small, text_color=C_SUB, anchor="w")
        self.lbl_status_side.pack(fill="x")

    def _build_pages(self):
        self.container = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.container.pack(side="left", fill="both", expand=True)

        self.pages = {}
        for key, _ in NAV_ITEMS:
            page = ctk.CTkFrame(self.container, corner_radius=0, fg_color="transparent")
            self.pages[key] = page
        self._build_home(self.pages["home"])
        self._build_download(self.pages["download"])
        self._build_mods(self.pages["mods"])
        self._build_netgame(self.pages["netgame"])
        self._build_chat(self.pages["chat"])
        self._build_skin(self.pages["skin"])
        self._build_accounts(self.pages["accounts"])
        self._build_settings(self.pages["settings"])

    def switch_page(self, key):
        for k, page in self.pages.items():
            page.pack_forget()
            active = (k == key)
            self.nav_buttons[k].configure(
                fg_color="#e6f7ee" if active else "transparent",
                text_color=C_ACCENT if active else "#5a6577")
        self.pages[key].pack(fill="both", expand=True, padx=24, pady=18)
        if key == "home":
            self._refresh_home_versions()
        elif key == "mods":
            self._refresh_mods_versions()
        elif key == "chat":
            self._refresh_chat()
        elif key == "skin":
            self._refresh_skin_accounts()

    # ---------- 主页 ----------
    def _build_home(self, page):
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text="开始游戏", font=self.f_section).pack(anchor="w")

        card = ctk.CTkFrame(page, corner_radius=14, fg_color=C_CARD)
        card.pack(fill="x", pady=(12, 10))

        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=18, pady=(16, 6))
        ctk.CTkLabel(row1, text="当前账号", font=self.f_text).pack(side="left")
        self.menu_account = ctk.CTkOptionMenu(
            row1, values=["（未创建账号）"], width=220, font=self.f_text,
            command=self._on_account_menu)
        self.menu_account.pack(side="left", padx=(10, 24))

        ctk.CTkLabel(row1, text="游戏版本", font=self.f_text).pack(side="left")
        self.menu_version = ctk.CTkOptionMenu(
            row1, values=["（暂无已安装版本）"], width=240, font=self.f_text)
        self.menu_version.pack(side="left", padx=10)

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=18, pady=(6, 16))
        self.btn_play = ctk.CTkButton(
            row2, text="▶  开始游戏", font=self.f_big, height=46, width=200,
            corner_radius=10, fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
            command=self.on_play)
        self.btn_play.pack(side="left")
        self.btn_stop = ctk.CTkButton(
            row2, text="■  结束游戏", font=self.f_text, height=46, width=120,
            corner_radius=10, fg_color=C_DANGER, hover_color=C_DANGER_HOVER,
            state="disabled", command=self.on_stop)
        self.btn_stop.pack(side="left", padx=10)
        ctk.CTkButton(
            row2, text="打开游戏目录", font=self.f_text, height=46, width=130,
            fg_color=C_BTN, hover_color=C_BTN_HOVER,
            command=self.on_open_dir).pack(side="left")

        self.lbl_progress = ctk.CTkLabel(page, text="就绪", font=self.f_small,
                                         text_color=C_SUB, anchor="w")
        self.lbl_progress.pack(fill="x", pady=(4, 2))
        self.bar = ctk.CTkProgressBar(page, height=10, corner_radius=6,
                                      progress_color=C_ACCENT)
        self.bar.pack(fill="x")
        self.bar.set(0)

        # 更新提示横幅（发现新版本时才显示）
        self.update_info = None
        self.update_banner = ctk.CTkFrame(page, corner_radius=10, fg_color="#e6f7ee")
        self.lbl_update = ctk.CTkLabel(self.update_banner, text="",
                                       font=self.f_text, justify="left",
                                       text_color="#1a5c3a")
        self.lbl_update.pack(side="left", padx=14, pady=10)
        self.btn_update_close = ctk.CTkButton(
            self.update_banner, text="×", width=32, font=self.f_text,
            fg_color="transparent", hover_color=C_CARD2,
            text_color="#1a5c3a",
            command=self._hide_update_banner)
        self.btn_update_close.pack(side="right", padx=(0, 10))
        self.btn_update_now = ctk.CTkButton(
            self.update_banner, text="立即更新", width=100, font=self.f_button,
            fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER, command=self.on_apply_update)
        self.btn_update_now.pack(side="right")

        ctk.CTkLabel(page, text="游戏日志", font=self.f_text).pack(anchor="w", pady=(14, 4))
        self.log_box = ctk.CTkTextbox(page, font=ctk.CTkFont("Consolas", 12),
                                      wrap="none", state="disabled")
        self.log_box.pack(fill="both", expand=True)

    def _on_account_menu(self, choice):
        if choice in self.store.names():
            self.store.set_current(choice)

    def _refresh_accounts_ui(self):
        names = self.store.names()
        values = names if names else ["（未创建账号）"]
        self.menu_account.configure(values=values)
        self.menu_account.set(self.store.current if names else "（未创建账号）")
        self._render_account_rows()

    def _refresh_home_versions(self):
        installed = game.installed_versions(game.mc_dir(self.settings))
        ids = [v["id"] for v in installed]
        if ids:
            self.menu_version.configure(values=ids)
            if self.menu_version.get() not in ids:
                self.menu_version.set(ids[0])
        else:
            self.menu_version.configure(values=["（暂无已安装版本）"])
            self.menu_version.set("（暂无已安装版本）")
        if hasattr(self, "menu_ng_version"):
            values = ids if ids else ["（暂无已安装版本）"]
            self.menu_ng_version.configure(values=values)
            self.menu_ng_version.set(values[0])
        if hasattr(self, "menu_mods_version"):
            self._refresh_mods_versions()

    def on_open_dir(self):
        d = game.mc_dir(self.settings)
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    # ---------- 下载页 ----------
    def _build_download(self, page):
        ctk.CTkLabel(page, text="下载版本", font=self.f_section).pack(anchor="w")

        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(10, 6))
        self.entry_search = ctk.CTkEntry(bar, placeholder_text="搜索版本号，如 1.20.4",
                                         width=240, font=self.f_text)
        self.entry_search.pack(side="left")
        self.entry_search.bind("<KeyRelease>", lambda e: self._render_version_rows())

        self.var_release = ctk.BooleanVar(value=True)
        self.var_snapshot = ctk.BooleanVar(value=False)
        self.var_old = ctk.BooleanVar(value=False)
        for text, var in [("正式版", self.var_release), ("快照", self.var_snapshot),
                          ("远古版本", self.var_old)]:
            ctk.CTkCheckBox(bar, text=text, variable=var, font=self.f_text,
                            command=self._render_version_rows).pack(side="left", padx=(14, 0))
        self.seg_source = ctk.CTkSegmentedButton(
            bar, values=["原版", "Fabric", "Forge"], font=self.f_text,
            command=lambda v: self._render_version_rows())
        self.seg_source.set("原版")
        self.seg_source.pack(side="right", padx=(0, 8))
        ctk.CTkButton(bar, text="刷新列表", width=90, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self._load_versions_async).pack(side="right")

        self.lbl_version_info = ctk.CTkLabel(page, text="正在获取版本列表…",
                                             font=self.f_small, text_color=C_SUB, anchor="w")
        self.lbl_version_info.pack(fill="x")

        self.version_list = ctk.CTkScrollableFrame(page, corner_radius=10)
        self.version_list.pack(fill="both", expand=True, pady=(4, 0))

    def _load_versions_async(self):
        def worker():
            try:
                versions = game.available_versions(game.mc_dir(self.settings))
                self.ui_queue.put({"versions_loaded": versions})
            except Exception as exc:
                self.ui_queue.put({"versions_error": str(exc)})
        self._spawn_worker(worker)

    def _render_version_rows(self):
        for w in self.version_list.winfo_children():
            w.destroy()
        self.dl_buttons.clear()

        keyword = self.entry_search.get().strip().lower()
        source = self.seg_source.get() if hasattr(self, "seg_source") else "原版"
        if source == "原版":
            types = set()
            if self.var_release.get():
                types.add("release")
            if self.var_snapshot.get():
                types.add("snapshot")
            if self.var_old.get():
                types |= {"old_beta", "old_alpha"}
        else:
            types = {"release"}  # 加载器只基于正式版

        installed = game.installed_versions(game.mc_dir(self.settings))
        installed_ids = {v["id"] for v in installed}

        shown = 0
        for v in self.all_versions:
            if v["type"] not in types:
                continue
            if keyword and keyword not in v["id"].lower():
                continue
            if source == "原版":
                self._version_row(v, v["id"] in installed_ids)
            else:
                has_loader = any(loader_of(i) == source.lower()
                                 and base_version(i) == v["id"]
                                 for i in installed_ids)
                self._version_row(v, has_loader, source)
            shown += 1
            if shown >= 300:
                ctk.CTkLabel(self.version_list,
                             text="仅显示前 300 条，请使用搜索缩小范围",
                             font=self.f_small, text_color=C_SUB).pack(pady=8)
                break
        if source != "原版":
            ctk.CTkLabel(self.version_list,
                         text="安装 %s 会自动下载所需文件，并在主页出现可启动的 %s 版本"
                              % (source, source),
                         font=self.f_small, text_color=C_SUB).pack(pady=6)
        self.lbl_version_info.configure(
            text="共 %d 个版本，当前显示 %d 个" % (len(self.all_versions), shown))

    def _version_row(self, v, installed, source="原版"):
        row = ctk.CTkFrame(self.version_list, corner_radius=8,
                           fg_color=C_CARD2)
        row.pack(fill="x", padx=4, pady=3)
        ctk.CTkLabel(row, text=v["id"], font=self.f_text, width=180,
                     anchor="w").pack(side="left", padx=(12, 8), pady=6)
        ctk.CTkLabel(row, text=TYPE_NAMES.get(v["type"], v["type"]),
                     font=self.f_small, text_color=C_SUB,
                     width=80).pack(side="left")
        ctk.CTkLabel(row, text=v["releaseTime"], font=self.f_small,
                     text_color=C_SUB, width=100).pack(side="left", padx=8)

        status = ctk.CTkLabel(row, text="", font=self.f_small,
                              text_color=C_SUB, width=150)
        status.pack(side="right", padx=10)
        if installed:
            ctk.CTkLabel(row, text="已安装 ✓", font=self.f_small,
                         text_color=C_ACCENT, width=80).pack(side="right", padx=4)
        else:
            text = "下载" if source == "原版" else "安装" + source
            btn = ctk.CTkButton(row, text=text, width=100, font=self.f_text,
                                fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                                command=lambda vid=v["id"]: (
                                    self.on_install_loader(source.lower(), vid)
                                    if source != "原版" else self.on_download(vid)))
            btn.pack(side="right", padx=4)
            self.dl_buttons[v["id"]] = (btn, status)

    def on_install_loader(self, loader, base_id):
        """安装 Fabric / Forge"""
        if self._check_busy():
            messagebox.showwarning("提示", "有任务正在进行，请稍候")
            return
        if loader == "forge":
            required = java_runtime.required_java_major(base_id)
            self._resolve_java_or_ask(
                required,
                lambda j: self._loader_worker("forge", base_id, j),
                "Forge 安装器")
        else:
            self._loader_worker("fabric", base_id, None)

    def _loader_worker(self, loader, base_id, java_exe):
        self.busy = True
        self._set_busy_ui(True, "正在安装 %s %s …" % (loader, base_id))
        mc_dir = game.mc_dir(self.settings)

        def emit(event):
            self.ui_queue.put(dict(event))

        def worker():
            try:
                if loader == "fabric":
                    game.install_fabric(base_id, mc_dir, emit)
                else:
                    game.install_forge(base_id, mc_dir, emit, java_exe)
                self.ui_queue.put({"loader_done": (loader, base_id)})
            except Exception as exc:
                self.ui_queue.put({"error": "安装 %s 失败：%s" % (loader, exc)})
        self._spawn_worker(worker)

    def on_download(self, version_id):
        if self._check_busy():
            messagebox.showwarning("提示", "有任务正在进行，请稍候")
            return
        self.busy = True
        self._set_row_status(version_id, "准备下载…")

        mc_dir = game.mc_dir(self.settings)

        def emit(event):
            if "progress" in event and "max" in event:
                pass
            self.ui_queue.put(dict(event, row=version_id))

        def worker():
            try:
                game.install(version_id, mc_dir, emit)
                self.ui_queue.put({"install_done": version_id, "row": version_id})
            except Exception as exc:
                self.ui_queue.put({"error": "下载 %s 失败：%s" % (version_id, exc),
                                   "row": version_id})
        self._spawn_worker(worker)

    def _set_row_status(self, version_id, text):
        entry = self.dl_buttons.get(version_id)
        if entry:
            btn, status = entry
            status.configure(text=text)

    # ---------- 模组页 ----------
    def _build_mods(self, page):
        ctk.CTkLabel(page, text="模组下载（Modrinth）", font=self.f_section).pack(anchor="w")

        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(10, 4))
        ctk.CTkLabel(bar, text="目标版本", font=self.f_text).pack(side="left")
        self.menu_mods_version = ctk.CTkOptionMenu(
            bar, values=["（暂无已安装版本）"], width=250, font=self.f_text,
            command=lambda v: self._refresh_installed_mods())
        self.menu_mods_version.pack(side="left", padx=8)
        ctk.CTkButton(bar, text="刷新模组列表", width=100, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self._refresh_installed_mods).pack(side="left", padx=(0, 8))

        bar2 = ctk.CTkFrame(page, fg_color="transparent")
        bar2.pack(fill="x", pady=(4, 6))
        self.entry_mod_search = ctk.CTkEntry(
            bar2, placeholder_text="搜索模组，如：jei、sodium、创造模式...", width=320,
            font=self.f_text)
        self.entry_mod_search.pack(side="left")
        self.entry_mod_search.bind("<Return>", lambda e: self.on_search_mods())
        ctk.CTkButton(bar2, text="搜索", width=90, font=self.f_text,
                      command=self.on_search_mods).pack(side="left", padx=8)
        self.lbl_mods_target = ctk.CTkLabel(bar2, text="", font=self.f_small,
                                            text_color=C_SUB)
        self.lbl_mods_target.pack(side="left", padx=8)

        ctk.CTkLabel(page, text="搜索结果", font=self.f_text).pack(anchor="w", pady=(6, 2))
        self.mods_results = ctk.CTkScrollableFrame(page, height=220, corner_radius=10)
        self.mods_results.pack(fill="x")

        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", pady=(10, 2))
        ctk.CTkLabel(row, text="已安装模组（mods 文件夹）", font=self.f_text).pack(side="left")
        ctk.CTkLabel(page, text="提示：模组要与目标版本的加载器和游戏版本匹配，否则游戏无法启动",
                     font=self.f_small, text_color=C_SUB).pack(anchor="w")
        self.mods_installed = ctk.CTkScrollableFrame(page, height=150, corner_radius=10)
        self.mods_installed.pack(fill="both", expand=True, pady=(2, 0))
        self._refresh_mods_versions()

    def _refresh_mods_versions(self):
        ids = [v["id"] for v in game.installed_versions(game.mc_dir(self.settings))]
        values = ids if ids else ["（暂无已安装版本）"]
        self.menu_mods_version.configure(values=values)
        if ids:
            if self.menu_mods_version.get() not in ids:
                self.menu_mods_version.set(ids[0])
        else:
            self.menu_mods_version.set("（暂无已安装版本）")
        self._update_mods_target()
        self._refresh_installed_mods()
        # 自动加载热门模组（搜索框为空时才触发）
        if hasattr(self, "entry_mod_search") \
                and not self.entry_mod_search.get().strip() \
                and self._mods_target() is not None \
                and not self.mod_hits:
            self.on_search_mods()

    def _mods_target(self):
        """模组页当前选中的 (版本id, 加载器, 游戏版本)；无效返回 None"""
        vid = self.menu_mods_version.get()
        if vid.startswith("（"):
            return None
        loader = loader_of(vid)
        if loader == "vanilla":
            return None
        return vid, loader, base_version(vid)

    def _update_mods_target(self):
        t = self._mods_target()
        if t is None:
            self.lbl_mods_target.configure(
                text="请先在下载页安装 Fabric / Forge 版本才能装模组")
        else:
            self.lbl_mods_target.configure(text="加载器：%s　游戏版本：%s" % (t[1], t[2]))

    def on_search_mods(self):
        t = self._mods_target()
        if t is None:
            messagebox.showwarning("提示", "请先在「下载」页安装一个 Fabric / Forge 版本")
            self.switch_page("download")
            return
        _, loader, gv = t
        query = self.entry_mod_search.get().strip()
        self.lbl_mods_target.configure(text="正在搜索…")

        def worker():
            try:
                hits = mr.search(query, loader, gv, limit=20)
                self.ui_queue.put({"mods_search_done": hits})
            except Exception as exc:
                self.ui_queue.put({"error": "搜索模组失败（检查网络）：%s" % exc})
        self._spawn_worker(worker)

    def _render_mod_results(self, hits):
        self.mod_hits = hits
        for w in self.mods_results.winfo_children():
            w.destroy()
        t = self._mods_target()
        if not hits:
            ctk.CTkLabel(self.mods_results, text="没有结果", font=self.f_small,
                         text_color=C_SUB).pack(pady=12)
            return
        for h in hits:
            row = ctk.CTkFrame(self.mods_results, corner_radius=8,
                               fg_color=C_CARD2)
            row.pack(fill="x", padx=4, pady=3)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=10, pady=5)
            ctk.CTkLabel(info, text=h.get("title") or h.get("slug"),
                         font=self.f_text, anchor="w").pack(anchor="w")
            ctk.CTkLabel(info, text="↓ %s　%s" % (
                format_downloads(h.get("downloads", 0)),
                (h.get("description") or "")[:60]),
                         font=self.f_small, text_color=C_SUB,
                         anchor="w").pack(anchor="w")
            ctk.CTkButton(row, text="下载", width=80, font=self.f_text,
                          fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                          command=lambda pid=h["project_id"], title=h.get("title", ""):
                          self.on_download_mod(pid, title)).pack(
                side="right", padx=10)
        if t:
            self.lbl_mods_target.configure(text="加载器：%s　游戏版本：%s" % (t[1], t[2]))

    def on_download_mod(self, project_id, title):
        t = self._mods_target()
        if t is None:
            return
        if self.busy:
            messagebox.showwarning("提示", "有任务正在进行，请稍候")
            return
        _, loader, gv = t
        self.busy = True
        self.lbl_progress.configure(text="正在下载模组：%s …" % title)
        self.bar.set(0)
        mc_dir = game.mc_dir(self.settings)

        def progress(cur, total):
            self.ui_queue.put({"progress": cur, "max": total,
                               "status": "下载模组 %s：%.1f / %.1f MB"
                                         % (title, cur / 1e6, total / 1e6)})

        def worker():
            try:
                url, filename = mr.latest_file(project_id, loader, gv)
                if not url:
                    raise RuntimeError("该模组没有适配 %s %s 的文件" % (loader, gv))
                mr.download(url, filename, mc_dir, progress)
                self.ui_queue.put({"mod_downloaded": filename})
            except Exception as exc:
                self.ui_queue.put({"error": "下载模组失败：%s" % exc})
        self._spawn_worker(worker)

    def _refresh_installed_mods(self):
        if not hasattr(self, "mods_installed"):
            return
        for w in self.mods_installed.winfo_children():
            w.destroy()
        entries = mr.list_mods(game.mc_dir(self.settings))
        if not entries:
            ctk.CTkLabel(self.mods_installed, text="还没有模组",
                         font=self.f_small, text_color=C_SUB).pack(pady=10)
            return
        for name, size in entries:
            row = ctk.CTkFrame(self.mods_installed, corner_radius=8,
                               fg_color=C_CARD2)
            row.pack(fill="x", padx=4, pady=2)
            ctk.CTkLabel(row, text=name, font=self.f_small,
                         anchor="w").pack(side="left", padx=10, pady=4)
            ctk.CTkLabel(row, text="%d KB" % size, font=self.f_small,
                         text_color=C_SUB).pack(side="left", padx=8)
            ctk.CTkButton(row, text="删除", width=60, font=self.f_small,
                          fg_color=C_DANGER, hover_color=C_DANGER_HOVER,
                          command=lambda n=name: self.on_delete_mod(n)).pack(
                side="right", padx=8)

    def on_delete_mod(self, name):
        if not messagebox.askyesno("删除模组", "确定删除 %s？" % name):
            return
        mr.delete_mod(game.mc_dir(self.settings), name)
        self._refresh_installed_mods()

    # ---------- 联机页 ----------
    def _build_netgame(self, page):
        ctk.CTkLabel(page, text="联机", font=self.f_section).pack(anchor="w")

        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(bar, text="启动用的版本", font=self.f_text).pack(side="left")
        self.menu_ng_version = ctk.CTkOptionMenu(
            bar, values=["（暂无已安装版本）"], width=250, font=self.f_text)
        self.menu_ng_version.pack(side="left", padx=8)

        self.seg_net = ctk.CTkSegmentedButton(
            bar, values=["联机大厅", "创建服务器", "陶瓦联机"],
            font=self.f_text, selected_color=C_ACCENT,
            selected_hover_color=C_ACCENT_HOVER,
            unselected_color=C_BTN, unselected_hover_color=C_BTN_HOVER,
            command=self._on_net_tab)
        self.seg_net.set("联机大厅")
        self.seg_net.pack(side="right")

        self.net_tabs = {}
        for t in ("lan", "server", "taowa"):
            self.net_tabs[t] = ctk.CTkFrame(page, fg_color="transparent")
        self._build_tab_lan(self.net_tabs["lan"])
        self._build_tab_server(self.net_tabs["server"])
        self._build_tab_taowa(self.net_tabs["taowa"])
        self._show_net_tab("lan")

    def _show_net_tab(self, key):
        for k, f in self.net_tabs.items():
            f.pack_forget()
        self.net_tabs[key].pack(fill="both", expand=True, pady=(8, 0))
        if key == "server":
            self._refresh_server_menus()

    def _on_net_tab(self, value):
        self._show_net_tab({"联机大厅": "lan", "创建服务器": "server",
                            "陶瓦联机": "taowa"}[value])

    def _build_tab_lan(self, f):
        card1 = ctk.CTkFrame(f, corner_radius=14, fg_color=C_CARD)
        card1.pack(fill="both", expand=True, pady=(4, 4))
        ctk.CTkLabel(card1, text="发现的局域网房间（同一 WiFi / 路由器下自动出现）",
                     font=self.f_text).pack(anchor="w", padx=16, pady=(12, 4))
        self.net_rooms = ctk.CTkScrollableFrame(card1, corner_radius=8, height=160,
                                                fg_color=C_CARD2)
        self.net_rooms.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        card2 = ctk.CTkFrame(f, corner_radius=14, fg_color=C_CARD)
        card2.pack(fill="x", pady=4)
        row1 = ctk.CTkFrame(card2, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(12, 2))
        ctk.CTkLabel(row1, text="创建房间：游戏中 ESC → 「对局域网开放」",
                     font=self.f_text).pack(side="left")
        ctk.CTkButton(row1, text="复制房间地址", width=110, font=self.f_small,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_copy_room).pack(side="right")
        self.lbl_room = ctk.CTkLabel(card2, text="未检测到本机房间（开启后自动显示端口）",
                                     font=self.f_small, text_color=C_SUB,
                                     anchor="w", wraplength=860, justify="left")
        self.lbl_room.pack(fill="x", padx=16, pady=(0, 12))

        card3 = ctk.CTkFrame(f, corner_radius=14, fg_color=C_CARD)
        card3.pack(fill="x", pady=(4, 0))
        row2 = ctk.CTkFrame(card3, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(row2, text="直接连接", font=self.f_text).pack(side="left")
        self.entry_direct = ctk.CTkEntry(row2, width=280, font=self.f_text,
                                         placeholder_text="IP:端口（如 192.168.1.5:54321）")
        self.entry_direct.pack(side="left", padx=10)
        ctk.CTkButton(row2, text="连接并启动", width=110, font=self.f_text,
                      command=self.on_direct_connect).pack(side="left")
        ctk.CTkLabel(card3, text="跨网络联机：用「陶瓦联机」标签页，或让房主使用内网穿透工具获得地址后在这里直接连接。",
                     font=self.f_small, text_color=C_SUB,
                     anchor="w", wraplength=860, justify="left").pack(
            fill="x", padx=16, pady=(0, 12))

    # ---------- 创建服务器 ----------
    def _build_tab_server(self, f):
        carda = ctk.CTkFrame(f, corner_radius=14, fg_color=C_CARD)
        carda.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(carda, text="创建服务器（官方服务端，存档在你电脑上，朋友连接你开的服务器）",
                     font=self.f_text).pack(anchor="w", padx=16, pady=(12, 4))
        rowa = ctk.CTkFrame(carda, fg_color="transparent")
        rowa.pack(fill="x", padx=16)
        ctk.CTkLabel(rowa, text="版本", font=self.f_text).pack(side="left")
        self.menu_srv_new = ctk.CTkOptionMenu(
            rowa, values=["（列表加载中…）"], width=200, font=self.f_text)
        self.menu_srv_new.pack(side="left", padx=8)
        self.var_eula = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(rowa, text="我已阅读并同意 Minecraft EULA（Mojang 用户协议）",
                        font=self.f_small, variable=self.var_eula).pack(
            side="left", padx=8)
        ctk.CTkButton(rowa, text="创建并下载", width=110, font=self.f_text,
                      command=self.on_create_server).pack(side="left", padx=8)
        ctk.CTkLabel(carda, text="下载官方 server.jar（约 50MB），自动写好配置：关闭正版验证、"
                                 "端口 25565。创建后点「启动」，朋友通过下面两种方式加入。",
                     font=self.f_small, text_color=C_SUB,
                     anchor="w", wraplength=860, justify="left").pack(
            fill="x", padx=16, pady=(4, 12))

        cardb = ctk.CTkFrame(f, corner_radius=14, fg_color=C_CARD)
        cardb.pack(fill="both", expand=True, pady=4)
        rowb = ctk.CTkFrame(cardb, fg_color="transparent")
        rowb.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(rowb, text="我的服务器", font=self.f_text).pack(side="left")
        self.menu_srv_list = ctk.CTkOptionMenu(
            rowb, values=["（还没有服务器）"], width=220, font=self.f_text)
        self.menu_srv_list.pack(side="left", padx=8)
        self.btn_srv_start = ctk.CTkButton(rowb, text="启动", width=80,
                                           font=self.f_text, fg_color=C_ACCENT,
                                           hover_color=C_ACCENT_HOVER,
                                           command=self.on_start_server)
        self.btn_srv_start.pack(side="left", padx=(8, 0))
        self.btn_srv_stop = ctk.CTkButton(rowb, text="停止", width=80,
                                          font=self.f_text, fg_color=C_DANGER,
                                          hover_color=C_DANGER_HOVER,
                                          command=self.on_stop_server,
                                          state="disabled")
        self.btn_srv_stop.pack(side="left", padx=6)
        ctk.CTkButton(rowb, text="打开目录", width=90, font=self.f_small,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_open_server_dir).pack(side="left", padx=6)
        ctk.CTkButton(rowb, text="删除", width=60, font=self.f_small,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_delete_server).pack(side="left")
        self.lbl_srv_status = ctk.CTkLabel(cardb, text="服务器未运行",
                                           font=self.f_small, text_color=C_SUB)
        self.lbl_srv_status.pack(anchor="w", padx=16)

        self.srv_console = ctk.CTkTextbox(cardb, height=170, font=("Consolas", 12),
                                          fg_color="#1e2530", corner_radius=8,
                                          text_color="#d4dae3")
        self.srv_console.pack(fill="both", expand=True, padx=12, pady=(6, 4))
        self.srv_console.configure(state="disabled")
        rowc = ctk.CTkFrame(cardb, fg_color="transparent")
        rowc.pack(fill="x", padx=12, pady=(0, 12))
        self.entry_srv_cmd = ctk.CTkEntry(rowc, font=("Consolas", 12),
                                          placeholder_text="输入服务器命令（如 list / op 玩家名 / stop）")
        self.entry_srv_cmd.pack(side="left", fill="x", expand=True)
        self.entry_srv_cmd.bind("<Return>", lambda e: self.on_server_cmd())
        ctk.CTkButton(rowc, text="发送", width=70, font=self.f_small,
                      command=self.on_server_cmd).pack(side="left", padx=(8, 0))

    # ---------- 陶瓦联机 ----------
    def _build_tab_taowa(self, f):
        cardt = ctk.CTkFrame(f, corner_radius=14, fg_color=C_CARD)
        cardt.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(cardt, text="陶瓦联机（Terracotta）— 免费跨网络联机工具",
                     font=self.f_text).pack(anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(cardt, text="开源免费的 P2P 联机工具（基于 EasyTier），无需公网 IP 即可和朋友远程联机。"
                                 "ZYCSSGXX 负责把游戏开好，陶瓦负责把网络打通。",
                     font=self.f_small, text_color=C_SUB,
                     anchor="w", wraplength=860, justify="left").pack(
            anchor="w", padx=16)
        rowt = ctk.CTkFrame(cardt, fg_color="transparent")
        rowt.pack(fill="x", padx=16, pady=(8, 12))
        ctk.CTkButton(rowt, text="打开下载页", width=110, font=self.f_text,
                      command=self.on_taowa_web).pack(side="left")
        ctk.CTkButton(rowt, text="打开陶瓦程序", width=110, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_open_taowa).pack(side="left", padx=8)
        ctk.CTkButton(rowt, text="选择陶瓦程序位置", width=130, font=self.f_small,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_pick_taowa).pack(side="left")
        ctk.CTkLabel(cardt, text="", font=self.f_small, text_color=C_GOLD).pack(
            anchor="w", padx=16, pady=(0, 10))
        self.lbl_tw_path = ctk.CTkLabel(
            cardt, text="", font=self.f_small, text_color=C_GOLD,
            anchor="w", wraplength=860, justify="left")
        self.lbl_tw_path.pack(anchor="w", padx=16, pady=(0, 12))

        cardg = ctk.CTkFrame(f, corner_radius=14, fg_color=C_CARD)
        cardg.pack(fill="both", expand=True, pady=4)
        ctk.CTkLabel(cardg, text="联机教程", font=self.f_text,
                     text_color=C_GOLD).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(cardg, text="【房主】\n"
                                 "1. 先创建服务器（上一个标签）或单机 ESC → 对局域网开放\n"
                                 "2. 打开陶瓦联机 → 创建房间，地址填 127.0.0.1:25565"
                                 "（服务器）或游戏显示的房间端口（局域网房间）\n"
                                 "3. 把陶瓦生成的房间号 / 邀请码发给朋友\n\n"
                                 "【朋友】\n"
                                 "1. 下载并打开陶瓦联机 → 加入房主的房间\n"
                                 "2. 陶瓦会给你一个本地地址（形如 127.0.0.1:xxxxx）\n"
                                 "3. 回到 ZYCSSGXX → 联机大厅 → 直接连接，填入该地址即可进入",
                     font=self.f_text, anchor="nw", justify="left").pack(
            fill="both", expand=True, padx=20, pady=(0, 12))
        ctk.CTkLabel(cardg, text="注：陶瓦联机为第三方开源项目（Burning_TNT 开发），"
                                 "与 ZYCSSGXX 相互独立，使用问题请查阅其官方说明。",
                     font=self.f_small, text_color=C_SUB,
                     anchor="w", wraplength=860, justify="left").pack(
            anchor="w", padx=16, pady=(0, 12))
        self._refresh_taowa_path()

    def _refresh_taowa_path(self):
        p = (self.settings.get("terracotta_path") or "").strip()
        if p:
            self.lbl_tw_path.configure(text="已设置陶瓦程序：%s" % p)
        else:
            self.lbl_tw_path.configure(text="未设置陶瓦程序位置，请先下载并安装陶瓦联机")

    def on_taowa_web(self):
        import webbrowser
        webbrowser.open("https://www.easytier.cn/guide/installation_gui.html")
        self.lbl_progress.configure(text="已在浏览器打开陶瓦联机官方页面")

    def on_pick_taowa(self):
        p = filedialog.askopenfilename(
            title="选择陶瓦联机程序（exe）",
            filetypes=[("程序", "*.exe"), ("所有文件", "*.*")])
        if p:
            self.settings["terracotta_path"] = p
            config.save_settings(self.settings)
            self._refresh_taowa_path()

    def on_open_taowa(self):
        p = (self.settings.get("terracotta_path") or "").strip()
        if p and os.path.isfile(p):
            os.startfile(p)
            self.lbl_progress.configure(text="已启动陶瓦联机")
        else:
            messagebox.showinfo(
                "提示", "还没有设置陶瓦程序位置。\n\n先点「打开下载页」下载安装陶瓦联机，"
                        "再点「选择陶瓦程序位置」选中它的 exe 文件。")

    # ---------- 服务器操作 ----------
    def _refresh_server_menus(self):
        releases = [v["id"] for v in self.all_versions if v["type"] == "release"][:60]
        self.menu_srv_new.configure(values=releases or ["（列表加载中…）"])
        if releases:
            if self.menu_srv_new.get().startswith("（"):
                self.menu_srv_new.set(releases[0])
        servers = server.list_servers(config.APP_DIR)
        self.menu_srv_list.configure(values=servers or ["（还没有服务器）"])
        if servers:
            self.menu_srv_list.set(servers[0])

    def on_create_server(self):
        if self._check_busy():
            messagebox.showwarning("提示", "有任务正在进行，请稍候")
            return
        if not self.var_eula.get():
            messagebox.showwarning("提示", "创建服务器前需要勾选同意 Minecraft EULA")
            return
        vid = self.menu_srv_new.get()
        if vid.startswith("（"):
            messagebox.showwarning("提示", "版本列表还没加载好")
            return
        self.busy = True
        self.lbl_progress.configure(text="下载服务器端：%s" % vid)
        self.bar.set(0)

        def worker():
            try:
                def progress(cur, total):
                    self.ui_queue.put({"progress": cur, "max": total,
                                       "status": "下载服务器端：%.1f / %.1f MB"
                                                 % (cur / 1e6, total / 1e6)})
                server.create_server(vid, config.APP_DIR, progress)
                self.ui_queue.put({"server_created": vid})
            except Exception as exc:
                self.ui_queue.put({"error": "创建服务器失败：%s" % exc})
        self._spawn_worker(worker)

    def on_start_server(self):
        if self.server_proc and self.server_proc.poll() is None:
            messagebox.showwarning("提示", "服务器已在运行")
            return
        vid = self.menu_srv_list.get()
        if vid.startswith("（"):
            messagebox.showwarning("提示", "请先创建一个服务器")
            return
        required = java_runtime.required_java_major(base_version(vid))
        self._resolve_java_or_ask(
            required, lambda j: self._server_worker(vid, j), "服务器 %s" % vid)

    def _server_worker(self, vid, java_exe):
        self.busy = True
        self.lbl_progress.configure(text="正在启动服务器：%s" % vid)
        d = server.server_dir(config.APP_DIR, vid)

        def worker():
            try:
                proc = server.launch(d, java_exe,
                                     int(self.settings.get("memory_gb", 2)) + 1)
                self.server_proc = proc
                self.ui_queue.put({"server_started": vid})
                import threading
                def reader():
                    for line in proc.stdout:
                        self.ui_queue.put({"server_log": line.rstrip()})
                    self.ui_queue.put({"server_exit": proc.wait()})
                threading.Thread(target=reader, daemon=True).start()
            except Exception as exc:
                self.ui_queue.put({"error": "启动服务器失败：%s" % exc})
        self._spawn_worker(worker)

    def on_stop_server(self):
        if self.server_proc and self.server_proc.poll() is None:
            server.send_command(self.server_proc, "stop")
            self.lbl_srv_status.configure(text="正在关闭服务器…")
        else:
            messagebox.showinfo("提示", "服务器没有在运行")

    def on_server_cmd(self):
        cmd = self.entry_srv_cmd.get().strip()
        if not cmd:
            return
        if not (self.server_proc and self.server_proc.poll() is None):
            messagebox.showinfo("提示", "服务器没有在运行")
            return
        server.send_command(self.server_proc, cmd)
        self._srv_log("[ZYCSSGXX] > %s" % cmd)
        self.entry_srv_cmd.delete(0, "end")

    def on_open_server_dir(self):
        vid = self.menu_srv_list.get()
        if vid.startswith("（"):
            messagebox.showinfo("提示", "还没有服务器")
            return
        os.startfile(server.server_dir(config.APP_DIR, vid))

    def on_delete_server(self):
        vid = self.menu_srv_list.get()
        if vid.startswith("（"):
            return
        if self.server_proc and self.server_proc.poll() is None \
                and self.menu_srv_list.get() == vid:
            messagebox.showwarning("提示", "请先停止服务器再删除")
            return
        if not messagebox.askyesno("确认", "删除服务器 %s ？\n（世界存档会一并删除，无法恢复）" % vid):
            return
        shutil.rmtree(server.server_dir(config.APP_DIR, vid), ignore_errors=True)
        self._refresh_server_menus()
        self.lbl_progress.configure(text="服务器已删除：%s" % vid)

    def _srv_log(self, text):
        self.srv_console.configure(state="normal")
        self.srv_console.insert("end", text + "\n")
        self.srv_console.see("end")
        self.srv_console.configure(state="disabled")

    def _poll_rooms(self):
        rooms = self.lan_scanner.snapshot()
        keys = tuple((r["ip"], r["port"]) for r in rooms)
        if keys != self._room_keys:
            self._room_keys = keys
            for w in self.net_rooms.winfo_children():
                w.destroy()
            if not rooms:
                ctk.CTkLabel(self.net_rooms,
                             text="暂无房间。朋友开启「对局域网开放」后会自动出现在这里",
                             font=self.f_small, text_color=C_SUB).pack(pady=14)
            for r in rooms:
                row = ctk.CTkFrame(self.net_rooms, corner_radius=8,
                                   fg_color=C_CARD2)
                row.pack(fill="x", padx=4, pady=3)
                ctk.CTkLabel(row, text=r["motd"], font=self.f_text, width=260,
                             anchor="w").pack(side="left", padx=12, pady=5)
                ctk.CTkLabel(row, text="%s:%d" % (r["ip"], r["port"]),
                             font=self.f_small, text_color=C_SUB).pack(
                    side="left", padx=8)
                ctk.CTkButton(row, text="加入", width=80, font=self.f_text,
                              fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                              command=lambda ip=r["ip"], p=r["port"]:
                              self.on_join_room(ip, p)).pack(side="right", padx=10)
        self.after(1000, self._poll_rooms)

    def _ng_version(self):
        vid = self.menu_ng_version.get()
        return None if vid.startswith("（") else vid

    def _launch_with_server(self, version, server):
        account = self.store.current_account()
        if not account:
            messagebox.showwarning("提示", "请先在「账号」页创建账号")
            self.switch_page("accounts")
            return
        required = java_runtime.required_java_major(base_version(version))
        self._resolve_java_or_ask(
            required,
            lambda j: self._start_game_worker(version, account, j, server),
            "联机")

    def on_join_room(self, ip, port):
        version = self._ng_version()
        if not version:
            messagebox.showwarning("提示", "请先在「下载」页安装一个游戏版本")
            self.switch_page("download")
            return
        self._launch_with_server(version, {"ip": ip, "port": port})

    def on_direct_connect(self):
        text = self.entry_direct.get().strip()
        if not text:
            messagebox.showwarning("提示", "请输入 IP:端口")
            return
        host, _, port = text.rpartition(":")
        if not host:
            host, port = text, ""
        if not port.isdigit():
            port = "25565"
        version = self._ng_version()
        if not version:
            messagebox.showwarning("提示", "请先在「下载」页安装一个游戏版本")
            self.switch_page("download")
            return
        self._launch_with_server(version, {"ip": host, "port": int(port)})

    def _sniff_lan(self, log_line):
        port = netgame.parse_lan_port(log_line)
        if port and port != self.lan_port:
            self.lan_port = port
            self._update_room_label()

    def _update_room_label(self):
        ips = ", ".join(netgame.local_ips()) or "（未检测到内网 IP）"
        if self.lan_port:
            self.lbl_room.configure(
                text="已检测到你的房间端口：%d　房间地址：%s:%d　（把这个地址发给同一网络下的朋友）"
                     % (self.lan_port, ips.split(", ")[0], self.lan_port))
        else:
            self.lbl_room.configure(text="未检测到本机房间（开启后自动显示端口）")

    def on_copy_room(self):
        ips = netgame.local_ips()
        if self.lan_port and ips:
            text = "%s:%d" % (ips[0], self.lan_port)
            self.clipboard_clear()
            self.clipboard_append(text)
            self.lbl_room.configure(text="已复制房间地址：%s" % text)
        else:
            messagebox.showinfo("提示", "先在游戏中开启「对局域网开放」，检测到端口后才能复制")

    # ---------- 聊天页 ----------
    def _build_chat(self, page):
        ctk.CTkLabel(page, text="聊天", font=self.f_section).pack(anchor="w")

        # 服务器状态条
        self.lbl_chat_status = ctk.CTkLabel(page, text="未连接（在设置页填聊天服务器地址）",
                                             font=self.f_small, text_color=C_SUB)
        self.lbl_chat_status.pack(anchor="w")

        # 主体：左侧好友列表 + 右侧聊天窗口
        body = ctk.CTkFrame(page, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=(8, 0))

        # 左侧面板
        left = ctk.CTkFrame(body, corner_radius=12, fg_color=C_CARD)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        left.configure(width=280)

        row1 = ctk.CTkFrame(left, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(14, 4))
        ctk.CTkLabel(row1, text="好友", font=self.f_text).pack(side="left")
        ctk.CTkButton(row1, text="＋", width=32, height=28, font=self.f_button,
                      fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                      command=self._on_add_friend).pack(side="right")

        self.chat_search = ctk.CTkEntry(
            left, placeholder_text="搜索账号 / 添加好友", font=self.f_text,
            height=34)
        self.chat_search.pack(fill="x", padx=14, pady=(0, 6))
        self.chat_search.bind("<Return>", lambda e: self._on_add_friend())

        self.chat_friends = ctk.CTkScrollableFrame(left, corner_radius=8,
                                                    fg_color=C_CARD2, height=380)
        self.chat_friends.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        # 待处理好友请求
        self.chat_requests_frame = ctk.CTkFrame(left, corner_radius=8, fg_color=C_CARD2)
        self.chat_requests_frame.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkLabel(self.chat_requests_frame, text="好友请求", font=self.f_small,
                     text_color=C_GOLD).pack(anchor="w", padx=10, pady=(8, 2))
        self.chat_requests_list = ctk.CTkScrollableFrame(self.chat_requests_frame,
                                                          height=100, fg_color="transparent")
        self.chat_requests_list.pack(fill="x", padx=10, pady=(0, 10))

        # 右侧聊天区域
        right = ctk.CTkFrame(body, corner_radius=12, fg_color=C_CARD)
        right.pack(side="left", fill="both", expand=True)

        self.chat_title = ctk.CTkLabel(right, text="选择一个好友开始聊天", font=self.f_text,
                                        text_color=C_SUB)
        self.chat_title.pack(anchor="w", padx=16, pady=(14, 4))

        self.chat_history = ctk.CTkScrollableFrame(right, corner_radius=8,
                                                    fg_color="#f0f3f7")
        self.chat_history.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        row_in = ctk.CTkFrame(right, fg_color="transparent")
        row_in.pack(fill="x", padx=12, pady=(0, 12))
        self.chat_input = ctk.CTkEntry(row_in, placeholder_text="输入消息…", font=self.f_text,
                                        height=34)
        self.chat_input.pack(side="left", fill="x", expand=True)
        self.chat_input.bind("<Return>", lambda e: self._on_send_chat())
        self.btn_chat_send = ctk.CTkButton(row_in, text="发送", width=80, height=34,
                                            font=self.f_text,
                                            fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                                            command=self._on_send_chat)
        self.btn_chat_send.pack(side="left", padx=(8, 0))

    def _chat_init(self):
        """启动聊天客户端（有账号 + 有服务器地址才启动）"""
        if self.chat_client and self.chat_client.running:
            return
        self_name = ""
        acc = self.store.current_account()
        if acc:
            self_name = acc["name"]
        if not self_name:
            self.lbl_chat_status.configure(text="请先在「账号」页创建账号，再填聊天服务器地址")
            return
        server = (self.settings.get("chat_server") or "").strip()
        if not server:
            self.lbl_chat_status.configure(text="未配置聊天服务器（设置页 → 聊天服务器地址）")
            return
        # 先注册
        try:
            chatlib.ChatClient(self.settings, self_name, self.ui_queue).register_account(
                self_name, acc.get("uuid", ""))
        except Exception:
            pass
        self.chat_client = chatlib.ChatClient(self.settings, self_name, self.ui_queue)
        self.chat_client.start()

    def _refresh_chat(self):
        if not self.chat_client:
            self._chat_init()
        self._render_friends()
        self._render_requests()
        self._render_history()

    def _render_friends(self):
        if not hasattr(self, "chat_friends"):
            return
        for w in self.chat_friends.winfo_children():
            w.destroy()
        if not self.chat_client:
            ctk.CTkLabel(self.chat_friends, text="未连接", font=self.f_small,
                         text_color=C_SUB).pack(pady=10)
            return
        friends = self.chat_client.friends() or self.chat_client.get_friends()
        if not friends:
            ctk.CTkLabel(self.chat_friends, text="还没有好友\n点右上角＋添加好友",
                         font=self.f_small, text_color=C_SUB,
                         justify="center").pack(pady=20)
            return
        for f in friends:
            fname = f.get("name") if isinstance(f, dict) else f
            online = f.get("online", False) if isinstance(f, dict) else False
            row = ctk.CTkFrame(self.chat_friends, corner_radius=6,
                                fg_color=C_CARD)
            row.pack(fill="x", padx=4, pady=2)
            dot_color = C_ACCENT if online else C_SUB
            ctk.CTkLabel(row, text="●", font=self.f_small,
                         text_color=dot_color, width=18).pack(side="left", padx=(10, 4))
            ctk.CTkLabel(row, text=fname, font=self.f_text,
                         anchor="w").pack(side="left", padx=(0, 8), pady=6)
            btn = ctk.CTkButton(row, text="聊", width=36, height=26, font=self.f_small,
                                fg_color=C_BTN, hover_color=C_BTN_HOVER,
                                command=lambda n=fname: self._select_friend(n))
            btn.pack(side="right", padx=8, pady=4)

    def _render_requests(self):
        if not hasattr(self, "chat_requests_list"):
            return
        for w in self.chat_requests_list.winfo_children():
            w.destroy()
        if not self.chat_client:
            return
        reqs = self.chat_client.get_requests() or []
        if not reqs:
            self.chat_requests_frame.pack_forget()
            return
        self.chat_requests_frame.pack(fill="x", padx=14, pady=(0, 14))
        for r in reqs:
            from_name = r.get("from", "") if isinstance(r, dict) else r
            row = ctk.CTkFrame(self.chat_requests_list, corner_radius=4, fg_color=C_CARD)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=from_name, font=self.f_small,
                         anchor="w").pack(side="left", padx=8, pady=4)
            ctk.CTkButton(row, text="接受", width=50, height=24, font=("Microsoft YaHei UI", 10),
                          fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                          command=lambda n=from_name: self._accept_request(n)).pack(
                side="right", padx=4)

    def _render_history(self):
        if not hasattr(self, "chat_history"):
            return
        for w in self.chat_history.winfo_children():
            w.destroy()
        if not self.chat_current_friend:
            self.chat_title.configure(text="选择一个好友开始聊天")
            return
        self.chat_title.configure(text="与 %s 聊天" % self.chat_current_friend)
        if not self.chat_client:
            return
        msgs = self.chat_client.get_history(self.chat_current_friend)
        if not msgs:
            ctk.CTkLabel(self.chat_history, text="还没有消息，发条问候吧～",
                         font=self.f_small, text_color=C_SUB).pack(pady=20)
            return
        for m in msgs:
            self._render_msg(m)

    def _render_msg(self, msg):
        """渲染单条消息气泡"""
        if not hasattr(self, "chat_history"):
            return
        from_self = msg.get("from", "") == (
            self.chat_client.username if self.chat_client else "")
        text = msg.get("content", "")
        bubble = ctk.CTkFrame(self.chat_history, corner_radius=10,
                              fg_color=C_ACCENT if from_self else "#ffffff")
        bubble.pack(fill="x", padx=8, pady=3,
                    anchor="e" if from_self else "w")
        ctk.CTkLabel(bubble, text=text, font=self.f_text,
                     text_color="#ffffff" if from_self else C_TEXT,
                     wraplength=380, justify="left").pack(padx=12, pady=6)

    def _select_friend(self, name):
        self.chat_current_friend = name
        self._render_history()

    def _on_send_chat(self):
        if not self.chat_client:
            messagebox.showwarning("提示", "聊天未连接，请检查服务器设置")
            return
        if not self.chat_current_friend:
            messagebox.showwarning("提示", "请先选择一个好友")
            return
        content = self.chat_input.get().strip()
        if not content:
            return
        ok = self.chat_client.send_chat(self.chat_current_friend, content)
        if ok:
            self.chat_input.delete(0, "end")
            self._render_history()

    def _on_add_friend(self):
        if not self.chat_client:
            messagebox.showwarning("提示", "聊天未连接")
            return
        name = self.chat_search.get().strip()
        if not name:
            return
        self.chat_client.add_friend(name)
        self.lbl_chat_status.configure(text="好友请求已发送给 %s" % name)

    def _accept_request(self, from_name):
        if self.chat_client:
            self.chat_client.accept_friend(from_name)
            self._render_requests()
            self._render_friends()

    # ---------- 聊天事件处理 ----------
    def _handle_chat_event(self, ev):
        if "chat_connected" in ev:
            connected = ev["chat_connected"]
            if connected:
                self.lbl_chat_status.configure(text="✅ 已连接到聊天服务器")
            else:
                self.lbl_chat_status.configure(text="❌ 连接断开，正在重连…")
        elif "chat_error" in ev:
            self.lbl_chat_status.configure(text="⚠ 聊天错误：" + str(ev["chat_error"]))
        elif "chat_login_ok" in ev:
            self._render_friends()
            self._render_requests()
            self.lbl_chat_status.configure(text="✅ 已连接到聊天服务器")
        elif "chat_message" in ev:
            msg = ev["chat_message"]
            # 如果是当前聊天对象，直接追加
            if self.chat_current_friend == msg.get("from"):
                self._render_history()
        elif "chat_sent" in ev:
            if self.chat_current_friend == ev["chat_sent"].get("to"):
                self._render_history()
        elif "chat_friend_request" in ev:
            self._render_requests()
        elif "chat_friend_accept" in ev:
            self._render_friends()
        elif "chat_friend_add_ok" in ev or "chat_friend_accept_ok" in ev:
            self._render_friends()

    # ---------- 皮肤页 ----------
    def _build_skin(self, page):
        ctk.CTkLabel(page, text="皮肤", font=self.f_section).pack(anchor="w")

        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(bar, text="账号", font=self.f_text).pack(side="left")
        self.menu_skin_account = ctk.CTkOptionMenu(
            bar, values=["（暂无账号）"], width=200, font=self.f_text,
            command=lambda v: self._refresh_skin_preview())
        self.menu_skin_account.pack(side="left", padx=8)

        body = ctk.CTkFrame(page, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=4)
        left = ctk.CTkFrame(body, corner_radius=12)
        left.pack(side="left", fill="y", padx=(0, 12))
        self.lbl_skin_preview = ctk.CTkLabel(left, text="")
        self.lbl_skin_preview.pack(padx=20, pady=(18, 8))
        ctk.CTkButton(left, text="选择皮肤图片（64x64 PNG）", width=210,
                      font=self.f_text, command=self.on_import_skin).pack(
            padx=20, pady=4)
        ctk.CTkButton(left, text="清除皮肤（恢复默认）", width=210,
                      font=self.f_text, fg_color=C_BTN,
                      hover_color=C_BTN_HOVER,
                      command=self.on_clear_skin).pack(padx=20, pady=4)
        self.lbl_skin_state = ctk.CTkLabel(left, text="", font=self.f_small,
                                           text_color=C_SUB)
        self.lbl_skin_state.pack(pady=(2, 16))

        right = ctk.CTkFrame(body, corner_radius=12)
        right.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(right, text="皮肤绘制器", font=self.f_text).pack(
            anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(right, text="像画像素画一样画自己的皮肤：支持画笔 / 橡皮 / 油漆桶 / "
                                 "取色 / 撤销，自动带部位模板。",
                     font=self.f_small, text_color=C_SUB,
                     anchor="w", wraplength=560, justify="left").pack(
            anchor="w", padx=16)
        row = ctk.CTkFrame(right, fg_color="transparent")
        row.pack(anchor="w", padx=16, pady=10)
        ctk.CTkButton(row, text="打开绘制器", width=140, height=40,
                      font=self.f_button, command=self.on_open_skin_editor).pack(
            side="left")
        ctk.CTkButton(row, text="用经典模板新建", width=140, height=40,
                      font=self.f_button, fg_color=C_BTN,
                      hover_color=C_BTN_HOVER,
                      command=lambda: self.on_open_skin_editor(
                          skinlib.classic_template())).pack(side="left", padx=8)

        ctk.CTkLabel(right, text="联机让对方也看到你的皮肤", font=self.f_text).pack(
            anchor="w", padx=16, pady=(8, 2))
        ctk.CTkLabel(right, text="需要 Fabric/Forge 版本安装 CustomSkinLoader 模组，"
                                 "双方都装了才能互相看到。",
                     font=self.f_small, text_color=C_SUB,
                     anchor="w", wraplength=560, justify="left").pack(
            anchor="w", padx=16)
        ctk.CTkButton(right, text="一键安装 CustomSkinLoader", width=200,
                      font=self.f_text, command=self.on_install_csl).pack(
            anchor="w", padx=16, pady=(6, 14))
        ctk.CTkLabel(page, text="说明：不用模组时，皮肤会在每次启动游戏前自动写入版本文件，"
                                "单机自己可见；重装版本后下次启动会自动重新应用。",
                     font=self.f_small, text_color=C_SUB,
                     anchor="w", wraplength=900, justify="left").pack(
        anchor="w", pady=(8, 0))
        self._refresh_skin_accounts()

    def _skin_account(self):
        name = self.menu_skin_account.get()
        return None if name.startswith("（") else name

    def _refresh_skin_accounts(self):
        names = self.store.names()
        if not hasattr(self, "menu_skin_account"):
            return
        values = names if names else ["（暂无账号）"]
        self.menu_skin_account.configure(values=values)
        acc = self.store.current_account()
        cur = acc["name"] if acc else None
        self.menu_skin_account.set(cur if cur in names else values[0])
        self._refresh_skin_preview()

    def _refresh_skin_preview(self):
        name = self._skin_account()
        img = None
        if name:
            p = skinlib.account_skin_path(config.APP_DIR, name)
            if os.path.isfile(p):
                img = skinlib.validate_skin(p)
        self.lbl_skin_state.configure(
            text="当前账号：%s　自定义皮肤：%s" % (name or "无", "已启用" if img else "未设置"))
        if img is None:
            img = skinlib.classic_template()
            img.putalpha(90)
        prev = skinlib.render_front(img, zoom=6)
        self._skin_preview_img = ctk.CTkImage(
            light_image=prev, dark_image=prev, size=prev.size)
        self.lbl_skin_preview.configure(image=self._skin_preview_img)

    def on_import_skin(self):
        name = self._skin_account()
        if not name:
            messagebox.showwarning("提示", "请先在「账号」页创建账号")
            self.switch_page("accounts")
            return
        path = filedialog.askopenfilename(
            title="选择皮肤（64x64 PNG）", filetypes=[("PNG 图片", "*.png")])
        if not path:
            return
        img = skinlib.validate_skin(path)
        if img is None:
            messagebox.showerror("出错了", "不是有效的皮肤文件（需要 64x64 或 64x32 的 PNG）")
            return
        img.save(skinlib.account_skin_path(config.APP_DIR, name))
        self._refresh_skin_preview()
        self.lbl_progress.configure(text="皮肤已设置到账号 %s，下次启动游戏自动生效" % name)

    def on_clear_skin(self):
        name = self._skin_account()
        if not name:
            return
        p = skinlib.account_skin_path(config.APP_DIR, name)
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
        skinlib.clear_skin_patches(game.mc_dir(self.settings))
        self._refresh_skin_preview()
        self.lbl_progress.configure(text="皮肤已清除（已安装的版本下次启动不再套用皮肤）")

    def on_open_skin_editor(self, base_img=None):
        name = self._skin_account()
        if not name:
            messagebox.showwarning("提示", "请先在「账号」页创建账号")
            self.switch_page("accounts")
            return
        if base_img is None:
            p = skinlib.account_skin_path(config.APP_DIR, name)
            base_img = skinlib.validate_skin(p) if os.path.isfile(p) \
                else skinlib.classic_template()
        win = SkinEditor(self, base_img)
        win.after(250, win.grab_set)

    def on_install_csl(self):
        if self._check_busy():
            messagebox.showwarning("提示", "有任务正在进行，请稍候")
            return
        t = self._mods_target()
        if t is None:
            messagebox.showwarning("提示", "请先在「下载」页安装一个 Fabric / Forge 版本")
            self.switch_page("download")
            return
        _, loader, gv = t
        self.busy = True
        self.lbl_progress.configure(text="正在下载 CustomSkinLoader…")
        self.bar.set(0)
        mc_dir = game.mc_dir(self.settings)

        def progress(cur, total):
            self.ui_queue.put({"progress": cur, "max": total,
                               "status": "下载 CustomSkinLoader：%.1f / %.1f MB"
                                         % (cur / 1e6, total / 1e6)})

        def worker():
            try:
                url, filename = mr.latest_file("customskinloader", loader, gv)
                if not url:
                    raise RuntimeError("Modrinth 上没有适配 %s %s 的版本" % (loader, gv))
                mr.download(url, filename, mc_dir, progress)
                self.ui_queue.put({"mod_downloaded": filename})
            except Exception as exc:
                self.ui_queue.put({"error": "安装 CustomSkinLoader 失败：%s\n"
                                            "也可以在模组页搜索手动安装" % exc})
        self._spawn_worker(worker)

    # ---------- 账号页 ----------
    def _build_accounts(self, page):
        ctk.CTkLabel(page, text="账号管理", font=self.f_section).pack(anchor="w")
        ctk.CTkLabel(page, text="离线模式登录。账号名唯一，不允许添加重复账号。",
                     font=self.f_small, text_color=C_SUB).pack(anchor="w", pady=(2, 10))

        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x")
        self.entry_name = ctk.CTkEntry(bar, placeholder_text="输入用户名（1-16 位）",
                                       width=260, font=self.f_text)
        self.entry_name.pack(side="left")
        self.entry_name.bind("<Return>", lambda e: self.on_add_account())
        ctk.CTkButton(bar, text="＋ 添加账号", width=120, font=self.f_text,
                      command=self.on_add_account).pack(side="left", padx=10)

        self.account_list = ctk.CTkScrollableFrame(page, corner_radius=10)
        self.account_list.pack(fill="both", expand=True, pady=(12, 0))

    def _render_account_rows(self):
        if not hasattr(self, "account_list"):
            return
        for w in self.account_list.winfo_children():
            w.destroy()
        if not self.store.names():
            ctk.CTkLabel(self.account_list, text="还没有账号，先添加一个吧",
                         font=self.f_small, text_color=C_SUB).pack(pady=20)
            return
        for acc in self.store.accounts:
            row = ctk.CTkFrame(self.account_list, corner_radius=8,
                               fg_color=C_CARD2)
            row.pack(fill="x", padx=4, pady=3)
            current = (acc["name"] == self.store.current)
            ctk.CTkLabel(row, text=("● " if current else "○ ") + acc["name"],
                         font=self.f_text, width=180, anchor="w").pack(
                side="left", padx=12, pady=6)
            ctk.CTkLabel(row, text=acc["uuid"], font=self.f_small,
                         text_color=C_SUB).pack(side="left", padx=8)
            if current:
                ctk.CTkLabel(row, text="当前使用", font=self.f_small,
                             text_color=C_ACCENT).pack(side="right", padx=14)
            else:
                ctk.CTkButton(row, text="设为当前", width=90, font=self.f_small,
                              fg_color=C_BTN,
                              hover_color=C_BTN_HOVER,
                              command=lambda n=acc["name"]: self.on_use_account(n)
                              ).pack(side="right", padx=4)
            ctk.CTkButton(row, text="删除", width=70, font=self.f_small,
                          fg_color=C_DANGER, hover_color=C_DANGER_HOVER,
                          command=lambda n=acc["name"]: self.on_del_account(n)
                          ).pack(side="right", padx=4)

    def on_add_account(self):
        try:
            name = self.store.add(self.entry_name.get())
            self.entry_name.delete(0, "end")
            self._refresh_accounts_ui()
            self._log("[launcher] 账号「%s」已添加\n" % name)
        except ValueError as exc:
            messagebox.showerror("添加失败", str(exc))

    def on_use_account(self, name):
        self.store.set_current(name)
        self._refresh_accounts_ui()

    def on_del_account(self, name):
        if not messagebox.askyesno("删除账号", "确定删除账号「%s」？" % name):
            return
        self.store.remove(name)
        self._refresh_accounts_ui()

    # ---------- 设置页 ----------
    def _build_settings(self, page):
        ctk.CTkLabel(page, text="设置", font=self.f_section).pack(anchor="w")

        card1 = ctk.CTkFrame(page, corner_radius=14, fg_color=C_CARD)
        card1.pack(fill="x", pady=(12, 8))
        ctk.CTkLabel(card1, text="游戏目录", font=self.f_text).pack(
            anchor="w", padx=18, pady=(14, 4))
        row = ctk.CTkFrame(card1, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(0, 14))
        self.entry_dir = ctk.CTkEntry(row, font=self.f_text)
        self.entry_dir.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="浏览…", width=80, font=self.f_text,
                      command=self.on_browse_dir).pack(side="left", padx=(8, 0))
        ctk.CTkButton(row, text="恢复默认", width=90, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=lambda: self.entry_dir.delete(0, "end")).pack(
            side="left", padx=(8, 0))
        self.var_isolation = ctk.BooleanVar(
            value=bool(self.settings.get("version_isolation")))
        ctk.CTkSwitch(card1, text="版本隔离（每个版本独立的存档 / 模组 / 配置目录）",
                      variable=self.var_isolation, font=self.f_text).pack(
            anchor="w", padx=18, pady=(0, 14))

        card2 = ctk.CTkFrame(page, corner_radius=14, fg_color=C_CARD)
        card2.pack(fill="x", pady=8)
        self.lbl_mem = ctk.CTkLabel(card2, text="", font=self.f_text)
        self.lbl_mem.pack(anchor="w", padx=18, pady=(14, 4))
        self.slider_mem = ctk.CTkSlider(card2, from_=1, to=16, number_of_steps=15,
                                        width=320, command=self._on_mem_slide)
        self.slider_mem.pack(anchor="w", padx=18, pady=(0, 4))
        ctk.CTkLabel(card2, text="内存过大会导致游戏启动失败，建议 2-8 GB",
                     font=self.f_small, text_color=C_SUB).pack(
            anchor="w", padx=18, pady=(0, 14))

        card3 = ctk.CTkFrame(page, corner_radius=14, fg_color=C_CARD)
        card3.pack(fill="x", pady=8)
        ctk.CTkLabel(card3, text="Java 路径（留空自动检测）", font=self.f_text).pack(
            anchor="w", padx=18, pady=(14, 4))
        row3 = ctk.CTkFrame(card3, fg_color="transparent")
        row3.pack(fill="x", padx=18)
        self.entry_java = ctk.CTkEntry(row3, font=self.f_text)
        self.entry_java.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row3, text="浏览…", width=80, font=self.f_text,
                      command=self.on_browse_java).pack(side="left", padx=(8, 0))
        ctk.CTkButton(row3, text="检测本机 Java", width=120, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_detect_java).pack(side="left", padx=(8, 0))

        row4 = ctk.CTkFrame(card3, fg_color="transparent")
        row4.pack(fill="x", padx=18, pady=(8, 14))
        ctk.CTkLabel(row4, text="本机没有 Java？自动下载：", font=self.f_text).pack(side="left")
        self.menu_java_major = ctk.CTkOptionMenu(
            row4, values=["8", "16", "17", "21"], width=80, font=self.f_text)
        self.menu_java_major.set("21")
        self.menu_java_major.pack(side="left", padx=8)
        ctk.CTkButton(row4, text="下载 Java", width=110, font=self.f_text,
                      command=self.on_download_java).pack(side="left")

        card4 = ctk.CTkFrame(page, corner_radius=14, fg_color=C_CARD)
        card4.pack(fill="x", pady=8)
        row5 = ctk.CTkFrame(card4, fg_color="transparent")
        row5.pack(fill="x", padx=18, pady=(14, 4))
        ctk.CTkLabel(row5, text="关于与更新　当前版本 v%s" % config.APP_VERSION,
                     font=self.f_text).pack(side="left")
        ctk.CTkButton(row5, text="检查更新", width=100, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=lambda: self._check_update_async(False)).pack(side="right")
        row6 = ctk.CTkFrame(card4, fg_color="transparent")
        row6.pack(fill="x", padx=18)
        self.entry_update_url = ctk.CTkEntry(
            row6, placeholder_text="更新源 manifest.json 地址（可托管在 GitHub/Gitee 等）",
            font=self.f_text)
        self.entry_update_url.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(card4, text="留空则不检查更新。发现新版本后会在主页显示一键更新。",
                     font=self.f_small, text_color=C_SUB).pack(
            anchor="w", padx=18, pady=(4, 14))

        # 聊天服务器设置
        card4b = ctk.CTkFrame(page, corner_radius=14, fg_color=C_CARD)
        card4b.pack(fill="x", pady=8)
        ctk.CTkLabel(card4b, text="聊天服务器（ZYCSSGXX 内置聊天，只有本启动器账号之间可用）",
                     font=self.f_text).pack(anchor="w", padx=18, pady=(14, 4))
        row_chat = ctk.CTkFrame(card4b, fg_color="transparent")
        row_chat.pack(fill="x", padx=18)
        self.entry_chat_server = ctk.CTkEntry(
            row_chat, placeholder_text="ws://xxx.onrender.com 或 wss://...（留空=不使用聊天）",
            font=self.f_text)
        self.entry_chat_server.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row_chat, text="测试连接", width=100, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self._test_chat_server).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(card4b, text="部署说明：把 chat-server 目录推到 GitHub，Render.com 免费层即可。"
                                 "好友之间都需要填同一个服务器地址才能互相聊天。",
                     font=self.f_small, text_color=C_SUB,
                     anchor="w", wraplength=860, justify="left").pack(
            anchor="w", padx=18, pady=(4, 14))

        # 管理员推送面板（只有作者本人解锁）
        card5 = ctk.CTkFrame(page, corner_radius=14, fg_color=C_CARD)
        card5.pack(fill="x", pady=8)
        ctk.CTkLabel(card5, text="🔑 管理员推送（仅作者）", font=self.f_text,
                     text_color=C_GOLD).pack(anchor="w", padx=18, pady=(14, 4))
        ctk.CTkLabel(card5, text="填好管理员 token 和仓库信息后，可一键打包推送启动器更新。"
                                 "其他人没有 token，看不到推送按钮。",
                     font=self.f_small, text_color=C_SUB,
                     anchor="w", wraplength=860, justify="left").pack(
            anchor="w", padx=18)

        row_adm1 = ctk.CTkFrame(card5, fg_color="transparent")
        row_adm1.pack(fill="x", padx=18, pady=(8, 2))
        ctk.CTkLabel(row_adm1, text="管理员 Token", font=self.f_text,
                     width=110).pack(side="left")
        self.entry_admin_token = ctk.CTkEntry(
            row_adm1, placeholder_text="GitHub/Gitee Personal Access Token",
            font=self.f_text, show="●")
        self.entry_admin_token.pack(side="left", fill="x", expand=True)

        row_adm2 = ctk.CTkFrame(card5, fg_color="transparent")
        row_adm2.pack(fill="x", padx=18, pady=(2, 2))
        ctk.CTkLabel(row_adm2, text="推送平台", font=self.f_text,
                     width=110).pack(side="left")
        self.seg_push_provider = ctk.CTkSegmentedButton(
            row_adm2, values=["GitHub", "Gitee"], font=self.f_text,
            selected_color=C_ACCENT, selected_hover_color=C_ACCENT_HOVER,
            unselected_color=C_BTN, unselected_hover_color=C_BTN_HOVER)
        self.seg_push_provider.set("GitHub")
        self.seg_push_provider.pack(side="left")
        ctk.CTkLabel(row_adm2, text="仓库 (owner/repo)", font=self.f_text).pack(side="left", padx=(16, 4))
        self.entry_push_repo = ctk.CTkEntry(row_adm2, width=240, font=self.f_text,
                                             placeholder_text="如 zycssg/launcher")
        self.entry_push_repo.pack(side="left")

        row_adm3 = ctk.CTkFrame(card5, fg_color="transparent")
        row_adm3.pack(fill="x", padx=18, pady=(2, 2))
        ctk.CTkLabel(row_adm3, text="Manifest 地址", font=self.f_text,
                     width=110).pack(side="left")
        self.entry_push_url = ctk.CTkEntry(
            row_adm3, placeholder_text="manifest.json 的 Raw 地址（供客户端检查更新用）",
            font=self.f_text)
        self.entry_push_url.pack(side="left", fill="x", expand=True)

        row_adm4 = ctk.CTkFrame(card5, fg_color="transparent")
        row_adm4.pack(fill="x", padx=18, pady=(8, 14))
        ctk.CTkLabel(row_adm4, text="更新版本号", font=self.f_text).pack(side="left")
        self.entry_push_version = ctk.CTkEntry(row_adm4, width=120, font=self.f_text,
                                                placeholder_text="如 1.4.1")
        self.entry_push_version.insert(0, config.APP_VERSION)
        self.entry_push_version.pack(side="left", padx=8)
        ctk.CTkLabel(row_adm4, text="更新说明", font=self.f_text).pack(side="left", padx=(8, 4))
        self.entry_push_notes = ctk.CTkEntry(row_adm4, width=320, font=self.f_text,
                                              placeholder_text="本次更新内容")
        self.entry_push_notes.pack(side="left")
        self.btn_do_push = ctk.CTkButton(
            row_adm4, text="🚀 一键推送", width=140, font=self.f_button,
            fg_color=C_GOLD, hover_color="#e5b235",
            command=self.on_do_push)
        self.btn_do_push.pack(side="left", padx=12)

        ctk.CTkButton(page, text="保存设置", width=140, height=40,
                      font=self.f_button, command=self.on_save_settings).pack(
            anchor="w", pady=(14, 0))
        self._load_settings_to_ui()

    def _load_settings_to_ui(self):
        self.entry_dir.insert(0, self.settings.get("game_dir", ""))
        self.entry_java.insert(0, self.settings.get("java_path", ""))
        self.entry_update_url.insert(0, self.settings.get("update_manifest_url", ""))
        self.slider_mem.set(self.settings.get("memory_gb", 2))
        self._on_mem_slide(self.settings.get("memory_gb", 2))
        # 聊天服务器
        self.entry_chat_server.insert(0, self.settings.get("chat_server", ""))
        # 管理员字段
        self.entry_admin_token.insert(0, self.settings.get("admin_token", ""))
        self.seg_push_provider.set((self.settings.get("push_provider") or "github").capitalize())
        self.entry_push_repo.insert(0, self.settings.get("push_repo", ""))
        self.entry_push_url.insert(0, self.settings.get("push_url", ""))

    def _update_push_button(self):
        """根据 token 状态决定推送按钮是否启用"""
        if not hasattr(self, "btn_do_push"):
            return
        has_token = bool((self.entry_admin_token.get() or "").strip())
        self.btn_do_push.configure(state="normal" if has_token else "disabled")

    def _on_mem_slide(self, value):
        self.lbl_mem.configure(text="游戏内存：%.0f GB" % value)

    def on_browse_dir(self):
        d = filedialog.askdirectory(title="选择游戏目录（.minecraft）")
        if d:
            self.entry_dir.delete(0, "end")
            self.entry_dir.insert(0, d)

    def on_browse_java(self):
        f = filedialog.askopenfilename(title="选择 java.exe",
                                       filetypes=[("java.exe", "*.exe")])
        if f:
            self.entry_java.delete(0, "end")
            self.entry_java.insert(0, f)

    def on_detect_java(self):
        javas = java_runtime.find_javas()
        if not javas:
            messagebox.showinfo("检测结果", "未在本机找到 Java。\n可以在下方自动下载。")
            return
        lines = []
        for path in javas:
            major = java_runtime.java_major(path)
            lines.append("Java %d：%s" % (major, path) if major else path)
        messagebox.showinfo("检测结果（%d 个）" % len(javas), "\n".join(lines))

    def on_download_java(self):
        if self._check_busy():
            messagebox.showwarning("提示", "有任务正在进行，请稍候")
            return
        major = int(self.menu_java_major.get())
        self.busy = True
        self.lbl_progress.configure(text="正在下载 Java %d …" % major)
        self.bar.set(0)

        def progress(cur, total):
            self.ui_queue.put({"progress": cur, "max": total,
                               "status": "下载 Java %d：%.1f / %.1f MB"
                                         % (major, cur / 1e6, total / 1e6)})

        def worker():
            try:
                path = java_runtime.download_java(major, config.JAVA_DIR, progress)
                self.ui_queue.put({"java_done": path, "status": "Java %d 安装完成" % major})
            except Exception as exc:
                self.ui_queue.put({"error": "下载 Java 失败：%s" % exc})
        self._spawn_worker(worker)

    def on_save_settings(self):
        self.settings["game_dir"] = self.entry_dir.get().strip()
        self.settings["java_path"] = self.entry_java.get().strip()
        self.settings["update_manifest_url"] = self.entry_update_url.get().strip()
        self.settings["memory_gb"] = int(self.slider_mem.get())
        self.settings["version_isolation"] = bool(self.var_isolation.get())
        # 聊天服务器
        self.settings["chat_server"] = self.entry_chat_server.get().strip()
        # 管理员推送字段
        self.settings["admin_token"] = self.entry_admin_token.get().strip()
        self.settings["push_provider"] = self.seg_push_provider.get().lower()
        self.settings["push_repo"] = self.entry_push_repo.get().strip()
        self.settings["push_url"] = self.entry_push_url.get().strip()
        config.save_settings(self.settings)
        self._refresh_home_versions()
        self._log("[launcher] 设置已保存\n")
        self.lbl_progress.configure(text="设置已保存")
        # 重启聊天客户端（如果服务器地址变了）
        if self.chat_client:
            self.chat_client.stop()
            self.chat_client = None
        self._chat_init()

    def _test_chat_server(self):
        """测试聊天服务器连通性"""
        server = self.entry_chat_server.get().strip()
        if not server:
            messagebox.showinfo("测试", "聊天服务器地址为空")
            return
        # 用 HTTP API ping 一下
        base = server
        if base.startswith("ws://"):
            base = "http://" + base[5:]
        elif base.startswith("wss://"):
            base = "https://" + base[6:]
        base = base.rstrip("/")
        try:
            import urllib.request
            req = urllib.request.Request(base + "/", headers={"User-Agent": "ZYCSSGXX-test"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read().decode()
            messagebox.showinfo("连接成功", "聊天服务器响应正常 ✅\n\n" + data[:200])
        except Exception as exc:
            messagebox.showerror("连接失败", "无法连接：\n%s\n\n请检查地址是否正确，服务器是否已启动" % exc)

    def on_do_push(self):
        """一键推送启动器更新"""
        token = self.entry_admin_token.get().strip()
        if not token:
            messagebox.showwarning("提示", "请先填写管理员 Token")
            return
        repo = self.entry_push_repo.get().strip()
        push_url = self.entry_push_url.get().strip()
        version = self.entry_push_version.get().strip()
        notes = self.entry_push_notes.get().strip() or "更新"
        provider = self.seg_push_provider.get().lower()

        if not repo:
            messagebox.showwarning("提示", "请填写仓库地址（owner/repo）")
            return
        if not push_url:
            messagebox.showwarning("提示", "请填写 Manifest 地址")
            return
        if not version:
            messagebox.showwarning("提示", "请填写更新版本号")
            return

        # 确认
        if not messagebox.askyesno(
                "确认推送",
                "准备推送 ZYCSSGXX v%s\n"
                "仓库：%s（%s）\n"
                "\n这会打包启动器源码并上传到 Release，同时更新 manifest.json。\n"
                "确定要推送吗？" % (version, repo, provider.upper())):
            return

        self.busy = True
        self.btn_do_push.configure(state="disabled")
        self.lbl_progress.configure(text="正在打包并推送 v%s …" % version)

        def worker():
            try:
                # 临时把 token 注入 settings（已经保存过但这里用当前 UI 值）
                tmp = dict(self.settings)
                tmp["admin_token"] = token
                tmp["push_provider"] = provider
                tmp["push_repo"] = repo
                tmp["push_url"] = push_url
                ok, msg, url = pushlib.do_push(tmp, version, notes)
                self.ui_queue.put({"push_done": (ok, msg, url)})
            except Exception as exc:
                self.ui_queue.put({"push_error": str(exc)})
        self._spawn_worker(worker)

    # ---------- 管理员推送事件 ----------
    def _handle_push_event(self, ev):
        if "push_done" in ev:
            ok, msg, url = ev["push_done"]
            self.busy = False
            self._update_push_button()
            if ok:
                self.lbl_progress.configure(text=msg)
                messagebox.showinfo("推送完成", msg + "\n\n下载地址：\n" + url)
            else:
                self.lbl_progress.configure(text=msg)
                messagebox.showerror("推送失败", msg)
        if "push_error" in ev:
            self.busy = False
            self._update_push_button()
            self.lbl_progress.configure(text="推送出错：" + ev["push_error"])
            messagebox.showerror("推送出错", ev["push_error"])

    # ---------- 自更新 ----------
    def _check_update_async(self, silent=False):
        if getattr(sys, "frozen", False):
            if not silent:
                self.lbl_progress.configure(text="单文件版暂不支持自更新，请向作者获取新版本")
            return
        url = (self.settings.get("update_manifest_url") or "").strip()
        if not url:
            if not silent:
                self.lbl_progress.configure(text="未配置更新源（设置页 → 关于与更新）")
            return

        def worker():
            try:
                info = updater.check_update(url)
                self.ui_queue.put({"update_found": info} if info
                                  else {"update_none": silent})
            except Exception as exc:
                self.ui_queue.put({"update_error": str(exc), "silent": silent})
        self._spawn_worker(worker)

    def on_apply_update(self):
        if self._check_busy() or not self.update_info:
            return
        info = self.update_info
        self.busy = True
        self._set_busy_ui(True, "正在下载更新 v%s …" % info["version"])
        self.bar.set(0)

        def progress(cur, total):
            self.ui_queue.put({"progress": cur, "max": total,
                               "status": "下载更新 v%s：%.1f / %.1f MB"
                                         % (info["version"], cur / 1e6, total / 1e6)})

        def worker():
            try:
                zip_path = updater.download_update(info["url"], progress)
                updater.apply_update(zip_path)
                self.ui_queue.put({"update_applied": info["version"]})
            except Exception as exc:
                self.ui_queue.put({"error": "更新失败：%s" % exc})
        self._spawn_worker(worker)

    def _show_update_banner(self, info):
        self.update_info = info
        text = "发现新版本 v%s" % info["version"]
        if info.get("notes"):
            text += "　" + info["notes"]
        self.lbl_update.configure(text=text)
        if not self.update_banner.winfo_ismapped():
            self.update_banner.pack(fill="x", pady=(0, 10), before=self.lbl_progress)

    def _hide_update_banner(self):
        self.update_banner.pack_forget()
        self.update_info = None

    # ---------- 启动游戏 ----------
    def _resolve_java(self, required):
        custom = self.settings.get("java_path", "")
        if custom and os.path.isfile(custom):
            if java_runtime.java_major(custom) >= required:
                return custom
        return java_runtime.pick_java(required, custom)

    def on_play(self):
        if self._check_busy():
            messagebox.showwarning("提示", "有任务正在进行，请稍候")
            return
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("提示", "游戏已在运行中，可用「结束游戏」关闭后重试")
            return
        account = self.store.current_account()
        if not account:
            messagebox.showwarning("提示", "请先在「账号」页创建账号")
            self.switch_page("accounts")
            return
        version = self.menu_version.get()
        if version.startswith("（"):
            messagebox.showwarning("提示", "请先在「下载」页安装一个游戏版本")
            self.switch_page("download")
            return
        required = java_runtime.required_java_major(base_version(version))
        self._resolve_java_or_ask(
            required,
            lambda j: self._start_game_worker(version, account, j),
            "游戏 %s" % version)

    def _resolve_java_or_ask(self, required, then, what):
        """解析可用 Java；没有则引导自动下载，完成后继续 then(java_path)"""
        java_exe = self._resolve_java(required)
        if java_exe:
            then(java_exe)
            return
        if not messagebox.askyesno(
                "缺少 Java",
                "运行%s需要 Java %d，本机未检测到。\n是否自动下载（约 40-200 MB）？"
                % (what, required)):
            return
        self.busy = True
        self._pending_after_java = then
        self.lbl_progress.configure(text="正在下载 Java %d …" % required)
        self.bar.set(0)

        def progress(cur, total):
            self.ui_queue.put({"progress": cur, "max": total,
                               "status": "下载 Java %d：%.1f / %.1f MB"
                                         % (required, cur / 1e6, total / 1e6)})

        def worker():
            try:
                path = java_runtime.download_java(required, config.JAVA_DIR, progress)
                self.ui_queue.put({"java_ready": path})
            except Exception as exc:
                self._pending_after_java = None
                self.ui_queue.put({"error": "下载 Java 失败：%s" % exc})
        self._spawn_worker(worker)

    def _start_game_worker(self, version, account, java_exe, server=None):
        self.busy = True
        self._set_busy_ui(True, "准备启动 %s …" % version)
        mc_dir = game.mc_dir(self.settings)

        def emit(event):
            self.ui_queue.put(dict(event))

        def worker():
            try:
                if not game.is_installed(version, mc_dir):
                    emit({"status": "安装游戏文件：%s" % version})
                    game.install(version, mc_dir, emit)
                skin_path = skinlib.account_skin_path(config.APP_DIR, account["name"])
                if os.path.isfile(skin_path):
                    emit({"status": "应用自定义皮肤…"})
                    skinlib.apply_skin(skin_path, mc_dir, version)
                cmd = game.build_launch_command(version, mc_dir, account,
                                                self.settings, java_exe, server)
                emit({"status": "正在启动游戏…"})
                proc = game.launch(cmd, mc_dir)
                emit({"launched": version})
                for line in iter(proc.stdout.readline, b""):
                    emit({"log": line.decode("utf-8", "replace")})
                code = proc.wait()
                emit({"game_exit": code})
            except Exception as exc:
                emit({"error": "启动失败：%s" % exc})
        self._spawn_worker(worker)

    def on_stop(self):
        if self.proc and self.proc.poll() is None:
            if messagebox.askyesno("结束游戏", "确定强制结束游戏进程？"):
                self.proc.kill()
                self._log("[launcher] 已强制结束游戏\n")

    # ---------- 事件队列 / 日志 ----------
    def _process_queue(self):
        try:
            while True:
                event = self.ui_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.after(80, self._process_queue)

    def _handle_event(self, ev):
        # 先处理推送相关事件（独立分支）
        if "push_done" in ev or "push_error" in ev:
            self._handle_push_event(ev)
            return
        # 聊天相关事件
        chat_keys = ("chat_connected", "chat_error", "chat_login_ok",
                     "chat_message", "chat_sent", "chat_friend_request",
                     "chat_friend_accept", "chat_friend_add_ok", "chat_friend_accept_ok",
                     "chat_offline", "chat_status")
        if any(k in ev for k in chat_keys):
            self._handle_chat_event(ev)
            return
        row = ev.get("row")
        if "status" in ev:
            self.lbl_progress.configure(text=ev["status"])
            self.lbl_status_side.configure(text=ev["status"])
        if "max" in ev:
            self.bar.configure(maximum=max(1, ev["max"]))
        if "progress" in ev:
            self.bar.set(min(1.0, ev["progress"] / max(1, ev.get("max", 1))))
        if "log" in ev:
            self._log(ev["log"])
            self._sniff_lan(ev["log"])
        if row and ("progress" in ev or "status" in ev):
            self._set_row_status(row, ev.get("status", ""))
        if "error" in ev:
            self.busy = False
            self._set_busy_ui(False, ev["error"])
            if row:
                self._set_row_status(row, "失败")
            messagebox.showerror("出错了", ev["error"])
        if "versions_loaded" in ev:
            self.all_versions = ev["versions_loaded"]
            self._render_version_rows()
        if "versions_error" in ev:
            self.lbl_version_info.configure(
                text="获取版本列表失败，请检查网络后点「刷新列表」（%s）" % ev["versions_error"])
        if "update_found" in ev:
            self._show_update_banner(ev["update_found"])
        if "update_none" in ev:
            if not ev["update_none"]:
                self.lbl_progress.configure(
                    text="当前已是最新版本 v%s" % config.APP_VERSION)
        if "update_error" in ev:
            if not ev.get("silent"):
                self.lbl_progress.configure(text="检查更新失败：%s" % ev["update_error"])
        if "update_applied" in ev:
            self.busy = False
            self.bar.set(1)
            self._set_busy_ui(False, "更新完成")
            self._hide_update_banner()
            if messagebox.askyesno("更新完成",
                                   "已更新到 v%s，是否立即重启启动器？"
                                   % ev["update_applied"]):
                updater.restart()
                self.destroy()
        if "install_done" in ev:
            self.busy = False
            self._set_busy_ui(False, "%s 安装完成" % ev["install_done"])
            self._refresh_home_versions()
            self._render_version_rows()
        if "java_done" in ev:
            self.busy = False
            self.bar.set(1)
            self.entry_java.delete(0, "end")
            self.entry_java.insert(0, ev["java_done"])
            self.settings["java_path"] = ev["java_done"]
            config.save_settings(self.settings)
            self._log("[launcher] Java 安装于 %s\n" % ev["java_done"])
            self.lbl_progress.configure(text="Java 安装完成，已写入设置")
        if "java_ready" in ev:
            self.busy = False
            self.bar.set(1)
            java_path = ev["java_ready"]
            self.settings["java_path"] = java_path
            config.save_settings(self.settings)
            self._log("[launcher] Java 安装于 %s\n" % java_path)
            then, self._pending_after_java = self._pending_after_java, None
            if then:
                then(java_path)
        if "loader_done" in ev:
            loader, base_id = ev["loader_done"]
            self.busy = False
            self._set_busy_ui(False, "%s %s 安装完成" % (loader, base_id))
            self._refresh_home_versions()
            self._render_version_rows()
        if "mods_search_done" in ev:
            self._render_mod_results(ev["mods_search_done"])
        if "mod_downloaded" in ev:
            self.busy = False
            self.bar.set(1)
            self.lbl_progress.configure(text="模组已安装：%s" % ev["mod_downloaded"])
            self._refresh_installed_mods()
        if "server_created" in ev:
            self.busy = False
            self.bar.set(1)
            self._set_busy_ui(False, "服务器创建完成：%s" % ev["server_created"])
            self._refresh_server_menus()
        if "server_started" in ev:
            self.busy = False
            self.btn_srv_start.configure(state="disabled")
            self.btn_srv_stop.configure(state="normal")
            ips = netgame.local_ips() or ["?"]
            self.lbl_srv_status.configure(
                text="服务器运行中　同网络直连地址：%s:25565　跨网络联机：用「陶瓦联机」标签页"
                     % ips[0])
            self.lbl_progress.configure(text="服务器已启动")
        if "server_log" in ev:
            self._srv_log(ev["server_log"])
        if "server_exit" in ev:
            self.btn_srv_start.configure(state="normal")
            self.btn_srv_stop.configure(state="disabled")
            self.lbl_srv_status.configure(
                text="服务器已退出（代码 %s）" % ev["server_exit"])
            if self.server_proc and self.server_proc.poll() is not None:
                self.server_proc = None
        if "launched" in ev:
            self.busy = False  # 启动阶段结束，游戏运行状态由 proc 单独跟踪
            self._set_busy_ui(False, "游戏运行中：%s" % ev["launched"])
            self.lbl_status_side.configure(text="游戏运行中")
            self.btn_play.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self._log("[launcher] 游戏 %s 已启动（关闭游戏进程后日志结束）\n" % ev["launched"])
        if "game_exit" in ev:
            self.btn_play.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.lbl_progress.configure(text="游戏已退出（代码 %s）" % ev["game_exit"])
            self.lbl_status_side.configure(text="空闲")
            self.lan_port = None
            self._update_room_label()
            self._log("[launcher] 游戏退出，代码 %s\n" % ev["game_exit"])

    def _check_busy(self):
        """True 表示确实有任务进行中；若 busy 标志卡死（工作线程已结束且游戏未运行）则自动恢复"""
        if not self.busy:
            return False
        wt = self._worker_thread
        game_running = self.proc is not None and self.proc.poll() is None
        if (wt is None or not wt.is_alive()) and not game_running:
            self.busy = False
            self._set_busy_ui(False, "就绪")
            return False
        return True

    def _spawn_worker(self, target):
        t = threading.Thread(target=target, daemon=True)
        self._worker_thread = t
        t.start()

    def _set_busy_ui(self, busy, text):
        self.btn_play.configure(state="disabled" if busy else "normal")
        self.lbl_progress.configure(text=text)
        self.lbl_status_side.configure(text="任务进行中" if busy else "空闲")

    def _log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_close(self):
        self.lan_scanner.stop()
        if self.chat_client:
            self.chat_client.stop()
        if self.server_proc and self.server_proc.poll() is None:
            if not messagebox.askyesno("退出", "服务器正在运行，退出启动器会自动关闭服务器。确定退出？"):
                return
            server.send_command(self.server_proc, "stop")
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("退出", "游戏仍在运行，确定退出启动器吗？\n（游戏进程不会被关闭）"):
                return
        self.destroy()


class SkinEditor(ctk.CTkToplevel):
    """皮肤绘制器：64x64 像素编辑，画笔/橡皮/油漆桶/取色/撤销 + 部位模板引导"""

    ZOOM = 8
    TOOLS = [("pen", "画笔"), ("eraser", "橡皮"), ("fill", "油漆桶"), ("pick", "取色")]

    def __init__(self, app, base_img):
        super().__init__(app)
        self.app = app
        self.f_text = app.f_text
        self.f_small = app.f_small
        self.f_button = app.f_button
        self.title("皮肤绘制器 — ZYCSSGXX")
        self.geometry("940x660")
        self.protocol("WM_DELETE_WINDOW", self._on_editor_close)
        self.img = base_img.copy()
        self.undo_stack = []
        self.tool = "pen"
        self.brush = 1
        self.color = (244, 180, 27, 255)
        self._last_px = None

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(12, 4))
        self._build_toolbar(bar)

        pal = ctk.CTkFrame(self, fg_color="transparent")
        pal.pack(fill="x", padx=14, pady=4)
        self._build_palette(pal)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=(6, 12))
        canvas_holder = ctk.CTkFrame(body, corner_radius=8)
        canvas_holder.pack(side="left")
        self.canvas = tk.Canvas(canvas_holder, width=64 * self.ZOOM,
                                height=64 * self.ZOOM, highlightthickness=0,
                                bg="#20242b")
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_last_px", None))

        side = ctk.CTkFrame(body, corner_radius=12)
        side.pack(side="left", fill="y", padx=(12, 0))
        ctk.CTkLabel(side, text="部位模板", font=self.f_text).pack(anchor="w", padx=16, pady=(16, 4))
        for label, box in skinlib.REGIONS:
            ctk.CTkLabel(side, text="%s　(%d,%d)-(%d,%d)" % (label, *box),
                         font=self.f_small, text_color=C_SUB,
                         anchor="w").pack(anchor="w", padx=16)
        ctk.CTkLabel(side, text="上半为正面/背面，下半为\n左臂左腿等镜像部位", font=self.f_small,
                     text_color=C_SUB, anchor="w", justify="left").pack(
            anchor="w", padx=16, pady=(6, 14))

        self.lbl_pos = ctk.CTkLabel(side, text="坐标：-, -", font=self.f_small,
                                    text_color=C_SUB)
        self.lbl_pos.pack(anchor="w", padx=16)
        ctk.CTkButton(side, text="保存到当前账号", width=170, height=38,
                      font=self.f_button, command=self.on_save).pack(padx=16, pady=(10, 4))
        ctk.CTkButton(side, text="另存为 PNG…", width=170, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_save_as).pack(padx=16, pady=4)
        ctk.CTkButton(side, text="放弃修改并关闭", width=170, font=self.f_text,
                      fg_color=C_DANGER, hover_color=C_DANGER_HOVER,
                      command=self._on_editor_close).pack(padx=16, pady=(14, 0))

        self._draw_grid()
        self._update_canvas()

    # ---------- 界面构建 ----------
    def _build_toolbar(self, bar):
        self.tool_buttons = {}
        for key, label in self.TOOLS:
            btn = ctk.CTkButton(bar, text=label, width=84, font=self.f_text,
                                command=lambda k=key: self.set_tool(k))
            btn.pack(side="left", padx=(0, 6))
            self.tool_buttons[key] = btn
        ctk.CTkLabel(bar, text="笔刷", font=self.f_small).pack(side="left", padx=(10, 4))
        self.menu_brush = ctk.CTkOptionMenu(
            bar, values=["1", "2", "4"], width=64, font=self.f_text,
            command=lambda v: setattr(self, "brush", int(v)))
        self.menu_brush.set("1")
        self.menu_brush.pack(side="left")
        ctk.CTkButton(bar, text="撤销", width=70, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_undo).pack(side="left", padx=(10, 0))
        ctk.CTkButton(bar, text="清空为透明", width=100, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_clear_all).pack(side="left", padx=(6, 0))
        ctk.CTkButton(bar, text="重新载入", width=90, font=self.f_text,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      command=self.on_reload).pack(side="left", padx=(6, 0))
        self.set_tool("pen")

    def _build_palette(self, pal):
        ctk.CTkLabel(pal, text="颜色", font=self.f_small).pack(side="left", padx=(0, 6))
        self.color_btns = []
        for rgb in skinlib.PALETTE:
            hexc = "#%02x%02x%02x" % rgb[:3]
            btn = tk.Button(pal, bg=hexc, width=2, relief="flat",
                            activebackground=hexc, bd=0,
                            command=lambda c=rgb: self.set_color(c))
            btn.pack(side="left", padx=1)
            self.color_btns.append(btn)
        tk.Button(pal, text="…", width=2, relief="flat", bd=0,
                  bg="#3a414f", fg="white",
                  command=self.on_pick_custom).pack(side="left", padx=(4, 0))
        tk.Button(pal, text="透明", width=4, relief="flat", bd=0,
                  bg="#20242b", fg="#8a8f98",
                  command=lambda: self.set_color((0, 0, 0, 0))).pack(side="left", padx=4)
        self.lbl_color = ctk.CTkLabel(pal, text="", width=60, height=24,
                                      corner_radius=4, fg_color="#f4b41b")
        self.lbl_color.pack(side="left", padx=8)
        self.set_color(self.color)

    def on_pick_custom(self):
        rgb, _ = colorchooser.askcolor(color=self.color[:3], parent=self,
                                       title="选择颜色")
        if rgb:
            self.set_color(tuple(int(c) for c in rgb) + (255,))

    def set_color(self, rgba):
        self.color = tuple(rgba)
        rgb = rgba[:3]
        fg = "#20242b" if sum(rgb) > 380 else "#ffffff"
        if len(rgba) == 4 and rgba[3] == 0:
            self.lbl_color.configure(fg_color="transparent",
                                     text_color=C_SUB, text="透明")
        else:
            self.lbl_color.configure(fg_color=("#%02x%02x%02x" % rgb),
                                     text_color=fg, text="")

    def set_tool(self, key):
        self.tool = key
        for k, btn in self.tool_buttons.items():
            active = (k == key)
            btn.configure(fg_color=C_ACCENT if active else C_BTN,
                          hover_color=C_ACCENT_HOVER if active else C_BTN_HOVER)

    # ---------- 绘制 ----------
    def _draw_grid(self):
        z = self.ZOOM
        c = self.canvas
        for y in range(0, 64, 2):
            for x in range(0, 64, 2):
                if (x // 2 + y // 2) % 2 == 0:
                    c.create_rectangle(x * z, y * z, (x + 2) * z, (y + 2) * z,
                                       fill="#2a2f38", outline="")
        for _, (l, t, r, b) in skinlib.REGIONS:
            c.create_rectangle(l * z, t * z, r * z, b * z,
                               outline="#4a5568", dash=(3, 3))
        self._grid_id = None
        c.tag_lower("all")

    def _update_canvas(self):
        z = self.ZOOM
        shown = self.img.resize((64 * z, 64 * z), Image.NEAREST)
        self._tkimg = ImageTk.PhotoImage(shown)
        self.canvas.delete("skin")
        self.canvas.create_image(0, 0, anchor="nw", image=self._tkimg, tags="skin")

    def _push_undo(self):
        self.undo_stack.append(self.img.copy())
        if len(self.undo_stack) > 40:
            self.undo_stack.pop(0)

    def _paint(self, x, y):
        half = self.brush // 2
        for dy in range(self.brush):
            for dx in range(self.brush):
                px, py = x - half + dx, y - half + dy
                if 0 <= px < 64 and 0 <= py < 64:
                    if self.tool == "pen":
                        self.img.putpixel((px, py), self.color)
                    elif self.tool == "eraser":
                        self.img.putpixel((px, py), (0, 0, 0, 0))

    def _on_press(self, event):
        x, y = event.x // self.ZOOM, event.y // self.ZOOM
        if not (0 <= x < 64 and 0 <= y < 64):
            return
        if self.tool == "pick":
            self.set_color(self.img.getpixel((x, y)))
            self.set_tool("pen")
            return
        if self.tool == "fill":
            self._push_undo()
            skinlib.flood_fill(self.img, x, y, self.color)
            self._update_canvas()
            return
        self._push_undo()
        self._paint(x, y)
        self._last_px = (x, y)
        self._update_canvas()

    def _on_drag(self, event):
        x, y = event.x // self.ZOOM, event.y // self.ZOOM
        if not (0 <= x < 64 and 0 <= y < 64):
            return
        if self.tool not in ("pen", "eraser"):
            return
        lx, ly = self._last_px or (x, y)
        # 线性插值补齐快速移动的空隙
        steps = max(abs(x - lx), abs(y - ly))
        for i in range(1, steps + 1):
            ix = lx + (x - lx) * i // max(steps, 1)
            iy = ly + (y - ly) * i // max(steps, 1)
            self._paint(ix, iy)
        self._last_px = (x, y)
        self._update_canvas()

    # ---------- 动作 ----------
    def on_undo(self):
        if self.undo_stack:
            self.img = self.undo_stack.pop()
            self._update_canvas()

    def on_clear_all(self):
        self._push_undo()
        self.img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        self._update_canvas()

    def on_reload(self):
        self._push_undo()
        self.img = self._base_img_backup.copy() if hasattr(self, "_base_img_backup") \
            else self.img
        self._update_canvas()

    def on_save(self):
        name = self.app._skin_account()
        if not name:
            messagebox.showwarning("提示", "没有可用账号", parent=self)
            return
        self.img.save(skinlib.account_skin_path(config.APP_DIR, name))
        self._base_img_backup = self.img.copy()
        self.app._refresh_skin_preview()
        self.app.lbl_progress.configure(text="皮肤已保存到账号 %s，下次启动游戏自动生效" % name)
        self.destroy()

    def on_save_as(self):
        path = filedialog.asksaveasfilename(
            title="另存皮肤", defaultextension=".png",
            initialfile="myskin.png", filetypes=[("PNG 图片", "*.png")], parent=self)
        if path:
            self.img.save(path)
            self._base_img_backup = self.img.copy()

    def _on_editor_close(self):
        self.destroy()
