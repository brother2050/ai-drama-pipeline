// MODULE: projects — 项目管理
// ══════════════════════════════════════════════════════════

async function loadProjects() {
  const el = document.getElementById('page-projects');
  el.innerHTML = `<div class="card"><h2>${t('common.loading')}</h2></div>`;
  try {
    const d = await api('/projects');
    const rows = (d.projects || []).map(p => {
      const switchBtn = p.active ? '' : `<button class="btn btn-sm btn-primary" onclick="switchProj('${esc(p.name)}')">${t('common.switch')}</button> `;
      const deleteBtn = (!p.active && !p.isDefault) ? `<button class="btn btn-sm btn-danger" onclick="deleteProj('${esc(p.name)}')">🗑</button>` : '';
      return `<tr><td>${p.active ? '→' : ''}</td><td>${esc(p.name)}</td><td class="dim" style="font-size:0.75rem">${esc(p.path)}</td><td>${p.active ? `<span class="badge badge-green">${t('common.current')}</span>` : switchBtn + deleteBtn}</td></tr>`;
    }).join('');

    el.innerHTML = `
      <style>
        .proj-section{margin-bottom:1rem}
        .proj-section h3{margin-bottom:.5rem;font-size:.95rem}
        .proj-status-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:.4rem}
        .proj-status-card{background:var(--bg2,#151922);padding:.5rem;border-radius:6px;text-align:center}
        .proj-status-card .num{font-size:1.2rem;font-weight:700}
        .proj-status-card .label{font-size:.72rem;color:var(--text-dim,#888)}
      </style>
      <div class="card">
        <div style="display:flex;justify-content:space-between;margin-bottom:1rem">
          <h2>${t('proj.title')}</h2>
          <div>
            <button class="btn btn-success" onclick="newProj()">+ ${t('btn.add')}</button>
            <button class="btn btn-primary" onclick="importJsonProj()" style="margin-left:.5rem">📥 导入剧本</button>
          </div>
        </div>
        <table><thead><tr><th></th><th>${t('common.name')}</th><th>${t('common.path')}</th><th>${t('common.status')}</th></tr></thead><tbody>${rows}</tbody></table>
      </div>
      <div id="ep-manager"></div>

      <div class="card" style="margin-top:1rem">
        <div class="proj-section">
          <h3>📊 ${t('drama.status')}</h3>
          <div id="proj-status" class="proj-status-grid"></div>
        </div>
      </div>`;

    loadEpisodeManager();
    _projLoadStatus();
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

async function _projLoadStatus() {
  const el = document.getElementById('proj-status');
  if (!el) return;
  try {
    const [chars, scenes, epsSummary] = await Promise.all([
      api('/characters'), api('/scenes'), api('/episodes/summary'),
    ]);
    const charCount = (chars.characters || chars || []).length;
    const sceneCount = (scenes.scenes || scenes || []).length;
    const eps = epsSummary.episodes || [];
    const totalShots = eps.reduce((s, e) => s + (e.shots || 0), 0);
    el.innerHTML = `
      <div class="proj-status-card"><div class="num">${charCount}</div><div class="label">${t('drama.st_chars')}</div></div>
      <div class="proj-status-card"><div class="num">${sceneCount}</div><div class="label">${t('drama.st_scenes')}</div></div>
      <div class="proj-status-card"><div class="num">${totalShots}</div><div class="label">${t('drama.st_shots')}</div></div>
      ${eps.map(e => `<div class="proj-status-card"><div class="num">${e.shots}</div><div class="label">第${e.episode}集</div></div>`).join('')}
    `;
  } catch { el.innerHTML = '<p class="dim">—</p>'; }
}

// ── AI 生成 ──

// ══════════════════════════════════════════════════════════
//  剧本 JSON 导入
// ══════════════════════════════════════════════════════════

async function importJsonProj() {
  // 加载预设
  let styles = {}, genres = {};
  try {
    const presets = await api('/projects/presets');
    styles = presets.styles || {};
    genres = presets.genres || {};
  } catch (e) { /* 回退 */ }

  const styleOpts = Object.entries(styles).map(([k, v]) => `<option value="${k}">${esc(k)} — ${esc(v)}</option>`).join('');
  const genreOpts = Object.entries(genres).map(([k, v]) => `<option value="${k}">${esc(k)} — ${esc(v)}</option>`).join('');

  const overlay = document.createElement('div');
  overlay.className = 'edit-overlay';
  overlay.innerHTML = `<div class="edit-panel" style="width:640px;max-height:85vh;display:flex;flex-direction:column">
    <div class="edit-header"><h3>📥 导入剧本</h3></div>
    <div class="edit-body" style="flex:1;overflow-y:auto">
      <p style="color:var(--text-dim,#888);font-size:.85rem;margin-bottom:.8rem">
        在 DeepSeek / Kimi / 豆包 等平台用提示词提取剧本为 JSON，粘贴到下方或上传 .json 文件。
      </p>
      <div style="margin-bottom:.8rem">
        <button class="btn btn-primary" id="_ij-gen-prompt" style="font-size:.85rem">📋 生成提示词</button>
        <span style="color:var(--text-dim,#888);font-size:.8rem;margin-left:.5rem">一键生成可粘贴到三方平台的完整提示词</span>
      </div>
      <div class="edit-field">
        <label style="font-size:.85rem;margin-bottom:.2rem;display:block">JSON 内容</label>
        <textarea id="_ij-json" style="width:100%;height:240px;font-family:monospace;font-size:.8rem;resize:vertical" placeholder='粘贴 JSON 到这里...'></textarea>
      </div>
      <div class="edit-field" style="margin-top:.6rem">
        <label style="font-size:.85rem;margin-bottom:.2rem;display:block">或上传文件</label>
        <input id="_ij-file" type="file" accept=".json" style="font-size:.85rem">
      </div>
      <div style="margin-top:.8rem;padding:.5rem .6rem;background:var(--bg3,#1a1e2e);border-radius:6px">
        <label style="font-size:.85rem;display:flex;align-items:center;gap:.4rem;cursor:pointer">
          <input id="_ij-append" type="checkbox" style="cursor:pointer">
          <span>🔄 追加模式 — 向已有项目追加分镜（解决 LLM 输出截断，分批导入时使用）</span>
        </label>
      </div>
      <div id="_ij-preview" style="margin-top:.8rem"></div>
    </div>
    <div class="edit-footer">
      <button class="btn btn-primary" id="_ij-ok">🚀 导入</button>
      <button class="btn btn-outline" id="_ij-cancel">取消</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);

  const jsonArea = overlay.querySelector('#_ij-json');
  const fileInput = overlay.querySelector('#_ij-file');
  const previewEl = overlay.querySelector('#_ij-preview');
  const okBtn = overlay.querySelector('#_ij-ok');
  const appendCb = overlay.querySelector('#_ij-append');

  // 📋 生成提示词
  overlay.querySelector('#_ij-gen-prompt').onclick = () => _showPromptGenerator(styles, genres, styleOpts, genreOpts);

  // 文件上传 → 读取到 textarea
  fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { jsonArea.value = reader.result; _ij_updatePreview(); };
    reader.readAsText(file);
  });

  // 实时预览校验结果
  let _ij_debounce = null;
  jsonArea.addEventListener('input', () => { clearTimeout(_ij_debounce); _ij_debounce = setTimeout(_ij_updatePreview, 500); });
  appendCb.addEventListener('change', _ij_updatePreview);

  function _ij_updatePreview() {
    const raw = jsonArea.value.trim();
    if (!raw) { previewEl.innerHTML = ''; return; }
    try {
      const data = JSON.parse(raw);
      const chars = (data.characters || []).length;
      const scenes = (data.scenes || []).length;
      const shots = (data.shots || []).length;
      const dur = (data.shots || []).reduce((s, sh) => s + (parseInt(sh.duration) || 4), 0);
      const isAppend = appendCb.checked;
      const modeLabel = isAppend ? '<span style="color:var(--blue,#60a5fa)">🔄 追加模式</span>' : '<span style="color:var(--green,#4ade80)">📦 全量导入</span>';
      const eps = [...new Set((data.shots || []).map(s => parseInt(s.episode) || 1))].sort((a,b) => a-b);
      const epLabel = eps.length > 0 ? `第${eps.length > 1 ? eps[0]+'-'+eps[eps.length-1] : eps[0]}集` : '';
      const parts = [];
      if (chars) parts.push(`${chars} 角色`);
      if (scenes) parts.push(`${scenes} 场景`);
      if (shots) parts.push(`${shots} 镜头`);
      if (epLabel) parts.push(epLabel);
      parts.push(`${dur}s (${(dur/60).toFixed(1)}分钟)`);
      const nameDisplay = data.project_name || (isAppend ? '(当前项目)' : '?');
      previewEl.innerHTML = `<div style="background:var(--bg3,#1a1e2e);padding:.6rem;border-radius:6px;font-size:.85rem">
        <b>预览：</b> ${isAppend ? '' : esc(nameDisplay) + ' | '}${parts.join(' | ')} | ${modeLabel}
        <br><span style="color:var(--green,#4ade80)">✅ JSON 格式正确</span>
        ${isAppend ? '<br><span style="color:var(--text-dim,#888)">将追加到当前活动项目，重复的镜头会被覆盖</span>' : ''}
      </div>`;
    } catch (e) {
      previewEl.innerHTML = `<div style="background:#fef3cd;color:#856404;padding:.6rem;border-radius:6px;font-size:.85rem">⚠ JSON 解析失败: ${esc(e.message)}</div>`;
    }
  }

  const cleanup = () => overlay.remove();

  overlay.querySelector('#_ij-cancel').onclick = cleanup;
  overlay.addEventListener('keydown', (e) => { if (e.key === 'Escape') cleanup(); });

  okBtn.onclick = async () => {
    const raw = jsonArea.value.trim();
    if (!raw) { jsonArea.focus(); return; }
    let data;
    try { data = JSON.parse(raw); } catch (e) { toast('JSON 格式错误: ' + e.message, 'error'); return; }

    if (appendCb.checked) {
      data.append = true;
    }

    okBtn.disabled = true;
    okBtn.textContent = '⏳ 提交中...';
    try {
      const r = await api('/import/json', { method: 'POST', body: data });
      toast(appendCb.checked ? '追加任务已提交' : '导入任务已提交');
      cleanup();
      await _pollImportTask(r.task_id);
    } catch (e) {
      toast('导入失败: ' + e.message, 'error');
      okBtn.disabled = false;
      okBtn.textContent = '🚀 导入';
    }
  };
}

// ══════════════════════════════════════════════════════════
//  提示词生成器（📋 生成提示词）
// ══════════════════════════════════════════════════════════

async function _showPromptGenerator(styles, genres, styleOpts, genreOpts) {
  const overlay = document.createElement('div');
  overlay.className = 'edit-overlay';
  overlay.innerHTML = `<div class="edit-panel" style="width:100vw;height:100vh;max-width:100%;max-height:100%;border-radius:0;display:flex;flex-direction:column">
    <div class="edit-header" style="flex-shrink:0">
      <h3>📋 提示词 — 复制到 DeepSeek / Kimi / 豆包</h3>
    </div>
    <div style="flex-shrink:0;padding:.8rem 1.2rem;background:var(--bg2,#151922);border-bottom:1px solid var(--border,#334155)">
      <div id="_pg-stats" style="margin-bottom:.6rem;display:none"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:.6rem 1rem;align-items:center;margin-bottom:.6rem">
        <div style="display:flex;align-items:center;gap:.4rem">
          <label style="font-size:.85rem;color:var(--text-dim,#888);white-space:nowrap;min-width:42px">项目名</label>
          <input id="_pg-name" type="text" value="我的短剧" style="flex:1;font-size:.85rem;padding:6px 10px;border:1px solid var(--border,#334155);border-radius:4px;background:var(--bg,#0f1117);color:var(--text,#e2e8f0)">
        </div>
        <div style="display:flex;align-items:center;gap:.4rem">
          <label style="font-size:.85rem;color:var(--text-dim,#888);white-space:nowrap;min-width:42px">风格</label>
          <input id="_pg-style" type="text" value="cinematic" list="_pg-style-list" style="flex:1;font-size:.85rem;padding:6px 10px;border:1px solid var(--border,#334155);border-radius:4px;background:var(--bg,#0f1117);color:var(--text,#e2e8f0)">
          <datalist id="_pg-style-list">${styleOpts}</datalist>
        </div>
        <div style="display:flex;align-items:center;gap:.4rem">
          <label style="font-size:.85rem;color:var(--text-dim,#888);white-space:nowrap;min-width:42px">题材</label>
          <input id="_pg-genre" type="text" value="urban" list="_pg-genre-list" style="flex:1;font-size:.85rem;padding:6px 10px;border:1px solid var(--border,#334155);border-radius:4px;background:var(--bg,#0f1117);color:var(--text,#e2e8f0)">
          <datalist id="_pg-genre-list">${genreOpts}</datalist>
        </div>
        <div style="display:flex;align-items:center;gap:.4rem">
          <label style="font-size:.85rem;color:var(--text-dim,#888);white-space:nowrap;min-width:42px">时长</label>
          <input id="_pg-duration" type="number" value="90" min="10" max="3600" style="width:80px;font-size:.85rem;padding:6px 10px;border:1px solid var(--border,#334155);border-radius:4px;background:var(--bg,#0f1117);color:var(--text,#e2e8f0)">
          <span style="font-size:.8rem;color:var(--text-dim,#888)">秒</span>
        </div>
        <div style="display:flex;align-items:center;gap:.4rem">
          <label style="font-size:.85rem;color:var(--text-dim,#888);white-space:nowrap;min-width:42px">集数</label>
          <input id="_pg-episode" type="number" value="1" min="1" max="100" style="width:80px;font-size:.85rem;padding:6px 10px;border:1px solid var(--border,#334155);border-radius:4px;background:var(--bg,#0f1117);color:var(--text,#e2e8f0)">
          <span style="font-size:.8rem;color:var(--text-dim,#888)">集</span>
        </div>
      </div>
      <div id="_pg-batch-fields" style="display:grid;grid-template-columns:1fr 1fr 2fr;gap:.6rem 1rem;align-items:center">
        <div style="display:flex;align-items:center;gap:.4rem">
          <label style="font-size:.85rem;color:var(--text-dim,#888);white-space:nowrap;min-width:42px">从第</label>
          <input id="_pg-shot-start" type="number" value="1" min="1" max="9999" style="width:80px;font-size:.85rem;padding:6px 10px;border:1px solid var(--border,#334155);border-radius:4px;background:var(--bg,#0f1117);color:var(--text,#e2e8f0)">
          <span style="font-size:.8rem;color:var(--text-dim,#888)">个镜头</span>
        </div>
        <div style="display:flex;align-items:center;gap:.4rem">
          <label style="font-size:.85rem;color:var(--text-dim,#888);white-space:nowrap;min-width:42px">到第</label>
          <input id="_pg-shot-end" type="number" value="50" min="1" max="9999" style="width:80px;font-size:.85rem;padding:6px 10px;border:1px solid var(--border,#334155);border-radius:4px;background:var(--bg,#0f1117);color:var(--text,#e2e8f0)">
          <span style="font-size:.8rem;color:var(--text-dim,#888)">个（建议每批不超过 100，太多 LLM 易截断）</span>
        </div>
        <div style="display:flex;align-items:center;gap:.4rem">
          <label style="font-size:.85rem;color:var(--text-dim,#888);white-space:nowrap;min-width:42px">衔接</label>
          <input id="_pg-last-shot" type="text" placeholder="留空则自动从项目最后镜头读取" style="flex:1;font-size:.85rem;padding:6px 10px;border:1px solid var(--border,#334155);border-radius:4px;background:var(--bg,#0f1117);color:var(--text,#e2e8f0)">
        </div>
      </div>
    </div>
    <div style="flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0">
      <textarea id="_pg-prompt" style="flex:1;width:100%;font-family:monospace;font-size:.85rem;line-height:1.6;resize:none;border:none;outline:none;padding:1rem 1.2rem;background:var(--bg,#0f1117);color:var(--text,#e2e8f0);min-height:0"></textarea>
    </div>
    <div class="edit-footer" style="flex-shrink:0;justify-content:space-between">
      <div style="display:flex;align-items:center;gap:1rem">
        <span id="_pg-char-count" style="color:var(--text-dim,#888);font-size:.8rem"></span>
        <button class="btn btn-sm btn-primary" id="_pg-refresh" style="font-size:.8rem">🔄 刷新提示词</button>
        <button class="btn btn-sm btn-outline" id="_pg-toggle-mode" style="font-size:.8rem">📝 切换到分镜提取</button>
      </div>
      <div>
        <button class="btn btn-primary" id="_pg-copy">📋 复制</button>
        <button class="btn btn-outline" id="_pg-close" style="margin-left:.5rem">关闭</button>
      </div>
    </div>
  </div>`;
  document.body.appendChild(overlay);

  const promptArea = overlay.querySelector('#_pg-prompt');
  const charCount = overlay.querySelector('#_pg-char-count');

  const updateCount = () => { charCount.textContent = `${promptArea.value.length} 字符`; };
  promptArea.addEventListener('input', updateCount);

  let _pg_mode = 'setup';
  async function loadPrompt() {
    const params = new URLSearchParams({
      project_name: overlay.querySelector('#_pg-name').value.trim() || '我的短剧',
      style: overlay.querySelector('#_pg-style').value.trim() || 'cinematic',
      genre: overlay.querySelector('#_pg-genre').value.trim() || 'urban',
      duration: overlay.querySelector('#_pg-duration').value || '90',
      episode: overlay.querySelector('#_pg-episode').value || '1',
      mode: _pg_mode,
      shot_start: overlay.querySelector('#_pg-shot-start').value || '1',
      shot_end: overlay.querySelector('#_pg-shot-end').value || '50',
      last_shot_info: overlay.querySelector('#_pg-last-shot').value.trim(),
    });
    try {
      const res = await api(`/import/prompt-template?${params.toString()}`);
      promptArea.value = res.prompt || '';
      updateCount();
      const statsEl = overlay.querySelector('#_pg-stats');
      if (statsEl && res.episodes_summary) {
        statsEl.style.display = '';
        statsEl.innerHTML = `<div style="padding:.4rem .6rem;background:var(--bg3,#1a1e2e);border-radius:4px;font-size:.8rem;color:var(--text-dim,#888)">
          📊 ${esc(res.episodes_summary)}
        </div>`;
      }
    } catch (e) {
      toast('加载失败: ' + e.message, 'error');
    }
  }

  loadPrompt();

  const _pg_batchFields = overlay.querySelector('#_pg-batch-fields');
  const _pg_toggleBtn = overlay.querySelector('#_pg-toggle-mode');

  function _pg_applyMode() {
    const isShots = _pg_mode === 'shots';
    _pg_batchFields.style.display = isShots ? '' : 'none';
    _pg_toggleBtn.textContent = isShots ? '🔙 切换到角色+场景' : '📝 切换到分镜提取';
  }
  _pg_applyMode();

  let _pg_batchDebounce = null;
  const _pg_debouncedLoad = () => { clearTimeout(_pg_batchDebounce); _pg_batchDebounce = setTimeout(loadPrompt, 400); };
  overlay.querySelector('#_pg-shot-start').addEventListener('input', _pg_debouncedLoad);
  overlay.querySelector('#_pg-shot-end').addEventListener('input', _pg_debouncedLoad);
  overlay.querySelector('#_pg-episode').addEventListener('input', _pg_debouncedLoad);

  overlay.querySelector('#_pg-refresh').onclick = loadPrompt;

  _pg_toggleBtn.onclick = () => {
    _pg_mode = _pg_mode === 'setup' ? 'shots' : 'setup';
    _pg_applyMode();
    loadPrompt();
  };

  overlay.querySelector('#_pg-copy').onclick = async () => {
    const text = promptArea.value;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast('✅ 已复制到剪贴板');
    } catch (e) {
      promptArea.select();
      document.execCommand('copy');
      toast('✅ 已复制到剪贴板');
    }
  };

  const cleanup = () => overlay.remove();
  overlay.querySelector('#_pg-close').onclick = cleanup;
  overlay.addEventListener('keydown', (e) => { if (e.key === 'Escape') cleanup(); });
}

async function _pollImportTask(taskId) {
  const maxWait = 300;
  const interval = 2;
  let waited = 0;
  while (waited < maxWait) {
    await new Promise(r => setTimeout(r, interval * 1000));
    waited += interval;
    try {
      const info = await api(`/tasks/${taskId}`);
      if (info.status === 'success') {
        const res = (typeof info.result === 'object' && info.result !== null) ? info.result : {};
        if (res.status === 'done') {
          if (res.mode === 'append') {
            const parts = [];
            if (res.added_characters) parts.push(`${res.added_characters}角色`);
            if (res.added_scenes) parts.push(`${res.added_scenes}场景`);
            if (res.added_shots) parts.push(`${res.added_shots}镜头`);
            toast(`✅ 追加成功！${parts.join(', ')}`);
          } else {
            toast(`✅ 导入成功！${res.project_name || ''} (${res.characters || 0}角色, ${res.scenes || 0}场景, ${res.shots || 0}镜头)`);
          }
          if (typeof _updateSidebarProject !== 'undefined') _updateSidebarProject();
          _cache.clear();
          loadProjects();
          return;
        }
        if (res.status === 'error') {
          const errs = (res.errors || []).slice(0, 5).map(e => `\n• ${e}`).join('');
          toast(`❌ ${res.reason || '导入失败'}${errs}`, 'error');
          return;
        }
      }
      if (info.status === 'failed') {
        toast('❌ 导入任务失败: ' + (info.result?.reason || info.result || '未知错误'), 'error');
        return;
      }
    } catch (e) { /* 继续轮询 */ }
  }
  toast('导入任务超时，请查看任务面板', 'warning');
}
async function newProj() {
  let styles = {}, genres = {};
  try {
    const presets = await api('/projects/presets');
    styles = presets.styles || {};
    genres = presets.genres || {};
  } catch (e) { /* 回退到默认值 */ }

  const styleOpts = Object.entries(styles).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
  const genreOpts = Object.entries(genres).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');

  return new Promise(resolve => {
    const o = document.createElement('div'); o.className = 'edit-overlay';
    o.innerHTML = `<div class="edit-panel" style="width:480px"><div class="edit-header"><h3>🎬 ${t('proj.create_title')}</h3></div>
      <div class="edit-body">
        <div class="edit-field">
          <label style="font-size:.85rem;margin-bottom:.2rem;display:block">${t('proj.name')}</label>
          <input id="_np-name" type="text" placeholder="${t('proj.name_ph')}" style="width:100%">
        </div>
        <div class="edit-field" style="margin-top:.6rem">
          <label style="font-size:.85rem;margin-bottom:.2rem;display:block">${t('proj.style')}</label>
          <input id="_np-style" type="text" value="cinematic" list="_np-style-list" style="width:100%" placeholder="输入或选择风格">
          <datalist id="_np-style-list">${styleOpts}</datalist>
        </div>
        <div class="edit-field" style="margin-top:.6rem">
          <label style="font-size:.85rem;margin-bottom:.2rem;display:block">${t('proj.genre')}</label>
          <input id="_np-genre" type="text" value="urban" list="_np-genre-list" style="width:100%" placeholder="输入或选择题材">
          <datalist id="_np-genre-list">${genreOpts}</datalist>
        </div>
      </div>
      <div class="edit-footer"><button class="btn btn-primary" id="_np-ok">${t('btn.confirm')}</button>
      <button class="btn btn-outline" id="_np-cancel">${t('btn.cancel')}</button></div></div>`;
    document.body.appendChild(o);
    const nameInp = o.querySelector('#_np-name');
    const cleanup = (result) => { o.remove(); resolve(result); };
    o.querySelector('#_np-ok').onclick = () => {
      const name = nameInp.value.trim();
      if (!name) { nameInp.focus(); return; }
      cleanup({
        name,
        style: o.querySelector('#_np-style').value,
        genre: o.querySelector('#_np-genre').value,
      });
    };
    o.querySelector('#_np-cancel').onclick = () => cleanup(null);
    nameInp.focus();
    nameInp.addEventListener('keydown', (e) => { if (e.key === 'Enter') o.querySelector('#_np-ok').click(); if (e.key === 'Escape') cleanup(null); });
  }).then(result => {
    if (!result) return;
    api('/projects/new', { method: 'POST', body: result }).then(() => {
      toast(t('toast.created'));
      _cache.clear();
      if (typeof _updateSidebarProject !== 'undefined') _updateSidebarProject();
      loadProjects();
    }).catch(e => toast(e.message, 'error'));
  });
}
async function switchProj(name) {
  try {
    await api('/projects/switch', { method: 'POST', body: { name } });
    _cache.clear();
    Object.keys(_charNameMap).forEach(k => delete _charNameMap[k]);
    Object.keys(_sceneNameMap).forEach(k => delete _sceneNameMap[k]);
    _undoStack.length = 0;
    _redoStack.length = 0;
    _sbDirty = false;
    ep = 1;
    toast(t('toast.switched'));
    if (typeof _updateSidebarProject !== 'undefined') _updateSidebarProject();
    loadProjects();
    const p = document.querySelector('.page.active');
    if (p) { const pageName = p.id.replace('page-', ''); const fn = PAGES[pageName]; if (fn && typeof window[fn] === 'function') window[fn](); }
  } catch (e) { toast(e.message, 'error'); }
}
async function deleteProj(n) {
  if (!await modalConfirm(t('proj.confirm_delete', { name: n }))) return;
  api(`/projects/${encodeURIComponent(n)}`, { method: 'DELETE' }).then(() => {
    _cache.clear();
    toast(t('proj.deleted'));
    if (typeof _updateSidebarProject !== 'undefined') _updateSidebarProject();
    loadProjects();
  }).catch(e => toast(e.message, 'error'));
}


// ══════════════════════════════════════════════════════════

// ── Module: projects ──
Drama.pages.projects = loadProjects;
window.loadProjects = loadProjects;
window.newProj = newProj;
window.switchProj = switchProj;
window.deleteProj = deleteProj;
window.importJsonProj = importJsonProj;
window._showPromptGenerator = _showPromptGenerator;
