// MODULE: settings — 系统设置
// ══════════════════════════════════════════════════════════

function _backendSection(label, icon, idPrefix, backends, backend, url, available, reason, opts = {}) {
  const toolName = idPrefix === 'lipsync' ? 'lipsync' : idPrefix;
  const apiKeyHtml = opts.showApiKey ? `<div class="form-row"><label>${t('set.tts_api_key')}</label><div style="display:flex;gap:.3rem;flex:1"><input id="cfg-${idPrefix}-key" type="password" value="${esc(opts.apiKey || '')}" style="flex:1" placeholder="MIMO_API_KEY"><button class="btn btn-xs btn-outline" onclick="_toggleKeyVis('cfg-${idPrefix}-key','cfg-${idPrefix}-key-toggle')" id="cfg-${idPrefix}-key-toggle">👁</button></div></div>` : '';
  const testHtml = opts.showTest ? `<div style="margin-top:.5rem"><div class="form-row"><label>${t('set.tts_test_text')}</label><input id="cfg-${idPrefix}-test-text" value="${esc(opts.testText || '你好，这是一段测试语音。')}" style="flex:1"></div>
    <button class="btn btn-xs btn-outline" onclick="testTtsPreview()" id="test-btn-tts-preview" style="margin-top:.3rem">${t('set.tts_test')}</button>
    <span id="test-result-tts-preview" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div>` : '';
  return `<div class="config-section"><h3>${icon} ${label}</h3>
    <div class="form-row"><label>${t('set.backend')}</label><select id="cfg-${idPrefix}" onchange="_updateUrl('${idPrefix}')">${backends.map(b => `<option value="${b}" ${backend === b ? 'selected' : ''}>${b}</option>`).join('')}</select></div>
    <div class="form-row"><label>${t('set.address')}</label><input id="cfg-${idPrefix}-url" value="${esc(url)}"></div>
    ${apiKeyHtml}
    <div class="tool-status-inline"><span class="status-dot ${available ? 'ok' : 'err'}"></span>${available ? t('dash.available') : reason || t('dash.unavailable')}
      <button class="btn btn-xs btn-outline" onclick="testTool('${toolName}')" id="test-btn-${toolName}">🔌 ${t('set.test')}</button>
      <span id="test-result-${toolName}" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div>
    ${testHtml}</div>`;
}

function _updateUrl(prefix) {
  const key = $val(`cfg-${prefix}`).replace(/-/g, '_');
  const cfg = _cache.get('sysconfig')?.data || {};
  const inp = document.getElementById(`cfg-${prefix}-url`);
  if (inp) inp.value = cfg.models?.[key]?.api_url || '';
  // 同步 API Key 字段
  const keyInp = document.getElementById(`cfg-${prefix}-key`);
  if (keyInp) keyInp.value = cfg.models?.[key]?.api_key || '';
}

function _resolveBackendUrl(cfg, prefix) {
  const backend = cfg.models?.[`${prefix}_backend`] || '';
  return { backend, url: cfg.models?.[backend.replace(/-/g, '_')]?.api_url || '' };
}

