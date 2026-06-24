// MODULE: ai-gen — AI 生成
// ══════════════════════════════════════════════════════════

// ── 辅助：AI 生成完成后同时刷新项目管理页面状态面板 ──
function _dramaAwareReload(primaryFn) {
  return () => {
    primaryFn();
    // 如果当前在项目管理页面，也刷新状态面板
    const p = document.querySelector('.page.active');
    if (p?.id === 'page-projects' && typeof _projLoadStatus === 'function') {
      _projLoadStatus();
    }
  };
}

// ── AI 生成通用执行器 ──

async function _runAIGen(apiPath, body, statusId, overlayId, label, cacheKey, reloadFn) {
  const statusEl = document.getElementById(statusId);
  const reset = _btnLoad(document.querySelector(`#${overlayId} .btn-primary`), '⏳ 生成中...');
  _html(statusEl, `⏳ ${label}...`);
  try {
    const { task_id } = await api(apiPath, { method: 'POST', body });
    if (typeof TaskPanel !== "undefined") TaskPanel.trackTask(task_id, label);
    const result = await pollTask(task_id, info => _html(statusEl, `⏳ ${info.message || 'AI 生成中...'} (${info.progress || 0}%)`));
    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      const count = r.count || 0;
      let msg = t('toast.gen_count', { n: count });
      if (r.warnings && r.warnings.length) {
        msg += `<br><span style="color:var(--yellow,#f59e0b)">⚠ ${r.warnings.join('；')}</span>`;
      }
      // 分镜生成后提示下一步
      if (r.missing_characters?.length || r.missing_scenes?.length) {
        const missing = [];
        if (r.missing_characters?.length) missing.push(`${r.missing_characters.length} 个角色`);
        if (r.missing_scenes?.length) missing.push(`${r.missing_scenes.length} 个场景`);
        msg += `<br><span style="color:var(--fg2)">💡 引用了未创建的 ${missing.join('、')}，请到管线页面点击「👥 AI 生成角色/场景」</span>`;
      }
      _html(statusEl, msg);
      toast(t('toast.gen_count', { n: count }));
      invalidateCache(cacheKey);
      setTimeout(() => { document.getElementById(overlayId)?.remove(); reloadFn(); }, 1500);
    } else {
      const err = result.result?.reason || result.error || '生成失败';
      _html(statusEl, `❌ ${err}`); toast(`❌ ${err}`, 'error');
    }
  } catch (e) { _html(statusEl, `❌ ${e.message}`); toast(`❌ ${e.message}`, 'error'); }
  reset();
}

function showAIGenStoryboard() {
  _showOverlay('ai-gen-sb-overlay', '🤖 AI 生成分镜表', `
    <div class="edit-field"><label>剧情大纲</label>
      <textarea id="ai-sb-outline" rows="8" placeholder="输入剧情大纲，例如：\n\n林夏独自在家等顾辰来给她过生日，等了很久他都没回消息，她很失落。顾辰骑车赶路，终于到了。开门后两人对视，顾辰送上花，林夏感动落泪。" style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--bg4);padding:.6rem;border-radius:6px;font-size:.9rem;line-height:1.6;resize:vertical"></textarea></div>
    <div class="edit-field-row">
      <div class="edit-field"><label>集数</label><input id="ai-sb-ep" type="number" value="${ep}" min="1"></div>
      <div class="edit-field"><label>目标时长(秒)</label><input id="ai-sb-dur" type="number" value="90" min="10" max="3600"></div>
    </div>
    <div class="edit-field"><label><input type="checkbox" id="ai-sb-append"> 追加到现有分镜表（不覆盖）</label></div>
    <div id="ai-sb-status" class="dim" style="margin-top:0.5rem"></div>`, `doAIGenStoryboard()`, '🚀 生成');
}

async function doAIGenStoryboard() {
  const outline = document.getElementById('ai-sb-outline')?.value?.trim();
  if (!outline || outline.length < 10) { toast(t('toast.input_outline'), 'error'); return; }
  const episode = parseInt(document.getElementById('ai-sb-ep')?.value) || ep;
  const duration = parseInt(document.getElementById('ai-sb-dur')?.value) || 90;
  const append = document.getElementById('ai-sb-append')?.checked || false;
  await _runAIGen('/llm/storyboard', { episode, outline, duration, append },
    'ai-sb-status', 'ai-gen-sb-overlay', 'AI 生成分镜',
    `storyboard/${episode}`, () => {
      ep = episode;
      const p = document.querySelector('.page.active');
      if (p?.id === 'page-storyboard') loadStoryboard();
      else if (p?.id === 'page-pipeline') loadPipeline();
    });
}

