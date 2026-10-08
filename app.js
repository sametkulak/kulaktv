const DEFAULT_M3U = './channels.m3u';
const IPTV_ORG_TR = 'https://iptv-org.github.io/iptv/countries/tr.m3u';
const BYTEFIX_LIST = 'https://tinyurl.com/ByteFixRepairs2026';

const state = {
  channels: [],
  filtered: [],
  current: null,
  hls: null,
  sourceName: 'KulakTV otomatik kaynak listesi'
};

const $ = (id) => document.getElementById(id);
const video = $('video');

function setStatus(text) { $('statusText').textContent = text; }
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function parseAttrs(line) {
  const attrs = {};
  const re = /([\w-]+)="([^"]*)"/g;
  let m;
  while ((m = re.exec(line))) attrs[m[1]] = m[2];
  return attrs;
}

function parseM3U(text) {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/);
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line.startsWith('#EXTINF:')) continue;
    const comma = line.indexOf(',');
    const meta = comma >= 0 ? line.slice(0, comma) : line;
    let name = comma >= 0 ? line.slice(comma + 1).trim() : 'İsimsiz Kanal';
    const attrs = parseAttrs(meta);
    let url = '';
    for (let j = i + 1; j < lines.length; j++) {
      const next = lines[j].trim();
      if (!next || next.startsWith('#')) continue;
      url = next; i = j; break;
    }
    if (!url) continue;
    // Remove a few common status suffixes used by public playlists.
    name = name.replace(/\s*\[(?:Not 24\/7|Geo-blocked)\]\s*$/i, '').trim();
    out.push({
      id: attrs['tvg-id'] || `${name}-${url}`,
      name,
      group: attrs['group-title'] || 'Genel',
      logo: attrs['tvg-logo'] || '',
      url
    });
  }
  return dedupeChannels(out);
}

