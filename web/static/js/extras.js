// MODULE: extras — 辅助功能
// ══════════════════════════════════════════════════════════
// ── 3.1 拖拽排序 ──

function _initSortable() {
  const tbody = document.querySelector('#page-storyboard tbody');
  if (!tbody || !window.Sortable) return;
  Sortable.create(tbody, {
    animation: 150,
    handle: '.drag-handle',
    ghostClass: 'sortable-ghost',
    chosenClass: 'sortable-chosen',
    onEnd: async function(evt) {
      if (evt.oldIndex === evt.newIndex) return;
      const [moved] = shots.splice(evt.oldIndex, 1);
      shots.splice(evt.newIndex, 0, moved);
      pushUndo(t('sb.reordered'));
      try {
        await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
        invalidateCache(`storyboard/${ep}`);
        toast(t('sb.reordered'));
      } catch (e) { toast(e.message, 'error'); }
      const scrollY = window.scrollY;
      await loadStoryboard();
      window.scrollTo(0, scrollY);
    }
  });
}

function _initTimelineSortable() {
  const container = document.querySelector('.timeline-container');
  if (!container || !window.Sortable) return;
  Sortable.create(container, {
    animation: 150,
    handle: '.timeline-card',
    ghostClass: 'sortable-ghost',
    chosenClass: 'sortable-chosen',
    onEnd: async function(evt) {
      if (evt.oldIndex === evt.newIndex) return;
      const [moved] = shots.splice(evt.oldIndex, 1);
      shots.splice(evt.newIndex, 0, moved);
      pushUndo(t('sb.reordered'));
      try {
        await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
        invalidateCache(`storyboard/${ep}`);
        toast(t('sb.reordered'));
      } catch (e) { toast(e.message, 'error'); }
      const scrollY = window.scrollY;
      await loadStoryboard();
      window.scrollTo(0, scrollY);
    }
  });
}

// ── 3.2 批量导入/导出 ──

/** CSV 字段转义（处理换行、逗号、引号） */
function _csvEscape(s) {
  const v = String(s || '');
  if (v.includes('"') || v.includes(',') || v.includes('\n') || v.includes('\r')) {
    return `"${v.replace(/"/g, '""')}"`;
  }
  return v;
}

/** CSV 解析（支持多行字段、含引号/逗号的字段） */
function _parseCSV(text) {
  const rows = []; let row = []; let field = ''; let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += ch;
    } else {
      if (ch === '"') inQuotes = true;
      else if (ch === ',') { row.push(field.trim()); field = ''; }
      else if (ch === '\n' || (ch === '\r' && text[i + 1] === '\n')) {
        if (ch === '\r') i++;
        row.push(field.trim()); field = '';
        if (row.some(f => f)) rows.push(row);
        row = [];
      } else field += ch;
    }
  }
  row.push(field.trim());
  if (row.some(f => f)) rows.push(row);
  return rows;
}

function exportStoryboard() {
  const headers = ['shot_id', 'scene_id', 'characters', 'action', 'action_en', 'dialogue', 'dialogue_en', 'camera', 'shot_type', 'duration', 'emotion', 'language', 'outfit'];
  const csv = [headers.map(h => _csvEscape(h)).join(',')];
  shots.forEach(s => {
    csv.push(headers.map(h => _csvEscape(s[h])).join(','));
  });
  const blob = new Blob(['\uFEFF' + csv.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = `storyboard_ep${ep}.csv`;
  a.click(); URL.revokeObjectURL(url);
  toast(t('sb.export_done', { n: shots.length }));
}

function showImportDialog() {
  _showOverlay('import-overlay', t('sb.import_title'), `
    <div class="edit-field"><label>${t('sb.import_file')}</label>
      <input type="file" id="import-file" accept=".csv,.json" style="display:block;margin-top:.3rem"></div>
    <div class="edit-field"><label>${t('sb.import_mode')}</label>
      <select id="import-mode"><option value="merge">${t('sb.import_merge')}</option><option value="overwrite">${t('sb.import_overwrite')}</option></select></div>
    <div id="import-status" class="dim" style="margin-top:.5rem"></div>`, `doImport()`, `📥 ${t('sb.import')}`);
}

async function doImport() {
  const fileInput = document.getElementById('import-file');
  const mode = document.getElementById('import-mode')?.value || 'merge';
  const statusEl = document.getElementById('import-status');
  if (!fileInput?.files?.[0]) { toast(t('sb.import_file'), 'error'); return; }

  const file = fileInput.files[0];
  const text = await file.text();
  let newShots = [];

  try {
    if (file.name.endsWith('.json')) {
      const data = JSON.parse(text);
      newShots = Array.isArray(data) ? data : (data.shots || []);
    } else {
      // CSV（支持多行字段）
      const rows = _parseCSV(text);
      if (rows.length < 2) throw new Error('Empty CSV');
      const headers = rows[0];
      for (let i = 1; i < rows.length; i++) {
        const shot = {};
        headers.forEach((h, j) => { shot[h] = rows[i][j] || ''; });
        if (shot.shot_id) newShots.push(shot);
      }
    }
  } catch (e) { _html(statusEl, `❌ ${t('sb.import_parse_err')}: ${e.message}`); return; }

  if (!newShots.length) { _html(statusEl, `❌ ${t('sb.import_parse_err')}`); return; }

  // 确保导入的镜头带有正确的 episode 字段（导出 CSV 不含此列）
  newShots.forEach(s => { if (!s.episode) s.episode = String(ep); });

  const finalShots = mode === 'overwrite' ? newShots : [...(await api(`/storyboard/${ep}`)).shots, ...newShots];
  try {
    await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: finalShots } });
    shots = finalShots;
    invalidateCache(`storyboard/${ep}`);
    document.getElementById('import-overlay')?.remove();
    toast(t('sb.import_done', { n: newShots.length }));
    loadStoryboard();
  } catch (e) { toast(e.message, 'error'); }
}

