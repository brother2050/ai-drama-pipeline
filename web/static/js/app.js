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
  pages: {},
  state: {},
  lang: localStorage.getItem('drama_lang') || 'zh',
  t: null,
  api: null,
  toast: null,
};
