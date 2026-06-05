// MODULE: characters — 角色管理
// ══════════════════════════════════════════════════════════

/** 批量选择状态 */
const _batchState = {};

/** 通用实体列表渲染 */
function _loadEntityPage(type, { pageId, icon, titleKey, emptyHintKey, emptyDescKey, editFn, newFn, aiFn, card, extraButtons, batchDeleteLabel }) {
  const el = document.getElementById(pageId);
  const addLabel = t('btn.add');
  cachedFetch(type, () => api(`/${type}`)).then(d => {
    const items = d[type] || [];
    // 初始化批量选择状态
    if (!_batchState[type]) _batchState[type] = new Set();
    const selected = _batchState[type];
    const hasItems = items.length > 0;
    const batchEnabled = !!batchDeleteLabel;

    const grid = hasItems
      ? `<div class="entity-grid">${items.map(it => {
          const cardHtml = card(it);
          if (!batchEnabled) return cardHtml;
          // 在卡片前插入复选框
          const checked = selected.has(it.id) ? 'checked' : '';
          return `<div class="entity-card-wrap" style="position:relative"><label class="batch-check" style="position:absolute;top:6px;left:6px;z-index:2"><input type="checkbox" class="batch-cb-${type}" value="${esc(it.id)}" ${checked} onclick="event.stopPropagation();_toggleBatchSelect('${type}','${esc(it.id)}',this.checked)"></label>${cardHtml}</div>`;
        }).join('')}</div>`
      : `<div class="empty-state"><div class="empty-state-icon">${icon}</div><h3>${t(emptyHintKey)}</h3><p>${t(emptyDescKey)}</p><button class="btn btn-success" onclick="${newFn}()">+ ${addLabel}</button></div>`;

    const extraBtns = extraButtons ? extraButtons(items) : '';
    const batchBtns = hasItems && batchEnabled
      ? `<button class="btn btn-outline btn-sm" onclick="_toggleSelectAll('${type}')">${t('btn.select_all')}</button><button class="btn btn-danger btn-sm" onclick="_batchDeleteEntities('${type}','${batchDeleteLabel}')" id="batch-del-${type}" style="display:${selected.size > 0 ? '' : 'none'}">${t('btn.batch_delete')} (<span id="batch-count-${type}">${selected.size}</span>)</button>`
      : '';
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem"><h2>${icon} ${t(titleKey)}</h2><div style="display:flex;gap:0.5rem;flex-wrap:wrap">${batchBtns}${extraBtns}<button class="btn btn-outline btn-ai" onclick="${aiFn}()">🤖 AI 生成</button><button class="btn btn-success" onclick="${newFn}()">+ ${addLabel}</button></div></div>${grid}</div>`;
  }).catch(e => { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; });
}

function _toggleBatchSelect(type, id, checked) {
  if (!_batchState[type]) _batchState[type] = new Set();
  if (checked) _batchState[type].add(id); else _batchState[type].delete(id);
  _updateBatchBtn(type);
}

function _updateBatchBtn(type) {
  const countEl = document.getElementById(`batch-count-${type}`);
  const btnEl = document.getElementById(`batch-del-${type}`);
  const n = _batchState[type]?.size || 0;
  if (countEl) countEl.textContent = n;
  if (btnEl) btnEl.style.display = n > 0 ? '' : 'none';
}

function _toggleSelectAll(type) {
  const cbs = document.querySelectorAll(`.batch-cb-${type}`);
  if (!_batchState[type]) _batchState[type] = new Set();
  const allChecked = Array.from(cbs).every(cb => cb.checked);
  cbs.forEach(cb => { cb.checked = !allChecked; });
  if (allChecked) { _batchState[type].clear(); } else { cbs.forEach(cb => _batchState[type].add(cb.value)); }
  _updateBatchBtn(type);
}

async function _batchDeleteEntities(type, labelKey) {
  const ids = Array.from(_batchState[type] || []);
  if (!ids.length) { toast(t('toast.select_first'), 'error'); return; }
  if (!await modalConfirm(t(labelKey, { n: ids.length }))) return;
  try {
    const r = await api(`/${type}/batch-delete`, { method: 'POST', body: { ids } });
    const done = r.deleted?.length || 0;
    const fail = r.errors?.length || 0;
    _batchState[type].clear();
    invalidateCache(type);
    toast(t('toast.batch_delete_done', { done, fail }));
    // 重载页面
    if (type === 'characters') loadCharacters();
    else if (type === 'scenes') loadScenes();
  } catch (e) { toast(e.message, 'error'); }
}