function showAIGenCharacter() {
  _showOverlay('ai-gen-char-overlay', '🤖 AI 生成角色', `
    <div class="edit-field"><label>角色描述（每行一个角色）</label>
      <textarea id="ai-char-desc" rows="6" placeholder="输入角色描述，例如：\n\n22岁温柔女生，长发，喜欢穿浅色衣服，说话轻声细语\n25岁帅气男生，短发阳光，运动型，性格开朗" style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--bg4);padding:.6rem;border-radius:6px;font-size:.9rem;line-height:1.6;resize:vertical"></textarea></div>
    <div id="ai-char-status" class="dim" style="margin-top:0.5rem"></div>`, `doAIGenCharacter()`, '🚀 生成');
}

async function doAIGenCharacter() {
  const descText = document.getElementById('ai-char-desc')?.value?.trim();
  if (!descText) { toast(t('toast.input_desc'), 'error'); return; }
  const descriptions = descText.split('\n').map(s => s.trim()).filter(s => s.length > 0);
  if (!descriptions.length) { toast(t('toast.input_at_least_one'), 'error'); return; }
  await _runAIGen('/llm/characters', { descriptions }, 'ai-char-status', 'ai-gen-char-overlay',
    `正在生成 ${descriptions.length} 个角色`, 'characters', _dramaAwareReload(loadCharacters));
}

function showAIGenScene() {
  _showOverlay('ai-gen-scene-overlay', '🤖 AI 生成场景', `
    <div class="edit-field"><label>场景描述（每行一个场景）</label>
      <textarea id="ai-scene-desc" rows="6" placeholder="输入场景描述，例如：\n\n现代简约客厅，米色沙发，落地窗暖光\n繁华商业街，霓虹灯闪烁，人来人往" style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--bg4);padding:.6rem;border-radius:6px;font-size:.9rem;line-height:1.6;resize:vertical"></textarea></div>
    <div id="ai-scene-status" class="dim" style="margin-top:0.5rem"></div>`, `doAIGenScene()`, '🚀 生成');
}

async function doAIGenScene() {
  const descText = document.getElementById('ai-scene-desc')?.value?.trim();
  if (!descText) { toast(t('toast.input_desc'), 'error'); return; }
  const descriptions = descText.split('\n').map(s => s.trim()).filter(s => s.length > 0);
  if (!descriptions.length) { toast(t('toast.input_at_least_one'), 'error'); return; }
  await _runAIGen('/llm/scenes', { descriptions }, 'ai-scene-status', 'ai-gen-scene-overlay',
    `正在生成 ${descriptions.length} 个场景`, 'scenes', _dramaAwareReload(loadScenes));
}

