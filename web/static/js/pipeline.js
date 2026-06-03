// MODULE: pipeline — 生产工作台
// ══════════════════════════════════════════════════════════

function _updatePipelineStep(step, state) {
  // state: 'active' | 'done' | 'fail' | ''
  const el = document.getElementById(`pf-${step}`);
  if (!el) return;
  el.classList.remove('active', 'done', 'fail');
  if (state) el.classList.add(state);
  // 箭头联动：完成时标记前一段箭头
  const steps = ['portrait', 'scene', 'tts', 'first-frame', 'video', 'lipsync', 'post'];
  const idx = steps.indexOf(step);
  const arrows = document.querySelectorAll('.pipeline-arrow');
  if (state === 'done' && idx > 0 && arrows[idx - 1]) arrows[idx - 1].classList.add('done');
}

function _resetPipelineSteps() {
  document.querySelectorAll('.pipeline-step').forEach(el => el.classList.remove('active', 'done', 'fail'));
  document.querySelectorAll('.pipeline-arrow').forEach(el => el.classList.remove('done'));
}

function _isForce() { return document.getElementById('wb-force-cb')?.checked || false; }

const _stepBtns = () => [
  { step: 'tts', icon: '🎤', label: t('step.tts') },
  { step: 'first-frame', icon: '🎨', label: t('step.first_frame') },
  { step: 'video', icon: '🎬', label: t('step.video') },
  { step: 'lipsync', icon: '👄', label: t('step.lipsync') },
];

function _shotId(s, i) { return s.shot_id || String(i + 1).padStart(3, '0'); }
function _actionBtns(idx) {
  return `<button class="btn btn-xs" onclick="editShot(${idx})" title="${t('btn.edit')}">✏</button>` +
    _stepBtns().map(b => `<button class="btn btn-xs" onclick="runOne('${b.step}',${idx})" title="${b.label}">${b.icon}</button>`).join('') +
    `<button class="btn btn-xs btn-danger" onclick="deleteShot(${idx})" title="${t('btn.delete')}">🗑</button>`;
}