/** 通用编辑面板 */
function _editEntityPanel(type, id, { titleKey, notFoundKey, fields, imgPrefix, imgLabel, confirmMsg, imgKey = 'reference_images', buildExtra, reload, extraHtml, deleteFn }) {
  const p = imgPrefix;
  api(`/${type}`).then(d => {
    const item = (d[type] || []).find(x => x.id === id);
    if (!item) { toast(t(notFoundKey), 'error'); return; }
    const imgs = item[imgKey] || [];
    // 多图 gallery（五视图）或单图回退
    let existingImg;
    if (imgs.length > 1) {
      const viewLabels = ['正面', '左侧', '右侧', '背面', '3/4侧'];
      const gallery = imgs.map((url, i) =>
        `<div class="upload-preview" style="display:inline-block;margin-right:.4rem;position:relative">
          <img src="${esc(url)}" style="width:80px;height:80px;object-fit:cover;border-radius:6px;cursor:pointer" onclick="previewImage('${esc(url)}')" title="${viewLabels[i] || '参考图'}">
          <span style="position:absolute;bottom:2px;left:2px;background:rgba(0,0,0,.7);color:#fff;font-size:.6rem;padding:1px 4px;border-radius:3px">${viewLabels[i] || i+1}</span>
          <button class="btn btn-xs btn-danger upload-remove" style="position:absolute;top:-6px;right:-6px;width:18px;height:18px;padding:0;font-size:.65rem;line-height:1" onclick="${p}RemoveImgAt('${id}',${i})">✕</button>
        </div>`
      ).join('') + `<div class="upload-area" style="display:inline-flex;width:80px;height:80px;cursor:pointer" onclick="document.getElementById('${p}-file').click()"><span class="upload-icon" style="font-size:1.2rem">📷</span></div>`;
      existingImg = `<div id="${p}-img-wrap" style="display:flex;flex-wrap:wrap;align-items:center;gap:.3rem">${gallery}</div>`;
    } else if (imgs.length === 1) {
      existingImg = `<div id="${p}-img-wrap"><div class="upload-preview"><img src="${esc(imgs[0])}" id="${p}-img-preview"><button class="btn btn-xs btn-danger upload-remove" onclick="${p}RemoveImg('${id}')">✕</button></div></div>`;
    } else {
      existingImg = `<div id="${p}-img-wrap"><div class="upload-area" id="${p}-upload-area" onclick="document.getElementById('${p}-file').click()" ondragover="event.preventDefault();this.classList.add('dragover')" ondragleave="this.classList.remove('dragover')" ondrop="${p}HandleDrop(event,'${id}')"><span class="upload-icon">📷</span><span>${t('common.upload_hint')}</span></div></div>`;
    }
    const body = `<div class="edit-field"><label>${imgLabel}</label>${existingImg}<input type="file" id="${p}-file" accept="image/*" style="display:none" onchange="${p}UploadImg('${id}')"></div>` +
      fields.map(f => {
        const v = f.getValue ? f.getValue(item) : (item[f.key] || '');
        if (f.type === 'select') return `<div class="edit-field"><label>${f.label}</label><select id="${p}-${f.key}">${f.options.map(o => `<option value="${o.value}" ${v===o.value?'selected':''}>${o.label}</option>`).join('')}</select></div>`;
        if (f.type === 'textarea') return `<div class="edit-field"><label>${f.label}</label><textarea id="${p}-${f.key}" rows="3">${esc(v)}</textarea></div>`;
        return `<div class="edit-field"><label>${f.label}</label><input id="${p}-${f.key}" value="${esc(v)}"></div>`;
      }).join('') + (typeof extraHtml === 'function' ? extraHtml(item) : (extraHtml || ''));
    window[`_${p}ImgRemoved`] = false;
    const safeId = esc(id);
    const delFn = deleteFn ? `delete_${p}Edit('${safeId}')` : undefined;
    _showOverlay(`edit-${type.slice(0,-1)}-overlay`, `${t(titleKey)} ${safeId}`, body, `save_${p}Edit('${safeId}')`, undefined, delFn);
  }).catch(e => toast(e.message, 'error'));
  window[`save_${p}Edit`] = async function(eid) {
    const removed = window[`_${p}ImgRemoved`];
    const removedIndices = window[`_${p}RemovedIndices`] || [];
    window[`_${p}ImgRemoved`] = false;
    window[`_${p}RemovedIndices`] = [];
    const data = buildExtra ? { ...buildExtra() } : {};
    fields.forEach(f => { if (!f.getValue) data[f.key] = $val(`${p}-${f.key}`); });
    // 保留已有 reference_images（如果本次没有显式清除或覆盖）
    if (!(imgKey in data)) {
      const genUrl = window[`_${p}GeneratedPortraitUrl`];
      if (genUrl) {
        // 新上传的图片：追加到已有列表
        try {
          let items = _cache.get(type)?.data?.[type];
          if (!items) { const fresh = await api(`/${type}`); items = fresh[type] || []; }
          const existing = items.find(x => x.id === eid);
          const existingImgs = existing?.[imgKey]?.length ? [...existing[imgKey]] : [];
          existingImgs.push(genUrl);
          data[imgKey] = existingImgs;
        } catch {
          data[imgKey] = [genUrl];
        }
        window[`_${p}GeneratedPortraitUrl`] = null;
      } else if (removed) {
        data[imgKey] = [];
      } else if (removedIndices.length > 0) {
        // 删除了指定索引的图片
        try {
          let items = _cache.get(type)?.data?.[type];
          if (!items) { const fresh = await api(`/${type}`); items = fresh[type] || []; }
          const existing = items.find(x => x.id === eid);
          const existingImgs = existing?.[imgKey]?.length ? [...existing[imgKey]] : [];
          data[imgKey] = existingImgs.filter((_, i) => !removedIndices.includes(i));
        } catch {}
      } else {
        try {
          let items = _cache.get(type)?.data?.[type];
          if (!items) { const fresh = await api(`/${type}`); items = fresh[type] || []; }
          const existing = items.find(x => x.id === eid);
          if (existing && existing[imgKey]?.length) data[imgKey] = existing[imgKey];
        } catch {}
      }
    }
    await _crudSave(type, eid, () => data, `edit-${type.slice(0,-1)}-overlay`, reload);
  };
  if (deleteFn) {
    window[`delete_${p}Edit`] = async function(eid) {
      document.getElementById(`edit-${type.slice(0,-1)}-overlay`)?.remove();
      await deleteFn(eid);
    };
  }
  window[`${p}UploadImg`] = async function(eid) { await _uploadImg(type, eid); };
  window[`${p}HandleDrop`] = function(e, eid) { _handleImgDrop(e, type, eid); };
  window[`${p}RemoveImg`] = async function(eid) {
    if (!await modalConfirm(confirmMsg)) return;
    window[`_${p}ImgRemoved`] = true;
    _html(document.getElementById(`${p}-img-wrap`), `<div class="upload-area" onclick="document.getElementById('${p}-file').click()"><span class="upload-icon">📷</span><span>${t('common.upload_hint')}</span></div>`);
  };
  // 删除指定索引的图片（五视图场景）
  window[`${p}RemoveImgAt`] = async function(eid, idx) {
    if (!await modalConfirm('删除此图片？')) return;
    if (!window[`_${p}RemovedIndices`]) window[`_${p}RemovedIndices`] = [];
    window[`_${p}RemovedIndices`].push(idx);
    // 从 DOM 中移除
    const wrap = document.getElementById(`${p}-img-wrap`);
    if (wrap) {
      const previews = wrap.querySelectorAll('.upload-preview');
      if (previews[idx]) previews[idx].remove();
      // 如果删完了，显示上传区域
      if (wrap.querySelectorAll('.upload-preview').length === 0) {
        window[`_${p}ImgRemoved`] = true;
        _html(wrap, `<div class="upload-area" onclick="document.getElementById('${p}-file').click()"><span class="upload-icon">📷</span><span>${t('common.upload_hint')}</span></div>`);
      }
    }
  };
}