// ── 3.3 引用计数 ──

async function _getRefCounts(type) {
  try {
    const eps = await loadEpisodeSelector();
    const counts = {};
    for (const e of eps) {
      const d = await cachedFetch(`storyboard/${e}`, () => api(`/storyboard/${e}`));
      (d.shots || []).forEach(s => {
        const names = (type === 'characters' ? s.characters : s.scene_id) || '';
        names.split(/[+、,]/).map(n => n.trim()).filter(Boolean).forEach(n => { counts[n] = (counts[n] || 0) + 1; });
      });
    }
    return counts;
  } catch { return {}; }
}

async function deleteCharWithRef(id) {
  const counts = await _getRefCounts('characters');
  const count = counts[id] || 0;
  if (count > 0) {
    if (!await modalConfirm(t('char.confirm_delete_ref', { n: count }))) return;
  }
  _crudDelete('characters', id, t('char.title'), loadCharacters);
}

async function deleteSceneWithRef(id) {
  const counts = await _getRefCounts('scenes');
  const count = counts[id] || 0;
  if (count > 0) {
    if (!await modalConfirm(t('scene.confirm_delete_ref', { n: count }))) return;
  }
  _crudDelete('scenes', id, t('scene.title'), loadScenes);
}

// ── 3.4 配置预设模板 ──

