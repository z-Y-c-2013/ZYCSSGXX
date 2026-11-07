/* ZYCSSGXX 手机伴侣版 - app.js */
const VERSION = "v1.4.0";
const LS = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set(k, v) { localStorage.setItem(k, JSON.stringify(v)); },
  del(k) { localStorage.removeItem(k); }
};

const state = {
  user: LS.get("user") || null,       // {name, token}
  friends: LS.get("friends") || [],
  pending: LS.get("pending") || [],
  chatUrl: LS.get("chatUrl") || "",
  modsCache: null,
  ws: null,
  chatWith: null,
  chatLog: {}                         // friendName -> [{from, text, time}]
};

/* ============ Toast ============ */
function toast(msg, dur = 2000) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), dur);
}

/* ============ Tab 切换 ============ */
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    const page = btn.dataset.page;
    if (page === "game") {
      // 加载账号到 game.js
      const accounts = window.ZYCSSGame?.accounts ?? [];
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
      document.getElementById("page-game").classList.add("active");
      if (window.ZYCSSGame?.init) window.ZYCSSGame.init();
      return;
    }
    // 把账号同步给 game.js
    if (window.ZYCSSGame) {
      window.ZYCSSGame.accounts = state.user ? [{ name: state.user.name }] : [];
    }
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t === btn));
    document.querySelectorAll(".page").forEach(p => p.classList.toggle("active", p.id === `page-${page}`));
    if (page === "mods") loadMods();
    if (page === "chat") refreshChatPage();
  });
});

// 首页"进入游戏"按钮
document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "enterGameBtn") {
    document.querySelector('.tab[data-page="game"]').click();
  }
});

/* ============ 闪屏结束 ============ */
setTimeout(() => {
  document.getElementById("splash").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  init();
}, 4500);

/* ============ 初始化 ============ */
function init() {
  // 设置
  document.getElementById("setChatUrl").value = state.chatUrl || "";
  document.getElementById("saveSettings").onclick = () => {
    state.chatUrl = document.getElementById("setChatUrl").value.trim();
    LS.set("chatUrl", state.chatUrl);
    toast("✅ 设置已保存");
    connectChat();
  };
  document.getElementById("clearData").onclick = () => {
    if (!confirm("确定清除所有本地数据？")) return;
    Object.keys(localStorage).forEach(k => localStorage.removeItem(k));
    location.reload();
  };

  // 顶栏
  updateTopBar();

  // Auth
  renderAuth();

  // 添加好友
  document.getElementById("addFriendBtn").onclick = sendFriendReq;

  // 模组
  loadMods();

  // 聊天
  connectChat();

  // 版本号替换
  document.querySelector(".hero-sub").innerHTML = `${VERSION} · 纯离线免正版`;
}

function updateTopBar() {
  const uname = document.getElementById("topUname");
  const avatar = document.getElementById("topAvatar");
  if (state.user) {
    uname.textContent = state.user.name;
    avatar.textContent = state.user.name[0].toUpperCase();
    // 同步给 game.js
    if (window.ZYCSSGame) {
      window.ZYCSSGame.accounts = [{ name: state.user.name }];
      window.ZYCSSGame.selectedAccount = state.user.name;
    }
  } else {
    uname.textContent = "未登录";
    avatar.textContent = "?";
    if (window.ZYCSSGame) { window.ZYCSSGame.accounts = []; window.ZYCSSGame.selectedAccount = null; }
  }
}

