// MODULE: voices — 声线库选择器
// ══════════════════════════════════════════════════════════

/** 声线库页面状态 */
const _voicesState = { q: '', gender: '', page: 1, playing: null };

/** 加载声线库页面 */
function loadVoices() {
  const el = document.getElementById('page-voices');
  if (!el) return;

  const { q, gender, page } = _voicesState;
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (gender) params.set('gender', gender);
  params.set('page', page);
  params.set('page_size', 50);

  el.innerHTML = `<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;flex-wrap:wrap;gap:.5rem">
      <h2>🎤 ${t('voices.title') || '声线库'}</h2>
      <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
        <input id="voices-search" placeholder="${t('voices.search') || '搜索声线...'}" value="${esc(q)}" style="width:200px" onkeydown="if(event.key==='Enter')_voicesSearch()">
        <button class="btn btn-outline btn-sm" onclick="_voicesSearch()">🔍</button>
        <button class="btn btn-sm ${gender===''?'btn-primary':'btn-outline'}" onclick="_voicesFilter('')">${t('voices.all') || '全部'}</button>
        <button class="btn btn-sm ${gender==='male'?'btn-primary':'btn-outline'}" onclick="_voicesFilter('male')">♂ ${t('voices.male') || '男声'}</button>
        <button class="btn btn-sm ${gender==='female'?'btn-primary':'btn-outline'}" onclick="_voicesFilter('female')">♀ ${t('voices.female') || '女声'}</button>
        <span id="voices-count" class="dim" style="font-size:.8rem"></span>
      </div>
    </div>
    <div id="voices-grid"></div>
    <div id="voices-pagination" style="margin-top:1rem;text-align:center"></div>
  </div>`;

  _voicesLoadList();
}

async function _voicesLoadList() {
  const grid = document.getElementById('voices-grid');
  const countEl = document.getElementById('voices-count');
  const pagEl = document.getElementById('voices-pagination');
  if (!grid) return;

  const { q, gender, page } = _voicesState;
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (gender) params.set('gender', gender);
  params.set('page', page);
  params.set('page_size', 50);

  try {
    const d = await api(`/voices?${params}`);
    const voices = d.voices || [];
    const total = d.total || 0;
    _html(countEl, `${total} 条`);

    if (!voices.length) {
      _html(grid, `<div class="empty-state"><p>${t('voices.empty') || '声线库为空，请先同步声线数据'}</p></div>`);
      _html(pagEl, '');
      return;
    }

    _html(grid, `<div class="entity-grid">${voices.map(v => _voicesCardHtml(v)).join('')}</div>`);

    // 分页
    if (d.pages > 1) {
      let pag = '';
      if (page > 1) pag += `<button class="btn btn-outline btn-sm" onclick="_voicesPage(${page-1})">◀</button> `;
      pag += `<span style="margin:0 .5rem">${page} / ${d.pages}</span>`;
      if (page < d.pages) pag += ` <button class="btn btn-outline btn-sm" onclick="_voicesPage(${page+1})">▶</button>`;
      _html(pagEl, pag);
    } else {
      _html(pagEl, '');
    }
  } catch (e) {
    _html(grid, `<div class="empty-state"><p style="color:var(--red)">❌ ${esc(e.message)}</p></div>`);
  }
}

function _voicesCardHtml(v) {
  const id = esc(v.id);
  const scene = esc(v.scene || '');
  const style = esc(v.style || '');
  const genderIcon = v.gender === 'male' ? '♂' : v.gender === 'female' ? '♀' : '';
  const keywords = (v.keywords || []).map(k => `<span class="tag">${esc(k)}</span>`).join(' ');
  return `<div class="entity-card" style="cursor:default">
    <div class="entity-card-body">
      <h3>${genderIcon} ${style}</h3>
      <p style="font-size:.75rem;color:var(--dim)">${scene}</p>
      ${keywords ? `<div style="margin-top:.3rem">${keywords}</div>` : ''}
    </div>
    <div class="entity-card-footer" style="display:flex;gap:.3rem;flex-wrap:wrap">
      <span class="entity-card-id">${id}</span>
      <span style="flex:1"></span>
      <button class="btn btn-xs btn-outline" onclick="_voicesPlay('${id}')" id="vp-${id}">▶ ${t('voices.play') || '试听'}</button>
      <button class="btn btn-xs btn-ai" onclick="_voicesAssign('${id}')">${t('voices.assign') || '选用'}</button>
    </div>
  </div>`;
}