async function loadPipeline() {
  const el = document.getElementById('page-pipeline');
  el.innerHTML = `<div class="card"><h2>${t('common.loading')}</h2></div>`;
  try {
    await _loadNameMaps();
    const episodes = await loadEpisodeSelector();
    const d = await cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`));
    shots = d.shots || [];
    if (!shots.length) { el.innerHTML = `<div class="card"><h2>${t('wb.no_storyboard')}</h2><p class="dim">${t('wb.add_shots_first')}</p><button class="btn btn-primary" style="margin-top:0.5rem" onclick="navTo('storyboard')">${t('wb.go_edit_btn')}</button></div>`; return; }
    renderWB(episodes);
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

function renderWB(episodes) {
  const el = document.getElementById('page-pipeline');
  const epSelector = _episodeSelectHtml(episodes || [ep], 'switchEpisode');

  // 流程图
  const flowSteps = [
    { icon: '📸', label: t('wb.portrait_short'), step: 'portrait' },
    { icon: '🏔', label: t('wb.scene_short'), step: 'scene' },
    { icon: '🎤', label: t('step.tts'), step: 'tts' },
    { icon: '🎨', label: t('step.first_frame'), step: 'first-frame' },
    { icon: '🎬', label: t('step.video'), step: 'video' },
    { icon: '👄', label: t('step.lipsync'), step: 'lipsync' },
    { icon: '🎞', label: t('wb.post_short'), step: 'post' },
  ];
  const flowHtml = `<div class="pipeline-flow">${flowSteps.map((s, i) => {
    const arrow = i < flowSteps.length - 1 ? '<div class="pipeline-arrow"></div>' : '';
    return `<div class="pipeline-step" id="pf-${s.step}"><div class="pipeline-step-icon">${s.icon}</div><div class="pipeline-step-label">${s.label}</div></div>${arrow}`;
  }).join('')}</div>`;

  el.innerHTML = `<div class="wb-top-bar"><div style="display:flex;align-items:center;gap:0.5rem"><h2>🎬 ${t('nav.pipeline')}</h2>${epSelector}<span class="dim" style="font-size:.85rem">${shots.length} ${t('wb.shots_count')}</span></div>
    <div class="wb-batch-btns">
      <button class="btn btn-outline" onclick="undo()" title="Ctrl+Z">↩ ${t('undo.undo')}</button>
      <button class="btn btn-outline" onclick="redo()" title="Ctrl+Shift+Z">↪ ${t('undo.redo')}</button>
      <label class="force-toggle" title="${t('wb.force_overwrite')}"><input type="checkbox" id="wb-force-cb"> ${t('wb.force_overwrite')}</label>
      <span class="dim" style="margin:0 0.3rem">|</span>
      <button class="btn btn-primary" onclick="runPrepare()" title="${t('wb.prepare_hint')}">${t('wb.prepare')}</button>
      <button class="btn btn-outline" onclick="runPortraits()">📸 ${t('wb.gen_portraits')}</button>
      <button class="btn btn-outline" onclick="runSceneImages()">🏔 ${t('wb.gen_scene_images')}</button>
      <span class="dim" style="margin:0 0.3rem">|</span>
      ${_stepBtns().map(b => `<button class="btn btn-outline" onclick="batchRun('${b.step}')">${b.icon} ${t('wb.batch_label')} ${b.label}</button>`).join('')}
      <span class="dim" style="margin:0 0.3rem">|</span>
      <button class="btn btn-outline" onclick="runSubtitle()">📝 ${t('wb.gen_subtitle')}</button>
      <button class="btn btn-outline" onclick="runMusic()">🎵 ${t('wb.gen_music')}</button>
      <button class="btn btn-outline" onclick="runPost()">🎞 ${t('wb.post_process')}</button>
      <button class="btn btn-primary" onclick="runAll()">🚀 ${t('wb.run_all')}</button>
      <span class="dim" style="margin:0 0.3rem">|</span>
      <button class="btn btn-success" onclick="addShotFromPipeline()">+ ${t('btn.add')}</button>
    </div></div>
    <div class="card" style="margin-bottom:.7rem"><h2>${t('wb.flow_title')}</h2>${flowHtml}</div>
    <div id="wb-shots-grid" class="wb-shots-grid"></div>
    <div id="wb-batch-status" class="wb-batch-status" style="display:none"></div>
    <div class="card" style="margin-top:.7rem"><h2>${t('wb.final_preview')}</h2><div id="final-preview-area"></div></div>`;
  _resetPipelineSteps();
  renderShotsGrid();
  _loadFinalPreview();
  // Chat FAB
  if (!document.getElementById('chat-fab')) {
    const fab = document.createElement('button');
    fab.id = 'chat-fab';
    fab.className = 'chat-fab';
    fab.textContent = '💬';
    fab.title = t('chat.title');
    fab.onclick = toggleChat;
    document.body.appendChild(fab);
  }
}

function renderShotsGrid() {
  const grid = document.getElementById('wb-shots-grid');
  if (!grid) return;
  grid.innerHTML = shots.map((s, i) => {
    const sid = _shotId(s, i);
    return `<div class="wb-shot-card" id="shot-${esc(sid)}">
      <div class="wb-shot-head" id="shot-head-${esc(sid)}"><span class="wb-shot-num">${esc(sid)}</span><span class="wb-shot-char">${esc(_resolveChars(s.characters))}</span><span class="wb-shot-scene">${esc(_resolveScene(s.scene_id))}</span><span class="wb-shot-status"></span></div>
      <div class="wb-shot-body"><div class="wb-shot-text"><div class="wb-shot-action" title="${esc(s.action || '')}">${esc((s.action || '').substring(0, 30)) || '...'}</div>
        <div class="wb-shot-dialogue" title="${esc(s.dialogue || '')}">"${esc((s.dialogue || '').substring(0, 30)) || '...'}"</div></div>
        <div class="wb-shot-resources" id="res-${esc(sid)}"></div></div>
      <div class="wb-shot-actions">${_actionBtns(i)}</div></div>`;
  }).join('');
  shots.forEach((_, i) => loadResources(i));
}

async function loadResources(idx) {
  const sid = _shotId(shots[idx], idx), el = document.getElementById(`res-${sid}`);
  if (!el) return;
  try {
    const r = (await cachedFetch(`res/${ep}/${sid}`, () => api(`/shots/${ep}/${sid}/resources`))).resources || {};
    const chips = [
      r.audio && `<div class="res-chip res-audio" onclick="previewRes('${sid}','audio')">🎤</div>`,
      r.frame && `<div class="res-chip res-img" onclick="previewRes('${sid}','frame')"><img src="/api/files/${ep}/${sid}/frame.png" loading="lazy" onerror="this.parentElement.style.display='none'"></div>`,
      r.video && `<div class="res-chip res-video" onclick="previewRes('${sid}','video')">🎬</div>`,
      r.synced && `<div class="res-chip res-synced" onclick="previewRes('${sid}','synced')">👄</div>`,
    ].filter(Boolean).join('');
    el.innerHTML = chips || `<span class="dim" style="font-size:0.7rem">${t('wb.no_resource')}</span>`;
    // 更新卡片头部状态徽章
    const headEl = document.getElementById(`shot-head-${sid}`);
    if (headEl) {
      const st = (k, ok) => `<span class="st ${ok?'st-done':'st-miss'}">${k}</span>`;
      const badgeEl = headEl.querySelector('.wb-shot-status');
      if (badgeEl) badgeEl.innerHTML = st('🎤',r.audio) + st('🎨',r.frame) + st('🎬',r.video) + st('👄',r.synced);
    }
  } catch {}
}

function previewRes(sid, type) {
  const types = ['audio', 'frame', 'video', 'synced'].filter(typ => {
    const cls = typ === 'frame' ? 'img' : typ === 'audio' ? 'audio' : typ === 'synced' ? 'synced' : 'video';
    return !!document.querySelector(`#res-${sid} .res-${cls}`);
  });
  let currentType = type;

  function renderOverlay(resType) {
    const src = resType === 'audio' ? `/api/files/${ep}/${sid}/audio.wav`
      : resType === 'frame' ? `/api/files/${ep}/${sid}/frame.png`
      : `/api/files/${ep}/${sid}/${resType === 'synced' ? 'synced.mp4' : 'video.mp4'}`;
    const onErr = ` onerror="this.style.display='none';this.nextElementSibling&&this.nextElementSibling.style.display='block'"`;
    const tag = resType === 'audio' ? `audio controls src="${src}" style="width:400px"${onErr}`
      : resType === 'frame' ? `img src="${src}" style="max-width:90vw;max-height:80vh;border-radius:8px"${onErr}`
      : `video controls src="${src}" style="max-width:90vw;max-height:80vh;border-radius:8px"${onErr}`;
    const idx = types.indexOf(resType);
    const nav = types.length > 1 ? `<div style="display:flex;gap:1rem;justify-content:center;margin-top:.6rem">
      ${idx > 0 ? `<button class="btn btn-outline" id="_pr-prev">◀ ${types[idx-1]}</button>` : ''}
      <span class="dim">${idx+1}/${types.length}</span>
      ${idx < types.length-1 ? `<button class="btn btn-outline" id="_pr-next">${types[idx+1]} ▶</button>` : ''}
    </div>` : '';
    return `<div class="res-overlay-inner"><${tag}>${nav}<div class="dim" style="margin-top:0.5rem">${t('wb.esc_hint')}</div></div>`;
  }

  const o = document.createElement('div'); o.className = 'res-overlay';
  o.innerHTML = renderOverlay(currentType);
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);

  function switchTo(resType) { currentType = resType; o.innerHTML = renderOverlay(resType); bindNav(); }
  function bindNav() {
    o.querySelector('#_pr-prev')?.addEventListener('click', (e) => { e.stopPropagation(); switchTo(types[types.indexOf(currentType)-1]); });
    o.querySelector('#_pr-next')?.addEventListener('click', (e) => { e.stopPropagation(); switchTo(types[types.indexOf(currentType)+1]); });
  }
  bindNav();

  o._keyHandler = (e) => {
    // 忽略输入框内的方向键（避免冲突）
    if (e.target.matches('input, textarea, select')) return;
    if (e.key === 'ArrowLeft' && types.indexOf(currentType) > 0) switchTo(types[types.indexOf(currentType)-1]);
    if (e.key === 'ArrowRight' && types.indexOf(currentType) < types.length-1) switchTo(types[types.indexOf(currentType)+1]);
  };
  document.addEventListener('keydown', o._keyHandler);
  const origRemove = o.remove.bind(o);
  o.remove = () => { document.removeEventListener('keydown', o._keyHandler); origRemove(); };
}