/** 图片预览（点击放大） */
function previewImage(url) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:9999;display:flex;align-items:center;justify-content:center;cursor:pointer';
  overlay.innerHTML = `<img src="${esc(url)}" style="max-width:90vw;max-height:90vh;border-radius:8px"><div style="position:absolute;top:1rem;right:1rem;color:#fff;font-size:1.5rem;cursor:pointer">✕</div>`;
  overlay.onclick = () => overlay.remove();
  document.body.appendChild(overlay);
}

async function loadCharacters() {
  _loadEntityPage('characters', {
    pageId: 'page-characters', icon: '👤', titleKey: 'char.title',
    emptyHintKey: 'char.empty_hint', emptyDescKey: 'char.empty_desc',
    editFn: 'editChar', newFn: 'newChar', aiFn: 'showAIGenCharacter',
    batchDeleteLabel: 'confirm.batch_delete_chars',
    extraButtons: (items) => items.length ? `<button class="btn btn-outline btn-sm" onclick="batchTrainLora()" id="batch-train-btn">🏋 批量训练 LoRA</button>` : '',
    card: c => {
      const avatar = c.appearance ? esc(c.appearance.substring(0, 2)) : '👤';
      const imgCount = c.reference_images?.length || 0;
      const thumb = imgCount > 0 ? `<img src="${esc(c.reference_images[0])}" loading="lazy">${imgCount > 1 ? `<span style="position:absolute;bottom:2px;right:2px;background:rgba(0,0,0,.7);color:#fff;font-size:.6rem;padding:1px 4px;border-radius:3px">${imgCount}图</span>` : ''}` : avatar;
      return `<div class="entity-card" onclick="editChar('${esc(c.id)}')"><div class="entity-card-thumb">${thumb}</div><div class="entity-card-body"><h3>${esc(c.name || c.id)}</h3><p>${esc(c.appearance || '')}</p></div><div class="entity-card-footer"><span class="entity-card-id">${esc(c.id)}</span><span>${c.gender === 'male' ? '♂' : c.gender === 'female' ? '♀' : ''} <button class="btn btn-xs btn-danger" onclick="event.stopPropagation();deleteChar('${esc(c.id)}')" title="${t('btn.delete')}">🗑</button></span></div></div>`;
    }
  });
}
/** 通用新建面板 */
function _newEntityPanel(type, { titleKey, fields, buildExtra, reload, extraHtml }) {
  const p = `n${type[0]}`; // nc / ns
  const body = `<div class="edit-field"><label>ID</label><input id="${p}-id" placeholder="a-z, 0-9, _-"></div>` +
    fields.map(f => {
      if (f.type === 'select') return `<div class="edit-field"><label>${f.label}</label><select id="${p}-${f.key}">${f.options.map(o => `<option value="${o.value}">${o.label}</option>`).join('')}</select></div>`;
      if (f.type === 'textarea') return `<div class="edit-field"><label>${f.label}</label><textarea id="${p}-${f.key}" rows="3"></textarea></div>`;
      return `<div class="edit-field"><label>${f.label}</label><input id="${p}-${f.key}"${f.placeholder ? ` placeholder="${f.placeholder}"` : ''}></div>`;
    }).join('') + (extraHtml || '');
  _showOverlay(`new-${type.slice(0,-1)}-overlay`, `+ ${t(titleKey)}`, body, `save_${p}New()`);
  window[`save_${p}New`] = async function() {
    const id = $val(`${p}-id`);
    if (!id || !/^[a-zA-Z0-9_-]+$/.test(id)) { toast(t('common.id_invalid'), 'error'); return; }
    const data = buildExtra ? { id, ...buildExtra() } : { id };
    fields.forEach(f => { if (!f.getValue) data[f.key] = $val(`${p}-${f.key}`); });
    try {
      await api(`/${type}`, { method: 'POST', body: data });
      invalidateCache(type); document.getElementById(`new-${type.slice(0,-1)}-overlay`)?.remove(); toast(t('toast.created')); reload();
    } catch (e) { toast(e.message, 'error'); }
  };
}

/** 获取当前 TTS 后端名称（缓存） */
async function _getTtsBackend() {
  try {
    const cfg = await cachedFetch('sysconfig', () => api('/system/config'));
    return cfg.models?.tts_backend || 'mimo-voicedesign';
  } catch { return 'mimo-voicedesign'; }
}