async function loadStoryboard() {
  const el = document.getElementById('page-storyboard');
  try {
    await _loadNameMaps();
    const episodes = await loadEpisodeSelector();
    const d = await cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`));
    const ss = _normalizeShotsFromBackend(d.shots || []);
    shots = ss; // 同步全局变量（撤销/重做/时间轴缩略图依赖它）
    const epSelector = _episodeSelectHtml(episodes, 'switchEpisode');
    const header = `<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem"><h2>${t('sb.title')}</h2>
      <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">${epSelector}${_sbViewToggle()}<button class="btn btn-outline btn-ai" onclick="showAIGenStoryboard()">🤖 AI 生成分镜</button><button class="btn btn-outline" onclick="exportStoryboard()">📤 ${t('sb.export')}</button><button class="btn btn-outline" onclick="showImportDialog()">📥 ${t('sb.import')}</button><button class="btn btn-danger btn-sm" onclick="batchDeleteShots()" id="sb-batch-del-btn" style="display:none">${t('btn.batch_delete')} (<span id="sb-batch-count">0</span>)</button><button class="btn btn-primary" onclick="navTo('pipeline')">🎬 ${t('nav.pipeline')}</button><button class="btn btn-success" onclick="addShot()">+ ${t('btn.add')}</button></div></div>
      <p class="dim" style="font-size:.76rem;margin-bottom:.5rem">${t('sb.drag_hint')}</p>`;

    if (!ss.length) {
      el.innerHTML = header + `<div class="empty-state"><div class="empty-state-icon">📝</div><h3>${t('sb.none')}</h3><p>${t('sb.empty_desc')}</p><button class="btn btn-ai" onclick="showAIGenStoryboard()">🤖 AI 生成分镜</button></div></div>`;
      return;
    }

    if (_sbViewMode === 'timeline') {
      // 时间轴视图
      const timeline = `<div class="timeline-container">${ss.map((s, i) => {
        const sid = _shotId(s, i);
        return `<div class="timeline-item" id="tl-${esc(sid)}"><div class="timeline-dot"></div>
          <div class="timeline-card" style="position:relative">
            <label class="batch-check" style="position:absolute;top:6px;right:6px;z-index:2"><input type="checkbox" class="sb-batch-cb" value="${esc(sid)}" onclick="event.stopPropagation();_updateSB()"></label>
            <div class="timeline-thumb" id="tl-thumb-${esc(sid)}"><div class="thumb-skeleton"><div class="thumb-skeleton-pulse"></div></div></div>
            <div class="timeline-info">
              <div class="timeline-info-head"><span class="timeline-sid">${esc(sid)}</span><span class="timeline-meta">${esc(_resolveScene(s.scene_name))} · ${esc(_resolveChars(s.characters))}</span></div>
              <div class="timeline-info-body">${esc((s.action || '').substring(0, 60))}${(s.action||'').length > 60 ? '...' : ''}</div>
              ${s.dialogue && s.dialogue !== '......' ? `<div class="timeline-info-dialogue">"${esc((s.dialogue || '').substring(0, 50))}"</div>` : ''}
              <div class="timeline-meta" style="margin-top:.25rem">${esc(s.camera || '')} · ${esc(s.shot_type || '')} · ${s.duration || 4}s · ${esc(s.emotion || 'neutral')}</div>
              <div class="timeline-actions">${_actionBtns(i)}</div>
            </div>
          </div></div>`;
      }).join('')}</div>`;
      el.innerHTML = header + timeline + '</div>';
      // 加载缩略图
      ss.forEach((_, i) => _loadTimelineThumb(i));
      _initTimelineSortable();
    } else {
      // 表格视图
      const rows = ss.map((s, i) => `<tr>
        <td><input type="checkbox" class="sb-batch-cb" value="${esc(_shotId(s, i))}" onclick="event.stopPropagation();_updateSB()"></td>
        <td><span class="drag-handle" title="拖拽排序">⠿</span></td>
        <td>${_shotId(s, i)}</td>
        ${SB_FIELDS.slice(0, 4).map(f => { const _tip = f === 'characters' ? _resolveChars(s[f]) : f === 'scene_name' ? _resolveScene(s[f]) : ''; return `<td><input class="sb-inline-input" value="${esc(s[f] || '')}" data-idx="${i}" data-field="${f}"${_tip ? ` title="${esc(_tip)}"` : ''} onchange="updateShotField(this)"></td>`; }).join('')}
        <td><select class="sb-inline-input" data-idx="${i}" data-field="camera" onchange="updateShotField(this)">${_selectOpts(_cameras(), s.camera, _CAMERA_KEYS)}</select></td>
        <td><select class="sb-inline-input" data-idx="${i}" data-field="shot_type" onchange="updateShotField(this)">${_selectOpts(_shotTypes(), s.shot_type, _SHOTTYPE_KEYS)}</select></td>
        <td><input class="sb-inline-input" type="number" value="${s.duration || 4}" min="2" max="8" step="0.5" data-idx="${i}" data-field="duration" onchange="updateShotField(this)"></td>
        <td><select class="sb-inline-input" data-idx="${i}" data-field="emotion" onchange="updateShotField(this)">${_selectOpts(EMOTIONS, s.emotion)}</select></td>
        <td><input class="sb-inline-input" value="${esc(s.outfit || 'default')}" data-idx="${i}" data-field="outfit" placeholder="${t('edit.outfit_ph')}" onchange="updateShotField(this)"></td>
        <td><button class="btn btn-xs btn-danger" onclick="deleteShotFromSB(${i})">🗑</button></td></tr>`).join('');
      el.innerHTML = header + `<div style="overflow-x:auto"><table><thead><tr><th><input type="checkbox" onclick="_toggleAllSB(this.checked)"></th><th></th><th>${t('sb.shot_id')}</th><th>${t('edit.scene')}</th><th>${t('edit.characters')}</th><th>${t('edit.action')}</th><th>${t('edit.dialogue')}</th><th>${t('edit.camera')}</th><th>${t('edit.shot_type')}</th><th>${t('edit.duration')}</th><th>${t('sb.emotion')}</th><th>${t('edit.outfit')}</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
      _initSortable();
    }
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

async function _loadTimelineThumb(idx) {
  const sid = _shotId(shots[idx], idx);
  const el = document.getElementById(`tl-thumb-${sid}`);
  if (!el) return;
  try {
    const r = (await cachedFetch(`res/${ep}/${sid}`, () => api(`/shots/${ep}/${sid}/resources`))).resources || {};
    const item = document.getElementById(`tl-${sid}`);
    if (r.frame) {
      el.innerHTML = `<img src="/api/files/${ep}/${sid}/frame.png" loading="lazy" onclick="previewRes('${sid}','frame')" style="cursor:pointer" title="点击放大" onerror="this.outerHTML='🎬'">`;
      if (item) item.classList.add('has-frame');
    } else {
      el.innerHTML = '🎬';
    }
    if (r.video && item) item.classList.add('has-video');
    if (r.synced && item) item.classList.add('has-synced');
  } catch (e) { console.warn('操作失败:', e); el.innerHTML = '🎬'; }
}

let _sbDirty = false, _sbSaving = false;
const _debouncedSaveSB = debounce(async () => {
  if (!_sbDirty || _sbSaving) return;
  _sbSaving = true;
  try {
    // 直接从 DOM 同步到内存中的 shots，避免 GET→POST 竞态
    document.querySelectorAll('.sb-inline-input').forEach(inp => {
      const i = parseInt(inp.dataset.idx);
      if (shots[i]) shots[i][inp.dataset.field] = inp.value;
    });
    await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: _prepareShotsForSave(shots) } });
    invalidateCache(`storyboard/${ep}`);
    _sbDirty = false;
    toast(t('toast.saved'));
  } catch (e) { toast(e.message, 'error'); setTimeout(() => { if (_sbDirty) _debouncedSaveSB(); }, 5000); }
  finally { _sbSaving = false; }
}, 1000);
function updateShotField() {
  if (!_sbDirty) pushUndo(t('sb.title')); // 首次修改时保存快照用于 undo
  _sbDirty = true;
  _debouncedSaveSB();
}

