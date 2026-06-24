/**
 * AI 短剧工作台 v2 — 主应用
 *
 * 模块清单（按加载顺序）：
 *   1. core.js      — 基础设施：API/cache/toast/modal/pollTask/undo-redo/routing/CRUD
 *   2. dashboard.js — 仪表盘 + 灵感生成
 *   3. pipeline.js  — 生产工作台：步骤/镜头编辑/执行/工具
 *   4. characters.js— 角色管理 + 定妆照 + 服装 + LoRA 训练
 *   5. scenes.js    — 场景管理
 *   6. storyboard.js— 分镜表（表格/卡片视图）
 *   7. ai-gen.js    — AI 生成（通用执行器 + 对话式编辑）
 *   8. seko.js      — Seko 影视策划案
 *   9. projects.js  — 项目管理
 *  10. settings.js  — 系统设置 + 配置预设
 *  11. extras.js    — 拖拽排序/批量导入导出/引用计数/成片预览/主体库/多剧集/Worker状态
 *  12. init.js      — 启动入口
 */
const API = '/api';

// ── 基础设施 ──

const _cache = new Map();
const CACHE_TTL = 30000;
const MAX_CACHE_SIZE = 200;  // LRU：超过此数量时淘汰最旧的条目
const MAX_UNDO = 50;
const MAX_POLL = 300;

let ep = 1, shots = [], batchCancelled = false;
const _undoStack = [], _redoStack = [];
let _currentTaskId = null; // 当前正在执行的任务 ID（单任务）
const _activeTaskIds = new Set(); // 所有活跃任务 ID（批量并发用）
const _runningSteps = new Set(); // 正在执行的 shot+step 组合（防重复）

// ── ID→名字显示映射 ──
const _charNameMap = {};  // { 'ch_8a3f2b1c': '林夏', ... }
const _sceneNameMap = {}; // { 'sc_8a3f2b1c': '客厅', ... }

async function _loadNameMaps() {
  try {
    // 清空旧映射（防止删除/重命名后残留）
    Object.keys(_charNameMap).forEach(k => delete _charNameMap[k]);
    Object.keys(_sceneNameMap).forEach(k => delete _sceneNameMap[k]);
    const [charData, sceneData] = await Promise.all([
      cachedFetch('characters', () => api('/characters')),
      cachedFetch('scenes', () => api('/scenes')),
    ]);
    (charData.characters || []).forEach(c => { if (c.id) _charNameMap[c.id] = c.name || c.id; });
    (sceneData.scenes || []).forEach(s => { if (s.id) _sceneNameMap[s.id] = s.name || s.id; });
  } catch (e) { console.warn('[loadNameMaps]', e); }
}

function _resolveChars(ids) {
  if (!ids) return '';
  return ids.split('+').map(id => {
    id = id.trim();
    return _charNameMap[id] || id;
  }).join('+');
}

function _resolveScene(id) {
  if (!id) return '';
  return _sceneNameMap[id] || id;
}

// ── 集数选择器 ──
async function loadEpisodeSelector() {
  try {
    const d = await api('/episodes');
    const eps = d.episodes || [1];
    // 确保当前集在列表中
    if (!eps.includes(ep)) eps.push(ep);
    return eps.sort((a, b) => a - b);
  } catch (e) { console.warn('[loadEpisodeSelector]', e); return [ep]; }
}

function _episodeSelectHtml(episodes, onChangeFn) {
  const opts = episodes.map(e => `<option value="${e}" ${e === ep ? 'selected' : ''}>${e}</option>`).join('');
  return `<select class="btn btn-outline" style="padding:.3rem .6rem;font-size:.82rem" onchange="${onChangeFn}(this.value)">${opts}</select><button class="btn btn-xs btn-outline" onclick="addEpisode()" title="${t('btn.add')}">+</button>`;
}

function switchEpisode(val) {
  ep = parseInt(val) || 1;
  batchCancelled = false;
  invalidateCache(`storyboard/${ep}`);
  const p = document.querySelector('.page.active');
  if (p?.id === 'page-storyboard') loadStoryboard();
  else if (p?.id === 'page-pipeline') loadPipeline();
}