// ── 镜头编辑 ──

const _CAMERA_KEYS = ['fixed', 'push_in', 'pan', 'handheld', 'orbit', 'top', 'bottom'];
const _SHOTTYPE_KEYS = ['closeup', 'medium_close', 'medium', 'over_shoulder', 'full', 'wide', 'extreme_wide'];
/** 镜头默认值（新建镜头 / AI 编辑兜底共用） */
const _DEFAULT_SHOT = () => ({ shot_id: '', scene_id: '', characters: '', action: '', dialogue: '',
  camera: _CAMERA_KEYS[0], shot_type: _SHOTTYPE_KEYS[2], duration: 4, emotion: 'neutral',
  language: 'zh', outfit: '', action_en: '', dialogue_en: '' });
const _cameras = () => _CAMERA_KEYS.map(k => t(`camera.${k}`));
const _shotTypes = () => _SHOTTYPE_KEYS.map(k => t(`shot.${k}`));
const EMOTIONS = ['neutral', 'happy', 'sad', 'angry', 'worried', 'surprised', 'calm', 'determined'];
const LANGUAGES = [{ value: 'zh', label: '中文' }, { value: 'en', label: 'English' }, { value: 'ja', label: '日本語' }, { value: 'ko', label: '한국어' }, { value: 'fr', label: 'Français' }, { value: 'de', label: 'Deutsch' }, { value: 'es', label: 'Español' }];

