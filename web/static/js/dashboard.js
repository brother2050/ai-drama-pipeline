// MODULE: core — 通用 CRUD
// ══════════════════════════════════════════════════════════

function _crudTable(cols, items, editFn, delFn) {
  const ths = cols.map(c => `<th>${c.label}</th>`).join('') + `<th>${t('common.operations')}</th>`;
  const rows = items.length
    ? items.map(it => {
      const tds = cols.map(c => `<td>${c.render ? c.render(it) : esc(it[c.key] || '')}</td>`).join('');
      return `<tr>${tds}<td><button class="btn btn-xs" onclick="${editFn}('${it.id}')">✏</button>
        <button class="btn btn-xs btn-danger" onclick="${delFn}('${it.id}')">🗑</button></td></tr>`;
    }).join('')
    : `<tr><td colspan="${cols.length + 1}" class="dim" style="text-align:center">${t('common.none')}</td></tr>`;
  return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
}

function _crudPage(title, cols, items, editFn, delFn, newFn, emptyHint) {
  const table = _crudTable(cols, items, editFn, delFn);
  const hint = !items.length && emptyHint ? `<p class="dim" style="margin-top:0.5rem;font-size:0.85rem">${emptyHint}</p>` : '';
  return `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem">
    <h2>${title}</h2><button class="btn btn-success" onclick="${newFn}()">+ ${t('btn.add')}</button></div>${table}${hint}</div>`;
}

async function _crudDelete(endpoint, id, label, reload) {
  if (!await modalConfirm(`${label} ${id}？`)) return;
  try { await api(`/${endpoint}/${id}`, { method: 'DELETE' }); invalidateCache(endpoint); toast(t('toast.deleted')); reload(); } catch (e) { toast(e.message, 'error'); }
}
async function _crudSave(endpoint, id, fieldsFn, overlayId, reload) {
  try { await api(`/${endpoint}`, { method: 'POST', body: { id, ...fieldsFn() } }); invalidateCache(endpoint); document.getElementById(overlayId)?.remove(); toast(t('toast.saved')); reload(); } catch (e) { toast(e.message, 'error'); }
}

function _showOverlay(id, title, bodyHtml, saveFn, saveLabel, deleteFn) {
  const btnText = saveLabel || `💾 ${t('btn.save')}`;
  const deleteBtn = deleteFn ? `<button class="btn btn-danger" onclick="${deleteFn}" style="margin-right:auto">🗑 ${t('btn.delete')}</button>` : '';
  const o = document.createElement('div'); o.className = 'edit-overlay'; o.id = id;
  o.innerHTML = `<div class="edit-panel"><div class="edit-header"><h3>${esc(title)}</h3>
    <button class="btn btn-sm btn-outline" onclick="document.getElementById('${id}')?.remove()">✕</button></div>
    <div class="edit-body">${bodyHtml}</div><div class="edit-footer">
    ${deleteBtn}<button class="btn btn-primary" onclick="${saveFn}">${btnText}</button>
    <button class="btn btn-outline" onclick="document.getElementById('${id}')?.remove()">${t('btn.cancel')}</button></div></div>`;
  document.body.appendChild(o);
  o.querySelector('input,textarea')?.focus();
}


// ══════════════════════════════════════════════════════════
// MODULE: dashboard — 仪表盘
// ══════════════════════════════════════════════════════════

const TOOL_META = { redis:{icon:'🔴',label:'Redis'}, celery:{icon:'🔧',label:'Celery'}, ffmpeg:{icon:'🎞',label:'FFmpeg'}, tts:{icon:'🎤',label:'TTS'}, comfyui:{icon:'🎨',label:'ComfyUI'}, lipsync:{icon:'👄',label:'LipSync'}, llm:{icon:'🧠',label:'LLM'}, music:{icon:'🎵',label:'Music'}, seko:{icon:'🎬',label:'Seko'}, training:{icon:'🏋',label:'Training'} };

function _setupGuide(tools) {
  const missing = [];
  const redis = tools.redis || {};
  const celery = tools.celery || {};
  const comfyui = tools.comfyui || {};
  const tts = tools.tts || {};
  const lipsync = tools.lipsync || {};
  if (!redis.available) missing.push({ icon: '🔴', name: 'Redis', fix: 'redis-server --daemonize yes', hint: '任务队列（必选）', critical: true });
  if (!celery.available) missing.push({ icon: '🔧', name: 'Celery Worker', fix: 'drama worker', hint: '异步任务处理（必选）', critical: true });
  if (!comfyui.available) missing.push({ icon: '🎨', name: 'ComfyUI', fix: '启动 ComfyUI 并在设置中配置 URL', hint: '图片/视频生成（生产必须）' });
  if (!tts.available) missing.push({ icon: '🎤', name: 'TTS', fix: '配置 MIMO_API_KEY 或启动本地 TTS 服务', hint: '语音合成（生产必须）' });
  if (!lipsync.available) missing.push({ icon: '👄', name: 'LipSync', fix: '启动 MuseTalk/Wav2Lip 服务', hint: '口型同步（生产必须）' });
  if (!missing.length) return '';
  const items = missing.map(m =>
    `<div style="display:flex;align-items:center;gap:.5rem;padding:.4rem 0">
      <span>${m.icon}</span><b>${m.name}</b>${m.critical ? '<span style="color:var(--red);font-size:.75rem">必选</span>' : ''}
      <span class="dim">— ${m.hint}</span>
      <code style="margin-left:auto;background:var(--bg2);padding:.2rem .5rem;border-radius:4px;font-size:.82rem">${esc(m.fix)}</code>
    </div>`
  ).join('');
  return `<div class="card" style="border:1px solid var(--red);background:rgba(255,80,80,.06)">
    <h2 style="color:var(--red)">⚠ ${t('dash.setup_title')}</h2>
    <p style="font-size:.88rem;margin-bottom:.5rem">${t('dash.setup_desc')}</p>
    ${items}
    <p class="dim" style="font-size:.8rem;margin-top:.5rem">${t('dash.setup_hint')}</p>
  </div>`;
}

