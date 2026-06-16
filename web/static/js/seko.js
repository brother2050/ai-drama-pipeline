// MODULE: seko — Seko 影视策划案
// ══════════════════════════════════════════════════════════

const _sekoTasks = [];  // { task_id, prompt, status, created, result }

async function loadSeko() {
  const el = document.getElementById('page-seko');
  // 检查 API Key
  let sekoAvailable = false;
  try {
    const tools = await api('/tools');
    sekoAvailable = tools.tools?.seko?.available || false;
  } catch {}

  const taskRows = _sekoTasks.length ? _sekoTasks.map((task, i) => `
    <div class="card" style="margin-bottom:.5rem" id="seko-task-${i}">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem">
        <div>
          <span class="dim" style="font-size:.8rem">${task.task_id}</span>
          <span style="margin-left:.5rem">${esc(task.prompt.slice(0, 60))}${task.prompt.length > 60 ? '...' : ''}</span>
        </div>
        <div style="display:flex;gap:.3rem;align-items:center">
          <span class="status-dot ${task.status === 'OK' ? 'ok' : task.status === 'FAIL' ? 'err' : ''}"></span>
          <span>${t('seko.status_' + (task.status || 'RUNNING'))}</span>
          <button class="btn btn-xs btn-outline" onclick="sekoCheckStatus(${i})">${t('seko.check_btn')}</button>
          ${task.status === 'OK' ? `<button class="btn btn-xs btn-outline" onclick="sekoDownload(${i})">${t('seko.download_btn')}</button>` : ''}
          ${task.status === 'OK' ? `<button class="btn btn-xs btn-primary" onclick="sekoImport(${i})">${t('seko.import_btn') || '📥 导入项目'}</button>` : ''}
          <button class="btn btn-xs btn-outline" onclick="sekoModify(${i})">${t('seko.modify_btn')}</button>
        </div>
      </div>
      ${task.result ? `<details style="margin-top:.5rem"><summary>${t('seko.result_title')}</summary><pre style="max-height:400px;overflow:auto;font-size:.8rem;background:var(--bg3,#1a1e2e);color:var(--fg,#e6e8ef);padding:.5rem;border-radius:4px;border:1px solid rgba(255,255,255,.06)">${esc(JSON.stringify(task.result, null, 2))}</pre></details>` : ''}
    </div>
  `).join('') : `<div class="card"><p style="color:var(--text-dim,#888)">${t('seko.no_tasks')}</p></div>`;

  el.innerHTML = `
    <div class="card">
      <h2>${t('seko.title')}</h2>
      <p class="dim">${t('seko.desc')}</p>
      ${!sekoAvailable ? `<div style="background:#fef3cd;color:#856404;padding:.8rem;border-radius:6px;margin-top:.5rem">${t('seko.api_key_unset')}</div>` : ''}
    </div>
    <div class="card">
      <h3>${t('seko.new_proposal')}</h3>
      <div class="form-row"><label>${t('seko.prompt_label')}</label>
        <textarea id="seko-prompt" rows="4" style="width:100%" placeholder="${t('seko.prompt_ph')}" ${!sekoAvailable ? 'disabled' : ''}></textarea></div>
      <button class="btn btn-primary" onclick="sekoSubmit()" id="seko-submit-btn" ${!sekoAvailable ? 'disabled' : ''}>${t('seko.submit_btn')}</button>
      <span id="seko-submit-msg" class="dim" style="margin-left:.5rem"></span>
    </div>
    <div class="card">
      <h3>${t('seko.task_list')}</h3>
      ${taskRows}
    </div>`;
}

