// MODULE: scenes — 场景管理
// ══════════════════════════════════════════════════════════


async function loadScenes() {
  _loadEntityPage('scenes', {
    pageId: 'page-scenes', icon: '🏔', titleKey: 'scene.title',
    emptyHintKey: 'scene.empty_hint', emptyDescKey: 'scene.empty_desc',
    editFn: 'editScene', newFn: 'newScene', aiFn: 'showAIGenScene',
    batchDeleteLabel: 'confirm.batch_delete_scenes',
    card: s => {
      const thumb = (s.reference_images?.length) ? `<img src="${esc(s.reference_images[0])}" loading="lazy">` : '🏔';
      return `<div class="entity-card" onclick="editScene('${esc(s.id)}')"><div class="entity-card-thumb">${thumb}</div><div class="entity-card-body"><h3>${esc(s.name || s.id)}</h3><p>${esc(s.description || '')}</p></div><div class="entity-card-footer"><span class="entity-card-id">${esc(s.id)}</span><span class="dim" style="font-size:.7rem">${esc(s.lighting || '')} <button class="btn btn-xs btn-danger" onclick="event.stopPropagation();deleteScene('${esc(s.id)}')" title="${t('btn.delete')}">🗑</button></span></div></div>`;
    }
  });
}
function newScene() {
  _newEntityPanel('scenes', {
    titleKey: 'scene.title', reload: loadScenes,
    fields: [
      { key: 'name', label: t('scene.name') },
      { key: 'description', label: t('scene.desc'), type: 'textarea' },
      { key: 'lighting', label: t('scene.lighting') },
    ],
  });
}
function deleteScene(id) { deleteSceneWithRef(id); }

async function editScene(id) {
  _editEntityPanel('scenes', id, {
    titleKey: 'scene.edit_title', notFoundKey: 'scene.not_found', imgPrefix: 'es', imgLabel: t('scene.upload_img'), confirmMsg: '删除参考图？',
    reload: loadScenes,
    deleteFn: deleteSceneWithRef,
    extraHtml: `<div class="edit-field"><button class="btn btn-ai btn-sm" onclick="generateSceneImage('${esc(id)}')" id="gen-scene-img-btn">${t('scene.gen_image')}</button><span id="gen-scene-img-status" class="dim" style="font-size:.8rem;margin-left:.5rem"></span></div>`,
    fields: [
      { key: 'name', label: t('scene.name') },
      { key: 'description', label: t('scene.desc'), type: 'textarea' },
      { key: 'lighting', label: t('scene.lighting') },
    ],
  });
}

// $val 已移至 core.js


// ══════════════════════════════════════════════════════════

// ── Module: scenes ──
Drama.pages.scenes = loadScenes;
window.loadScenes = loadScenes;
window.newScene = newScene;
window.deleteScene = deleteScene;