/** 构建 TTS 语音参数 HTML 字段 */
function _ttsVoiceFieldsHtml(prefix, voiceData = {}) {
  const backend = _cache.get('sysconfig')?.data?.models?.tts_backend || 'mimo-voicedesign';
  const fields = TTS_VOICE_FIELDS[backend] || TTS_VOICE_FIELDS['mimo-voicedesign'];
  return `<div class="edit-field" style="margin-top:.5rem"><label>⚙ ${t('char.voice_params')} <span class="dim" style="font-size:.75rem">(${backend})</span></label></div>` +
    fields.map(f => {
      const v = voiceData[f.key] || '';
      const lbl = typeof f.label === 'function' ? f.label() : f.label;
      const ph = f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : '';
      if (f.type === 'textarea') return `<div class="edit-field"><label>${lbl}</label><textarea id="${prefix}-${f.key}" rows="2"${ph}>${esc(v)}</textarea></div>`;
      return `<div class="edit-field"><label>${lbl}</label><input id="${prefix}-${f.key}" value="${esc(v)}"${ph}></div>`;
    }).join('');
}

/** 从表单收集 TTS voice 参数 */
function _collectVoiceConfig(prefix) {
  const backend = _cache.get('sysconfig')?.data?.models?.tts_backend || 'mimo-voicedesign';
  const fields = TTS_VOICE_FIELDS[backend] || TTS_VOICE_FIELDS['mimo-voicedesign'];
  const voice = {};
  for (const f of fields) {
    const val = $val(`${prefix}-${f.key}`);
    if (val) voice[f.key] = val;
  }
  return Object.keys(voice).length ? voice : null;
}

function newChar() {
  _getTtsBackend().then(() => {
    _newEntityPanel('characters', {
      titleKey: 'char.title', reload: loadCharacters,
      buildExtra() {
        const coreTraits = $val('nc-personality') || '';
        const data = { voice: _collectVoiceConfig('nc') };
        if ($val('nc-outfits')) data.outfits = { default: { description: $val('nc-outfits'), reference_images: [] } };
        // bible: 只在用户填写了性格时才创建
        if (coreTraits) data.bible = { core_traits: coreTraits };
        return data;
      },
      extraHtml: _ttsVoiceFieldsHtml('nc'),
      fields: [
        { key: 'name', label: t('char.name') },
        { key: 'gender', label: t('char.gender'), type: 'select', options: [{ value: '', label: '-' }, { value: 'male', label: t('char.gender.male') }, { value: 'female', label: t('char.gender.female') }] },
        { key: 'appearance', label: t('char.appearance'), type: 'textarea' },
        { key: 'personality', label: t('char.personality') || '性格', type: 'textarea', getValue: (item) => (item.bible || {}).core_traits || '' },
        { key: 'outfits', label: t('char.outfit_desc'), type: 'textarea', getValue: true },
      ],
    });
  });
}
async function saveNewChar() { /* handled by _newEntityPanel */ }
function deleteChar(id) { deleteCharWithRef(id); }

async function generatePortrait(charId) {
  const btn = document.getElementById('gen-portrait-btn');
  const status = document.getElementById('gen-portrait-status');
  const reset = _btnLoad(btn, '⏳ 生成中...');
  _html(status, '⏳ AI 正在生成定妆照...');
  try {
    const { task_id } = await api(`/characters/${charId}/generate-portrait`, { method: 'POST' });
    if (typeof TaskPanel !== "undefined") TaskPanel.trackTask(task_id, "定妆照");
    const result = await pollTask(task_id, info => _html(status, `⏳ ${info.message || '生成中...'} (${info.progress || 0}%)`));
    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      _html(status, '✅ 生成完成');
      toast(t('toast.portrait_done'));
      const preview = document.getElementById('ec-img-preview');
      if (preview && r.url) {
        preview.src = r.url + '?t=' + Date.now();
      } else if (r.url) {
        const wrap = document.getElementById('ec-img-wrap');
        if (wrap) {
          wrap.innerHTML = `<div class="upload-preview"><img src="${r.url}?t=${Date.now()}" id="ec-img-preview"><button class="btn btn-xs btn-danger upload-remove" onclick="ecRemoveImg('${charId}')">✕</button></div>`;
        }
      }
      // 保存生成的 URL，确保后续保存时不会丢失
      window._ecGeneratedPortraitUrl = r.url;
      invalidateCache('characters');
    } else {
      const err = result.result?.reason || result.error || '生成失败';
      _html(status, `❌ ${err}`);
      toast(`❌ ${err}`, 'error');
    }
  } catch (e) {
    _html(status, `❌ ${e.message}`);
    toast(`❌ ${e.message}`, 'error');
  }
  reset();
}

async function generateSceneImage(sceneId) {
  const btn = document.getElementById('gen-scene-img-btn');
  const status = document.getElementById('gen-scene-img-status');
  const reset = _btnLoad(btn, '⏳ 生成中...');
  _html(status, '⏳ AI 正在生成场景图...');
  try {
    const { task_id } = await api(`/scenes/${sceneId}/generate-image`, { method: 'POST' });
    if (typeof TaskPanel !== "undefined") TaskPanel.trackTask(task_id, "场景图");
    const result = await pollTask(task_id, info => _html(status, `⏳ ${info.message || '生成中...'} (${info.progress || 0}%)`));
    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      _html(status, '✅ 生成完成');
      toast(t('toast.scene_img_done'));
      const preview = document.getElementById('es-img-preview');
      if (preview && r.url) {
        preview.src = r.url + '?t=' + Date.now();
      } else if (r.url) {
        const wrap = document.getElementById('es-img-wrap');
        if (wrap) {
          wrap.innerHTML = `<div class="upload-preview"><img src="${r.url}?t=${Date.now()}" id="es-img-preview"><button class="btn btn-xs btn-danger upload-remove" onclick="esRemoveImg('${sceneId}')">✕</button></div>`;
        }
      }
      // 保存生成的 URL，确保后续保存时不会丢失
      window._esGeneratedPortraitUrl = r.url;
      invalidateCache('scenes');
    } else {
      const err = result.result?.reason || result.error || '生成失败';
      _html(status, `❌ ${err}`);
      toast(`❌ ${err}`, 'error');
    }
  } catch (e) {
    _html(status, `❌ ${e.message}`);
    toast(`❌ ${e.message}`, 'error');
  }
  reset();
}