async function addEpisode() {
  const input = await modalPrompt(t('ep.input'), '', { inputType: 'number', placeholder: '1' });
  if (!input) return;
  const newEp = parseInt(input);
  if (!newEp || newEp < 1) { toast(t('ep.invalid'), 'error'); return; }
  ep = newEp;
  invalidateCache('episodes');
  invalidateCache(`storyboard/${ep}`);
  const p = document.querySelector('.page.active');
  if (p?.id === 'page-storyboard') loadStoryboard();
  else if (p?.id === 'page-pipeline') loadPipeline();
  toast(t('ep.switched', { ep }));
}

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

/**
 * 安全 HTML 模板标签 — 自动转义插值内容
 * 用法: element.innerHTML = safeHTML`⏳ ${msg}...`;
 * @param {string[]} strings - 模板字符串的静态部分
 * @param {...any} values - 插值内容（自动转义）
 * @returns {string} 转义后的安全 HTML
 */
function safeHTML(strings, ...values) {
    return strings.reduce((acc, str, i) => {
        const val = values[i];
        if (val === undefined || val === null) return acc + str;
        return acc + str + esc(String(val));
    }, '');
}

function debounce(fn, ms = 300) { let _t; return (...a) => { clearTimeout(_t); _t = setTimeout(() => fn(...a), ms); }; }
function toast(msg, type = 'success') { const el = document.createElement('div'); el.className = `toast toast-${type}`; el.textContent = msg; document.body.appendChild(el); setTimeout(() => el.remove(), 3500); }

// ── 简洁工具 ──

/** 安全设置元素 innerHTML（null 则跳过） */
function _html(el, content) { if (el) el.innerHTML = content; }

/** 安全设置按钮加载态 */
function _btnLoad(btn, text) {
  if (!btn) return () => {};
  const orig = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = text; btn.style.opacity = '0.7';
  return () => { btn.disabled = false; btn.innerHTML = orig; btn.style.opacity = ''; };
}

// ── 自定义模态框（替代原生 prompt/confirm）──

function modalConfirm(message) {
  return new Promise(resolve => {
    const o = document.createElement('div'); o.className = 'edit-overlay';
    o.innerHTML = `<div class="edit-panel" style="width:400px"><div class="edit-header"><h3>${t('btn.confirm')}</h3></div>
      <div class="edit-body"><p style="font-size:.88rem;line-height:1.6">${esc(message)}</p></div>
      <div class="edit-footer"><button class="btn btn-primary" id="_mc-ok">${t('btn.confirm')}</button>
      <button class="btn btn-outline" id="_mc-cancel">${t('btn.cancel')}</button></div></div>`;
    document.body.appendChild(o);
    const cleanup = (val) => { o.remove(); resolve(val); };
    o.querySelector('#_mc-ok').onclick = () => cleanup(true);
    o.querySelector('#_mc-cancel').onclick = () => cleanup(false);
    o.querySelector('#_mc-ok').focus();
    o.addEventListener('keydown', (e) => { if (e.key === 'Escape') cleanup(false); });
  });
}

function modalPrompt(message, defaultValue = '', opts = {}) {
  return new Promise(resolve => {
    const o = document.createElement('div'); o.className = 'edit-overlay';
    const inputTag = opts.type === 'select'
      ? `<select id="_mp-input">${(opts.options||[]).map(v => `<option ${v===defaultValue?'selected':''}>${v}</option>`).join('')}</select>`
      : opts.type === 'textarea'
      ? `<textarea id="_mp-input" rows="4" style="width:100%" ${opts.placeholder?`placeholder="${esc(opts.placeholder)}"`:''}>${esc(defaultValue)}</textarea>`
      : `<input id="_mp-input" type="${opts.inputType||'text'}" value="${esc(defaultValue)}" ${opts.placeholder?`placeholder="${esc(opts.placeholder)}"`:''}>`;
    o.innerHTML = `<div class="edit-panel" style="width:400px"><div class="edit-header"><h3>${esc(message)}</h3></div>
      <div class="edit-body"><div class="edit-field">${inputTag}</div></div>
      <div class="edit-footer"><button class="btn btn-primary" id="_mp-ok">${t('btn.confirm')}</button>
      <button class="btn btn-outline" id="_mp-cancel">${t('btn.cancel')}</button></div></div>`;
    document.body.appendChild(o);
    const inp = o.querySelector('#_mp-input');
    const cleanup = (val) => { o.remove(); resolve(val); };
    o.querySelector('#_mp-ok').onclick = () => cleanup(inp.value);
    o.querySelector('#_mp-cancel').onclick = () => cleanup(null);
    inp.focus(); inp.select();
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') cleanup(inp.value); if (e.key === 'Escape') cleanup(null); });
  });
}