// TTS 后端 → 角色 voice 参数字段定义
const TTS_VOICE_FIELDS = {
  'mimo-voicedesign': [],
  'mimo-voiceclone': [{ key: 'reference_audio', label: () => t('char.voice_ref_audio'), placeholder: '/path/to/ref.wav' }],
  'gpt-sovits': [{ key: 'reference_audio', label: () => t('char.voice_ref_audio'), placeholder: '/path/to/ref.wav' }, { key: 'prompt_text', label: () => t('char.voice_prompt_text') }],
  'cosyvoice': [{ key: 'speaker', label: () => t('char.voice_speaker'), placeholder: 'default' }],
  'fish-speech': [{ key: 'reference_id', label: () => t('char.voice_ref_id') }],
};

function _selectOpts(options, current, keys) {
  return options.map((o, i) => {
    const k = keys ? keys[i] : null;
    const selected = (k && current === k) || current === o ? 'selected' : '';
    return `<option value="${esc(k || o)}" ${selected}>${o}</option>`;
  }).join('');
}

async function editShot(idx) {
  const s = shots[idx], sid = _shotId(shots[idx], idx);
  // 加载角色和场景列表用于下拉选择
  let charOpts = `<option value="">${t('edit.select_char')}</option>`;
  let sceneOpts = `<option value="">${t('edit.select_scene')}</option>`;
  try {
    const [charData, sceneData] = await Promise.all([
      cachedFetch('characters', () => api('/characters')),
      cachedFetch('scenes', () => api('/scenes')),
    ]);
    (charData.characters || []).forEach(c => { const _cv = c.id || c.name; const _cn = c.name || c.id; charOpts += `<option value="${esc(_cv)}" ${(s.characters || '').split('+').map(x=>x.trim()).includes(_cv) ? 'selected' : ''}>${esc(_cn)}</option>`; });
    (sceneData.scenes || []).forEach(sc => { const _sv = sc.id || sc.name; const _sn = sc.name || sc.id; sceneOpts += `<option value="${esc(_sv)}" ${(s.scene_id || '') === _sv ? 'selected' : ''}>${esc(_sn)}</option>`; });
  } catch {}
  _showOverlay('edit-overlay', `${t('edit.shot_title')} ${sid}`, `
    <div class="edit-field"><label>${t('edit.scene')}</label>
      <div class="edit-field-combo"><select id="ed-scene-sel" onchange="document.getElementById('ed-scene').value=this.value">${sceneOpts}</select><input id="ed-scene" value="${esc(s.scene_id || '')}" placeholder="${t('edit.select_scene')}"></div></div>
    <div class="edit-field"><label>${t('edit.characters')}</label>
      <div class="edit-field-combo"><select id="ed-chars-sel" onchange="document.getElementById('ed-chars').value=this.value">${charOpts}</select><input id="ed-chars" value="${esc(s.characters || '')}" placeholder="${t('edit.select_char')}"></div></div>
    <div class="edit-field"><label>${t('edit.action')} <span class="char-count" id="cc-action">0</span></label><textarea id="ed-action" rows="2" oninput="updateCharCount('ed-action','cc-action')">${esc(s.action || '')}</textarea></div>
    <div class="edit-field"><label>${t('sb.action_en')} <span class="char-count" id="cc-action-en">0</span></label><textarea id="ed-action-en" rows="2" oninput="updateCharCount('ed-action-en','cc-action-en')">${esc(s.action_en || '')}</textarea></div>
    <div class="edit-field"><label>${t('edit.dialogue')} <span class="char-count" id="cc-dialogue">0</span></label><textarea id="ed-dialogue" rows="2" oninput="updateCharCount('ed-dialogue','cc-dialogue')">${esc(s.dialogue || '')}</textarea></div>
    <div class="edit-field"><label>${t('sb.dialogue_en')} <span class="char-count" id="cc-dialogue-en">0</span></label><textarea id="ed-dialogue-en" rows="2" oninput="updateCharCount('ed-dialogue-en','cc-dialogue-en')">${esc(s.dialogue_en || '')}</textarea></div>
    <div class="edit-field"><label>${t('edit.outfit')}</label><input id="ed-outfit" value="${esc(s.outfit || '')}" placeholder="${t('edit.outfit_ph')}"></div>
    <div class="edit-field-row">
      <div class="edit-field"><label>${t('edit.camera')}</label><select id="ed-camera">${_selectOpts(_cameras(), s.camera, _CAMERA_KEYS)}</select></div>
      <div class="edit-field"><label>${t('edit.shot_type')}</label><select id="ed-shottype">${_selectOpts(_shotTypes(), s.shot_type, _SHOTTYPE_KEYS)}</select></div>
      <div class="edit-field"><label>${t('edit.duration')}</label><input id="ed-dur" type="number" value="${s.duration || 4}" min="1" max="30"></div>
      <div class="edit-field"><label>${t('edit.emotion')}</label><select id="ed-emo">${_selectOpts(EMOTIONS, s.emotion)}</select></div>
      <div class="edit-field"><label>${t('edit.language')}</label><select id="ed-lang">${LANGUAGES.map(l => `<option value="${l.value}" ${(s.language || 'zh') === l.value ? 'selected' : ''}>${l.label}</option>`).join('')}</select></div>
    </div>
    <div class="edit-nav-row">
      ${idx > 0 ? `<button class="btn btn-xs btn-outline" onclick="_saveAndEdit(${idx},${idx-1})">${t('edit.prev_shot')}</button>` : '<span></span>'}
      ${idx < shots.length - 1 ? `<button class="btn btn-xs btn-outline" onclick="_saveAndEdit(${idx},${idx+1})">${t('edit.next_shot')}</button>` : '<span></span>'}
    </div>`, `saveShot(${idx})`);
  // 初始化字数统计
  ['ed-action','ed-action-en','ed-dialogue','ed-dialogue-en'].forEach(id => {
    const el = document.getElementById(id);
    if (el) updateCharCount(id, 'cc-' + id.replace('ed-', ''));
  });
}

