/* ZYCSSGXX 手机端 - MC 启动引擎
 * 
 * 原理：
 * - 从 Mojang API 拉取可用版本列表
 * - 手机端不直接跑 Java（浏览器做不到）
 * - 启动按钮通过 intent:// 唤起 PojavLauncher（Android）或
 *   通过 app scheme 唤起 Minecraft PE（iOS）
 * - 账号、版本、模组等管理完全在手机端
 */

const MOJANG_VERSIONS_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json";
const POJAV_DOWNLOAD = "https://github.com/PojavLauncherTeam/PojavLauncher/releases";

let state = {
  versions: [],           // [{id, type, url, releaseTime}]
  selected: null,         // 选中的版本 id
  accounts: [],           // [{name, offline}]
  selectedAccount: null,
  isAndroid: /Android/i.test(navigator.userAgent),
  isIOS: /iPhone|iPad|iPod/i.test(navigator.userAgent),
  isMobile: /Android|iPhone|iPad|iPod/i.test(navigator.userAgent),
};

const LS_K = {
  versions: "zycssgxx.versions",
  selected: "zycssgxx.selected",
  accounts: "zycssgxx.accounts",
  selectedAcc: "zycssgxx.selectedAcc",
};

/* ============ 初始化 ============ */
export async function initGame() {
  loadCache();
  renderGameUI();
  await loadVersions();
}

export function exitGame() { /* 纯前端，无清理 */ }

function loadCache() {
  try {
    const v = JSON.parse(localStorage.getItem(LS_K.versions));
    if (v && Date.now() - v.ts < 3600_000) state.versions = v.data;
    state.selected = localStorage.getItem(LS_K.selected);
    state.accounts = JSON.parse(localStorage.getItem(LS_K.accounts)) || [];
    state.selectedAccount = localStorage.getItem(LS_K.selectedAcc);
  } catch {}
}

function saveCache() {
  localStorage.setItem(LS_K.versions, JSON.stringify({ ts: Date.now(), data: state.versions }));
  if (state.selected) localStorage.setItem(LS_K.selected, state.selected);
  localStorage.setItem(LS_K.accounts, JSON.stringify(state.accounts));
  if (state.selectedAccount) localStorage.setItem(LS_K.selectedAcc, state.selectedAccount);
}

async function loadVersions() {
  showLoading("加载版本列表...");
  try {
    const resp = await fetch(MOJANG_VERSIONS_URL, { cache: "no-cache" });
    const data = await resp.json();
    state.versions = data.versions.filter(v => v.type === "release" || v.type === "snapshot");
    // 合并 Fabric/Forge（Modrinth）
    try {
      const mr = await fetch("https://api.modrinth.com/v2/tag/game_version?loader=fabric&limit=30");
      const m = await mr.json();
      const fabric = m.map(gv => ({ id: `${gv.version} (Fabric)`, type: "fabric", url: gv, releaseTime: gv }));
      state.versions = [...fabric, ...state.versions];
    } catch {}
    saveCache();
  } catch (e) {
    showError("版本列表加载失败（请检查网络）");
  }
  renderGameUI();
  hideLoading();
}

/* ============ 渲染 UI ============ */
function renderGameUI() {
  // 账号区
  const accArea = document.getElementById("mcAccountArea");
  if (!accArea) return;
  if (state.accounts.length === 0) {
    accArea.innerHTML = `
      <div class="mc-account-empty">
        <p>还没有账号</p>
        <p class="mc-hint">去「账号」页注册/登录</p>
      </div>`;
  } else {
    accArea.innerHTML = `
      <div class="mc-account-list">
        ${state.accounts.map((a, i) => `
          <div class="mc-acc-card ${state.selectedAccount === a.name ? "active" : ""}" data-idx="${i}">
            <div class="mc-acc-avatar">${a.name[0].toUpperCase()}</div>
            <div class="mc-acc-info">
              <div class="mc-acc-name">${a.name}</div>
              <div class="mc-acc-type">离线账号</div>
            </div>
          </div>
        `).join("")}
      </div>`;
    accArea.querySelectorAll(".mc-acc-card").forEach(el => {
      el.onclick = () => {
        state.selectedAccount = state.accounts[el.dataset.idx].name;
        saveCache(); renderGameUI();
      };
    });
  }

  // 版本区
  const verArea = document.getElementById("mcVersionArea");
  verArea.innerHTML = "";
  const releases = state.versions.filter(v => v.type === "release").slice(0, 15);
  const snapshots = state.versions.filter(v => v.type === "snapshot").slice(0, 5);
  const fabric = state.versions.filter(v => v.type === "fabric").slice(0, 8);

  const addSection = (title, items, accent) => {
    if (items.length === 0) return;
    const sec = document.createElement("div");
    sec.className = "mc-ver-section";
    sec.innerHTML = `<div class="mc-ver-title">${title}</div>
      <div class="mc-ver-scroll">
        ${items.map(v => `
          <div class="mc-ver-chip ${state.selected === v.id ? "active" : ""}" 
               data-id="${v.id}" style="--accent:${accent}">
            ${v.id}
          </div>
        `).join("")}
      </div>`;
    verArea.appendChild(sec);
    sec.querySelectorAll(".mc-ver-chip").forEach(el => {
      el.onclick = () => { state.selected = el.dataset.id; saveCache(); renderGameUI(); };
    });
  };
  addSection("正式版", releases, "#2fd582");
  addSection("Fabric", fabric, "#f2c23e");
  addSection("快照版", snapshots, "#9b59b6");

  // 启动按钮状态
  const launchBtn = document.getElementById("mcLaunchBtn");
  if (state.selected && state.selectedAccount) {
    launchBtn.disabled = false;
    launchBtn.textContent = "🚀 启动游戏";
    launchBtn.onclick = launchGame;
  } else {
    launchBtn.disabled = true;
    launchBtn.textContent = !state.selectedAccount ? "请先登录账号" : "请选择版本";
    launchBtn.onclick = null;
  }

  // 平台提示
  const plat = document.getElementById("mcPlatform");
  if (state.isAndroid) plat.textContent = "📱 Android · 将通过 PojavLauncher 启动 MC Java";
  else if (state.isIOS) plat.textContent = "📱 iOS · 将尝试启动 Minecraft PE";
  else plat.textContent = "💻 浏览器预览 · 启动功能请在手机上使用";
}