const CONFIG_PRESETS = {
  local_comfyui: {
    tts: { backend: 'gpt-sovits', url: 'http://127.0.0.1:9880' },
    lipsync: { backend: 'sadtalker', url: 'http://127.0.0.1:7860' },
    comfyui: { url: 'http://127.0.0.1:8188', api_key: '' },
    image_backend: 'sd15', video_backend: 'animatediff',
    llm: { enabled: false, backend: 'ollama', base_url: 'http://127.0.0.1:11434', model: 'qwen2.5:7b', api_key: '' },
  },
  cloud_siliconflow: {
    tts: { backend: 'mimo-voicedesign', url: 'https://api.siliconflow.cn/v1' },
    lipsync: { backend: 'musetalk', url: 'http://127.0.0.1:7860' },
    comfyui: { url: 'http://127.0.0.1:8188', api_key: '' },
    image_backend: 'sd15', video_backend: 'animatediff',
    llm: { enabled: true, backend: 'openai', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-7B-Instruct', api_key: '' },
  },
  ollama_local: {
    tts: { backend: 'mimo-voicedesign', url: '' },
    lipsync: { backend: 'musetalk', url: 'http://127.0.0.1:7860' },
    comfyui: { url: 'http://127.0.0.1:8188', api_key: '' },
    image_backend: 'sd15', video_backend: 'animatediff',
    llm: { enabled: true, backend: 'ollama', base_url: 'http://127.0.0.1:11434', model: 'qwen2.5:7b', api_key: '' },
  },
};

function applyPreset(key) {
  const p = CONFIG_PRESETS[key];
  if (!p) return;
  // TTS
  const ttsSel = document.getElementById('cfg-tts');
  if (ttsSel) { ttsSel.value = p.tts.backend; }
  const ttsUrl = document.getElementById('cfg-tts-url');
  if (ttsUrl) ttsUrl.value = p.tts.url;
  // LipSync
  const lsSel = document.getElementById('cfg-lipsync');
  if (lsSel) { lsSel.value = p.lipsync.backend; }
  const lsUrl = document.getElementById('cfg-lipsync-url');
  if (lsUrl) lsUrl.value = p.lipsync.url;
  // ComfyUI
  const cuUrl = document.getElementById('cfg-comfyui');
  if (cuUrl) cuUrl.value = p.comfyui.url;
  const cuKey = document.getElementById('cfg-comfyui-key');
  if (cuKey) cuKey.value = p.comfyui.api_key || '';
  // Image / Video backend
  const imgSel = document.getElementById('cfg-image-backend');
  if (imgSel && p.image_backend) imgSel.value = p.image_backend;
  const vidSel = document.getElementById('cfg-video-backend');
  if (vidSel && p.video_backend) vidSel.value = p.video_backend;
  // LLM
  const llmEnabled = document.getElementById('cfg-llm-enabled');
  if (llmEnabled) llmEnabled.value = String(p.llm.enabled);
  const llmBackend = document.getElementById('cfg-llm-backend');
  if (llmBackend) llmBackend.value = p.llm.backend;
  const llmUrl = document.getElementById('cfg-llm-url');
  if (llmUrl) llmUrl.value = p.llm.base_url;
  const llmModel = document.getElementById('cfg-llm-model');
  if (llmModel) llmModel.value = p.llm.model;
  toast(t('set.preset_applied'));
  saveCfg();
}

// ── 3.5 成片预览 ──

async function _loadFinalPreview() {
  const el = document.getElementById('final-preview-area');
  if (!el) return;
  try {
    const r = await api(`/shots/${ep}/final/resources`).catch(() => ({ resources: {} }));
    if (r.resources?.final) {
      const fname = r.resources.final;
      el.innerHTML = `<div class="final-preview-wrap">
        <video controls src="/api/files/${ep}/final/${fname}" style="max-width:100%;max-height:400px;border-radius:8px;background:#000" onerror="this.outerHTML='<p class=\\'dim\\'>视频加载失败</p>'"></video>
        <div style="margin-top:.5rem"><a href="/api/files/${ep}/final/${fname}" download class="btn btn-outline">⬇ ${t('wb.download')}</a></div></div>`;
    } else {
      el.innerHTML = `<div class="final-preview-wrap"><div style="font-size:2rem;opacity:.3">🎬</div><p class="dim">${t('wb.no_final')}</p><p class="dim" style="font-size:.76rem">${t('wb.no_final_hint')}</p></div>`;
    }
  } catch {
    el.innerHTML = `<div class="final-preview-wrap"><div style="font-size:2rem;opacity:.3">🎬</div><p class="dim">${t('wb.no_final')}</p></div>`;
  }
}

// ── 4.1 对话式编辑 ──

let _chatOpen = false;
let _chatHistory = [];
let _chatSending = false;

function toggleChat() {
  _chatOpen = !_chatOpen;
  let panel = document.getElementById('chat-panel');
  if (_chatOpen) {
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'chat-panel';
      panel.className = 'chat-panel';
      panel.innerHTML = `<div class="chat-header"><span>${t('chat.title')}</span><button class="btn btn-xs btn-outline" onclick="toggleChat()">✕</button></div>
        <div class="chat-messages" id="chat-messages"></div>
        <div class="chat-input-row"><textarea id="chat-input" rows="2" placeholder="${t('chat.placeholder')}" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChatMsg()}"></textarea>
          <button class="btn btn-primary" onclick="sendChatMsg()">${t('chat.send')}</button></div>`;
      document.body.appendChild(panel);
    }
    panel.style.display = 'flex';
    document.getElementById('chat-input')?.focus();
    _renderChatHistory();
  } else if (panel) {
    panel.style.display = 'none';
  }
}

function _renderChatHistory() {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  el.innerHTML = _chatHistory.map(m => `<div class="chat-msg chat-msg-${m.role}">${esc(m.text)}</div>`).join('');
  el.scrollTop = el.scrollHeight;
}