function updateCharCount(inputId, countId) {
  const inp = document.getElementById(inputId);
  const cnt = document.getElementById(countId);
  if (inp && cnt) cnt.textContent = t('edit.char_count', { count: inp.value.length });
}

const _SHOT_FIELDS = [['scene_id', 'ed-scene'], ['characters', 'ed-chars'], ['action', 'ed-action'], ['action_en', 'ed-action-en'], ['dialogue', 'ed-dialogue'], ['dialogue_en', 'ed-dialogue-en'], ['outfit', 'ed-outfit'], ['camera', 'ed-camera'], ['shot_type', 'ed-shottype'], ['duration', 'ed-dur'], ['emotion', 'ed-emo'], ['language', 'ed-lang']];

/** 从编辑面板读取字段值到 shots[idx] */
function _collectShotFields(idx) {
  const s = shots[idx];
  const _defaults = { duration: 4, emotion: 'neutral', language: 'zh' };
  for (const [k, id] of _SHOT_FIELDS)
    s[k] = document.getElementById(id)?.value || _defaults[k] || '';
  // duration 必须是有效正整数
  s.duration = Math.max(1, Math.min(30, parseInt(s.duration) || 4));
  return s;
}

/** 保存 shots 到后端并刷新缓存 */
async function _persistShots() {
  await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
  invalidateCache(`storyboard/${ep}`);
  invalidateCache(`res/${ep}`);
}

async function _saveAndEdit(fromIdx, toIdx) {
  const s = _collectShotFields(fromIdx);
  pushUndo(`${t('edit.shot_title')} ${s.shot_id || fromIdx + 1}`);
  try {
    await _persistShots();
    document.getElementById('edit-overlay')?.remove();
    editShot(toIdx);
  } catch (e) { toast(e.message, 'error'); }
}

async function saveShot(idx) {
  const s = _collectShotFields(idx);
  pushUndo(`${t('edit.shot_title')} ${s.shot_id || idx + 1}`);
  try { await _persistShots(); toast(t('toast.saved')); document.getElementById('edit-overlay')?.remove(); renderShotsGrid(); } catch (e) { toast(e.message, 'error'); }
}

async function deleteShot(idx) {
  const sid = _shotId(shots[idx], idx);
  if (!await modalConfirm(t('confirm.delete_shot', { id: sid }))) return;
  pushUndo(`${t('btn.delete')} ${sid}`); shots.splice(idx, 1);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }); invalidateCache(`storyboard/${ep}`); toast(t('toast.deleted')); renderShotsGrid(); } catch (e) { toast(e.message, 'error'); }
}

// ── 执行 ──