/** 构建服装列表 HTML（支持多套服装 + 单独/批量生成） */
function _outfitFieldsHtml(charId, outfits = {}) {
  const entries = Object.entries(outfits);
  let html = `<div class="edit-field"><label>👗 服装列表 <button class="btn btn-xs btn-ai" onclick="addOutfitField()">+ 添加</button> <button class="btn btn-xs btn-ai" onclick="generateAllOutfits('${esc(charId)}')" id="gen-all-outfits-btn">🎨 批量生成全部</button><span id="gen-all-outfits-status" class="dim" style="font-size:.8rem;margin-left:.5rem"></span></label></div>`;
  html += `<div id="ec-outfit-list">`;
  if (entries.length === 0) {
    html += _outfitEntryHtml('', '', charId);
  } else {
    for (const [key, val] of entries) {
      const desc = val?.description || '';
      const imgs = val?.reference_images || [];
      html += _outfitEntryHtml(key, desc, charId, imgs);
    }
  }
  html += `</div>`;
  return html;
}

function _outfitEntryHtml(key, desc, charId, imgs = []) {
  const k = esc(key);
  const d = esc(desc);
  const imgsJson = esc(JSON.stringify(imgs));
  const thumb = imgs.length ? `<img src="${esc(imgs[0])}" style="width:36px;height:36px;border-radius:4px;object-fit:cover;flex-shrink:0;cursor:pointer" onclick="previewImage('${esc(imgs[0])}')" title="点击放大">` : '';
  return `<div class="outfit-entry" data-imgs='${imgsJson}' style="display:flex;gap:.4rem;align-items:flex-start;margin-bottom:.5rem">` +
    thumb +
    `<input class="outfit-key" value="${k}" placeholder="服装名 (如 default)" style="width:120px;flex-shrink:0">` +
    `<textarea class="outfit-desc" rows="1" placeholder="服装描述" style="flex:1;min-height:1.8rem">${d}</textarea>` +
    `<button class="btn btn-xs btn-ai" onclick="generateOutfit('${esc(charId)}', this)" title="生成此服装参考图">🎨</button>` +
    `<button class="btn btn-xs btn-danger" onclick="removeOutfitField(this)" title="删除">✕</button>` +
    `</div>`;
}

function addOutfitField() {
  const list = document.getElementById('ec-outfit-list');
  if (!list) return;
  list.insertAdjacentHTML('beforeend', _outfitEntryHtml('', '', _currentEditCharId || ''));
}

function removeOutfitField(btn) {
  const entry = btn.closest('.outfit-entry');
  if (entry) entry.remove();
}

/** 从表单收集所有服装配置（保留 reference_images） */
function _collectOutfits() {
  const entries = document.querySelectorAll('#ec-outfit-list .outfit-entry');
  const outfits = {};
  for (const entry of entries) {
    const key = entry.querySelector('.outfit-key')?.value?.trim();
    const desc = entry.querySelector('.outfit-desc')?.value?.trim();
    if (!key || !desc) continue;
    let imgs = [];
    try { imgs = JSON.parse(entry.dataset.imgs || '[]'); } catch {}
    outfits[key] = { description: desc, reference_images: imgs };
  }
  return Object.keys(outfits).length ? outfits : null;
}

/** 单个服装参考图生成（异步） */
async function generateOutfit(charId, btnEl) {
  const entry = btnEl.closest('.outfit-entry');
  const key = entry?.querySelector('.outfit-key')?.value?.trim();
  if (!key) { toast(t('toast.fill_name'), 'error'); return; }
  const statusEl = document.getElementById('gen-all-outfits-status');
  const reset = _btnLoad(btnEl, '⏳');
  try {
    const { task_id } = await api(`/characters/${charId}/generate-outfit?outfit_key=${encodeURIComponent(key)}`, { method: 'POST' });
    if (typeof TaskPanel !== "undefined") TaskPanel.trackTask(task_id, "服装 " + key);
    const result = await pollTask(task_id, info => { if (statusEl) _html(statusEl, `⏳ ${key}: ${info.message || '生成中...'} (${info.progress || 0}%)`); });
    if (result.status === 'success' && result.result?.status === 'done') {
      toast(t('toast.outfit_done', { key }));
      // 更新 DOM 中的 data-imgs，确保后续保存不丢失
      const r = result.result;
      if (r.url && entry) {
        try { entry.dataset.imgs = JSON.stringify([r.url]); } catch {}
      }
      invalidateCache('characters');
    } else {
      const err = result.result?.reason || result.error || '生成失败';
      toast(`❌ ${key}: ${err}`, 'error');
    }
  } catch (e) { toast(`❌ ${e.message}`, 'error'); }
  reset();
  if (statusEl) _html(statusEl, '');
}

