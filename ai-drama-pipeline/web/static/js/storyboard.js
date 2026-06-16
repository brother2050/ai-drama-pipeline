// MODULE: storyboard — 分镜表
// ══════════════════════════════════════════════════════════

const SB_FIELDS = ['scene_name', 'characters', 'action', 'dialogue', 'camera', 'shot_type', 'duration', 'emotion', 'outfit'];
let _sbViewMode = localStorage.getItem('sb_view') || 'table'; // 'table' | 'timeline'

function _sbViewToggle() {
  return `<div class="view-toggle">
    <button class="btn btn-xs ${_sbViewMode==='table'?'active':''}" onclick="setSBView('table')">📋 表格</button>
    <button class="btn btn-xs ${_sbViewMode==='timeline'?'active':''}" onclick="setSBView('timeline')">📐 ${t('sb.timeline')}</button>
  </div>`;
}

function setSBView(mode) {
  _sbViewMode = mode;
  localStorage.setItem('sb_view', mode);
  loadStoryboard();
}


// ══════════════════════════════════════════════════════════

// ── Module: storyboard ──
// Drama.pages.storyboard 由 ai-gen.js 统一注册（loadStoryboard 定义在该文件中）
window.SB_FIELDS = SB_FIELDS;
window._sbViewMode = _sbViewMode;
window._sbViewToggle = _sbViewToggle;
window.setSBView = setSBView;