async function sendChatMsg() {
  if (_chatSending) return;
  const input = document.getElementById('chat-input');
  const text = input?.value?.trim();
  if (!text) { toast(t('chat.empty'), 'error'); return; }
  input.value = '';
  _chatSending = true;
  _chatHistory.push({ role: 'user', text });
  if (_chatHistory.length > 100) _chatHistory.splice(0, _chatHistory.length - 100);
  _renderChatHistory();

  _chatHistory.push({ role: 'ai', text: t('chat.thinking') });
  _renderChatHistory();

  try {
    const { task_id } = await api('/llm/chat-edit', { method: 'POST', body: { episode: ep, message: text, shots } });
    if (typeof TaskPanel !== "undefined") TaskPanel.trackTask(task_id, "AI 编辑");
    const result = await pollTask(task_id);
    _chatHistory.pop(); // remove thinking

    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      _chatHistory.push({ role: 'ai', text: `${t('chat.success')}\n${r.message || ''}` });
      if (r.shots && Array.isArray(r.shots)) {
        // 校验并补全缺失字段
        const defaults = _DEFAULT_SHOT();
        r.shots = r.shots.map((s, i) => {
          const merged = { ...defaults, ...s };
          if (!merged.shot_id) merged.shot_id = String(i + 1).padStart(3, '0');
          merged.duration = parseInt(merged.duration) || 4;
          return merged;
        });
        shots = r.shots;
        await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
        invalidateCache(`storyboard/${ep}`);
        const p = document.querySelector('.page.active');
        if (p?.id === 'page-storyboard') loadStoryboard();
        else if (p?.id === 'page-pipeline') { renderShotsGrid(); }
      }
    } else {
      const err = result.result?.reason || result.error || t('chat.error');
      _chatHistory.push({ role: 'err', text: `❌ ${err}` });
    }
  } catch (e) {
    _chatHistory.pop();
    _chatHistory.push({ role: 'err', text: `❌ ${e.message}` });
  } finally {
    _chatSending = false;
  }
  _renderChatHistory();
}

// ── 4.2 主体库管理 ──