async function sekoSubmit() {
  const prompt = document.getElementById('seko-prompt')?.value?.trim();
  if (!prompt) return;
  const btn = document.getElementById('seko-submit-btn');
  const msg = document.getElementById('seko-submit-msg');
  btn.disabled = true; btn.textContent = t('seko.submitting');
  try {
    const r = await api('/seko/proposal', { method: 'POST', body: { prompt } });
    _sekoTasks.unshift({ task_id: r.task_id, prompt, status: 'RUNNING', created: new Date().toLocaleString(), result: null });
    msg.innerHTML = `<span style="color:#22c55e">${t('seko.submitted', { id: r.task_id })}</span>`;
    loadSeko();
    // 自动轮询状态（每 15 秒，完成/失败后停止）
    _autoPollSeko(r.task_id);
  } catch (e) {
    msg.innerHTML = `<span style="color:#ef4444">${t('seko.submit_fail')}: ${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false; btn.textContent = t('seko.submit_btn');
  }
}

function _autoPollSeko(taskId) {
  const timer = setInterval(async () => {
    try {
      const r = await api('/seko/proposal/status', { method: 'POST', body: { task_id: taskId } });
      const task = _sekoTasks.find(t => t.task_id === taskId);
      if (!task) { clearInterval(timer); return; }
      task.status = r.status || 'UNKNOWN';
      task.result = r.raw?.data?.result || r.raw?.data || null;
      if (task.status === 'OK' || task.status === 'FAIL') {
        clearInterval(timer);
        toast(task.status === 'OK' ? t('toast.task_done') : t('toast.task_fail'), task.status === 'OK' ? 'info' : 'error');
        loadSeko();
      }
    } catch { /* 网络抖动，继续轮询 */ }
  }, 15000);
}

async function sekoCheckStatus(idx) {
  const task = _sekoTasks[idx];
  if (!task) return;
  task.status = 'RUNNING';
  loadSeko();
  try {
    const r = await api('/seko/proposal/status', { method: 'POST', body: { task_id: task.task_id } });
    task.status = r.status || 'UNKNOWN';
    task.result = r.raw?.data?.result || r.raw?.data || null;
    if (task.status === 'OK') toast(t('toast.task_done'));
    else if (task.status === 'FAIL') toast(t('toast.task_fail'), 'error');
    loadSeko();
  } catch (e) {
    task.status = 'FAIL';
    toast(e.message, 'error');
    loadSeko();
  }
}

async function sekoDownload(idx) {
  const task = _sekoTasks[idx];
  if (!task) return;
  try {
    const r = await api('/seko/proposal/status', {
      method: 'POST',
      body: { task_id: task.task_id, download_dir: '__project_assets__' }
    });
    const count = r.downloaded?.length || 0;
    toast(t('seko.downloaded', { n: count }));
  } catch (e) { toast(e.message, 'error'); }
}

async function sekoModify(idx) {
  const task = _sekoTasks[idx];
  if (!task) return;
  const prompt = await modalPrompt(t('seko.modify_ph'), '', { type: 'textarea', placeholder: t('seko.modify_ph') });
  if (!prompt) return;
  try {
    const r = await api('/seko/proposal/modify', { method: 'POST', body: { task_id: task.task_id, prompt } });
    _sekoTasks.unshift({ task_id: r.task_id, prompt: `[修改] ${prompt}`, status: 'RUNNING', created: new Date().toLocaleString(), result: null });
    toast(t('seko.task_added'));
    loadSeko();
  } catch (e) { toast(e.message, 'error'); }
}

async function sekoImport(idx) {
  const task = _sekoTasks[idx];
  if (!task?.result) return;

  // 从策划案中提取标题作为默认项目名
  const outlineStep = task.result.steps?.find(s => s.step === 'outline');
  const outlineText = outlineStep?.stepOutput || task.prompt || '';
  const titleMatch = outlineText.match(/剧[本名][：:]\s*(.+)/);
  const defaultName = titleMatch ? titleMatch[1].trim().slice(0, 30) : '';

  // 选择导入方式
  const importMode = await modalPrompt(
    (t('seko.import_mode_title') || '导入方式') + '\n\n' +
    (t('seko.import_mode_desc') || '输入新项目名创建项目并导入，留空则导入到当前项目'),
    defaultName,
    { type: 'text', placeholder: t('seko.import_mode_ph') || '留空 = 导入当前项目' }
  );
  if (importMode === null) return; // 取消

  const projectName = importMode.trim();

  // 防重入：禁用按钮
  const btn = document.querySelector(`#seko-task-${idx} .btn-primary`);
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 导入中...'; }
  try {
    toast(projectName
      ? (t('seko.import_creating') || '正在创建项目并导入...')
      : (t('seko.import_submitting') || '正在提交导入任务...'));
    const r = await api('/seko/proposal/import', {
      method: 'POST',
      body: {
        proposal_data: task.result,
        episode: 1,
        import_characters: true,
        import_scenes: true,
        import_storyboard: true,
        download_images: true,
        project_name: projectName,
      }
    });
    const taskId = r.task_id;
    toast((t('seko.import_submitted') || '导入任务已提交') + ` (${taskId})`);
    await _pollSekoImportTask(taskId, projectName);
  } catch (e) {
    toast((t('seko.import_fail') || '导入失败') + `: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = t('seko.import_btn') || '📥 导入项目'; }
  }
}

async function _pollSekoImportTask(taskId, projectName) {
  const maxWait = 960; // 最长等 16 分钟（对齐 Celery soft_time_limit 900s + 余量）
  let waited = 0, interval = 3;
  while (waited < maxWait) {
    await new Promise(r => setTimeout(r, interval * 1000));
    waited += interval;
    if (waited > 30) interval = 10; // 30 秒后降频到 10 秒
    try {
      const info = await api(`/tasks/${taskId}`);
      if (info.status === 'success') {
        const res = info.result || {};
        const msg = [
          res.characters ? `角色 ${res.characters}` : '',
          res.scenes ? `场景 ${res.scenes}` : '',
          res.shots ? `分镜 ${res.shots}` : '',
          res.images_downloaded ? `图片 ${res.images_downloaded}` : '',
        ].filter(Boolean).join('、');
        let doneMsg = (t('seko.import_done') || '导入完成！') + (msg ? ` (${msg})` : '');
        if (projectName) {
          doneMsg += ` | ${t('seko.import_switch_hint') || '已创建项目'}: ${projectName}`;
          try { await switchProj(projectName); } catch { loadProjects(); }
        }
        toast(doneMsg);
        return;
      } else if (info.status === 'failed') {
        toast((t('seko.import_fail') || '导入失败') + `: ${info.error || ''}`, 'error');
        return;
      }
      // running → 继续等
    } catch {
      // 网络抖动，继续等
    }
  }
  toast(t('seko.import_timeout') || '导入任务超时，请稍后查看结果');
}


// ══════════════════════════════════════════════════════════

// ── Module: seko ──
Drama.pages.seko = loadSeko;
Drama.state.sekoTasks = _sekoTasks;
window.loadSeko = loadSeko;
window.sekoSubmit = sekoSubmit;
window.sekoCheckStatus = sekoCheckStatus;
window.sekoDownload = sekoDownload;
window.sekoModify = sekoModify;
window.sekoImport = sekoImport;
