/**
 * AI 短剧工作台 v2 — 模块命名空间
 *
 * 所有 JS 模块挂载公共 API 到 window.Drama。
 * 共享可变状态统一管理在 Drama.state 中。
 *
 * 加载顺序：app.js → i18n.js → core.js → 其余（任意顺序）
 *
 * 用法：
 *   const { api, toast, t, state } = Drama;
 *   console.log(state.ep);  // 当前集数
 */
window.Drama = {
  // ── 共享可变状态（跨模块读写）──
  // ep/shots/sbDirty 不在此存储，通过 Drama.ep / Drama.shots / Drama.sbDirty 访问
  state: {
    batchCancelled: false,
    currentTaskId: null,
    activeTaskIds: new Set(),
    charNameMap: {},
    sceneNameMap: {},
    undoStack: [],
    redoStack: [],
    chatOpen: false,
    chatHistory: [],
    sekoTasks: [],
    sbViewMode: localStorage.getItem('sb_view') || 'table',
  },

  pages: {},
  lang: localStorage.getItem('drama_lang') || 'zh',
  t: null,
  api: null,
  toast: null,
};