/** 播放/停止声线 */
function _voicesPlay(voiceId) {
  const btn = document.getElementById(`vp-${voiceId}`);
  if (!btn) return;

  // 停止当前播放
  if (_voicesState.playing) {
    const prev = _voicesState.playing;
    _voicesState.playing = null;
    const prevAudio = document.getElementById(`va-${prev}`);
    if (prevAudio) { prevAudio.pause(); prevAudio.remove(); }
    const prevBtn = document.getElementById(`vp-${prev}`);
    if (prevBtn) prevBtn.textContent = `▶ ${t('voices.play') || '试听'}`;
    if (prev === voiceId) return; // 点击同一个停止
  }

  const audio = document.createElement('audio');
  audio.id = `va-${voiceId}`;
  audio.src = `/api/voices/${voiceId}/audio`;
  audio.style.display = 'none';
  document.body.appendChild(audio);
  audio.play();
  _voicesState.playing = voiceId;
  btn.textContent = `⏹ ${t('voices.stop') || '停止'}`;
  audio.onended = () => {
    _voicesState.playing = null;
    btn.textContent = `▶ ${t('voices.play') || '试听'}`;
    audio.remove();
  };
}

/** 分配声线到角色（弹出角色选择） */
async function _voicesAssign(voiceId) {
  let chars = [];
  try {
    const d = await api('/characters');
    chars = d.characters || [];
  } catch (e) { toast(e.message, 'error'); return; }

  if (!chars.length) {
    toast(t('char.empty_hint') || '请先创建角色', 'error');
    return;
  }

  const charList = chars.map(c =>
    `<label class="inspire-check" style="display:flex;align-items:center;gap:.4rem;padding:.3rem 0;cursor:pointer">
      <input type="radio" name="voice-assign-char" value="${esc(c.id)}">
      ${esc(c.name || c.id)} <span class="dim" style="font-size:.7rem">${esc(c.id)}</span>
    </label>`
  ).join('');

  const body = `<p style="margin-bottom:.8rem">${t('voices.assign_hint') || '选择要应用此声线的角色：'}</p>
    <div style="max-height:300px;overflow-y:auto">${charList}</div>`;

  _showOverlay('voice-assign-overlay', `🎤 ${t('voices.assign') || '选用声线'}`, body, `_voicesDoAssign('${voiceId}')`);
}

async function _voicesDoAssign(voiceId) {
  const selected = document.querySelector('input[name="voice-assign-char"]:checked');
  if (!selected) { toast(t('toast.select_first') || '请先选择角色', 'error'); return; }
  const charId = selected.value;
  try {
    const r = await api(`/voices/${voiceId}/assign/${charId}`, { method: 'POST' });
    document.getElementById('voice-assign-overlay')?.remove();
    toast(`✅ ${t('voices.assigned') || '声线已分配'}: ${r.style || voiceId} → ${charId}`);
    invalidateCache('characters');
  } catch (e) { toast(`❌ ${e.message}`, 'error'); }
}

function _voicesSearch() {
  _voicesState.q = document.getElementById('voices-search')?.value?.trim() || '';
  _voicesState.page = 1;
  _voicesLoadList();
}

function _voicesFilter(gender) {
  _voicesState.gender = gender;
  _voicesState.page = 1;
  loadVoices();
}

function _voicesPage(p) {
  _voicesState.page = p;
  _voicesLoadList();
}

// ── Module registration ──
Drama.pages.voices = loadVoices;
window.loadVoices = loadVoices;
window._voicesSearch = _voicesSearch;
window._voicesFilter = _voicesFilter;
window._voicesPage = _voicesPage;
window._voicesPlay = _voicesPlay;
window._voicesAssign = _voicesAssign;
window._voicesDoAssign = _voicesDoAssign;