/* ============ 启动游戏 ============ */
async function launchGame() {
  if (!state.selected || !state.selectedAccount) return;
  if (!state.isMobile) {
    alert("⚠️ 手机浏览器预览模式\n\n真正启动 Minecraft 需要：\n• Android 安装 PojavLauncher\n• 或回桌面版 ZYCSSGXX\n\n\n电脑版地址：desktop/ 文件夹");
    return;
  }

  showLoading("启动中...");

  if (state.isAndroid) {
    // 尝试通过 intent scheme 唤起 PojavLauncher
    // 格式：pojav://launch?username=XXX&version=XXX
    const intent = `intent://#Intent;scheme=pojav;package=net.kdt.pojavlauncher;S.username=${encodeURIComponent(state.selectedAccount)};S.version=${encodeURIComponent(state.selected)};end;`;
    window.location.href = intent;

    // 3 秒后如果还在本页面，说明没装 Pojav
    setTimeout(() => {
      if (document.hidden) return; // 真的切走了
      hideLoading();
      showPojavInstallDialog();
    }, 3500);
    return;
  }

  if (state.isIOS) {
    // iOS 尝试打开 Minecraft PE App Store
    window.location.href = "minecraft://";
    setTimeout(() => {
      if (document.hidden) return;
      hideLoading();
      alert("iOS 上请在 App Store 搜索 Minecraft 下载安装，然后用我们的账号登录。");
    }, 2000);
  }
}

function showPojavInstallDialog() {
  const html = `
    <div class="mc-modal" id="mcModal">
      <div class="mc-modal-card">
        <h3>📥 需要安装 PojavLauncher</h3>
        <p>ZYCSSGXX 通过 PojavLauncher 在手机上启动 Minecraft Java 版（和电脑上完全一样）</p>
        <div class="mc-modal-btns">
          <a class="mc-btn-primary" href="${POJAV_DOWNLOAD}" target="_blank">⬇️ 下载 PojavLauncher APK</a>
          <button id="mcModalClose" class="mc-btn-sec">我已安装，重试启动</button>
        </div>
        <p class="mc-modal-tip">安装后再打开 ZYCSSGXX，启动按钮会自动唤起 Pojav</p>
      </div>
    </div>`;
  document.body.insertAdjacentHTML("beforeend", html);
  document.getElementById("mcModalClose").onclick = () => {
    document.getElementById("mcModal").remove();
    launchGame();
  };
}

/* ============ 辅助 ============ */
function showLoading(msg) {
  let l = document.getElementById("mcLoading");
  if (!l) {
    l = document.createElement("div");
    l.id = "mcLoading";
    l.className = "mc-loading";
    document.body.appendChild(l);
  }
  l.innerHTML = `<div class="mc-loader-spinner"></div><div>${msg}</div>`;
}
function hideLoading() {
  const l = document.getElementById("mcLoading");
  if (l) l.remove();
}
function showError(msg) { alert("❌ " + msg); }

// 暴露 + accounts setter
const proxy = {
  accounts: [],
  init: initGame,
  exit: exitGame,
  launch: launchGame,
};
Object.defineProperty(proxy, "accounts", {
  get: () => state.accounts,
  set: (arr) => { state.accounts = arr || []; saveCache(); renderGameUI(); }
});
window.ZYCSSGame = proxy;
