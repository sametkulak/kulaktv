const DEFAULT_M3U = 'https://raw.githubusercontent.com/sametkulak/kulaktv/main/channels.m3u';
const LOCAL_M3U = './channels.m3u';
const IPTV_ORG_TR = 'https://iptv-org.github.io/iptv/countries/tr.m3u';
const BYTEFIX_LIST = 'https://tinyurl.com/ByteFixRepairs2026';

const state = {
  channels: [], filtered: [], current: null, currentUrl: '', hls: null,
  sourceName: 'KulakTV otomatik kaynak listesi',
  sourceCandidates: [], sourceIndex: -1,
  drawerOpen: false, settingsOpen: false,
  showFavorites: false,
  activeCategory: 'all',
  favorites: new Set((() => {
    try {
      return JSON.parse(localStorage.getItem('kulaktv-favorites') || '[]');
    } catch {
      return [];
    }
  })())
};

const $ = id => document.getElementById(id);
const video = $('video');
function setStatus(text) {
  const statusText = $('statusText');
  const topStatus = $('topStatus');

  if (statusText) {
    statusText.textContent = text;
  }

  if (topStatus) {
    topStatus.textContent = text;
  }
}
function escapeHtml(s) { return String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function parseAttrs(line) { const attrs={}; const re=/([\w-]+)="([^"]*)"/g; let m; while((m=re.exec(line))) attrs[m[1]]=m[2]; return attrs; }
function parseM3U(text) {
  const lines=text.replace(/^\uFEFF/,'').split(/\r?\n/), out=[];
  for(let i=0;i<lines.length;i++){
    const line=lines[i].trim(); if(!line.startsWith('#EXTINF:')) continue;
    const comma=line.indexOf(','), meta=comma>=0?line.slice(0,comma):line;
    let name=comma>=0?line.slice(comma+1).trim():'İsimsiz Kanal'; const attrs=parseAttrs(meta); let url='';
    for(let j=i+1;j<lines.length;j++){ const next=lines[j].trim(); if(!next||next.startsWith('#')) continue; url=next;i=j;break; }
    if(!url) continue;
    name=name.replace(/\s*\[(?:Not 24\/7|Geo-blocked)\]\s*$/i,'').trim();
    const alternatives = Object.entries(attrs)
      .filter(([key, value]) => /^(?:yedek\d*|backup\d*)$/i.test(key) && /^https?:\/\//i.test(value) && value !== url)
      .map(([, value]) => value);
    out.push({
      id: attrs['tvg-id'] || `${name}-${url}`,
      name,
      group: attrs['group-title'] || 'Genel',
      logo: attrs['tvg-logo'] || '',
      url,
      alternatives: [...new Set(alternatives)]
    });
  }
  return dedupeChannels(out);
}
function dedupeChannels(channels){ const seen=new Set(); return channels.filter(ch=>{const key=`${ch.name.toLowerCase()}|${ch.url}`; if(seen.has(key))return false;seen.add(key);return true;}); }
function getInitials(name){ const words=name.replace(/[^\p{L}\p{N} ]/gu,' ').trim().split(/\s+/).filter(Boolean); if(!words.length)return'TV'; if(words.length===1)return words[0].slice(0,2).toUpperCase(); return(words[0][0]+words[1][0]).toUpperCase(); }
function renderGroups(){
  renderCategoryChips();
}
function groupLabel(group){return String(group||'Diğer').replace(/^ulusal\s*-\s*/i,'').trim();}
function renderCategoryChips(){
  const root=$('categoryChips');
  if(!root)return;
  const groups=[...new Set(state.channels.map(c=>groupLabel(c.group)).filter(Boolean))];
  const counts=new Map(groups.map(g=>[g,state.channels.filter(c=>groupLabel(c.group)===g).length]));
  root.innerHTML=[
    `<button type="button" class="category-chip active" data-group="all">Tümü ${state.channels.length}</button>`,
    ...groups.map(g=>`<button type="button" class="category-chip" data-group="${escapeHtml(g)}">${escapeHtml(g)} ${counts.get(g)}</button>`)
  ].join('');
  root.querySelectorAll('.category-chip').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const group=btn.dataset.group||'all';
      state.activeCategory = group;
      root.querySelectorAll('.category-chip').forEach(x=>x.classList.toggle('active',x===btn));
      applyFilters();
    });
  });
}
function updateBarState(){
  const active = Boolean(state.current && !video.paused);
  $('playPause').textContent = active ? '❚❚' : '▶';
}
function updateFavoriteUi(){
  const count=$('favoriteCount');
  if(count)count.textContent=state.favorites.size;
  $('favoritesTab')?.classList.toggle('active',state.showFavorites);
  $('allChannelsTab')?.classList.toggle('active',!state.showFavorites);
}
function toggleFavorite(ch,event){
  event?.stopPropagation();
  const id=String(ch.id);
  if(state.favorites.has(id))state.favorites.delete(id);else state.favorites.add(id);
  localStorage.setItem('kulaktv-favorites',JSON.stringify([...state.favorites]));
  updateFavoriteUi();
  applyFilters();
}
function applyFilters(){
  const q=$('search').value.trim().toLocaleLowerCase('tr-TR');
  const group=state.activeCategory;
  state.filtered=state.channels.filter(c=>{
    const matchesSearch=!q||c.name.toLocaleLowerCase('tr-TR').includes(q)||c.group.toLocaleLowerCase('tr-TR').includes(q);
    const matchesGroup=group==='all'||c.group===group||groupLabel(c.group)===group;
    const matchesFavorites=!state.showFavorites||state.favorites.has(String(c.id));
    return matchesSearch&&matchesGroup&&matchesFavorites;
  });
  renderChannelList();
  const prefix=state.showFavorites?'Favoriler':'Tüm kanallar';
  $('channelCount').textContent=`${state.filtered.length} / ${state.channels.length} kanal • ${prefix}`;
  updateFavoriteUi();
}
function renderChannelList(){
  const root=$('channelList'); root.innerHTML='';
  if(!state.filtered.length){root.innerHTML='<div class="empty">Bu filtreyle kanal bulunamadı.</div>';return;}
  const frag=document.createDocumentFragment();
  state.filtered.forEach(ch=>{
    const div=document.createElement('div'); div.className='channel-item'+(state.current?.id===ch.id?' active':''); div.dataset.id=ch.id;
    const initials = escapeHtml(getInitials(ch.name));
    const logo=ch.logo
      ? `<img loading="lazy" src="${escapeHtml(ch.logo)}" alt="" onerror="this.onerror=null;this.parentElement.textContent='${initials}'">`
      : initials;
    div.innerHTML=`<button class="channel-fav${state.favorites.has(String(ch.id))?' active':''}" type="button" aria-label="Favoriye ekle">${state.favorites.has(String(ch.id))?'★':'☆'}</button><div class="channel-logo">${logo}</div><div class="channel-name-wrap"><div class="channel-name">${escapeHtml(ch.name)}</div><div class="channel-group">${escapeHtml(ch.group)}</div></div><span class="state-dot" id="dot-${CSS.escape(ch.id)}" title="Henüz test edilmedi"></span>`;
    div.querySelector('.channel-fav').addEventListener('click',e=>toggleFavorite(ch,e));
    div.addEventListener('click',()=>{playChannel(ch);closeChannels();}); frag.appendChild(div);
  }); root.appendChild(frag);
}
function mark(ch,status){const el=document.getElementById(`dot-${CSS.escape(ch.id)}`);if(!el)return;el.classList.remove('ok','bad');if(status==='ok'){el.classList.add('ok');el.title='Oynatma başarılı';}else if(status==='bad'){el.classList.add('bad');el.title='Oynatma başarısız / erişilemedi';}}
function stopHls(){if(state.hls){state.hls.destroy();state.hls=null;}}
function showError(message){$('errorBox').textContent=message;$('errorBox').hidden=false;}
function clearError(){$('errorBox').hidden=true;$('errorBox').textContent='';}
function canonicalChannelKey(ch){const base=String(ch.id||'').trim().toLowerCase();if(base)return base;return String(ch.name||'').toLocaleLowerCase('tr-TR').replace(/\s*\([^)]*\)\s*$/g,'').replace(/\s+/g,' ').trim();}
function getAlternativeChannels(ch){
  const key=canonicalChannelKey(ch), sameId=state.channels.filter(x=>x!==ch&&canonicalChannelKey(x)===key); if(sameId.length)return sameId;
  const normalized=String(ch.name||'').toLocaleLowerCase('tr-TR').replace(/\s*\([^)]*\)\s*$/g,'').replace(/\s+(live|hd|fhd|sd)$/i,'').replace(/\s+/g,' ').trim();
  return state.channels.filter(x=>x!==ch&&String(x.name||'').toLocaleLowerCase('tr-TR').replace(/\s*\([^)]*\)\s*$/g,'').replace(/\s+(live|hd|fhd|sd)$/i,'').replace(/\s+/g,' ').trim()===normalized);
}
async function openInExternalPlayer(url){
  try {
    const opened = window.open(url, '_blank', 'noopener,noreferrer');
    if (!opened) throw new Error('popup-blocked');
  } catch {
    try {
      await navigator.clipboard.writeText(url);
      showError('Yayın URL\'si panoya kopyalandı. APTV gibi bir dış oynatıcıya yapıştırabilirsiniz.');
      setTimeout(clearError, 2200);
    } catch {
      showError('Dış oynatıcı açılamadı. Yayın URL\'sini kopyalayın.');
    }
  }
}
function updateNowLogo(ch){
  const root=$('nowLogo');
  const initials=escapeHtml(getInitials(ch.name));
  root.innerHTML=ch.logo
    ? `<img src="${escapeHtml(ch.logo)}" alt="" onerror="this.onerror=null;this.parentElement.textContent='${initials}'">`
    : initials;
}
function setCurrentTitle(ch){
  $('nowTitle').textContent=ch.name;
  $('mobileNowTitle').textContent=ch.name;
  $('barChannelName').textContent=ch.name;
  const fallbackCount = Array.isArray(ch.alternatives) ? ch.alternatives.length : 0;
  $('nowMeta').textContent = `${ch.group} • HLS / M3U8${fallbackCount ? ` • ${fallbackCount} yedek kaynak` : ''}`;
  updateNowLogo(ch);
}
function playChannel(ch){
  clearError();
  stopHls();
  state.current = ch;
  state.sourceCandidates = [
    ch,
    ...(ch.alternatives || []).map(url => ({...ch, url})),
    ...getAlternativeChannels(ch)
  ]
    .filter((item,index,arr)=>item?.url && arr.findIndex(x=>x.url===item.url)===index)
    .slice(0,7);
  state.sourceIndex = 0;
  state.currentUrl = state.sourceCandidates[0]?.url || ch.url;
  updateStreamActions();
  setCurrentTitle(ch);
  renderChannelList();
  $('playerOverlay').classList.add('hidden');
  setStatus('Yayın açılıyor…');

  const alternatives = state.sourceCandidates;
  const maxAttempts = alternatives.length;
  let attemptIndex = 0;
  let settled = false;
  const timers = new Set();

  const clearTimers = () => {
    for(const t of timers) clearTimeout(t);
    timers.clear();
  };

  const success = (url, sourceIndex) => {
    if(settled) return;
    settled = true;
    clearTimers();
    state.sourceIndex = sourceIndex;
    state.currentUrl = url;
    updateSourceButton();
    mark(ch,'ok');
    setStatus(sourceIndex ? 'Canlı • alternatif kaynak' : 'Canlı');
  };

  const failure = (detail='Yayın açılamadı') => {
    if(settled) return;
    clearTimers();
    stopHls();
    if(attemptIndex + 1 < maxAttempts){
      attemptIndex++;
      state.sourceIndex = attemptIndex;
      updateSourceButton();
      setStatus(`Alternatif kaynak ${attemptIndex+1}/${maxAttempts} deneniyor…`);
      trySource(alternatives[attemptIndex], attemptIndex);
      return;
    }
    settled = true;
    mark(ch,'bad');
    setStatus('Açılamadı');
    showError(`${detail}. ${maxAttempts}/${maxAttempts} kaynak denendi. Diğer kaynakları "Kaynak değiştir" düğmesiyle tekrar sırayla deneyebilirsiniz.`);
  };

  const trySource = (candidate, sourceIndex) => {
    clearError();
    state.sourceIndex = sourceIndex;
    state.currentUrl = candidate.url;
    updateStreamActions();
    setStatus(`Kaynak ${sourceIndex+1}/${maxAttempts} deneniyor…`);
    video.pause();
    video.removeAttribute('src');
    video.load();
    let started = false;

    const onPlaying = () => {
      started = true;
      success(candidate.url, sourceIndex);
    };
    const onLoaded = () => {
      setStatus(`Kaynak ${sourceIndex+1}/${maxAttempts} hazır…`);
      video.play().catch(()=>{});
    };
    const onVideoError = () => {
      if(!started) failure('Video kaynağı tarayıcı tarafından reddedildi');
    };

    video.onplaying = onPlaying;
    video.onloadedmetadata = onLoaded;
    video.onerror = onVideoError;

    const timeout = setTimeout(() => {
      if(!started) failure('Kaynak 14.4 saniye içinde oynatılmaya başlamadı');
    },14400);
    timers.add(timeout);

    if(video.canPlayType('application/vnd.apple.mpegurl')){
      video.src = candidate.url;
      video.load();
      video.play().catch(()=>{});
      return;
    }

    if(!window.Hls || !Hls.isSupported()){
      failure('Tarayıcınız HLS oynatmayı desteklemiyor');
      return;
    }

    state.hls = new Hls({
      enableWorker:true,
      lowLatencyMode:true,
      backBufferLength:30,
      maxBufferLength:20,
      manifestLoadingTimeOut:12000,
      fragLoadingTimeOut:12000
    });
    state.hls.loadSource(candidate.url);
    state.hls.attachMedia(video);
    state.hls.on(Hls.Events.MANIFEST_PARSED,()=>{
      setStatus(`Kaynak ${sourceIndex+1}/${maxAttempts} hazır…`);
      video.play().catch(()=>{});
    });
    state.hls.on(Hls.Events.ERROR,(_e,data)=>{
      if(data?.fatal) failure(data.details || 'HLS fatal error');
    });
  };

  state._switchSource = (sourceIndex) => {
    if(!alternatives[sourceIndex]) return;
    clearTimers();
    stopHls();
    settled = false;
    attemptIndex = sourceIndex;
    trySource(alternatives[sourceIndex], sourceIndex);
  };
  trySource(alternatives[0],0);
}
async function loadM3UText(text,sourceName){
  const channels=parseM3U(text);
  if(!channels.length)throw new Error('Geçerli #EXTINF kayıtları bulunamadı.');

  state.channels=channels;
  state.sourceName=sourceName;
  state.showFavorites=false;
  state.activeCategory='all';

  const nowMeta=$('nowMeta');
  if(nowMeta) nowMeta.textContent=`${sourceName} • ${channels.length} kanal`;
  const footerSource=$('footerSource');
  if(footerSource) footerSource.textContent=sourceName;

  // Açılışta kanal listesi doğrudan tüm kanallarla doldurulsun.
  try { renderCategoryChips(); } catch(err) { console.warn('Kategori çipleri oluşturulamadı:',err); }

  state.filtered=[...state.channels];
  renderChannelList();

  const count=$('channelCount');
  if(count) count.textContent=`${state.filtered.length} / ${state.channels.length} kanal • Tüm kanallar`;

  try { updateFavoriteUi(); } catch(err) { console.warn('Favori UI güncellenemedi:',err); }

  setStatus('Hazır');
}
async function loadUrl(url,sourceLabel=url){const u=url.trim();if(!/^https?:\/\//i.test(u))throw new Error('Geçerli bir http/https M3U URL gir.');setStatus('Liste indiriliyor…');const res=await fetch(u,{cache:'no-store'});if(!res.ok)throw new Error(`Liste HTTP ${res.status} ile döndü.`);await loadM3UText(await res.text(),sourceLabel);}
async function loadDefault(){
  setStatus('Liste yükleniyor…');
  const urls = [DEFAULT_M3U, LOCAL_M3U];
  let lastErr = null;
  for (const url of urls) {
    try {
      const bust = (url.includes('?') ? '&' : '?') + '_=' + Date.now();
      const res = await fetch(url + bust, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      await loadM3UText(text, url === DEFAULT_M3U ? 'KulakTV otomatik liste' : 'Yerel M3U');
      return;
    } catch (e) {
      lastErr = e;
    }
  }
  throw new Error(`Liste yüklenemedi: ${lastErr?.message || 'bilinmeyen hata'}`);
}
function openChannels(){state.drawerOpen=true;$('channelDrawer').classList.add('open');$('drawerBackdrop').classList.add('open');$('channelDrawer').setAttribute('aria-hidden','false');setTimeout(()=>$('search').focus({preventScroll:true}),150);}
function closeChannels(){state.drawerOpen=false;$('channelDrawer').classList.remove('open');if(!state.settingsOpen)$('drawerBackdrop').classList.remove('open');$('channelDrawer').setAttribute('aria-hidden','true');}
function openSettings(){state.settingsOpen=true;closeChannels();$('settingsDrawer').classList.add('open');$('settingsBackdrop').classList.add('open');$('settingsDrawer').setAttribute('aria-hidden','false');}
function closeSettings(){state.settingsOpen=false;$('settingsDrawer').classList.remove('open');$('settingsBackdrop').classList.remove('open');$('settingsDrawer').setAttribute('aria-hidden','true');}
function nextChannel(dir){if(!state.current||!state.filtered.length)return;const i=state.filtered.findIndex(c=>c.id===state.current.id);const next=state.filtered[(i+dir+state.filtered.length)%state.filtered.length];if(next)playChannel(next);}
$('openChannels').addEventListener('click',openChannels);$('closeChannels').addEventListener('click',closeChannels);$('drawerBackdrop').addEventListener('click',closeChannels);$('openSettings').addEventListener('click',openSettings);$('closeSettings').addEventListener('click',closeSettings);$('settingsBackdrop').addEventListener('click',closeSettings);
$('prevChannel').addEventListener('click',()=>nextChannel(-1));$('nextChannel').addEventListener('click',()=>nextChannel(1));$('playPause').addEventListener('click',()=>{if(video.paused)video.play().catch(()=>{});else video.pause();});
async function toggleFullscreen(){
  try{
    if(document.fullscreenElement){
      await document.exitFullscreen();
      return;
    }
    if(video.webkitEnterFullscreen){
      video.webkitEnterFullscreen();
      return;
    }
    const target=$('videoStage');
    if(target?.requestFullscreen){
      await target.requestFullscreen();
      return;
    }
    showError('Bu tarayıcı tam ekran oynatmayı desteklemiyor.');
  }catch{
    try{
      if(video.webkitEnterFullscreen) video.webkitEnterFullscreen();
      else showError('Tam ekran açılamadı.');
    }catch{
      showError('Tam ekran açılamadı.');
    }
  }
}
$('fullscreenBtn').addEventListener('click',toggleFullscreen);
$('changeSourceBtn').addEventListener('click',()=>{
  const total = state.sourceCandidates.length;
  if(total < 2 || !state.current || !state._switchSource) return;
  const nextIndex = (state.sourceIndex + 1) % total;
  state._switchSource(nextIndex);
});
video.addEventListener('play',()=>{$('playPause').textContent='❚❚';});
video.addEventListener('pause',()=>{$('playPause').textContent='▶';});video.addEventListener('playing',()=>{if(state.current){mark(state.current,'ok');setStatus('Canlı');}});video.addEventListener('waiting',()=>{if(state.current)setStatus('Yükleniyor…');});
$('search').addEventListener('input',applyFilters);
$('allChannelsTab').addEventListener('click',()=>{state.showFavorites=false;applyFilters();});
$('favoritesTab').addEventListener('click',()=>{state.showFavorites=true;applyFilters();});
$('loadUrl').addEventListener('click',async()=>{clearError();try{await loadUrl($('playlistUrl').value,'Özel M3U listesi');closeSettings();openChannels();}catch(e){setStatus('Hata');showError(`Liste yüklenemedi: ${e.message}. Harici M3U sunucusunun CORS izni vermesi gerekebilir.`);}});
$('playlistUrl').addEventListener('keydown',e=>{if(e.key==='Enter')$('loadUrl').click();});
$('defaultList').addEventListener('click',async()=>{try{await loadDefault();closeSettings();openChannels();}catch(e){showError(e.message);}});
$('bytefixList').addEventListener('click',async()=>{$('playlistUrl').value=BYTEFIX_LIST;try{await loadUrl(BYTEFIX_LIST,'ByteFix Repairs kaynak listesi');closeSettings();openChannels();}catch(e){showError(`ByteFix listesi tarayıcıdan doğrudan yüklenemedi: ${e.message}`);}});
$('refreshDefault').addEventListener('click',async()=>{try{await loadDefault();closeSettings();openChannels();}catch(e){showError(e.message);}});
$('iptvOrgList').addEventListener('click',async()=>{$('playlistUrl').value=IPTV_ORG_TR;try{await loadUrl(IPTV_ORG_TR,'iptv-org Türkiye');closeSettings();openChannels();}catch(e){showError(`iptv-org listesi yüklenemedi: ${e.message}`);}});
$('loadFile').addEventListener('click',()=>$('fileInput').click());$('fileInput').addEventListener('change',async e=>{const file=e.target.files?.[0];if(!file)return;try{await loadM3UText(await file.text(),file.name);closeSettings();openChannels();}catch(err){showError(`Dosya okunamadı: ${err.message}`);}e.target.value='';});
function updateSourceButton(){
  const btn = $('changeSourceBtn');
  if(!btn) return;
  const total = state.sourceCandidates.length;
  btn.disabled = total < 2;
  btn.classList.toggle('source-switching', total >= 2);
  if(total >= 2){
    const next = (state.sourceIndex + 1) % total;
    btn.title = `Sonraki kaynak: ${next + 1}/${total}`;
    btn.setAttribute('aria-label', `Kaynak değiştir, sonraki kaynak ${next + 1}/${total}`);
  }else{
    btn.title = 'Bu kanal için başka kaynak yok';
    btn.setAttribute('aria-label', 'Bu kanal için başka kaynak yok');
  }
}
function updateStreamActions(){
  const hasUrl = Boolean(state.currentUrl);
  $('copyStream').disabled = !hasUrl;
  $('openStream').disabled = !hasUrl;
  updateSourceButton();
}
$('copyStream').addEventListener('click',async()=>{
  if(!state.currentUrl)return;
  try{
    await navigator.clipboard.writeText(state.currentUrl);
    showError('Yayın URL\'si panoya kopyalandı.');
    setTimeout(clearError,1800);
  }catch{
    showError('Panoya erişilemedi.');
  }
});
updateStreamActions();
$('openStream').addEventListener('click',()=>{if(state.currentUrl)openInExternalPlayer(state.currentUrl);});
async function loadUpdateStatus(){
  try{
    const res=await fetch('./update-status.json',{cache:'no-store'});
    if(!res.ok)return;
    const info=await res.json();
    const el=$('autoUpdateStatus');
    if(!el||!info.updatedAt)return;

    const d=new Date(info.updatedAt);
    const count=info.channelCount ? ` • ${info.channelCount} benzersiz kanal` : '';
    const sourceCount=info.sourceCount ? ` • ${info.sourceCount} kaynak` : '';
    const health=info.healthCheck;
    const healthText=health?.enabled
      ? ` • Yayın kontrolü: ${health.healthyUrls}/${health.checkedUrls} URL çalışıyor`
      : '';

    el.textContent=info.status==='fetch_failed'
      ? `Kaynak alınamadı • son liste korunuyor (${d.toLocaleString('tr-TR')})`
      : `Son otomatik güncelleme: ${d.toLocaleString('tr-TR')}${count}${sourceCount}${healthText}`;

    if(Array.isArray(info.sources)){
      el.title=info.sources.map(s=>`${s.name}: ${s.status||'unknown'}`).join(' | ');
    }
  }catch{}
}
loadUpdateStatus();loadDefault().catch(e=>{setStatus('Liste yüklenemedi');showError(`Başlangıç listesi yüklenemedi: ${e.message}`);});

// Initial UI state
updateFavoriteUi();