async function loadAssets() {
  const el = document.getElementById('page-assets');
  el.innerHTML = `<div class="card"><h2>${t('common.loading')}</h2></div>`;
  try {
    const [charData, sceneData] = await Promise.all([
      api('/assets/shared/characters').catch(() => ({ assets: [] })),
      api('/assets/shared/scenes').catch(() => ({ assets: [] })),
    ]);
    const chars = charData.assets || [];
    const scenes = sceneData.assets || [];

    const charCards = chars.map(c => {
      const thumb = c.reference_images?.length ? `<img src="${esc(c.reference_images[0])}" loading="lazy">` : '👤';
      return `<div class="asset-card"><div class="asset-card-thumb">${thumb}</div><div class="asset-card-info"><h4>${esc(c.name || c.id)}</h4><p>${esc(c.appearance || '')}</p></div><button class="btn btn-xs btn-outline" onclick="copyAssetToProject('characters','${esc(c.id)}')">${t('asset.copy_to_proj')}</button></div>`;
    }).join('');
    const sceneCards = scenes.map(s => {
      const thumb = s.reference_images?.length ? `<img src="${esc(s.reference_images[0])}" loading="lazy">` : '🏔';
      return `<div class="asset-card"><div class="asset-card-thumb">${thumb}</div><div class="asset-card-info"><h4>${esc(s.name || s.id)}</h4><p>${esc(s.description || '')}</p></div><button class="btn btn-xs btn-outline" onclick="copyAssetToProject('scenes','${esc(s.id)}')">${t('asset.copy_to_proj')}</button></div>`;
    }).join('');

    const allCards = charCards + sceneCards;
    el.innerHTML = `<div class="card"><h2>${t('asset.title')}</h2><p class="dim" style="margin-bottom:1rem">${t('asset.desc')}</p>
      ${allCards ? `<div style="display:flex;flex-direction:column;gap:.5rem">${allCards}</div>` : `<div class="empty-state"><div class="empty-state-icon">📦</div><h3>${t('asset.empty')}</h3><p>${t('asset.empty_hint')}</p></div>`}</div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

async function copyAssetToProject(type, id) {
  try {
    await api(`/assets/shared/${type}/${id}/copy`, { method: 'POST' });
    invalidateCache(type);
    toast(t('asset.copied'));
  } catch (e) { toast(e.message, 'error'); }
}

async function addToSharedLibrary(type, id) {
  try {
    await api(`/assets/${type}/${id}/share`, { method: 'POST' });
    toast(t('asset.copied'));
  } catch (e) { toast(e.message, 'error'); }
}

// ── 4.3 多剧集管理 ──

async function loadEpisodeManager() {
  // This is embedded in the projects page
  const el = document.getElementById('ep-manager');
  if (!el) return;
  try {
    const d = await api('/episodes/summary');
    const episodes = d.episodes || [];
    if (!episodes.length) {
      el.innerHTML = `<div class="card" style="margin-top:1rem"><h2>${t('ep.title')}</h2><p class="dim">暂无剧集</p></div>`;
      return;
    }
    const cards = episodes.map(ep => {
      const statusKey = `ep.status_${ep.status}`;
      const badgeClass = ep.status === 'done' ? 'badge-green' : ep.status === 'progress' ? 'badge' : '';
      return `<div class="ep-card"><div class="ep-card-clickable" onclick="ep=${ep.episode};navTo('pipeline')"><div class="ep-card-num">EP ${ep.episode}</div><div class="ep-card-meta">${ep.shots} ${t('ep.shots')} · ${ep.duration}s · ${ep.done}/${ep.shots} ✅</div><div class="ep-card-status"><span class="badge ${badgeClass}">${t(statusKey)}</span></div></div><div class="ep-card-actions"><button class="btn btn-xs btn-outline" onclick="event.stopPropagation();clearEpisodeOutputs(${ep.episode})" title="${t('ep.clear_outputs')}">🧹</button><button class="btn btn-xs btn-danger" onclick="event.stopPropagation();deleteEpisode(${ep.episode})" title="${t('btn.delete')}">🗑</button></div></div>`;
    });
    el.innerHTML = `<div class="card" style="margin-top:1rem"><h2>${t('ep.title')}</h2><div class="ep-grid">${cards.join('')}</div></div>`;
  } catch (e) { el.innerHTML = `<div class="dim">${e.message}</div>`; }
}

async function deleteEpisode(episode) {
  if (!await modalConfirm(t('ep.confirm_delete', { ep: episode }))) return;
  try {
    const r = await api(`/episodes/${episode}`, { method: 'DELETE' });
    _cache.clear();
    toast(t('ep.deleted', { ep: episode, n: r.removed_shots || 0 }));
    // 如果删除的是当前集，切到最小可用集
    const d = await api('/episodes');
    const eps = d.episodes || [1];
    if (!eps.includes(ep)) ep = Math.min(...eps);
    loadEpisodeManager();
    // 刷新当前页面
    const p = document.querySelector('.page.active');
    if (p) { const pageName = p.id.replace('page-', ''); const fn = PAGES[pageName]; if (fn && typeof window[fn] === 'function') window[fn](); }
  } catch (e) { toast(e.message, 'error'); }
}

async function clearEpisodeOutputs(episode) {
  if (!await modalConfirm(t('ep.confirm_clear', { ep: episode }))) return;
  try {
    const r = await api(`/episodes/${episode}/clear`, { method: 'POST' });
    invalidateCache(`storyboard/${episode}`);
    invalidateCache(`res/${episode}`);
    toast(t('ep.cleared', { ep: episode, n: r.cleared_files || 0 }));
    loadEpisodeManager();
  } catch (e) { toast(e.message, 'error'); }
}

// ── 4.4 Worker 实时状态 ──

async function _updateWorkerStatus() {
  const el = document.getElementById('sidebar-worker');
  if (!el) return;
  try {
    const r = await api('/system/workers').catch(() => ({ active: 0, status: 'offline' }));
    if (r.status === 'offline') {
      el.innerHTML = `<span class="status-dot err"></span> ${t('worker.offline')}`;
    } else if (r.active > 0) {
      el.innerHTML = `<span class="status-dot ok"></span> ${t('worker.running')} · ${t('worker.tasks', { n: r.active })}`;
    } else {
      el.innerHTML = `<span class="status-dot ok"></span> ${t('worker.idle')}`;
    }
  } catch {
    el.innerHTML = `<span class="status-dot err"></span> ${t('worker.offline')}`;
  }
}

// Poll worker status every 15 seconds
setInterval(_updateWorkerStatus, 15000);

applyI18n();
_updateWorkerStatus();
loadDashboard();

// ── Module: extras ──
Drama.extras = {
  exportStoryboard, showImportDialog, doImport,
  deleteCharWithRef, deleteSceneWithRef,
  applyPreset, CONFIG_PRESETS,
  _initSortable, _initTimelineSortable,
  _loadFinalPreview, _showPromptGenerator,
};
Drama.pages.assets = typeof loadAssets !== 'undefined' ? loadAssets : undefined;
window.exportStoryboard = exportStoryboard;
window.showImportDialog = showImportDialog;
window.doImport = doImport;
window.deleteCharWithRef = deleteCharWithRef;
window.deleteSceneWithRef = deleteSceneWithRef;
window.applyPreset = applyPreset;
window._initSortable = _initSortable;
window._initTimelineSortable = _initTimelineSortable;
window._loadFinalPreview = _loadFinalPreview;
if (typeof loadAssets !== 'undefined') window.loadAssets = loadAssets;