async function runOne(step, idx) {
  const sid = _shotId(shots[idx], idx);
  const act = document.getElementById(`shot-${sid}`)?.querySelector('.wb-shot-actions');
  _html(act, `<span class="run-indicator">⏳ ${step}...</span> <button class="btn btn-xs btn-danger" onclick="cancelCurrentTask()">⏹</button>`);
  _updatePipelineStep(step, 'active');
  try {
    const force = _isForce();
    const { task_id } = await api(`/steps/${step}`, { method: 'POST', body: { episode: ep, shot_id: sid, force } });
    _currentTaskId = task_id;
    if (typeof TaskPanel !== 'undefined') TaskPanel.trackTask(task_id, `${step} ${sid}`);
    const result = await pollTask(task_id, info => _html(act, `<span class="run-indicator">⏳ ${info.message || step} (${info.progress || 0}%)</span> <button class="btn btn-xs btn-danger" onclick="cancelCurrentTask()">⏹</button>`));
    _currentTaskId = null;
    const sub = result.result;
    if (result.status === 'success' && sub?.status !== 'error' && sub?.status !== 'skipped') {
      toast(`✅ ${sid} ${step} ${t('wb.shot_done')}`); _updatePipelineStep(step, 'done');
    } else if (result.status === 'success' && sub?.status === 'skipped') {
      toast(`⏭ ${sid} ${step}: ${sub.reason || t('wb.shot_skip')}`); _updatePipelineStep(step, 'done');
    } else {
      const err = sub?.reason || result.error || t('wb.shot_fail');
      toast(`❌ ${sid} ${step}: ${err}`, 'error'); _updatePipelineStep(step, 'fail');
    }
  } catch (e) { _currentTaskId = null; toast(`❌ ${sid}: ${e.message}`, 'error'); _updatePipelineStep(step, 'fail'); }
  _html(act, _actionBtns(idx));
  invalidateCache(`res/${ep}/`);  // 清除该集所有镜头缓存（含聚合资源）
  loadResources(idx);
}

async function cancelCurrentTask() {
  // 批量模式：取消所有活跃任务
  if (_activeTaskIds.size > 0) {
    const ids = [..._activeTaskIds];
    _activeTaskIds.clear();
    await Promise.allSettled(ids.map(id => api(`/tasks/${id}/cancel`, { method: 'POST' })));
    toast(t('toast.cancelled'));
    return;
  }
  // 单任务模式
  if (!_currentTaskId) return;
  try { await api(`/tasks/${_currentTaskId}/cancel`, { method: 'POST' }); toast(t('toast.cancelled')); } catch (e) { toast(e.message, 'error'); }
}

function _batchSummary(done, skip, fail, cancelled) {
  return `<div class="batch-done">${cancelled ? t('wb.batch_cancelled') : t('wb.batch_done')} · ${t('wb.batch_ok')} ${done} · ${t('wb.batch_skip')} ${skip} · ${t('wb.batch_fail')} ${fail}
    <button class="btn btn-sm btn-outline" style="margin-left:0.5rem" onclick="this.parentElement.parentElement.style.display='none'">${t('batch.close_btn')}</button></div>`;
}

async function batchRun(step) {
  const names = { tts: t('step.tts'), 'first-frame': t('step.first_frame'), video: t('step.video'), lipsync: t('step.lipsync') };
  if (!await modalConfirm(t('batch.confirm', { step: names[step], n: shots.length }))) return;
  batchCancelled = false;
  _updatePipelineStep(step, 'active');
  const statusEl = document.getElementById('wb-batch-status');
  statusEl.style.display = 'block';
  const concurrency = parseInt(localStorage.getItem('drama_concurrency') || '1');
  let done = 0, fail = 0, skip = 0, idx = 0;

  function _batchProgressHTML(i, sid) {
    return `<div class="batch-progress"><div class="batch-bar"><div class="batch-fill" style="width:${(i / shots.length) * 100}%"></div></div>
      <div class="batch-text">[${i + 1}/${shots.length}] ${sid} — ${t('batch.progress', { step: names[step] })}</div>
      <div style="font-size:.82rem;margin-top:.25rem;color:var(--fg2)">${t('wb.batch_ok')} <b>${done}</b> · ${t('wb.batch_skip')} <b>${skip}</b> · ${t('wb.batch_fail')} <b style="color:${fail?'var(--red)':'inherit'}">${fail}</b></div>
      <button class="btn btn-sm btn-danger" onclick="batchCancelled=true;cancelCurrentTask()" style="margin-top:0.3rem">${t('batch.cancel_btn')}</button></div>`;
  }

  async function processShot(i) {
    if (batchCancelled) return;
    const sid = _shotId(shots[i], i);
    let task_id;
    try {
      const force = _isForce();
      ({ task_id } = await api(`/steps/${step}`, { method: 'POST', body: { episode: ep, shot_id: sid, force } }));
      _currentTaskId = task_id;
      _activeTaskIds.add(task_id);
      if (typeof TaskPanel !== 'undefined') TaskPanel.trackTask(task_id, `${names[step]} ${sid}`);
      const result = await pollTask(task_id);
      _activeTaskIds.delete(task_id);
      _currentTaskId = null;
      if (result.status === 'success') {
        const sub = result.result;
        if (sub?.status === 'error') fail++;
        else if (sub?.status === 'skipped') skip++;
        else { done++; invalidateCache(`res/${ep}/`); loadResources(i); }
      } else fail++;
    } catch { if (task_id) _activeTaskIds.delete(task_id); _currentTaskId = null; fail++; }
  }

  if (concurrency <= 1) {
    // 串行
    for (let i = 0; i < shots.length; i++) {
      if (batchCancelled) break;
      const sid = _shotId(shots[i], i);
      statusEl.innerHTML = _batchProgressHTML(i, sid);
      await processShot(i);
      statusEl.innerHTML = _batchProgressHTML(i, sid); // 更新计数
    }
  } else {
    // 并发
    const pool = new Set();
    for (let i = 0; i < shots.length; i++) {
      if (batchCancelled) break;
      const sid = _shotId(shots[i], i);
      statusEl.innerHTML = _batchProgressHTML(i, sid);
      const p = processShot(i).then(() => { pool.delete(p); statusEl.innerHTML = _batchProgressHTML(i, sid); });
      pool.add(p);
      if (pool.size >= concurrency) await Promise.race(pool);
    }
    await Promise.all(pool);
  }

  if (batchCancelled) { statusEl.innerHTML = _batchSummary(done, skip, fail, true); toast(t('toast.cancelled')); _updatePipelineStep(step, 'fail'); return; }
  statusEl.innerHTML = _batchSummary(done, skip, fail, false);
  _updatePipelineStep(step, fail > 0 ? 'fail' : 'done');
  toast(t('batch.complete', { done, skip, fail }));
}