async function deleteShotFromSB(idx) {
  const sid = shots[idx]?.shot_id || idx + 1;
  if (!await modalConfirm(t('confirm.delete_shot', { id: sid }))) return;
  pushUndo(`${t('btn.delete')} ${sid}`);
  shots.splice(idx, 1);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: _prepareShotsForSave(shots) } }); invalidateCache(`storyboard/${ep}`); toast(t('toast.deleted')); loadStoryboard(); } catch (e) { toast(e.message, 'error'); }
}

async function addShot(renderFn) {
  const maxNum = Math.max(0, ...shots.map(s => parseInt(s.shot_id, 10)).filter(n => !isNaN(n)));
  const newId = String(maxNum + 1).padStart(3, '0');
  pushUndo(`${t('btn.add')} ${newId}`);
  const newShot = { ..._DEFAULT_SHOT(), episode: ep, shot_id: newId };
  shots.push(newShot);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: _prepareShotsForSave(shots) } }); invalidateCache(`storyboard/${ep}`); toast(t('toast.created')); (renderFn || loadStoryboard)(); } catch (e) { toast(e.message, 'error'); }
}

// ── 分镜表批量选择/删除 ──

function _updateSB() {
  const cbs = document.querySelectorAll('.sb-batch-cb:checked');
  const n = cbs.length;
  const btn = document.getElementById('sb-batch-del-btn');
  const count = document.getElementById('sb-batch-count');
  if (btn) btn.style.display = n > 0 ? '' : 'none';
  if (count) count.textContent = n;
}

function _toggleAllSB(checked) {
  document.querySelectorAll('.sb-batch-cb').forEach(cb => { cb.checked = checked; });
  _updateSB();
}

async function batchDeleteShots() {
  const cbs = document.querySelectorAll('.sb-batch-cb:checked');
  const shotIds = Array.from(cbs).map(cb => cb.value).filter(Boolean);
  if (!shotIds.length) { toast(t('toast.select_first'), 'error'); return; }
  if (!await modalConfirm(t('confirm.batch_delete_shots', { n: shotIds.length }))) return;
  try {
    const r = await api(`/storyboard/${ep}/batch-delete`, { method: 'POST', body: { shot_ids: shotIds } });
    invalidateCache(`storyboard/${ep}`);
    toast(t('toast.batch_deleted', { n: r.deleted || shotIds.length }));
    loadStoryboard();
  } catch (e) { toast(e.message, 'error'); }
}


// ══════════════════════════════════════════════════════════

// ── Module: ai-gen ──
Drama.pages.storyboard = loadStoryboard;
window.loadStoryboard = loadStoryboard;
window.showAIGenStoryboard = showAIGenStoryboard;
window.showAIGenCharacter = showAIGenCharacter;
window.showAIGenScene = showAIGenScene;
window.updateShotField = updateShotField;
window.addShot = addShot;
window.deleteShotFromSB = deleteShotFromSB;