/** 批量生成所有服装参考图（异步） */
async function generateAllOutfits(charId) {
  const btn = document.getElementById('gen-all-outfits-btn');
  const status = document.getElementById('gen-all-outfits-status');
  const reset = _btnLoad(btn, '⏳ 批量生成中...');
  _html(status, '⏳ 提交批量任务...');
  try {
    const { task_id } = await api(`/characters/${charId}/generate-outfits`, { method: 'POST' });
    if (typeof TaskPanel !== "undefined") TaskPanel.trackTask(task_id, "批量服装");
    const result = await pollTask(task_id, info => _html(status, `⏳ ${info.message || '生成中...'} (${info.progress || 0}%)`));
    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      _html(status, `✅ 完成 (${r.success || 0}/${r.total || 0})`);
      toast(t('toast.outfits_batch_done', { done: r.success || 0, total: r.total || 0 }));
      // 更新 DOM 中各服装的 data-imgs
      if (r.generated) {
        for (const g of r.generated) {
          if (g.url && g.outfit) {
            const entries = document.querySelectorAll('#ec-outfit-list .outfit-entry');
            for (const entry of entries) {
              if (entry.querySelector('.outfit-key')?.value?.trim() === g.outfit) {
                try { entry.dataset.imgs = JSON.stringify([g.url]); } catch {}
                break;
              }
            }
          }
        }
      }
      invalidateCache('characters');
    } else {
      const err = result.result?.reason || result.error || '生成失败';
      _html(status, `❌ ${err}`);
      toast(`❌ ${err}`, 'error');
    }
  } catch (e) { _html(status, `❌ ${e.message}`); toast(`❌ ${e.message}`, 'error'); }
  reset();
}

let _currentEditCharId = '';

// ── LoRA 训练 ──

function _loraTrainHtml(charId, item) {
  const loraPath = item.lora_path || '';
  const hasLora = !!loraPath;
  const statusDot = hasLora ? '<span class="status-dot ok"></span>' : '<span class="status-dot err"></span>';
  const statusText = hasLora ? t('train.trained') : t('train.not_trained');
  return `
    <div class="config-section" style="margin-top:1rem;border-top:1px solid var(--bg3);padding-top:1rem">
      <h3>${t('train.title')}</h3>
      <p class="dim" style="font-size:.8rem;margin-bottom:.8rem">${t('train.desc')}</p>
      <div id="lora-status-row" style="display:flex;align-items:center;gap:.5rem;margin-bottom:.8rem">
        ${statusDot}<span id="lora-status-text">${statusText}</span>
        <span id="lora-status-detail" class="dim" style="font-size:.75rem">${loraPath ? loraPath.split('/').pop() : ''}</span>
      </div>
      <div class="edit-field"><label>${t('train.trigger')}</label><input id="train-trigger" value="${esc(item.lora_trigger || '')}" placeholder="ohwx ${esc(item.name || charId)}"><span class="dim" style="font-size:.7rem">${t('train.trigger_hint')}</span></div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.5rem">
        <div class="edit-field"><label>${t('train.steps')}</label><input id="train-steps" type="number" value="600" min="100" max="10000" step="100"></div>
        <div class="edit-field"><label>${t('train.lr')}</label><input id="train-lr" type="text" value="0.0001"></div>
        <div class="edit-field"><label>${t('train.rank')}</label><select id="train-rank"><option value="4">4</option><option value="8">8</option><option value="16" selected>16</option><option value="32">32</option><option value="64">64</option><option value="128">128</option></select></div>
      </div>
      <div class="edit-field"><label>${t('train.resolution')}</label><select id="train-resolution"><option value="512x512">512x512</option><option value="512x768" selected>512x768</option><option value="768x768">768x768</option><option value="768x1024">768x1024</option></select></div>
      <div style="display:flex;align-items:center;gap:.8rem;margin-top:.5rem">
        <button class="btn btn-primary btn-sm" onclick="startLoraTraining('${esc(charId)}')" id="train-lora-btn">${t('train.start')}</button>
        <label class="inspire-check" style="font-size:.8rem"><input type="checkbox" id="train-force"> ${t('train.force')}</label>
        <span id="train-lora-status" class="dim" style="font-size:.8rem"></span>
      </div>
      <div id="train-lora-progress" style="margin-top:.5rem"></div>
    </div>`;
}

async function _loadLoraStatus(charId) {
  try {
    const d = await api(`/training/status/${charId}`);
    const dot = document.querySelector('#lora-status-row .status-dot');
    const text = document.getElementById('lora-status-text');
    const detail = document.getElementById('lora-status-detail');
    if (!dot || !text) return;
    if (d.has_lora) {
      dot.className = 'status-dot ok';
      text.textContent = t('train.trained');
      const sizeMB = d.lora_size ? (d.lora_size / 1024 / 1024).toFixed(1) : '?';
      detail.textContent = `${t('train.size')}: ${sizeMB}MB`;
    } else {
      dot.className = 'status-dot err';
      text.textContent = t('train.not_trained');
      detail.textContent = '';
    }
  } catch {}
}