// ── 管线工具 ──

async function _runTool(apiPath, body, label, queryParams) {
  if (!await modalConfirm(label + '?')) return;
  let url = apiPath;
  if (queryParams) {
    const qs = Object.entries(queryParams).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${v}`).join('&');
    if (qs) url += (url.includes('?') ? '&' : '?') + qs;
  }
  try {
    toast('⏳ ' + label);
    const { task_id } = await api(url, { method: 'POST', body });
    if (typeof TaskPanel !== 'undefined') TaskPanel.trackTask(task_id, label);
    const result = await pollTask(task_id);
    if (result.status === 'success' && result.result?.status !== 'error') toast('✅ ' + label);
    else toast('❌ ' + (result.result?.reason || result.error || t('wb.shot_fail')), 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
}

async function runPortraits() { _updatePipelineStep('portrait', 'active'); await _runTool('/tools/portraits', {}, t('wb.gen_portraits'), { force: _isForce() }); _updatePipelineStep('portrait', 'done'); }
async function runSceneImages() { _updatePipelineStep('scene', 'active'); await _runTool('/tools/scene-images', {}, t('wb.gen_scene_images'), { force: _isForce() }); _updatePipelineStep('scene', 'done'); }
async function runPost() { await _runTool('/tools/post', { episode: ep }, t('wb.post_process')); }

async function runPrepare() {
  if (!await modalConfirm(t('wb.prepare') + '？\n' + t('wb.prepare_hint'))) return;
  const statusEl = document.getElementById('wb-batch-status');
  statusEl.style.display = 'block';
  statusEl.innerHTML = `<div class="batch-progress"><div class="batch-bar"><div class="batch-fill" style="width:5%"></div></div>
    <div class="batch-text">⏳ ${t('wb.prepare')}...</div></div>`;
  try {
    const force = _isForce();
    const { task_id } = await api('/prepare', { method: 'POST', body: { episode: ep, force } });
    if (typeof TaskPanel !== 'undefined') TaskPanel.trackTask(task_id, t('wb.prepare'));
    const result = await pollTask(task_id, info => {
      statusEl.innerHTML = `<div class="batch-progress"><div class="batch-bar"><div class="batch-fill" style="width:${info.progress || 10}%"></div></div>
        <div class="batch-text">⏳ ${info.message || t('wb.prepare')} (${info.progress || 0}%)</div></div>`;
    });
    if (result.status === 'success' && result.result?.status !== 'error') {
      const r = result.result || {};
      statusEl.innerHTML = `<div class="batch-done">✅ ${t('wb.prepare')}
        <span style="margin-left:.5rem;font-size:.85rem;color:var(--fg2)">
          翻译: ${r.prompt_chars || 0}角色prompt + ${r.translated_scenes || 0}场景 + ${r.translated_shots || 0}镜头
        </span></div>`;
      toast('✅ ' + t('wb.prepare'));
      // 刷新资源
      invalidateCache(`storyboard/${ep}`);
      invalidateCache(`res/${ep}`);
      invalidateCache('characters');
      invalidateCache('scenes');
      renderShotsGrid();
    } else {
      statusEl.innerHTML = `<div class="batch-done">❌ ${t('wb.prepare')}: ${esc(result.result?.reason || result.error || t('wb.shot_fail'))}</div>`;
      toast('❌ ' + t('wb.prepare'), 'error');
    }
  } catch (e) {
    statusEl.innerHTML = `<div class="batch-done">❌ ${t('wb.prepare')}: ${esc(e.message)}</div>`;
    toast('❌ ' + e.message, 'error');
  }
}

async function runAll() {
  if (!await modalConfirm(t('wb.run_all') + '?')) return;
  const statusEl = document.getElementById('wb-batch-status');
  statusEl.style.display = 'block';
  const stages = ['preview', 'produce', 'post'];
  for (let i = 0; i < stages.length; i++) {
    const cmd = stages[i];
    statusEl.innerHTML = `<div class="batch-progress"><div class="batch-bar"><div class="batch-fill" style="width:${(i / stages.length) * 100}%"></div></div>
      <div class="batch-text">[${i + 1}/${stages.length}] ${cmd}...</div></div>`;
    try {
      const { task_id } = await api('/pipeline/run', { method: 'POST', body: { episode: ep, command: cmd } });
      if (typeof TaskPanel !== 'undefined') TaskPanel.trackTask(task_id, `全流程 ${cmd}`);
      const result = await pollTask(task_id);
      if (result.status !== 'success') { statusEl.innerHTML = `<div class="batch-done">❌ ${cmd}: ${esc(result.error || t('wb.shot_fail'))}</div>`; return; }
      // 检查子任务返回的实际状态（Celery SUCCESS 不代表业务成功）
      const sub = result.result;
      if (sub?.status === 'error' || sub?.status === 'empty') {
        statusEl.innerHTML = `<div class="batch-done">❌ ${cmd}: ${esc(sub.reason || sub.message || t('wb.shot_fail'))}</div>`; return;
      }
      // produce 阶段：检查是否有镜头执行失败
      if (cmd === 'produce' && sub?.shots) {
        const errors = sub.shots.filter(s => s.error || (s.errors && s.errors.length));
        if (errors.length > 0) {
          const errShots = errors.map(s => s.shot_id || '?').join(', ');
          statusEl.innerHTML = `<div class="batch-done">⚠ ${cmd}: ${errors.length} 个镜头失败 (${esc(errShots)})，后续步骤继续执行</div>`;
        }
      }
    } catch (e) { statusEl.innerHTML = `<div class="batch-done">❌ ${cmd}: ${esc(e.message)}</div>`; return; }
  }
  statusEl.innerHTML = `<div class="batch-done">✅ ${t('wb.run_all')}</div>`;
  toast('✅ ' + t('wb.run_all'));
  // 刷新资源
  invalidateCache(`storyboard/${ep}`);
  invalidateCache(`res/${ep}`);
  renderShotsGrid();
}

async function addShotFromPipeline() {
  const maxNum = Math.max(0, ...shots.map(s => parseInt(s.shot_id, 10)).filter(n => !isNaN(n)));
  const newId = String(maxNum + 1).padStart(3, '0');
  pushUndo(`${t('btn.add')} ${newId}`);
  const newShot = { ..._DEFAULT_SHOT(), episode: ep, shot_id: newId };
  shots.push(newShot);
  try {
    await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
    invalidateCache(`storyboard/${ep}`);
    toast(t('toast.created'));
    renderShotsGrid();
  } catch (e) { toast(e.message, 'error'); }
}

async function runMusic() {
  const duration = await modalPrompt(t('wb.music_duration') + ':', '60', { inputType: 'number' });
  if (!duration) return;
  const mood = await modalPrompt(t('wb.music_mood') + ':', 'neutral');
  await _runTool('/tools/music', { duration: parseFloat(duration), mood: mood || 'neutral' }, t('wb.gen_music'));
}

async function runSubtitle() { await _runTool('/tools/subtitle', { episode: ep }, t('wb.gen_subtitle')); }


// ══════════════════════════════════════════════════════════

// ── Module: pipeline ──
Drama.pipeline = { renderShotsGrid, previewRes, loadResources, loadPipeline };
Drama.pages.pipeline = loadPipeline;
window.loadPipeline = loadPipeline;
window.renderShotsGrid = renderShotsGrid;
window.previewRes = previewRes;
window.loadResources = loadResources;
window.renderWB = renderWB;
window._actionBtns = _actionBtns;
window._cameras = _cameras;
window._shotTypes = _shotTypes;
window._CAMERA_KEYS = _CAMERA_KEYS;
window._SHOTTYPE_KEYS = _SHOTTYPE_KEYS;
window._DEFAULT_SHOT = _DEFAULT_SHOT;
window.TTS_VOICE_FIELDS = TTS_VOICE_FIELDS;
window.LANGUAGES = LANGUAGES;
window.EMOTIONS = EMOTIONS;