function cachedFetch(key, fetcher, ttl = CACHE_TTL) {
  const e = _cache.get(key);
  if (e && Date.now() - e.ts < ttl) return Promise.resolve(e.data);
  return fetcher().then(d => {
    // LRU：超过容量时淘汰最旧的条目
    if (_cache.size >= MAX_CACHE_SIZE) {
      const oldest = _cache.keys().next().value;
      _cache.delete(oldest);
    }
    _cache.set(key, { data: d, ts: Date.now() });
    return d;
  });
}
function invalidateCache(prefix) { for (const k of _cache.keys()) if (k.startsWith(prefix)) _cache.delete(k); }

async function api(path, opts = {}) {
  const { body, headers, ...rest } = opts;
  const h = { ...headers };
  if (body) h['Content-Type'] = 'application/json';
  const r = await fetch(API + path, {
    headers: h, ...rest,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const raw = await r.text();
    try { const j = JSON.parse(raw); throw new Error(j.detail || raw); } catch (e) { if (e.message) throw e; throw new Error(raw); }
  }
  return r.json();
}

async function pollTask(taskId, onProgress) {
  let delay = 500;
  for (let i = 0; i < MAX_POLL; i++) {
    const info = await api(`/tasks/${taskId}`);
    // 同步更新到全局任务面板
    if (typeof TaskPanel !== 'undefined') TaskPanel.updateTask(taskId, info);
    if (onProgress) onProgress(info);
    if (['success', 'failed', 'cancelled'].includes(info.status)) return info;
    await new Promise(r => setTimeout(r, delay));
    delay = Math.min(delay * 1.5, 5000); // 指数退避，上限5秒
  }
  return { status: 'timeout', error: t('toast.timeout') + ` (task: ${taskId})` };
}

// ── 撤销/重做 ──

function _applyHistory(from, to, label) {
  if (!from.length) { toast(t('undo.no_action', { label }), 'error'); return; }
  const entry = from.pop();
  to.push({ shots: JSON.parse(JSON.stringify(shots)), desc: entry.desc });
  const prevShots = JSON.parse(JSON.stringify(shots)); // 保存回滚快照
  shots = entry.shots;
  invalidateCache(`storyboard/${ep}`);
  api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }).then(() => {
    toast(`${label === t('undo.undo') ? '↩' : '↪'} ${label}: ${entry.desc}`);
    const p = document.querySelector('.page.active');
    p?.id === 'page-storyboard' ? loadStoryboard() : renderShotsGrid();
  }).catch(e => { shots = prevShots; toast(e.message, 'error'); });
}
function pushUndo(desc) { _undoStack.push({ shots: JSON.parse(JSON.stringify(shots)), desc }); if (_undoStack.length > MAX_UNDO) _undoStack.shift(); _redoStack.length = 0; }
function undo() { _applyHistory(_undoStack, _redoStack, t('undo.undo')); }
function redo() { _applyHistory(_redoStack, _undoStack, t('undo.redo')); }

// ── 路由 ──