async function startLoraTraining(charId) {
  const btn = document.getElementById('train-lora-btn');
  const statusEl = document.getElementById('train-lora-status');
  const progressEl = document.getElementById('train-lora-progress');
  const reset = _btnLoad(btn, '⏳');
  _html(statusEl, t('train.progress'));
  _html(progressEl, '');
  try {
    // 先保存触发词到 YAML
    const trigger = $val('train-trigger') || '';
    await api(`/training/trigger?char_id=${encodeURIComponent(charId)}&trigger=${encodeURIComponent(trigger)}`, { method: 'POST' });
    const body = {
      char_id: charId,
      steps: parseInt($val('train-steps')) || 600,
      learning_rate: parseFloat($val('train-lr')) || 0.0001,
      rank: parseInt($val('train-rank')) || 16,
      resolution: $val('train-resolution') || '512x768',
      force: document.getElementById('train-force')?.checked || false,
    };
    const { task_id } = await api('/training/lora', { method: 'POST', body });
    if (typeof TaskPanel !== "undefined") TaskPanel.trackTask(task_id, "LoRA 训练");
    const result = await pollTask(task_id, info => {
      _html(progressEl, `<div style="background:var(--bg2);border-radius:6px;padding:.4rem .6rem;font-size:.8rem">
        <div style="display:flex;justify-content:space-between;margin-bottom:.3rem"><span>${esc(info.message || '训练中...')}</span><span>${info.progress || 0}%</span></div>
        <div style="background:var(--bg4);border-radius:3px;height:6px;overflow:hidden"><div style="background:var(--primary);height:100%;width:${info.progress || 0}%;transition:width .3s"></div></div>
      </div>`);
    });
    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      _html(statusEl, `✅ ${t('train.done')} (${r.images} imgs, ${r.steps} steps)`);
      _html(progressEl, '');
      toast(t('toast.lora_done', { id: charId }));
      _loadLoraStatus(charId);
      invalidateCache('characters');
    } else {
      const err = result.result?.reason || result.error || t('train.failed');
      _html(statusEl, `❌ ${err}`);
      _html(progressEl, '');
      toast(`❌ ${err}`, 'error');
    }
  } catch (e) { _html(statusEl, `❌ ${e.message}`); toast(`❌ ${e.message}`, 'error'); }
  reset();
}

/** 批量训练所有角色 LoRA */
async function batchTrainLora() {
  // 弹出确认面板：显示参数选项 + 角色列表
  let chars = [];
  try {
    const d = await api('/characters');
    chars = d.characters || [];
  } catch (e) { toast(e.message, 'error'); return; }
  if (!chars.length) { toast(t('char.empty_hint'), 'error'); return; }

  const charList = chars.map(c => {
    const hasPortrait = c.reference_images?.length;
    const dot = hasPortrait ? '🟢' : '🔴';
    return `<label class="inspire-check" style="display:flex;align-items:center;gap:.4rem;padding:.2rem 0"><input type="checkbox" class="batch-train-char" value="${esc(c.id)}" ${hasPortrait ? 'checked' : 'disabled'}> ${dot} ${esc(c.name || c.id)} <span class="dim" style="font-size:.7rem">${esc(c.id)}</span></label>`;
  }).join('');

  const body = `
    <p class="dim" style="font-size:.8rem;margin-bottom:.8rem">选择要训练 LoRA 的角色（🟢 有定妆照可训练，🔴 无定妆照需先生成）</p>
    <div style="max-height:300px;overflow-y:auto;margin-bottom:1rem">${charList}</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.5rem;margin-bottom:.5rem">
      <div class="edit-field"><label>${t('train.steps')}</label><input id="batch-train-steps" type="number" value="600" min="100" max="10000" step="100"></div>
      <div class="edit-field"><label>${t('train.lr')}</label><input id="batch-train-lr" type="text" value="0.0001"></div>
      <div class="edit-field"><label>${t('train.rank')}</label><select id="batch-train-rank"><option value="8">8</option><option value="16" selected>16</option><option value="32">32</option><option value="64">64</option></select></div>
    </div>
    <div class="edit-field"><label>${t('train.resolution')}</label><select id="batch-train-resolution"><option value="512x512">512x512</option><option value="512x768" selected>512x768</option><option value="768x768">768x768</option></select></div>
    <label class="inspire-check" style="margin-top:.5rem"><input type="checkbox" id="batch-train-force"> ${t('train.force')}</label>
    <div id="batch-train-status" style="margin-top:.8rem"></div>
    <div id="batch-train-progress" style="margin-top:.5rem"></div>`;

  _showOverlay('batch-train-overlay', '🏋 批量训练 LoRA', body, undefined, undefined, undefined);
  // 替换保存按钮为开始训练按钮
  const overlay = document.getElementById('batch-train-overlay');
  const saveBtn = overlay?.querySelector('.btn-primary');
  if (saveBtn) {
    saveBtn.textContent = t('train.start');
    saveBtn.onclick = _doBatchTrain;
  }
}