function dedupeChannels(channels) {
  const seen = new Set();
  return channels.filter(ch => {
    const key = `${ch.name.toLowerCase()}|${ch.url}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
}

function getInitials(name) {
  const words = name.replace(/[^\p{L}\p{N} ]/gu,' ').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return 'TV';
  if (words.length === 1) return words[0].slice(0,2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

function renderGroups() {
  const select = $('groupFilter');
  const current = select.value;
  const groups = [...new Set(state.channels.map(c => c.group).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'tr'));
  select.innerHTML = '<option value="all">Tüm kategoriler</option>' + groups.map(g => `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`).join('');
  select.value = groups.includes(current) ? current : 'all';
}

function applyFilters() {
  const q = $('search').value.trim().toLocaleLowerCase('tr-TR');
  const group = $('groupFilter').value;
  state.filtered = state.channels.filter(c => {
    const matchesText = !q || c.name.toLocaleLowerCase('tr-TR').includes(q) || c.group.toLocaleLowerCase('tr-TR').includes(q);
    const matchesGroup = group === 'all' || c.group === group;
    return matchesText && matchesGroup;
  });
  renderChannelList();
  $('channelCount').textContent = `${state.filtered.length} / ${state.channels.length} kanal`;
}

function renderChannelList() {
  const root = $('channelList');
  root.innerHTML = '';
  if (!state.filtered.length) {
    root.innerHTML = '<div class="empty">Bu filtreyle kanal bulunamadı.</div>';
    return;
  }
  const frag = document.createDocumentFragment();
  state.filtered.forEach((ch, index) => {
    const div = document.createElement('div');
    div.className = 'channel-item' + (state.current?.id === ch.id ? ' active' : '');
    div.dataset.id = ch.id;
    const logo = ch.logo ? `<img loading="lazy" src="${escapeHtml(ch.logo)}" alt="" onerror="this.style.display='none'">` : getInitials(ch.name);
    div.innerHTML = `
      <div class="channel-logo">${logo}</div>
      <div>
        <div class="channel-name">${escapeHtml(ch.name)}</div>
        <div class="channel-group">${escapeHtml(ch.group)}</div>
      </div>
      <span class="state-dot" id="dot-${CSS.escape(ch.id)}" title="Henüz test edilmedi"></span>`;
    div.addEventListener('click', () => playChannel(ch));
    frag.appendChild(div);
  });
  root.appendChild(frag);
}

function mark(ch, status) {
  const el = document.getElementById(`dot-${CSS.escape(ch.id)}`);
  if (!el) return;
  el.classList.remove('ok','bad');
  if (status === 'ok') { el.classList.add('ok'); el.title = 'Oynatma başarılı'; }
  else if (status === 'bad') { el.classList.add('bad'); el.title = 'Oynatma başarısız / erişilemedi'; }
}

function stopHls() {
  if (state.hls) { state.hls.destroy(); state.hls = null; }
}

function showError(message) {
  $('errorBox').textContent = message;
  $('errorBox').hidden = false;
}
function clearError() { $('errorBox').hidden = true; $('errorBox').textContent = ''; }

function playChannel(ch) {
  clearError();
  stopHls();
  state.current = ch;
  renderChannelList();
  $('nowTitle').textContent = ch.name;
  $('nowMeta').textContent = `${ch.group} • HLS / M3U8`;
  $('copyStream').disabled = false;
  $('copyStream').onclick = async () => {
    try { await navigator.clipboard.writeText(ch.url); $('copyStream').textContent = 'Kopyalandı ✓'; setTimeout(()=> $('copyStream').textContent = "Yayın URL'sini Kopyala", 1400); }
    catch { showError('Tarayıcı panoya erişimi reddetti.'); }
  };
  $('playerOverlay').classList.add('hidden');
  setStatus('Yayın açılıyor…');

  video.pause();
  video.removeAttribute('src');
  video.load();

  const onSuccess = () => { mark(ch, 'ok'); setStatus('Canlı'); clearError(); };
  const onError = (detail='') => {
    mark(ch, 'bad');
    setStatus('Hata');
    showError(`Yayın açılamadı. Kaynak geçici olarak kapalı, CORS/kısıtlı erişim veya bölgesel engel olabilir.${detail ? ` (${detail})` : ''}`);
  };

  if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = ch.url;
    video.addEventListener('loadedmetadata', onSuccess, {once:true});
    video.addEventListener('error', () => onError(), {once:true});
    video.play().catch(() => {});
    return;
  }

  if (!window.Hls || !Hls.isSupported()) {
    onError('Tarayıcınız HLS oynatmayı desteklemiyor');
    return;
  }

  state.hls = new Hls({ enableWorker:true, lowLatencyMode:true, backBufferLength:30 });
  state.hls.loadSource(ch.url);
  state.hls.attachMedia(video);
  state.hls.on(Hls.Events.MANIFEST_PARSED, () => { onSuccess(); video.play().catch(()=>{}); });
  state.hls.on(Hls.Events.ERROR, (_event, data) => {
    if (data?.fatal) {
      try { state.hls.destroy(); } catch {}
      state.hls = null;
      onError(data.details || 'HLS fatal error');
    }
  });
}

async function loadM3UText(text, sourceName) {
  const channels = parseM3U(text);
  if (!channels.length) throw new Error('Geçerli #EXTINF kayıtları bulunamadı.');
  state.channels = channels;
  state.sourceName = sourceName;
  $('nowMeta').textContent = `${sourceName} • ${channels.length} kanal`;
  renderGroups();
  applyFilters();
  setStatus('Hazır');
}

async function loadUrl(url, sourceLabel=url) {
  const u = url.trim();
  if (!/^https?:\/\//i.test(u)) throw new Error('Geçerli bir http/https M3U URL gir.');
  setStatus('Liste indiriliyor…');
  const res = await fetch(u, { cache:'no-store' });
  if (!res.ok) throw new Error(`Liste HTTP ${res.status} ile döndü.`);
  const text = await res.text();
  await loadM3UText(text, sourceLabel);
}

async function loadDefault() {
  setStatus('Yerleşik liste açılıyor…');
  const res = await fetch(DEFAULT_M3U, { cache:'no-store' });
  if (!res.ok) throw new Error('Yerleşik M3U dosyasına erişilemedi.');
  await loadM3UText(await res.text(), 'Yerleşik Türkiye listesi');
}

$('search').addEventListener('input', applyFilters);
$('groupFilter').addEventListener('change', applyFilters);
$('loadUrl').addEventListener('click', async () => {
  clearError();
  try { await loadUrl($('playlistUrl').value, 'Özel M3U listesi'); }
  catch (e) { setStatus('Hata'); showError(`Liste yüklenemedi: ${e.message}. Harici M3U sunucusunun CORS izni vermesi gerekebilir.`); }
});
$('playlistUrl').addEventListener('keydown', e => { if (e.key === 'Enter') $('loadUrl').click(); });
$('defaultList').addEventListener('click', async () => { try { await loadDefault(); } catch(e) { showError(e.message); } });
$('bytefixList').addEventListener('click', async () => {
  $('playlistUrl').value = BYTEFIX_LIST;
  try { await loadUrl(BYTEFIX_LIST, 'ByteFix Repairs kaynak listesi'); }
  catch(e) { showError(`ByteFix listesi tarayıcıdan doğrudan yüklenemedi: ${e.message}`); }
});
$('refreshDefault').addEventListener('click', async () => { try { await loadDefault(); } catch(e) { showError(e.message); } });
$('iptvOrgList').addEventListener('click', async () => {
  $('playlistUrl').value = IPTV_ORG_TR;
  try { await loadUrl(IPTV_ORG_TR, 'iptv-org Türkiye'); }
  catch(e) { showError(`iptv-org listesi yüklenemedi: ${e.message}`); }
});
$('loadFile').addEventListener('click', () => $('fileInput').click());
$('fileInput').addEventListener('change', async e => {
  const file = e.target.files?.[0]; if (!file) return;
  try { await loadM3UText(await file.text(), file.name); } catch(err) { showError(`Dosya okunamadı: ${err.message}`); }
  e.target.value = '';
});

video.addEventListener('playing', () => { if (state.current) { mark(state.current,'ok'); setStatus('Canlı'); } });
video.addEventListener('waiting', () => { if (state.current) setStatus('Yükleniyor…'); });

async function loadUpdateStatus() {
  try {
    const res = await fetch('./update-status.json', { cache:'no-store' });
    if (!res.ok) return;
    const info = await res.json();
    const el = $('autoUpdateStatus');
    if (!el || !info.updatedAt) return;
    const d = new Date(info.updatedAt);
    const count = info.channelCount ? ` • ${info.channelCount} kanal` : '';
    if (info.status === 'fetch_failed') {
      el.textContent = `Kaynak alınamadı • son liste korunuyor (${d.toLocaleString('tr-TR')})`;
      el.title = info.error || '';
    } else {
      el.textContent = `Otomatik güncelleme: ${d.toLocaleString('tr-TR')}${count}`;
      el.title = `Kaynak: ${info.source || ''}`;
    }
  } catch {}
}

loadUpdateStatus();

loadDefault().catch(e => {
  setStatus('Liste yüklenemedi');
  showError(`Başlangıç listesi yüklenemedi: ${e.message}`);
});