/* ============ 账号注册/登录 ============ */
let authMode = "login"; // login | register
function renderAuth() {
  const panel = document.getElementById("authPanel");
  if (!state.user) {
    const title = authMode === "login" ? "登录" : "注册新账号";
    const switchText = authMode === "login" ? "没有账号？点这里注册" : "已有账号？点这里登录";
    panel.innerHTML = `
      <h4 style="margin:0 0 8px">${title}</h4>
      <div class="auth-row">
        <input type="text" id="authName" placeholder="账号名" autocomplete="off">
      </div>
      <div class="auth-row">
        <input type="password" id="authPass" placeholder="密码（注册必填）">
      </div>
      <button class="primary" id="authSubmit">${authMode === "login" ? "登录" : "注册"}</button>
      <div class="auth-switch"><a id="authSwitch">${switchText}</a></div>
    `;
    document.getElementById("authSubmit").onclick = authSubmit;
    document.getElementById("authSwitch").onclick = () => {
      authMode = authMode === "login" ? "register" : "login";
      renderAuth();
    };
  } else {
    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
        <span class="avatar">${state.user.name[0].toUpperCase()}</span>
        <div>
          <div style="font-weight:700">${state.user.name}</div>
          <div style="font-size:12px;color:#888">已登录</div>
        </div>
      </div>
      <button id="logoutBtn">退出登录</button>
    `;
    document.getElementById("logoutBtn").onclick = () => {
      state.user = null; LS.del("user");
      state.friends = []; LS.del("friends");
      state.pending = []; LS.del("pending");
      state.chatLog = {}; LS.del("chatLog");
      updateTopBar(); renderAuth(); connectChat(); toast("已退出");
    };
  }
}

async function authSubmit() {
  const name = document.getElementById("authName").value.trim();
  const pass = document.getElementById("authPass").value;
  if (!name) return toast("请输入账号名");
  if (name.length < 2 || name.length > 20) return toast("账号名 2-20 字符");
  if (authMode === "register" && !pass) return toast("请输入密码");

  // 纯前端本地账号（手机版先做本地，连服务器可选）
  if (authMode === "register") {
    let all = LS.get("allUsers") || {};
    if (all[name.toLowerCase()]) return toast("❌ 账号已存在");
    all[name.toLowerCase()] = { name, pass, created: Date.now() };
    LS.set("allUsers", all);
    state.user = { name, token: "local_" + btoa(name + ":" + Date.now()) };
    LS.set("user", state.user);
    toast("✅ 注册成功");
  } else {
    let all = LS.get("allUsers") || {};
    let u = all[name.toLowerCase()];
    if (!u) return toast("❌ 账号不存在");
    if (pass && u.pass !== pass) return toast("❌ 密码错误");
    state.user = { name: u.name, token: "local_" + btoa(u.name + ":" + Date.now()) };
    LS.set("user", state.user);
    toast("✅ 登录成功");
  }
  updateTopBar(); renderAuth(); connectChat();
}

/* ============ 好友 ============ */
function sendFriendReq() {
  if (!state.user) return toast("请先登录");
  const input = document.getElementById("addFriendInput");
  const name = input.value.trim();
  if (!name) return toast("请输入账号名");
  if (name.toLowerCase() === state.user.name.toLowerCase()) return toast("不能加自己");
  let pending = state.pending.filter(p => p !== name);
  pending.push(name);
  state.pending = pending; LS.set("pending", pending);
  input.value = "";
  toast(`✅ 请求已发送给 ${name}（对方接受后互加好友）`);
  refreshFriendPanel();
}

function refreshFriendPanel() {
  // 渲染"待接受的请求"面板
  const fr = document.getElementById("friendRequests");
  if (!fr) return;
  if (state.pending.length === 0 && state.friends.length === 0) {
    fr.innerHTML = "";
    return;
  }
  let html = "";
  if (state.pending.length) {
    html += `<div style="font-size:12px;color:#888;margin:6px 0 4px">待接受（自己点"接受"模拟对方同意）</div>`;
    state.pending.forEach(n => {
      html += `<div class="fr-item">
        <span class="fname">${n}</span>
        <button data-act="accept" data-name="${n}" class="primary">接受</button>
        <button data-act="decline" data-name="${n}">取消</button>
      </div>`;
    });
  }
  fr.innerHTML = html;
  fr.querySelectorAll("button").forEach(b => {
    b.onclick = () => {
      const name = b.dataset.name;
      const act = b.dataset.act;
      if (act === "accept") {
        state.pending = state.pending.filter(p => p !== name);
        if (!state.friends.includes(name)) state.friends.push(name);
        LS.set("pending", state.pending); LS.set("friends", state.friends);
        toast(`✅ ${name} 已成为好友`);
      } else {
        state.pending = state.pending.filter(p => p !== name);
        LS.set("pending", state.pending);
        toast("已取消");
      }
      refreshFriendPanel();
    };
  });
}

/* ============ 聊天 UI ============ */
function refreshChatPage() {
  refreshFriendPanel();
  const list = document.getElementById("friendList");
  const empty = document.getElementById("chatEmpty");
  const area = document.getElementById("chatArea");
  if (!state.user) {
    list.innerHTML = `<div class="loading">请先登录</div>`;
    empty.classList.remove("hidden"); area.classList.add("hidden");
    return;
  }
  if (state.friends.length === 0) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    area.classList.add("hidden");
    return;
  }
  empty.classList.add("hidden");
  list.innerHTML = state.friends.map(n => {
    const msgs = state.chatLog[n] || [];
    const last = msgs[msgs.length - 1];
    return `<div class="friend-item" data-name="${n}">
      <span class="avatar">${n[0].toUpperCase()}</span>
      <div style="flex:1;min-width:0">
        <div class="fname">${n}</div>
        <div class="fsub">${last ? (last.from === n ? last.text : "我: " + last.text) : "点击开始聊天"}</div>
      </div>
      <span class="time">${last ? fmtTime(last.time) : ""}</span>
    </div>`;
  }).join("");
  list.querySelectorAll(".friend-item").forEach(el => {
    el.onclick = () => openChat(el.dataset.name);
  });
}

function fmtTime(t) {
  if (!t) return "";
  const d = new Date(t);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
  return `${d.getMonth()+1}/${d.getDate()}`;
}

function openChat(name) {
  state.chatWith = name;
  document.getElementById("chatArea").classList.remove("hidden");
  document.getElementById("chatWith").textContent = name;
  const log = document.getElementById("chatLog");
  const msgs = state.chatLog[name] || [];
  log.innerHTML = msgs.map(m => `
    <div class="msg ${m.from === name ? 'other' : 'me'}">
      ${escapeHtml(m.text)}
      <div class="mtime">${fmtTime(m.time)}</div>
    </div>
  `).join("");
  log.scrollTop = log.scrollHeight;
  document.getElementById("chatBack").onclick = () => {
    document.getElementById("chatArea").classList.add("hidden");
    state.chatWith = null;
  };
  document.getElementById("sendBtn").onclick = sendMsg;
  document.getElementById("msgInput").addEventListener("keydown", e => {
    if (e.key === "Enter") sendMsg();
  });
}

function sendMsg() {
  const input = document.getElementById("msgInput");
  const text = input.value.trim();
  if (!text || !state.chatWith) return;
  if (!state.chatLog[state.chatWith]) state.chatLog[state.chatWith] = [];
  state.chatLog[state.chatWith].push({
    from: state.user.name, text, time: Date.now()
  });
  LS.set("chatLog", state.chatLog);
  input.value = "";
  openChat(state.chatWith);
  // 广播给 WebSocket（如果连着）
  if (state.ws && state.ws.readyState === 1) {
    state.ws.send(JSON.stringify({ type: "chat", to: state.chatWith, text }));
  }
}

function escapeHtml(s) {
  const d = document.createElement("div"); d.textContent = s; return d.innerHTML;
}

/* ============ WebSocket 聊天 ============ */
function connectChat() {
  const dot = document.getElementById("connDot");
  if (state.ws) { try { state.ws.close(); } catch {} state.ws = null; }
  if (!state.chatUrl) { dot.className = "conn-dot"; return; }
  if (!state.user) { dot.className = "conn-dot disconnected"; return; }
  try {
    state.ws = new WebSocket(state.chatUrl);
    dot.className = "conn-dot disconnected";
    state.ws.onopen = () => {
      dot.className = "conn-dot connected";
      state.ws.send(JSON.stringify({ type: "auth", name: state.user.name, token: state.user.token }));
    };
    state.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "chat" && data.from && state.friends.includes(data.from)) {
          if (!state.chatLog[data.from]) state.chatLog[data.from] = [];
          state.chatLog[data.from].push({ from: data.from, text: data.text, time: data.time || Date.now() });
          LS.set("chatLog", state.chatLog);
          if (state.chatWith === data.from) openChat(data.from);
          else updateChatBadge();
        }
      } catch {}
    };
    state.ws.onclose = () => { dot.className = "conn-dot disconnected"; setTimeout(connectChat, 5000); };
    state.ws.onerror = () => { dot.className = "conn-dot disconnected"; };
  } catch {
    dot.className = "conn-dot disconnected";
  }
}

function updateChatBadge() {
  // 简化：有好友就显示空徽章
  const b = document.getElementById("chatBadge");
  b.classList.toggle("show", state.friends.length > 0);
}

/* ============ 模组浏览（Modrinth API） ============ */
async function loadMods() {
  if (state.modsCache) { renderMods(state.modsCache); return; }
  const list = document.getElementById("modList");
  const loading = document.getElementById("modLoading");
  list.innerHTML = ""; loading.style.display = "";
  try {
    const resp = await fetch("https://api.modrinth.com/v2/search?limit=20&facets=[[\"project_type:mod\"]]");
    const data = await resp.json();
    state.modsCache = data.hits;
    renderMods(data.hits);
  } catch (e) {
    loading.textContent = "加载失败，请检查网络";
  }
}

function renderMods(hits) {
  const list = document.getElementById("modList");
  const loading = document.getElementById("modLoading");
  const q = (document.getElementById("modSearch")?.value || "").toLowerCase();
  loading.style.display = "none";
  const filtered = q ? hits.filter(h => h.title.toLowerCase().includes(q) || (h.description||"").toLowerCase().includes(q)) : hits;
  if (filtered.length === 0) { list.innerHTML = `<div class="loading">没有匹配的模组</div>`; return; }
  list.innerHTML = filtered.map(h => `
    <a class="mod-item" href="https://modrinth.com/mod/${h.slug}" target="_blank" style="text-decoration:none;color:inherit">
      <img class="mod-icon" src="${h.icon_url || ''}" alt="" onerror="this.style.visibility='hidden'">
      <div class="mod-info">
        <div class="mod-name">${escapeHtml(h.title)}</div>
        <div class="mod-desc">${escapeHtml(h.description || "")}</div>
        <div class="mod-tags">
          ${(h.categories || []).slice(0,4).map(c => `<span class="mod-tag">${c}</span>`).join("")}
          ${h.downloads ? `<span class="mod-tag">⬇ ${(h.downloads/1000).toFixed(1)}K</span>` : ""}
        </div>
      </div>
    </a>
  `).join("");
}

const modSearch = document.getElementById("modSearch");
if (modSearch) modSearch.addEventListener("input", () => {
  if (state.modsCache) renderMods(state.modsCache);
});

/* ============ 皮肤预览 ============ */
(function() {
  const prev = document.getElementById("skinPreview");
  if (!prev) return;
  const icon = new URL("../assets/zycssgxx.ico", import.meta.url);
  prev.innerHTML = `<img src="${icon}" alt="skin">`;
})();