async function _doBatchTrain() {
  const checkboxes = document.querySelectorAll('.batch-train-char:checked');
  const charIds = Array.from(checkboxes).map(cb => cb.value).filter(Boolean);
  if (!charIds.length) { toast(t('toast.select_chars'), 'error'); return; }

  const steps = parseInt($val('batch-train-steps')) || 600;
  const lr = parseFloat($val('batch-train-lr')) || 0.0001;
  const rank = parseInt($val('batch-train-rank')) || 16;
  const resolution = $val('batch-train-resolution') || '512x768';
  const force = document.getElementById('batch-train-force')?.checked || false;

  const statusEl = document.getElementById('batch-train-status');
  const progressEl = document.getElementById('batch-train-progress');
  const total = charIds.length;
  let done = 0, failed = 0, skipped = 0;

  _html(statusEl, `⏳ 开始批量训练 ${total} 个角色...`);

  for (let i = 0; i < charIds.length; i++) {
    const cid = charIds[i];
    _html(progressEl, `
      <div style="margin-bottom:.5rem">
        <div style="display:flex;justify-content:space-between;font-size:.8rem;margin-bottom:.2rem">
          <span>[${i+1}/${total}] ${esc(cid)}</span><span>${done}✅ ${skipped}⏭ ${failed}❌</span>
        </div>
        <div style="background:var(--bg4);border-radius:3px;height:6px;overflow:hidden">
          <div style="background:var(--primary);height:100%;width:${(i/total)*100}%;transition:width .3s"></div>
        </div>
      </div>`);

    try {
      const { task_id } = await api('/training/lora', {
        method: 'POST',
        body: { char_id: cid, steps, learning_rate: lr, rank, resolution, force }
      });
      if (typeof TaskPanel !== "undefined") TaskPanel.trackTask(task_id, "批量 LoRA " + cid);
      const result = await pollTask(task_id, info => {
        const statusLine = document.querySelector('#batch-train-status');
        if (statusLine) _html(statusLine, `⏳ [${i+1}/${total}] ${esc(cid)}: ${info.message || '训练中...'} ${info.progress || 0}%`);
      });
      if (result.status === 'success') {
        const r = result.result;
        if (r?.status === 'done') { done++; toast(t('toast.lora_done', { id: cid })); }
        else if (r?.status === 'skipped') { skipped++; }
        else { failed++; toast(`⚠ ${cid}: ${r?.reason || 'unknown'}`, 'error'); }
      } else { failed++; toast(`❌ ${cid}: ${result.error || 'failed'}`, 'error'); }
    } catch (e) { failed++; toast(`❌ ${cid}: ${e.message}`, 'error'); }
  }

  _html(progressEl, '');
  _html(statusEl, `<div style="padding:.5rem;background:var(--bg2);border-radius:6px;font-size:.9rem">批量训练完成: ${done}✅ ${skipped}⏭跳过 ${failed}❌失败 / 共${total}个</div>`);
  invalidateCache('characters');
  toast(t('toast.lora_batch_done', { done, fail: failed }));
}

async function editChar(id) {
  _currentEditCharId = id;
  await _getTtsBackend();
  _editEntityPanel('characters', id, {
    titleKey: 'char.edit_title', notFoundKey: 'char.not_found', imgPrefix: 'ec', imgLabel: t('char.upload_img'), confirmMsg: '删除定妆照？',
    reload: loadCharacters,
    deleteFn: deleteCharWithRef,
    buildExtra() {
      const coreTraits = $val('ec-personality') || '';
      const data = { voice: _collectVoiceConfig('ec'), outfits: _collectOutfits() };
      // bible: 只在有内容时更新 core_traits
      if (coreTraits) data.bible = { core_traits: coreTraits };
      return data;
    },
    extraHtml: (item) => `<div class="edit-field"><button class="btn btn-ai btn-sm" onclick="generatePortrait('${esc(id)}')" id="gen-portrait-btn">🎨 AI 生成定妆照</button><span id="gen-portrait-status" class="dim" style="font-size:.8rem;margin-left:.5rem"></span></div>` + _outfitFieldsHtml(id, item.outfits || {}) + _ttsVoiceFieldsHtml('ec', item.voice || {}) + _loraTrainHtml(id, item),
    fields: [
      { key: 'name', label: t('char.name') },
      { key: 'gender', label: t('char.gender'), type: 'select', options: [{ value: '', label: '-' }, { value: 'male', label: t('char.gender.male') }, { value: 'female', label: t('char.gender.female') }] },
      { key: 'appearance', label: t('char.appearance'), type: 'textarea' },
      { key: 'personality', label: t('char.personality') || '性格', type: 'textarea', getValue: (item) => (item.bible || {}).core_traits || '' },
    ],
  });
  // 异步加载 LoRA 状态
  _loadLoraStatus(id);
}

/** 通用图片上传 */
async function _uploadImg(entityType, id) {
  const prefix = entityType === 'characters' ? 'ec' : 'es';
  const fileInput = document.getElementById(`${prefix}-file`);
  if (!fileInput?.files?.[0]) return;
  const wrap = document.getElementById(`${prefix}-img-wrap`);
  _html(wrap, `<span class="dim">${t('common.uploading')}</span>`);
  const form = new FormData(); form.append('file', fileInput.files[0]);
  try {
    const r = await fetch(`${API}/assets/${entityType}/${id}/upload`, { method: 'POST', body: form });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '上传失败');
    // 标记新上传的 URL，save 时会追加到已有列表
    window[`_${prefix}GeneratedPortraitUrl`] = d.url;
    invalidateCache(entityType); toast(t('toast.upload_done'));
    // 刷新编辑面板以显示新图
    if (entityType === 'characters') editChar(id);
    else if (entityType === 'scenes') editScene(id);
  } catch (e) { _html(wrap, `<span style="color:var(--red)">❌ ${e.message}</span>`); toast(e.message, 'error'); }
  finally { fileInput.value = ''; }
}

/** 通用拖拽上传 */
function _handleImgDrop(e, entityType, id) {
  e.preventDefault(); e.currentTarget.classList.remove('dragover');
  const file = e.dataTransfer?.files?.[0]; if (!file) return;
  const prefix = entityType === 'characters' ? 'ec' : 'es';
  const inp = document.getElementById(`${prefix}-file`);
  if (inp) { const dt = new DataTransfer(); dt.items.add(file); inp.files = dt.files; _uploadImg(entityType, id); }
}



// ══════════════════════════════════════════════════════════

// ── Module: characters ──
Drama.pages.characters = loadCharacters;
window.loadCharacters = loadCharacters;
window.newChar = newChar;
window.deleteChar = deleteChar;
window.previewImage = previewImage;
window.addOutfitField = addOutfitField;
window.removeOutfitField = removeOutfitField;
window._loadEntityPage = _loadEntityPage;
window._editEntityPanel = _editEntityPanel;
window._newEntityPanel = _newEntityPanel;