document.querySelectorAll('.nav-item').forEach(item => {
  item.onclick = async () => {
    // 检查分镜表是否有未保存的修改
    if (typeof _sbDirty !== 'undefined' && _sbDirty) {
      const ok = await modalConfirm(t('sb.unsaved_confirm'));
      if (!ok) return;
      _sbDirty = false;
    }
    document.querySelectorAll('.nav-item,.page').forEach(el => el.classList.remove('active'));
    item.classList.add('active');
    document.getElementById(`page-${item.dataset.page}`).classList.add('active');
    loadPage(item.dataset.page);
  };
});
function navTo(p) { document.querySelector(`.nav-item[data-page="${p}"]`).click(); }
// PAGES 使用惰性查找，避免动态加载脚本时函数尚未定义
const PAGES = { dashboard: 'loadDashboard', characters: 'loadCharacters', scenes: 'loadScenes', storyboard: 'loadStoryboard', pipeline: 'loadPipeline', projects: 'loadProjects', settings: 'loadSettings', seko: 'loadSeko', voices: 'loadVoices', assets: 'loadAssets' };
async function loadPage(p) { const fn = PAGES[p]; if (fn && typeof window[fn] === 'function') await window[fn](); }

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelector('.res-overlay, .edit-overlay')?.remove();
  if (e.ctrlKey || e.metaKey) {
    if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
    if ((e.key === 'z' && e.shiftKey) || e.key === 'y') { e.preventDefault(); redo(); }
  }
});

// ── DOM 取值快捷 ──
function $val(id) { return document.getElementById(id)?.value || ''; }


// ══════════════════════════════════════════════════════════

// ── Module: core ──
Drama.core = {
  api, toast, cachedFetch, invalidateCache, esc, safeHTML, debounce, $val,
  modalConfirm, modalPrompt, pollTask, _html, _btnLoad,
  pushUndo, undo, redo, loadEpisodeSelector, _episodeSelectHtml,
  switchEpisode, addEpisode, navTo, loadPage, _loadNameMaps,
  _resolveChars, _resolveScene, _applyHistory,
};
// Shared state bridges — ep/shots/sbDirty 通过 getter/setter 与模块变量双向同步
Object.defineProperty(Drama, 'ep', {
  get: () => ep, set: (v) => { ep = v; },
});
Object.defineProperty(Drama, 'shots', {
  get: () => shots, set: (v) => { shots = v; },
});
Object.defineProperty(Drama, 'sbDirty', {
  get: () => typeof _sbDirty !== 'undefined' ? _sbDirty : false,
  set: (v) => { if (typeof _sbDirty !== 'undefined') _sbDirty = v; },
});
// Export to window for backward compat (getter/setter to stay in sync with module variables)
Object.defineProperty(window, 'ep', { get: () => ep, set: (v) => { ep = v; } });
Object.defineProperty(window, 'shots', { get: () => shots, set: (v) => { shots = v; } });
window.api = api;
window.toast = toast;
window.cachedFetch = cachedFetch;
window.invalidateCache = invalidateCache;
window.esc = esc;
window.safeHTML = safeHTML;
window.debounce = debounce;
window.$val = $val;
window.modalConfirm = modalConfirm;
window.modalPrompt = modalPrompt;
window.pollTask = pollTask;
window._html = _html;
window._btnLoad = _btnLoad;
window.pushUndo = pushUndo;
window.undo = undo;
window.redo = redo;
window.loadEpisodeSelector = loadEpisodeSelector;
window._episodeSelectHtml = _episodeSelectHtml;
window.switchEpisode = switchEpisode;
window.addEpisode = addEpisode;
window.navTo = navTo;
window.loadPage = loadPage;
window._loadNameMaps = _loadNameMaps;
window._resolveChars = _resolveChars;
window._resolveScene = _resolveScene;
window._charNameMap = _charNameMap;
window._sceneNameMap = _sceneNameMap;
window._cache = _cache;
window._undoStack = _undoStack;
window._redoStack = _redoStack;
Object.defineProperty(window, '_currentTaskId', { get: () => _currentTaskId, set: (v) => { _currentTaskId = v; } });
window._activeTaskIds = _activeTaskIds;
Object.defineProperty(window, 'batchCancelled', { get: () => batchCancelled, set: (v) => { batchCancelled = v; } });
window.PAGES = PAGES;