async function loadSettings() {
  const el = document.getElementById('page-settings');
  try {
    const [sysCfg, env, td, backends] = await Promise.all([
      cachedFetch('sysconfig', () => api('/system/config'), 30000),
      cachedFetch('sysenv', () => api('/system/env'), 60000),
      cachedFetch('tools', () => api('/tools'), 15000),
      cachedFetch('backends', () => api('/backends').catch(() => ({ tts: {}, lipsync: {}, llm: {}, music: {}, image: {}, video: {} })), 60000),
    ]);
    _cache.set('sysconfig', { data: sysCfg, ts: Date.now() });
    const tools = td.tools || {}, lang = localStorage.getItem('drama_lang') || 'zh';
    const tts = _resolveBackendUrl(sysCfg, 'tts'), ls = _resolveBackendUrl(sysCfg, 'lip_sync');
    const llm = sysCfg.llm || {};
    const training = sysCfg.training || {};
    // 从模型注册表动态获取后端列表（降级为硬编码兜底）
    const ttsBackends = Object.keys(backends.tts || {}).length ? Object.keys(backends.tts) : ['mimo-voicedesign', 'mimo-voiceclone', 'gpt-sovits', 'cosyvoice', 'fish-speech'];
    const lsBackends = Object.keys(backends.lipsync || {}).length ? Object.keys(backends.lipsync) : ['musetalk', 'sadtalker', 'wav2lip'];
    const llmBackends = Object.keys(backends.llm || {}).length ? Object.keys(backends.llm) : ['openai', 'ollama'];
    const imageBackends = Object.keys(backends.image || {});
    const videoBackends = Object.keys(backends.video || {});
    const curImageBackend = sysCfg.models?.image_backend || 'sd15';
    const curVideoBackend = sysCfg.models?.video_backend || 'animatediff';
    el.innerHTML = `
      <div class="card"><h2>🌐 语言 / Language</h2><div class="form-row"><label>Language</label>
        <select id="cfg-lang" onchange="setLang(this.value);loadSettings()"><option value="zh" ${lang === 'zh' ? 'selected' : ''}>中文</option><option value="en" ${lang === 'en' ? 'selected' : ''}>English</option></select></div></div>
      <div class="card"><h2>💻 ${t('set.env')}</h2><div class="info-grid"><div><span class="dim">${t('set.os')}:</span> ${env.os}</div><div><span class="dim">${t('set.python')}:</span> ${env.python}</div></div></div>
      <div class="card"><h2>${t('set.presets')}</h2>
        <div class="preset-btns">
          <button class="preset-btn" onclick="applyPreset('local_comfyui')">${t('set.preset_local')}</button>
          <button class="preset-btn" onclick="applyPreset('cloud_siliconflow')">${t('set.preset_cloud')}</button>
          <button class="preset-btn" onclick="applyPreset('ollama_local')">${t('set.preset_ollama')}</button>
        </div>
      </div>
      <div class="card"><h2>🔧 系统配置</h2>
        ${_backendSection(t('set.tts'), '🎤', 'tts', ttsBackends, tts.backend, tts.url, tools.tts?.available, tools.tts?.reason, { showApiKey: true, apiKey: sysCfg.models?.[tts.backend.replace(/-/g, '_')]?.api_key || '', showTest: true })}
        ${_backendSection(t('set.lipsync'), '👄', 'lipsync', lsBackends, ls.backend, ls.url, tools.lipsync?.available, tools.lipsync?.reason)}
        <div class="config-section"><h3>🎨 ComfyUI</h3>
          <div class="form-row"><label>${t('set.address')}</label><input id="cfg-comfyui" value="${esc(sysCfg.comfyui?.url || '')}"></div>
          <div class="form-row"><label>API Key</label><input id="cfg-comfyui-key" value="${esc(sysCfg.comfyui?.api_key || '')}" placeholder="${t('set.optional')}"></div>
          ${imageBackends.length ? `<div class="form-row"><label>${t('set.image_backend')}</label><select id="cfg-image-backend">${imageBackends.map(b => `<option value="${b}" ${curImageBackend===b?'selected':''}>${b}</option>`).join('')}</select></div>` : ''}
          ${videoBackends.length ? `<div class="form-row"><label>${t('set.video_backend')}</label><select id="cfg-video-backend">${videoBackends.map(b => `<option value="${b}" ${curVideoBackend===b?'selected':''}>${b}</option>`).join('')}</select></div>` : ''}
          <div class="tool-status-inline"><span class="status-dot ${tools.comfyui?.available ? 'ok' : 'err'}"></span>${tools.comfyui?.available ? t('dash.available') : tools.comfyui?.reason || t('dash.unavailable')}
            <button class="btn btn-xs btn-outline" onclick="testTool('comfyui')" id="test-btn-comfyui">🔌 ${t('set.test')}</button>
            <span id="test-result-comfyui" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div></div>
        <div class="config-section"><h3>🧠 ${t('set.llm')}</h3>
          <div class="form-row"><label>${t('set.llm_enabled')}</label><select id="cfg-llm-enabled"><option value="false" ${!llm.enabled ? 'selected' : ''}>${lang==='zh'?'关闭':'Off'}</option><option value="true" ${llm.enabled ? 'selected' : ''}>${lang==='zh'?'开启':'On'}</option></select></div>
          <div class="form-row"><label>${t('set.backend')}</label><select id="cfg-llm-backend">${llmBackends.map(b => `<option value="${b}" ${llm.backend===b?'selected':''}>${b}</option>`).join('')}</select></div>
          <div class="form-row"><label>API URL</label><input id="cfg-llm-url" value="${esc(llm.base_url || '')}"></div>
          <div class="form-row"><label>${t('set.llm_model')}</label><input id="cfg-llm-model" value="${esc(llm.model || '')}"></div>
          <div class="form-row"><label>API Key</label><div style="display:flex;gap:.3rem;flex:1"><input id="cfg-llm-key" type="password" value="${esc(llm.api_key || '')}" style="flex:1"><button class="btn btn-xs btn-outline" onclick="_toggleKeyVis()" id="cfg-llm-key-toggle">👁</button></div></div>
          <div class="tool-status-inline"><span class="status-dot ${tools.llm?.available ? 'ok' : 'err'}"></span>${tools.llm?.available ? t('dash.available') : tools.llm?.reason || t('dash.unavailable')}
            <button class="btn btn-xs btn-outline" onclick="testTool('llm')" id="test-btn-llm">🔌 ${t('set.test')}</button>
            <span id="test-result-llm" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div></div>
        <div class="config-section"><h3>⚡ ${t('batch.concurrent')}</h3>
          <div class="form-row"><label>${t('batch.concurrent')}</label><select id="cfg-concurrency" onchange="localStorage.setItem('drama_concurrency',this.value)">
            <option value="1" ${(localStorage.getItem('drama_concurrency')||'1')==='1'?'selected':''}>1</option>
            <option value="2" ${localStorage.getItem('drama_concurrency')==='2'?'selected':''}>2</option>
            <option value="3" ${localStorage.getItem('drama_concurrency')==='3'?'selected':''}>3</option>
            <option value="5" ${localStorage.getItem('drama_concurrency')==='5'?'selected':''}>5</option>
          </select></div></div>
        <div class="config-section"><h3>🎬 Seko 影视策划</h3>
          <div class="form-row"><label>API Key</label><div style="display:flex;gap:.3rem;flex:1"><input id="cfg-seko-key" type="password" value="${esc(sysCfg.seko?.api_key || '')}" style="flex:1" placeholder="获取: seko.sensetime.com/explore"><button class="btn btn-xs btn-outline" onclick="_toggleKeyVis('cfg-seko-key','cfg-seko-key-toggle')" id="cfg-seko-key-toggle">👁</button></div></div>
          <div class="tool-status-inline"><span class="status-dot ${tools.seko?.available ? 'ok' : 'err'}"></span>${tools.seko?.available ? t('dash.available') : tools.seko?.reason || t('dash.unavailable')}</div></div>
        <div class="config-section"><h3>🏋 ${t('set.training')}</h3>
          <div class="form-row"><label>${t('set.backend')}</label><select id="cfg-training-backend"><option value="ai-toolkit" ${training.backend === 'ai-toolkit' || !training.backend ? 'selected' : ''}>AI Toolkit</option></select></div>
          <div class="form-row"><label>${t('set.address')}</label><input id="cfg-training-url" value="${esc(training.api_url || '')}" placeholder="http://127.0.0.1:7860"></div>
          <div class="form-row"><label>API Key</label><div style="display:flex;gap:.3rem;flex:1"><input id="cfg-training-key" type="password" value="${esc(training.api_key || '')}" style="flex:1" placeholder="${t('set.optional')}（Docker 部署时需要）"><button class="btn btn-xs btn-outline" onclick="_toggleKeyVis('cfg-training-key','cfg-training-key-toggle')" id="cfg-training-key-toggle">👁</button></div></div>
          <div class="form-row"><label>${t('set.training_timeout')}</label><input id="cfg-training-timeout" type="number" value="${training.timeout || 3600}" min="60" max="86400"></div>
          <div class="form-row"><label>${t('set.training_poll')}</label><input id="cfg-training-poll" type="number" value="${training.poll_interval || 10}" min="5" max="120"></div>
          <div class="tool-status-inline"><span class="status-dot ${tools.training?.available ? 'ok' : 'err'}"></span>${tools.training?.available ? t('dash.available') : tools.training?.reason || t('dash.unavailable')}
            <button class="btn btn-xs btn-outline" onclick="testTool('training')" id="test-btn-training">🔌 ${t('set.test')}</button>
            <span id="test-result-training" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div></div>
        <button class="btn btn-primary" style="margin-top:1rem" onclick="saveCfg()">💾 ${t('btn.save')}</button></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

async function saveCfg() {
  try {
    const sys = {};
    // TTS
    const ttsBackend = $val('cfg-tts');
    sys.models = sys.models || {};
    sys.models.tts_backend = ttsBackend;
    const ttsKey = ttsBackend.replace(/-/g, '_');
    const ttsUrl = $val('cfg-tts-url');
    const ttsApiKey = $val('cfg-tts-key');
    const ttsCfg = {};
    if (ttsUrl) ttsCfg.api_url = ttsUrl;
    ttsCfg.api_key = ttsApiKey || '';  // 保存空串可清除旧 key
    sys.models[ttsKey] = ttsCfg;
    // LipSync
    const lsBackend = $val('cfg-lipsync');
    sys.models.lip_sync_backend = lsBackend;
    const lsKey = lsBackend.replace(/-/g, '_');
    const lsUrl = $val('cfg-lipsync-url');
    if (lsUrl) sys.models[lsKey] = { api_url: lsUrl };
    // ComfyUI
    sys.comfyui = { url: $val('cfg-comfyui'), api_key: $val('cfg-comfyui-key') };
    // Image / Video backend
    const imageBackend = $val('cfg-image-backend');
    const videoBackend = $val('cfg-video-backend');
    if (imageBackend) sys.models.image_backend = imageBackend;
    if (videoBackend) sys.models.video_backend = videoBackend;
    // LLM
    const llmEnabled = $val('cfg-llm-enabled') === 'true';
    sys.llm = { enabled: llmEnabled, backend: $val('cfg-llm-backend'), base_url: $val('cfg-llm-url'), model: $val('cfg-llm-model'), api_key: $val('cfg-llm-key') };
    // Seko
    const sekoKey = $val('cfg-seko-key');
    if (sekoKey) sys.seko = { api_key: sekoKey };
    // Training
    const trainingBackend = $val('cfg-training-backend');
    const trainingUrl = $val('cfg-training-url');
    const trainingApiKey = $val('cfg-training-key');
    const trainingTimeout = parseInt($val('cfg-training-timeout')) || 3600;
    const trainingPoll = parseInt($val('cfg-training-poll')) || 10;
    sys.training = { backend: trainingBackend, api_url: trainingUrl, api_key: trainingApiKey || '', timeout: trainingTimeout, poll_interval: trainingPoll };

    await api('/system/config', { method: 'POST', body: sys });
    toast(t('toast.saved'));
    invalidateCache('sysconfig');
  } catch (e) { toast(e.message, 'error'); }
}

// ── 工具测试 ──

function _toggleKeyVis(inpId, btnId) {
  const inp = document.getElementById(inpId || 'cfg-llm-key');
  const btn = document.getElementById(btnId || 'cfg-llm-key-toggle');
  if (!inp) return;
  if (inp.type === 'password') { inp.type = 'text'; if (btn) btn.textContent = '🙈'; }
  else { inp.type = 'password'; if (btn) btn.textContent = '👁'; }
}

async function testTool(name) {
  const btn = document.getElementById(`test-btn-${name}`);
  const resultEl = document.getElementById(`test-result-${name}`);
  if (btn) btn.disabled = true;
  if (resultEl) resultEl.innerHTML = '⏳ 测试中...';
  try {
    const r = await api(`/tools/${name}/test`, { method: 'POST' });
    if (r.ok) {
      if (resultEl) resultEl.innerHTML = `<span style="color:#22c55e">✅ ${esc(r.message)}</span>`;
      toast(`✅ ${name}: ${r.message}`);
    } else {
      if (resultEl) resultEl.innerHTML = `<span style="color:#ef4444">❌ ${esc(r.message)}</span>`;
      toast(`❌ ${name}: ${r.message}`, 'error');
    }
  } catch (e) {
    if (resultEl) resultEl.innerHTML = `<span style="color:#ef4444">❌ ${esc(e.message)}</span>`;
    toast(`❌ ${name}: ${e.message}`, 'error');
  }
  if (btn) btn.disabled = false;
}

async function testTtsPreview() {
  const btn = document.getElementById('test-btn-tts-preview');
  const resultEl = document.getElementById('test-result-tts-preview');
  const text = $val('cfg-tts-test-text') || '你好，这是一段测试语音。';
  if (btn) btn.disabled = true;
  if (resultEl) resultEl.innerHTML = '⏳ 合成中...';
  try {
    const r = await api('/tools/tts', { method: 'POST', body: { text, language: 'zh' } });
    if (r.task_id) {
      // 轮询任务
      const poll = async () => {
        for (let i = 0; i < 60; i++) {
          await new Promise(res => setTimeout(res, 1000));
          let info;
          try { info = await api(`/tasks/${r.task_id}`); } catch { continue; }
          if (info.status === 'success') {
            const audioPath = info.result?.path || info.result?.audio || info.result?.output;
            if (audioPath) {
              const audio = new Audio(`/api/project-file/${audioPath}`);
              audio.play().catch(() => {});
              if (resultEl) resultEl.innerHTML = `<span style="color:#22c55e">✅ 播放中...</span>`;
            } else {
              if (resultEl) resultEl.innerHTML = `<span style="color:#22c55e">✅ 完成</span>`;
            }
            toast(t('toast.tts_preview_done'));
            if (btn) btn.disabled = false;
            return;
          }
          if (info.status === 'failed' || info.status === 'cancelled') {
            if (resultEl) resultEl.innerHTML = `<span style="color:#ef4444">❌ ${esc(info.error || info.reason || info.status)}</span>`;
            toast(`❌ TTS: ${info.error || info.reason || info.status}`, 'error');
            if (btn) btn.disabled = false;
            return;
          }
        }
        if (resultEl) resultEl.innerHTML = `<span style="color:#eab308">⏰ 超时</span>`;
        if (btn) btn.disabled = false;
      };
      poll();
      return; // 不在下方 re-enable，由 poll 管理
    }
  } catch (e) {
    if (resultEl) resultEl.innerHTML = `<span style="color:#ef4444">❌ ${esc(e.message)}</span>`;
    toast(`❌ TTS: ${e.message}`, 'error');
  }
  if (btn) btn.disabled = false;
}


// ══════════════════════════════════════════════════════════

// ── Module: settings ──
Drama.pages.settings = loadSettings;
window.loadSettings = loadSettings;
window.saveCfg = saveCfg;
window.testTool = testTool;
window.testTtsPreview = testTtsPreview;