async function loadDashboard() {
  const el = document.getElementById('page-dashboard');
  try {
    const [s, projData, sbData, epsSummary] = await Promise.all([
      cachedFetch('system/status', () => api('/system/status'), 10000),
      cachedFetch('projects', () => api('/projects'), 30000).catch(() => ({ projects: [] })),
      cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`), 30000).catch(() => ({ shots: [] })),
      cachedFetch('episodes/summary', () => api('/episodes/summary'), 30000).catch(() => ({ episodes: [] })),
    ]);
    const tools = s.tools || {};
    const okCount = Object.values(tools).filter(t => t.available).length;
    const totalCount = Object.keys(tools).length;
    const shots = sbData.shots || [];
    const projects = projData.projects || [];
    const currentProj = projects.find(p => p.active) || projects[0] || { name: '' };
    const totalShots = (epsSummary.episodes || []).reduce((sum, e) => sum + (e.shots || 0), 0);

    // 工具状态分组
    const groups = [
      { label: t('dash.infra'), keys: ['redis', 'celery', 'ffmpeg'] },
      { label: t('dash.ai_tools'), keys: ['tts', 'music', 'seko', 'training'] },
      { label: t('dash.gpu_tools'), keys: ['comfyui', 'lipsync', 'llm'] },
    ];
    let toolHtml = '';
    for (const g of groups) {
      toolHtml += `<div class="section-label">${g.label}</div><div class="tool-grid">`;
      for (const k of g.keys) {
        const info = tools[k] || {}, meta = TOOL_META[k] || {};
        toolHtml += `<div class="tool-card ${info.available ? 'tool-ok' : 'tool-off'}"><span>${meta.icon} ${meta.label}</span>
          <span class="status-dot ${info.available ? 'ok' : 'err'}"></span>
          <span class="dim" style="font-size:0.75rem">${info.available ? t('dash.available') : info.reason || t('dash.unavailable')}</span></div>`;
      }
      toolHtml += '</div>';
    }

    el.innerHTML = `
      <div class="dash-hero">
        <h1>${currentProj?.name ? `🎬 ${currentProj.name}` : t('app.title')}</h1>
        <p>${t('dash.welcome_desc')}</p>
        <div class="inspire-box">
          <textarea id="dash-inspire-input" class="inspire-input" rows="3" placeholder="${esc(t('dash.inspire_placeholder'))}"></textarea>
          <div class="inspire-footer">
            <div class="inspire-options">
              <label class="inspire-toggle" onclick="document.getElementById('inspire-adv').classList.toggle('open')">${t('dash.inspire_advanced')}</label>
              <div id="inspire-adv" class="inspire-advanced">
                <div class="inspire-adv-row">
                  <label>${t('dash.inspire_ep')}</label>
                  <input id="dash-inspire-ep" type="number" value="${ep}" min="1" style="width:60px">
                  <label>${t('dash.inspire_dur')}</label>
                  <input id="dash-inspire-dur" type="number" value="90" min="10" max="600" style="width:80px">
                </div>
                <label class="inspire-check"><input type="checkbox" id="dash-inspire-append"> ${t('dash.inspire_append')}</label>
              </div>
            </div>
            <button class="btn btn-ai btn-inspire" id="dash-inspire-btn" onclick="dashInspireGen()">${t('dash.inspire_btn')}</button>
          </div>
          <div id="dash-inspire-status" class="inspire-status"></div>
        </div>
        <div class="dash-hero-actions">
          <button class="btn btn-primary" onclick="navTo('storyboard')">📝 ${t('nav.storyboard')}</button>
          <button class="btn btn-outline" onclick="navTo('pipeline')">🎬 ${t('nav.pipeline')}</button>
          <button class="btn btn-outline btn-ai" onclick="navTo('storyboard');setTimeout(()=>showAIGenStoryboard(),300)">🤖 ${t('dash.ai_gen')}</button>
        </div>
      </div>

      <div class="stat-grid">
        <div class="stat-card"><div class="stat-icon">📂</div><div class="stat-value">${projects.length}</div><div class="stat-label">${t('dash.stat_projects')}</div></div>
        <div class="stat-card"><div class="stat-icon">🎬</div><div class="stat-value">${totalShots}</div><div class="stat-label">${t('dash.stat_shots')}</div></div>
        <div class="stat-card"><div class="stat-icon">🔧</div><div class="stat-value">${okCount}/${totalCount}</div><div class="stat-label">${t('dash.stat_tools')}</div></div>
        <div class="stat-card"><div class="stat-icon">📅</div><div class="stat-value">${ep}</div><div class="stat-label">${t('dash.stat_episode')}</div></div>
      </div>

      ${_setupGuide(tools)}

      <div class="card"><h2>⚡ ${t('dash.quick_actions')}</h2>
        <div class="quick-entry-grid">
          <div class="quick-entry" onclick="navTo('storyboard')"><span class="quick-entry-icon">📝</span><div><div class="quick-entry-text">${t('nav.storyboard')}</div><div class="quick-entry-desc">${t('dash.qe_storyboard')}</div></div></div>
          <div class="quick-entry" onclick="navTo('characters')"><span class="quick-entry-icon">👤</span><div><div class="quick-entry-text">${t('nav.characters')}</div><div class="quick-entry-desc">${t('dash.qe_characters')}</div></div></div>
          <div class="quick-entry" onclick="navTo('scenes')"><span class="quick-entry-icon">🏔</span><div><div class="quick-entry-text">${t('nav.scenes')}</div><div class="quick-entry-desc">${t('dash.qe_scenes')}</div></div></div>
          <div class="quick-entry" onclick="navTo('pipeline')"><span class="quick-entry-icon">🎬</span><div><div class="quick-entry-text">${t('nav.pipeline')}</div><div class="quick-entry-desc">${t('dash.qe_pipeline')}</div></div></div>
          <div class="quick-entry" onclick="navTo('projects')"><span class="quick-entry-icon">📂</span><div><div class="quick-entry-text">${t('nav.projects')}</div><div class="quick-entry-desc">${t('dash.qe_projects')}</div></div></div>
          <div class="quick-entry" onclick="navTo('settings')"><span class="quick-entry-icon">⚙</span><div><div class="quick-entry-text">${t('nav.settings')}</div><div class="quick-entry-desc">${t('dash.qe_settings')}</div></div></div>
        </div>
      </div>

      <div class="card"><h2>${t('dash.title')}</h2>${toolHtml}</div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('dash.conn_fail')}</h2><p>${esc(e.message)}</p></div>`; }
}

// ── 灵感生成（一键从大纲生成分镜）──

async function dashInspireGen() {
  const input = document.getElementById('dash-inspire-input');
  const outline = input?.value?.trim();
  if (!outline || outline.length < 10) { toast(t('toast.input_outline'), 'error'); input?.focus(); return; }
  const episode = parseInt(document.getElementById('dash-inspire-ep')?.value) || ep;
  const duration = parseInt(document.getElementById('dash-inspire-dur')?.value) || 90;
  const append = document.getElementById('dash-inspire-append')?.checked || false;
  const statusEl = document.getElementById('dash-inspire-status');
  const reset = _btnLoad(document.getElementById('dash-inspire-btn'), '⏳ AI 生成中...');

  try {
    const { task_id } = await api('/llm/storyboard', { method: 'POST', body: { episode, outline, duration, append } });
    const result = await pollTask(task_id, info => {
      _html(statusEl, `<div class="inspire-progress"><div class="batch-bar"><div class="batch-fill" style="width:${info.progress || 0}%"></div></div><span>⏳ ${info.message || 'AI 生成中...'} (${info.progress || 0}%)</span></div>`);
    });

    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      let msg = `✅ 生成 ${r.count} 个镜头，共 ${r.total_duration} 秒`;
      if (r.warnings && r.warnings.length) {
        msg += `<br><span style="color:var(--yellow)">⚠ ${r.warnings.join('；')}</span>`;
      }
      _html(statusEl, msg);
      toast(t('toast.gen_count', { n: r.count || 0 }));
      invalidateCache(`storyboard/${episode}`);
      invalidateCache('episodes');
      setTimeout(() => { ep = episode; navTo('storyboard'); }, 1200);
    } else {
      const err = result.result?.reason || result.error || '生成失败';
      _html(statusEl, `❌ ${err}`);
      toast(`❌ ${err}`, 'error');
    }
  } catch (e) {
    _html(statusEl, `❌ ${e.message}`);
    toast(`❌ ${e.message}`, 'error');
  }
  reset();
}


// ══════════════════════════════════════════════════════════

// ── Module: dashboard ──
Drama.pages.dashboard = loadDashboard;
window.loadDashboard = loadDashboard;
window.dashInspireGen = dashInspireGen;
window._crudDelete = _crudDelete;
window._crudTable = _crudTable;
window._crudPage = _crudPage;
