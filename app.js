const DEFAULT_M3U = 'https://raw.githubusercontent.com/sametkulak/kulaktv/main/channels.m3u';
const LOCAL_M3U = './channels.m3u';
const IPTV_ORG_TR = 'https://iptv-org.github.io/iptv/countries/tr.m3u';
const BYTEFIX_LIST = 'https://tinyurl.com/ByteFixRepairs2026';

const SOURCE_QUALITY_KEY = 'kulaktv-source-quality-v1';
const EPG_URL = './epg.json';
const EPG_STATUS_URL = './epg-status.json';
const UPDATE_HISTORY_URL = './update-history.json';

const TELEMETRY_CONFIG = window.KULAKTV_TELEMETRY_CONFIG || {};
const TELEMETRY_API_BASE = 'https://api.github.com/repos/sametkulak/kulaktv/issues';
const TELEMETRY_STORAGE_KEY = 'kulaktv-pending-player-telemetry-v1';
let telemetryQueue = [];
let telemetrySending = false;
let telemetryDisabledForSession = false;
let telemetryFlushTimer = null;

function getTelemetrySessionId(){
  try{
    const key='kulaktv-telemetry-session-v1';
    const saved=sessionStorage.getItem(key);
    if(saved)return saved;
    const id=(globalThis.crypto?.randomUUID)
      ? crypto.randomUUID()
      : 's-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
    sessionStorage.setItem(key,id);
    return id;
  }catch{
    return 's-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  }
}
const telemetrySessionId=getTelemetrySessionId();

function loadTelemetryQueue(){
  try{
    const data=JSON.parse(localStorage.getItem(TELEMETRY_STORAGE_KEY)||'[]');
    return Array.isArray(data) ? data.slice(-60) : [];
  }catch{return [];}
}

function saveTelemetryQueue(){
  try{
    localStorage.setItem(TELEMETRY_STORAGE_KEY,JSON.stringify(telemetryQueue.slice(-60)));
  }catch{}
}

telemetryQueue=loadTelemetryQueue();

function telemetryEnabled(){
  const token=String(TELEMETRY_CONFIG.githubToken||'').trim();
  const issueNumber=Number(TELEMETRY_CONFIG.issueNumber||0);
  return Boolean(
    TELEMETRY_CONFIG.enabled &&
    token &&
    token !== 'PASTE_FINE_GRAINED_TOKEN_HERE' &&
    issueNumber > 0 &&
    !telemetryDisabledForSession
  );
}

function getTelemetryDevice(){
  const width=Math.min(window.innerWidth||0,window.screen?.width||0);
  if(width<=700)return 'mobile';
  if(width<=1100)return 'tablet';
  return 'desktop';
}

function getTelemetryBrowser(){
  const ua=navigator.userAgent||'';
  if(/edg\//i.test(ua))return 'Edge';
  if(/firefox\//i.test(ua))return 'Firefox';
  if(/samsungbrowser\//i.test(ua))return 'Samsung Internet';
  if(/opr\//i.test(ua))return 'Opera';
  if(/chrome\//i.test(ua)&&!/edg\//i.test(ua))return 'Chrome';
  if(/safari\//i.test(ua)&&!/chrome\//i.test(ua))return 'Safari';
  return 'Diğer';
}

function getTelemetryConnection(){
  const connection=navigator.connection||navigator.mozConnection||navigator.webkitConnection;
  return String(connection?.effectiveType||connection?.type||'unknown');
}

function queuePlaybackTelemetry(type,url,extra={}){
  if(!telemetryEnabled()||!url)return;

  telemetryQueue.push({
    type,
    at:new Date().toISOString(),
    url,
    host:(() => { try{return new URL(url).hostname;}catch{return '';} })(),
    channel:state.current?.name||'unknown',
    sourceIndex:Number(extra.sourceIndex ?? state.sourceIndex ?? -1)+1,
    latencyMs:Number(extra.latencyMs||0)||0,
    detail:String(extra.detail||''),
  });

  saveTelemetryQueue();

  const flushEvery=Math.max(1,Number(TELEMETRY_CONFIG.flushEvery||6));
  if(telemetryQueue.length>=flushEvery){
    flushPlaybackTelemetry();
  }else{
    clearTimeout(telemetryFlushTimer);
    telemetryFlushTimer=setTimeout(()=>flushPlaybackTelemetry(),Math.max(3000,Number(TELEMETRY_CONFIG.flushIntervalMs||15000)));
  }
}

async function flushPlaybackTelemetry(keepalive=false){
  if(telemetrySending||!telemetryEnabled()||!telemetryQueue.length)return;

  const maxBatch=Math.max(1,Math.min(12,Number(TELEMETRY_CONFIG.maxBatchEvents||12)));
  const batch=telemetryQueue.splice(0,maxBatch);
  saveTelemetryQueue();
  telemetrySending=true;

  const token=String(TELEMETRY_CONFIG.githubToken||'').trim();
  const issueNumber=Number(TELEMETRY_CONFIG.issueNumber||0);
  const payload={
    sessionId:telemetrySessionId,
    sentAt:new Date().toISOString(),
    client:{
      device:getTelemetryDevice(),
      browser:getTelemetryBrowser(),
      connection:getTelemetryConnection(),
      touchPoints:Number(navigator.maxTouchPoints||0),
      language:String(navigator.language||'unknown'),
      width:Number(window.innerWidth||0),
      height:Number(window.innerHeight||0)
    },
    events:batch
  };

  try{
    const res=await fetch(`${TELEMETRY_API_BASE}/${issueNumber}/comments`,{
      method:'POST',
      keepalive:Boolean(keepalive),
      headers:{
        'Accept':'application/vnd.github+json',
        'Authorization':`Bearer ${token}`,
        'Content-Type':'application/json',
        'X-GitHub-Api-Version':'2026-03-10'
      },
      body:JSON.stringify({
        body:`KULAKTV-TELEMETRY v1\\n${JSON.stringify(payload)}`
      })
    });

    if(!res.ok){
      telemetryQueue=[...batch,...telemetryQueue].slice(-60);
      saveTelemetryQueue();
      if(res.status===401||res.status===403){
        telemetryDisabledForSession=true;
        console.warn('KulakTV telemetry yetkisi reddedildi.');
      }
    }
  }catch(err){
    telemetryQueue=[...batch,...telemetryQueue].slice(-60);
    saveTelemetryQueue();
    console.warn('KulakTV telemetry gönderilemedi:',err);
  }finally{
    telemetrySending=false;
    if(telemetryQueue.length){
      const flushEvery=Math.max(1,Number(TELEMETRY_CONFIG.flushEvery||6));
      clearTimeout(telemetryFlushTimer);
      if(telemetryQueue.length>=flushEvery){
        void flushPlaybackTelemetry();
      }else{
        telemetryFlushTimer=setTimeout(
          ()=>flushPlaybackTelemetry(),
          Math.max(3000,Number(TELEMETRY_CONFIG.flushIntervalMs||15000))
        );
      }
    }
  }
}

window.addEventListener('pagehide',()=>{ void flushPlaybackTelemetry(true); });
document.addEventListener('visibilitychange',()=>{
  if(document.visibilityState==='hidden') void flushPlaybackTelemetry(true);
});

function loadSourceQuality(){
  try{
    const data=JSON.parse(localStorage.getItem(SOURCE_QUALITY_KEY)||'{}');
    return data && typeof data==='object' ? data : {};
  }catch{return {};}
}
const sourceQuality=loadSourceQuality();
let sharedSourceQuality = {};
let sharedSourceProviders = {};
let sharedSourceQualityLoaded = false;
const SHARED_SOURCE_QUALITY_URL = './source-quality.json';

function saveSourceQuality(){
  try{localStorage.setItem(SOURCE_QUALITY_KEY,JSON.stringify(sourceQuality));}catch{}
}


async function loadSharedSourceQuality(){
  try{
    const bust=(SHARED_SOURCE_QUALITY_URL.includes('?')?'&':'?')+'_='+Date.now();
    const res=await fetch(SHARED_SOURCE_QUALITY_URL+bust,{cache:'no-store'});
    if(!res.ok)throw new Error(`HTTP ${res.status}`);
    const data=await res.json();
    sharedSourceQuality=(data && data.sources && typeof data.sources==='object') ? data.sources : {};
    sharedSourceProviders=(data && data.providers && typeof data.providers==='object') ? data.providers : {};
    sharedSourceQualityLoaded=true;
    renderSourceTrustList();
  }catch(err){
    sharedSourceQualityLoaded=false;
    console.warn('Ortak kaynak kalite verisi yüklenemedi:',err);
  }
}

function getSharedSourceQuality(url){
  return sharedSourceQuality && sharedSourceQuality[url]
    ? sharedSourceQuality[url]
    : null;
}

function sortSourceCandidatesByQuality(items){
  return items
    .map((item,index)=>({item,index,quality:getSharedSourceQuality(item.url)}))
    .sort((a,b)=>{
      const aq=a.quality,bq=b.quality;
      if(aq && !bq)return -1;
      if(!aq && bq)return 1;
      if(!aq && !bq)return a.index-b.index;

      const aOk=aq.lastStatus==='ok';
      const bOk=bq.lastStatus==='ok';
      if(aOk!==bOk)return aOk?-1:1;

      const scoreA=Number(aq.score ?? 50);
      const scoreB=Number(bq.score ?? 50);
      if(scoreA!==scoreB)return scoreB-scoreA;

      const checksA=Number(aq.checks||0);
      const checksB=Number(bq.checks||0);
      if(checksA!==checksB)return checksB-checksA;

      return a.index-b.index;
    })
    .map(x=>x.item);
}


function normalizeSearchText(value){
  return String(value||'')
    .toLocaleLowerCase('tr-TR')
    .replace(/ı/g,'i').replace(/ş/g,'s').replace(/ç/g,'c')
    .replace(/ö/g,'o').replace(/ü/g,'u').replace(/ğ/g,'g')
    .replace(/[^a-z0-9]+/g,'');
}

const CHANNEL_SEARCH_ALIASES={
  'trt1':['trt1','trt one'],
  'trtspor':['trtspor','spor'],
  'trthaber':['trthaber'],
  'trtbelgesel':['trtbelgesel','belgesel'],
  'trtcocuk':['trtcocuk','cocuk'],
  'kanald':['kanald'],
  'showtv':['show','showtv','showhd'],
  'startv':['star','startv'],
  'now':['nowtv'],
  'cnnturk':['cnn','cnnturk'],
  'ahaber':['ahaber'],
  'aspor':['aspor'],
  'tv8':['tv8','tvsekiz'],
  'beyaztv':['beyaz','beyaztv'],
  'ntv':['ntvhd'],
  'haberturk':['ht','haberturk'],
  'haberglobal':['haberglobal','hglobal'],
  'tgrthaber':['tgrt','tgrthaber'],
  'sozcutv':['sozcu','sozcutv'],
  'halktv':['halk','halktv'],
  'kanal7':['kanal7','kanalyedi'],
  'tivibuspor':['tivibuspor'],
  'fbtv':['fbtv','fenerbahce'],
  'gstv':['gstv','galatasaray'],
  'htspor':['htspor'],
  'kralpoptv':['kralpop','kralpoptv'],
  'dreamturk':['dreamturk'],
  'powerturktv':['powerturk','powerturktv'],
  'number1tv':['number1','numberonetv'],
  'nr1turk':['nr1','nr1turk']
};

const SOURCE_START_TIMEOUT_MS = 14400;
const SOURCE_STABILITY_MS = 3500;
const SOURCE_STALL_GRACE_MS = 1800;
const SOURCE_SWITCH_DELAY_MS = 1200;

const state = {
  channels: [], filtered: [], current: null, currentUrl: '', hls: null,
  sourceName: 'KulakTV kaynak listesi',
  sourceCandidates: [], sourceIndex: -1,
  autoStarting: false,
  playbackGeneration: 0,
  cancelPlayback: null,
  drawerOpen: false, settingsOpen: false,
  showFavorites: false,
  activeCategory: 'all',
  favorites: new Set((() => {
    try {
      return JSON.parse(localStorage.getItem('kulaktv-favorites') || '[]');
    } catch {
      return [];
    }
  })()),
  epg: { updatedAt:null, channels:{} },
  epgLoaded: false,
  epgOpen: false
};

const $ = id => document.getElementById(id);
const video = $('video');
function setStatus(text) {
  const topStatus = $('topStatus');
  if (topStatus) topStatus.textContent = text;
}
function setConnectionStatus(kind,text){
  const root=$('connectionStatus');
  if(!root)return;
  root.className='connection-status '+(kind||'connecting');
  const label=root.querySelector('b');
  if(label)label.textContent=text||'Bağlanıyor';
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
  const id=channelFavoriteKey(ch);
  if(state.favorites.has(id))state.favorites.delete(id);else state.favorites.add(id);
  localStorage.setItem('kulaktv-favorites',JSON.stringify([...state.favorites]));
  updateFavoriteUi();
  applyFilters();
}
function normalizeChannelName(value){
  return normalizeSearchText(value)
    .replace(/(?:2160p|1440p|1080p|720p|576p|480p|360p|240p|4k|8k)$/,'')
    .replace(/(?:fhd|hd|sd|live|canli)$/,'')
    .replace(/(?:turkiye|turkey)$/,'');
}


function getEpgChannel(ch){
  const key=normalizeChannelName(ch?.name||'');
  const channels=state.epg?.channels||{};
  return channels[key]
    || channels[key.toUpperCase()]
    || Object.entries(channels).find(([channelKey])=>normalizeChannelName(channelKey)===key)?.[1]
    || null;
}
function getCurrentProgramme(ch,at=Date.now()){
  const data=getEpgChannel(ch);
  if(!data||!Array.isArray(data.programs))return null;
  return data.programs.find(p=>{
    const start=Date.parse(p.start||'');
    const stop=Date.parse(p.stop||'');
    return Number.isFinite(start)&&Number.isFinite(stop)&&start<=at&&at<stop;
  }) || null;
}
function getNextProgrammes(ch,limit=10,at=Date.now()){
  const data=getEpgChannel(ch);
  if(!data||!Array.isArray(data.programs))return [];
  return data.programs
    .filter(p=>Date.parse(p.stop||'')>at)
    .sort((a,b)=>Date.parse(a.start||'')-Date.parse(b.start||''))
    .slice(0,limit);
}
function formatEpgTime(iso){
  const d=new Date(iso);
  if(Number.isNaN(d.getTime()))return '--:--';
  return d.toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'});
}
function formatEpgDate(iso){
  const d=new Date(iso);
  if(Number.isNaN(d.getTime()))return '';
  return d.toLocaleDateString('tr-TR',{day:'2-digit',month:'2-digit'});
}
function renderCurrentEpg(ch){
  const current=getCurrentProgramme(ch);
  const next=getNextProgrammes(ch,2);
  const nowEl=$('nowProgramme');
  const nextEl=$('nextProgramme');
  if(nowEl){
    nowEl.textContent=current ? '▶ '+current.title+' • '+formatEpgTime(current.start)+'-'+formatEpgTime(current.stop) : 'Program bilgisi bulunamadı';
  }
  if(nextEl){
    const nxt=next.find(p=>!current||p.start!==current.start);
    nextEl.textContent=nxt ? 'Sonraki: '+nxt.title+' • '+formatEpgTime(nxt.start) : '';
  }
  if(state.epgOpen)renderEpgDrawer(ch);
}
function renderEpgDrawer(ch=state.current){
  const title=$('epgDrawerSubtitle');
  const currentTitle=$('epgCurrentTitle');
  const currentTime=$('epgCurrentTime');
  const list=$('epgList');
  if(!title||!currentTitle||!currentTime||!list)return;
  if(!ch){
    title.textContent='Kanal seçin';
    currentTitle.textContent='Program bilgisi yok';
    currentTime.textContent='--:--';
    list.innerHTML='<div class="mini-muted">Önce bir kanal seçin.</div>';
    return;
  }
  title.textContent=ch.name;
  const current=getCurrentProgramme(ch);
  currentTitle.textContent=current?.title||'Şu anda program bilgisi yok';
  currentTime.textContent=current ? formatEpgTime(current.start)+' - '+formatEpgTime(current.stop) : '--:--';
  const programs=getNextProgrammes(ch,16);
  if(!programs.length){
    list.innerHTML='<div class="mini-muted">Bu kanal için EPG verisi bulunamadı.</div>';
    return;
  }
  list.innerHTML=programs.map(program=>{
    const active=current && current.start===program.start;
    const desc=program.desc ? '<div class="epg-item-desc">'+escapeHtml(program.desc)+'</div>' : '';
    return '<div class="epg-item'+(active?' current':'')+'"><div class="epg-item-time">'+formatEpgDate(program.start)+' • '+formatEpgTime(program.start)+'-'+formatEpgTime(program.stop)+'</div><div class="epg-item-title">'+escapeHtml(program.title)+'</div>'+desc+'</div>';
  }).join('');
}
function setEpgStatusText(text,kind=''){
  const el=$('epgStatus');
  if(!el)return;
  el.textContent=text;
  el.className='mini-muted'+(kind ? ' epg-status-'+kind : '');
}
async function loadEpg(){
  try{
    const res=await fetch(EPG_URL+'?_='+Date.now(),{cache:'no-store'});
    if(!res.ok)throw new Error('HTTP '+res.status);
    const data=await res.json();
    if(!data||!data.channels||typeof data.channels!=='object')throw new Error('EPG biçimi geçersiz');
    state.epg={updatedAt:data.updatedAt||null,channels:data.channels};
    state.epgLoaded=true;
    const count=Object.keys(data.channels).length;
    const dateText=data.updatedAt ? new Date(data.updatedAt).toLocaleString('tr-TR') : '';
    setEpgStatusText('Hazır • '+count+' kanal için program verisi • '+dateText,'ok');
    renderChannelList();
    if(state.current)renderCurrentEpg(state.current);
    if(state.epgOpen)renderEpgDrawer();
  }catch(err){
    state.epgLoaded=false;
    setEpgStatusText('EPG kullanılamıyor: '+err.message,'error');
  }
}
function friendlyProviderName(name){
  const raw=String(name||'');
  if(raw.startsWith('auto:')){
    const parts=raw.slice(5).split(':');
    return 'Otomatik • '+parts.slice(0,2).join('/');
  }
  return raw;
}
function renderSourceTrustList(){
  const root=$('sourceTrustList');
  if(!root)return;
  const entries=Object.entries(sharedSourceProviders||{})
    .map(([name,data])=>({name:name,data:data||{}}))
    .sort((a,b)=>Number(b.data.score||0)-Number(a.data.score||0));
  if(!entries.length){
    root.innerHTML='<div class="mini-muted">Henüz kaynak güven puanı oluşturulmadı.</div>';
    return;
  }
  root.innerHTML=entries.slice(0,12).map(entry=>{
    const name=entry.name, data=entry.data;
    const score=Math.max(0,Math.min(100,Number(data.score||0)));
    const level=score>=85?'strong':score>=70?'good':score>=50?'medium':'weak';
    return '<div class="trust-item"><div class="trust-main"><span class="trust-dot '+level+'"></span><div class="trust-name">'+escapeHtml(friendlyProviderName(name))+'</div><div class="trust-score">'+score+'</div></div><div class="trust-meta">'+escapeHtml(data.label||'')+' • '+Number(data.healthyUrls||0)+'/'+Number(data.checkedUrls||0)+' URL sağlıklı</div><div class="trust-track"><span class="'+level+'" style="width:'+score+'%"></span></div></div>';
  }).join('');
}
async function loadHistory(){
  try{
    const historyRes=await fetch(UPDATE_HISTORY_URL+'?_='+Date.now(),{cache:'no-store'});
    if(!historyRes.ok)return;
    const history=await historyRes.json();
    const runs=Array.isArray(history?.runs)?history.runs.slice(-10).reverse():[];
    const root=$('updateHistoryList');
    if(!root)return;
    if(!runs.length){
      root.innerHTML='<div class="mini-muted">Henüz güncelleme geçmişi yok.</div>';
      return;
    }
    root.innerHTML=runs.map(run=>{
      const d=run.updatedAt?new Date(run.updatedAt):null;
      const health=run.health||{};
      const changes=run.changes||{};
      const dateText=d&&!Number.isNaN(d.getTime())?d.toLocaleDateString('tr-TR'):'';
      const timeText=d&&!Number.isNaN(d.getTime())?d.toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'}):'';
      const delta=Number(changes.channelDelta||0);
      const deltaText=delta>0 ? `+${delta}` : delta<0 ? `-${Math.abs(delta)}` : '±0';
      return '<div class="history-item"><div><b>'+dateText+'</b><span>'+timeText+' • '+(run.status==='fetch_failed'?'Kaynak hatası':'Güncelleme')+'</span></div><div class="history-value">'+Number(run.channelCount||0)+' kanal <small>'+deltaText+'</small></div><div class="history-sub">'+Number(run.configuredSourceCount||run.sourceCount||0)+' kaynak • '+Number(health.healthy||0)+'/'+Number(health.checked||0)+' URL • '+Number(changes.addedCount||0)+' eklendi / '+Number(changes.removedCount||0)+' çıkarıldı</div></div>';
    }).join('');
  }catch(err){
    console.warn('Güncelleme geçmişi yüklenemedi:',err);
  }
}
function channelFavoriteKey(ch){
  // Favoriler kaynak URL'sine bağlı olmamalı. Günlük güncellemede URL
  // değişse bile aynı kanal favori olarak kalır.
  return `${normalizeChannelName(ch?.name)}|${normalizeSearchText(ch?.group||'')}`;
}

function applyFilters(){
  const q=normalizeSearchText($('search').value.trim());
  const group=state.activeCategory;
  state.filtered=state.channels.filter(c=>{
    const nameKey=normalizeSearchText(c.name);
    const groupKey=normalizeSearchText(c.group);
    const aliasKey=nameKey.replace(/hd|fhd|sd|live|canli/g,'');
    const aliases=CHANNEL_SEARCH_ALIASES[aliasKey]||[];
    const matchesSearch=!q||nameKey.includes(q)||groupKey.includes(q)||aliases.some(a=>normalizeSearchText(a).includes(q));
    const matchesGroup=group==='all'||c.group===group||groupLabel(c.group)===group;
    const matchesFavorites=!state.showFavorites||state.favorites.has(channelFavoriteKey(c));
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
    const div=document.createElement('div'); div.className='channel-item'+(state.current===ch?' active':''); div.dataset.id=ch.id;
    const initials = escapeHtml(getInitials(ch.name));
    const logo=ch.logo
      ? `<img loading="lazy" src="${escapeHtml(ch.logo)}" alt="" onerror="this.onerror=null;this.parentElement.textContent='${initials}'">`
      : initials;
    const currentProgram=getCurrentProgramme(ch); const programmeText=currentProgram ? escapeHtml(currentProgram.title) : '';
    div.innerHTML=`<button class="channel-fav${state.favorites.has(channelFavoriteKey(ch))?' active':''}" type="button" aria-label="Favoriye ekle">${state.favorites.has(channelFavoriteKey(ch))?'★':'☆'}</button><div class="channel-logo">${logo}</div><div class="channel-name-wrap"><div class="channel-name">${escapeHtml(ch.name)}</div><div class="channel-group">${escapeHtml(ch.group)}</div>${programmeText?`<div class="channel-program" title="${programmeText}">▶ ${programmeText}</div>`:''}</div><span class="state-dot" id="dot-${CSS.escape(ch.id)}" title="Henüz test edilmedi"></span>`;
    div.querySelector('.channel-fav').addEventListener('click',e=>toggleFavorite(ch,e));
    div.addEventListener('click',()=>{playChannel(ch);closeChannels();}); frag.appendChild(div);
  }); root.appendChild(frag);
}
function mark(ch,status){const el=document.getElementById(`dot-${CSS.escape(ch.id)}`);if(!el)return;el.classList.remove('ok','bad');if(status==='ok'){el.classList.add('ok');el.title='Oynatma başarılı';}else if(status==='bad'){el.classList.add('bad');el.title='Oynatma başarısız / erişilemedi';}}
function stopHls(){if(state.hls){state.hls.destroy();state.hls=null;}}
function showError(message){$('errorBox').textContent=message;$('errorBox').hidden=false;}
function clearError(){$('errorBox').hidden=true;$('errorBox').textContent='';}
function canonicalChannelKey(ch){
  return normalizeChannelName(ch?.name||'');
}
function getAlternativeChannels(ch){
  const normalized=canonicalChannelKey(ch);
  if(!normalized)return [];
  return state.channels.filter(x=>x!==ch&&canonicalChannelKey(x)===normalized);
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
  renderCurrentEpg(ch);
}
function playChannel(ch){
  // Eski kanalın tüm timer/callback/event zincirini kesin olarak geçersiz kıl.
  if(typeof state.cancelPlayback==='function') state.cancelPlayback();
  stopHls();
  state.playbackGeneration += 1;
  const generation = state.playbackGeneration;
  const isCurrentRun = () =>
    generation === state.playbackGeneration && state.current === ch;

  clearError();
  state.current = ch;

  const originalCandidates = [
    ch,
    ...(ch.alternatives || []).map(url => ({...ch, url})),
    ...getAlternativeChannels(ch)
  ]
    .filter((item,index,arr)=>item?.url && arr.findIndex(x=>x.url===item.url)===index);

  // Shared GitHub quality history now decides the initial source order.
  const orderedCandidates = sharedSourceQualityLoaded
    ? sortSourceCandidatesByQuality(originalCandidates)
    : originalCandidates;

  state.sourceCandidates = orderedCandidates.slice(0,10);
  state.sourceIndex = 0;
  state.currentUrl = state.sourceCandidates[0]?.url || ch.url;
  updateStreamActions();
  setCurrentTitle(ch);
  renderChannelList();
  $('playerOverlay').classList.add('hidden');
  setConnectionStatus('connecting','Bağlanıyor');
  setStatus('Yayın açılıyor…');

  const alternatives = state.sourceCandidates;
  const maxAttempts = alternatives.length;
  let attemptIndex = 0;
  let settled = false;
  const timers = new Set();
  let sourceStartedAt = 0;
  let sourceStallRecorded = false;
  let runtimeStallRecorded = false;
  let activeSourceToken = 0;

  const clearTimers = () => {
    for(const t of timers) clearTimeout(t);
    timers.clear();
  };

  const detachVideoHandlers = () => {
    video.onplaying = null;
    video.onloadedmetadata = null;
    video.onerror = null;
    video.onwaiting = null;
  };

  const cancelPlayback = () => {
    clearTimers();
    detachVideoHandlers();
    if(state.hls){
      try{ state.hls.destroy(); }catch{}
      state.hls=null;
    }
  };
  state.cancelPlayback = cancelPlayback;

  const schedule = (fn, delay) => {
    const timer = setTimeout(() => {
      timers.delete(timer);
      if(!isCurrentRun()) return;
      fn();
    }, delay);
    timers.add(timer);
    return timer;
  };

  const success = (url, sourceIndex) => {
    if(!isCurrentRun() || settled) return;
    settled = true;
    clearTimers();
    const latencyMs=sourceStartedAt ? performance.now()-sourceStartedAt : 0;
    recordSourceEvent(url,'success',latencyMs);
    state.sourceIndex = sourceIndex;
    state.currentUrl = url;
    state.autoStarting = false;
    updateSourceButton();
    const latencyText = latencyMs > 0 ? ` • ${(latencyMs / 1000).toFixed(1)} sn` : '';
    setConnectionStatus('online',`Bağlı • Kaynak ${sourceIndex + 1}/${maxAttempts}${latencyText}`);
    mark(ch,'ok');
    setStatus(sourceIndex ? 'Canlı • alternatif kaynak' : 'Canlı');
  };

  const failure = (detail='Yayın açılamadı') => {
    if(!isCurrentRun() || settled) return;
    clearTimers();
    detachVideoHandlers();

    if(alternatives[attemptIndex]?.url) {
      recordSourceEvent(alternatives[attemptIndex].url,'failure');
    }

    stopHls();

    if(attemptIndex + 1 < maxAttempts){
      attemptIndex++;
      state.sourceIndex = attemptIndex;
      updateSourceButton();
      setConnectionStatus('connecting','Yeni kaynak deneniyor');
      setStatus(`Kaynak ${attemptIndex+1}/${maxAttempts} için hazırlanıyor…`);

      schedule(() => {
        if(!isCurrentRun() || settled) return;
        trySource(alternatives[attemptIndex], attemptIndex);
      }, SOURCE_SWITCH_DELAY_MS);
      return;
    }

    settled = true;
    mark(ch,'bad');
    setConnectionStatus('error','Bağlantı yok');
    setStatus('Açılamadı');
    state.cancelPlayback = null;
    showError(`${detail}. ${maxAttempts}/${maxAttempts} kaynak denendi. Diğer kaynakları "Kaynak Listesi" düğmesiyle tekrar seçebilirsiniz.`);
  };

  const trySource = (candidate, sourceIndex) => {
    if(!isCurrentRun() || settled) return;

    clearTimers();
    detachVideoHandlers();
    clearError();

    const sourceToken=++activeSourceToken;
    sourceStartedAt=performance.now();
    sourceStallRecorded=false;
    state.sourceIndex = sourceIndex;
    state.currentUrl = candidate.url;
    updateStreamActions();
    setConnectionStatus('connecting','Bağlanıyor • '+(sourceIndex+1)+'/'+maxAttempts);
    setStatus(`Kaynak ${sourceIndex+1}/${maxAttempts} deneniyor…`);

    video.pause();
    video.removeAttribute('src');
    video.load();

    let started = false;
    let waitingAfterStart = false;

    const onPlaying = () => {
      if(!isCurrentRun() || sourceToken!==activeSourceToken) return;

      // Yayın başarıyla açıldıktan sonra da runtime buffering olaylarını
      // telemetry'ye kaydet. Böylece sadece ilk 3.5 saniyeyi değil,
      // izleme sırasındaki gerçek deneyimi de ölçeriz.
      if(settled){
        runtimeStallRecorded=false;
        setConnectionStatus('online',`Bağlı • Kaynak ${state.sourceIndex + 1}/${state.sourceCandidates.length}`);
        return;
      }

      setConnectionStatus('online','Bağlı');
      started = true;
      waitingAfterStart = false;
      setStatus(`Kaynak ${sourceIndex+1}/${maxAttempts} oynatılıyor, doğrulanıyor…`);

      schedule(() => {
        if(!isCurrentRun() || settled || sourceToken!==activeSourceToken || !started || waitingAfterStart || video.paused) {
          return;
        }
        success(candidate.url, sourceIndex);
      }, SOURCE_STABILITY_MS);
    };

    const startPlayback = () => {
      if(!isCurrentRun() || settled) return;
      const promise = video.play();
      if(!promise || typeof promise.catch !== 'function') return;
      promise.catch(err => {
        if(isCurrentRun() && state.autoStarting && err?.name === 'NotAllowedError'){
          video.muted = true;
          video.play().catch(()=>{});
        }
      });
    };

    const onLoaded = () => {
      if(!isCurrentRun() || settled || sourceToken!==activeSourceToken) return;
      setStatus(`Kaynak ${sourceIndex+1}/${maxAttempts} hazır, oynatılıyor…`);
      startPlayback();
    };

    const onVideoError = () => {
      if(!isCurrentRun() || settled || sourceToken!==activeSourceToken) return;
      if(!started) {
        failure('Video kaynağı tarayıcı tarafından reddedildi');
      } else {
        failure('Yayın başladıktan sonra durdu');
      }
    };

    const onWaiting = () => {
      if(!isCurrentRun() || sourceToken!==activeSourceToken) return;

      if(settled){
        setConnectionStatus('buffering','Tamponlanıyor');
        if(!runtimeStallRecorded){
          runtimeStallRecorded=true;
          recordSourceEvent(candidate.url,'stall');
        }
        return;
      }

      if(!started) return;

      waitingAfterStart = true;
      setConnectionStatus('buffering','Tamponlanıyor');
      if(!sourceStallRecorded){
        sourceStallRecorded=true;
        recordSourceEvent(candidate.url,'stall');
        updateSourceButton();
      }
      setStatus(`Kaynak ${sourceIndex+1}/${maxAttempts} yeniden tamponlanıyor…`);

      schedule(() => {
        if(!isCurrentRun() || settled || sourceToken!==activeSourceToken || !started || !waitingAfterStart) return;
        failure('Yayın başladıktan sonra yeterince uzun süre devam etmedi');
      }, SOURCE_STALL_GRACE_MS);
    };

    video.onplaying = onPlaying;
    video.onloadedmetadata = onLoaded;
    video.onerror = onVideoError;
    video.onwaiting = onWaiting;

    schedule(() => {
      if(!isCurrentRun() || settled || sourceToken!==activeSourceToken) return;
      if(!started) {
        failure(`Kaynak ${SOURCE_START_TIMEOUT_MS / 1000} saniye içinde oynatılmaya başlamadı`);
      }
    }, SOURCE_START_TIMEOUT_MS);

    if(video.canPlayType('application/vnd.apple.mpegurl')){
      video.src = candidate.url;
      video.load();
      startPlayback();
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

    const hlsInstance = state.hls;

    hlsInstance.loadSource(candidate.url);
    hlsInstance.attachMedia(video);

    hlsInstance.on(Hls.Events.MANIFEST_PARSED,()=>{
      if(!isCurrentRun() || settled || sourceToken!==activeSourceToken) return;
      setStatus(`Kaynak ${sourceIndex+1}/${maxAttempts} hazır, oynatılıyor…`);
      startPlayback();
    });

    hlsInstance.on(Hls.Events.ERROR,(_e,data)=>{
      if(!isCurrentRun() || settled || sourceToken!==activeSourceToken) return;
      if(data?.fatal) {
        failure(data.details || 'HLS fatal error');
      }
    });
  };

  state._switchSource = (sourceIndex) => {
    if(!isCurrentRun() || !alternatives[sourceIndex]) return;

    clearTimers();
    detachVideoHandlers();
    stopHls();
    settled = false;
    attemptIndex = sourceIndex;

    // Eski kaynağın geç gelen video event'leri yeni kaynağa karışmasın.
    video.pause();
    video.removeAttribute('src');
    video.load();

    state.sourceIndex = sourceIndex;
    state.currentUrl = alternatives[sourceIndex].url;
    updateStreamActions();
    setStatus(`Kaynak ${sourceIndex+1}/${maxAttempts} hazırlanıyor…`);

    schedule(() => {
      if(!isCurrentRun() || settled) return;
      trySource(alternatives[sourceIndex], sourceIndex);
    }, SOURCE_SWITCH_DELAY_MS);
  };

  trySource(alternatives[0],0);
}
async function loadM3UText(text,sourceName,autoPlayFirst=false){
  const channels=parseM3U(text);
  if(!channels.length)throw new Error('Geçerli #EXTINF kayıtları bulunamadı.');

  const previousName=state.current?.name||'';
  if(state.cancelPlayback) state.cancelPlayback();
  stopHls();
  video.pause();
  video.removeAttribute('src');
  video.load();
  state.current=null;
  state.currentUrl='';
  state.sourceCandidates=[];
  state.sourceIndex=-1;

  if(!sharedSourceQualityLoaded){
    await loadSharedSourceQuality();
  }

  state.autoStarting = Boolean(autoPlayFirst);
  state.channels=channels;
  state.sourceName=sourceName;
  state.showFavorites=false;
  state.activeCategory='all';

  const nowMeta=$('nowMeta');
  if(nowMeta) nowMeta.textContent=`${sourceName} • ${channels.length} kanal`;
  // Açılışta kanal listesi doğrudan tüm kanallarla doldurulsun.
  try { renderCategoryChips(); } catch(err) { console.warn('Kategori çipleri oluşturulamadı:',err); }

  state.filtered=[...state.channels];
  renderChannelList();

  const count=$('channelCount');
  if(count) count.textContent=`${state.filtered.length} / ${state.channels.length} kanal • Tüm kanallar`;

  try { updateFavoriteUi(); } catch(err) { console.warn('Favori UI güncellenemedi:',err); }

  setStatus('Hazır');

  if(autoPlayFirst && state.channels.length){
    // İlk açılışta TRT 1 başlar. Liste yenileniyorsa mümkünse daha önce
    // izlenen kanal korunur. Liste sırası değişse bile seçim isim üzerinden yapılır.
    const previousChannel = previousName
      ? state.channels.find(channel => normalizeChannelName(channel.name) === normalizeChannelName(previousName))
      : null;
    const startupChannel = previousChannel || state.channels.find(channel => normalizeChannelName(channel.name) === 'trt1')
      || state.channels.find(channel => normalizeChannelName(channel.name).includes('trt1'));
    playChannel(startupChannel || state.channels[0]);
  }
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
      await loadM3UText(
        text,
        url === DEFAULT_M3U ? 'KulakTV kaynak listesi' : 'Yerel M3U',
        true
      );
      return;
    } catch (e) {
      lastErr = e;
    }
  }
  throw new Error(`Liste yüklenemedi: ${lastErr?.message || 'bilinmeyen hata'}`);
}
function updateChannelButton(){
  const btn=$('barChannelsBtn');
  if(!btn)return;
  btn.classList.toggle('active',state.drawerOpen);
  btn.setAttribute('aria-label',state.drawerOpen?'Kanal listesini kapat':'Kanal listesini aç');
}
function openChannels(){
  if(state.epgOpen)closeEpg();
  state.drawerOpen=true;
  $('channelDrawer').classList.add('open');
  $('drawerBackdrop').classList.add('open');
  $('channelDrawer').setAttribute('aria-hidden','false');
  updateChannelButton();
  setTimeout(()=>$('search').focus({preventScroll:true}),150);
}
function closeChannels(){
  state.drawerOpen=false;
  $('channelDrawer').classList.remove('open');
  if(!state.settingsOpen)$('drawerBackdrop').classList.remove('open');
  $('channelDrawer').setAttribute('aria-hidden','true');
  updateChannelButton();
}
function openSettings(){
  if(state.epgOpen)closeEpg();
  state.settingsOpen=true;
  closeChannels();
  $('settingsDrawer').classList.add('open');
  $('settingsBackdrop').classList.add('open');
  $('settingsDrawer').setAttribute('aria-hidden','false');
}
function closeSettings(){
  state.settingsOpen=false;
  $('settingsDrawer').classList.remove('open');
  $('settingsBackdrop').classList.remove('open');
  $('settingsDrawer').setAttribute('aria-hidden','true');
}
function openEpg(){
  if(state.settingsOpen)closeSettings();
  if(state.drawerOpen)closeChannels();
  state.epgOpen=true;
  $('epgDrawer').classList.add('open');
  $('epgBackdrop').classList.add('open');
  $('epgDrawer').setAttribute('aria-hidden','false');
  renderEpgDrawer();
}
function closeEpg(){
  state.epgOpen=false;
  $('epgDrawer').classList.remove('open');
  $('epgBackdrop').classList.remove('open');
  $('epgDrawer').setAttribute('aria-hidden','true');
}
function nextChannel(dir){
  if(!state.current||!state.filtered.length)return;

  // Kanal geçişinde tvg-id/id kullanma. Birçok M3U kaynağı aynı id'yi
  // birden fazla kanala verdiği için (ör. "ext") yanlış kanala sıçrayabilir.
  // Önce gerçek obje referansını bul, bulunamazsa URL ile eşleştir.
  let i = state.filtered.findIndex(c => c === state.current);

  if(i < 0){
    i = state.filtered.findIndex(c =>
      c.url === state.current.url || c.name === state.current.name
    );
  }

  if(i < 0) i = 0;

  const next = state.filtered[(i + dir + state.filtered.length) % state.filtered.length];
  if(next) playChannel(next);
}
$('openChannels').addEventListener('click',openChannels);$('barChannelsBtn').addEventListener('click',()=>state.drawerOpen?closeChannels():openChannels());$('closeChannels').addEventListener('click',closeChannels);$('drawerBackdrop').addEventListener('click',closeChannels);$('openSettings').addEventListener('click',openSettings);$('closeSettings').addEventListener('click',closeSettings);$('settingsBackdrop').addEventListener('click',closeSettings);$('epgBtn').addEventListener('click',openEpg);$('closeEpg').addEventListener('click',closeEpg);$('epgBackdrop').addEventListener('click',closeEpg);
$('prevChannel').addEventListener('click',()=>nextChannel(-1));$('nextChannel').addEventListener('click',()=>nextChannel(1));$('playPause').addEventListener('click',()=>{
  if(video.muted){
    video.muted=false;
    video.play().catch(()=>{});
    return;
  }
  if(video.paused)video.play().catch(()=>{});else video.pause();
});
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
video.addEventListener('pause',()=>{$('playPause').textContent='▶';});video.addEventListener('playing',()=>{updateBarState();});
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
function getSourceQuality(url){
  const m=getSharedSourceQuality(url)||sourceQuality[url];
  if(!m)return {score:50,label:'Yeni'};
  const success=Number(m.successes||0);
  const failures=Number(m.failures||0);
  const stalls=Number(m.stalls||0);
  const bad=failures+stalls*1.5;
  let score=((success+3)/(success+bad+6))*100;
  const lc=Number(m.latencyCount||0);
  if(lc){
    const avg=Number(m.latencySum||0)/lc;
    if(avg<3000)score+=5;
    else if(avg>10000)score-=10;
  }
  score=Math.max(0,Math.min(100,Math.round(score)));
  return {score,label:score>=85?'Çok iyi':score>=70?'İyi':score>=50?'Orta':'Zayıf'};
}
function recordSourceEvent(url,type,latencyMs=0){
  if(!url)return;
  const m=sourceQuality[url]||(sourceQuality[url]={successes:0,failures:0,stalls:0,latencySum:0,latencyCount:0});
  if(type==='success')m.successes++;
  if(type==='failure')m.failures++;
  if(type==='stall')m.stalls++;
  if(type==='success'&&latencyMs>0){m.latencySum+=latencyMs;m.latencyCount++;}
  m.lastChecked=Date.now();
  saveSourceQuality();

  queuePlaybackTelemetry(type,url,{
    latencyMs,
    sourceIndex:state.sourceIndex,
    detail:type==='failure'
      ? (state.current ? 'Kaynak oynatılamadı veya stabil başlayamadı' : 'Yayın açılamadı')
      : type==='stall'
        ? 'Yayın başladıktan sonra yeniden tamponlandı'
        : 'Kaynak stabil oynatmaya ulaştı'
  });
}
function updateSourceButton(){
  const btn=$('changeSourceBtn');
  const qualityEl=$('sourceQuality');
  if(!btn)return;
  const total=state.sourceCandidates.length;
  btn.disabled=total<2;
  btn.classList.toggle('source-switching',total>=2);
  const current=state.sourceCandidates[state.sourceIndex];
  const q=current?getSourceQuality(current.url):{score:50,label:'Yeni'};
  if(qualityEl){
    qualityEl.textContent=q.label;
    qualityEl.className='source-quality '+normalizeSearchText(q.label).replace(/[^a-z0-9]+/g,'-');
    qualityEl.title=`Kaynak kalite puanı: ${q.score}/100`;
  }
  const label=btn.querySelector('span');
  if(total>=2){
    const next=(state.sourceIndex+1)%total;
    btn.title=`Sonraki kaynak: ${next+1}/${total} • mevcut: ${q.label} ${q.score}/100`;
    btn.setAttribute('aria-label',`Kaynak değiştir, sonraki kaynak ${next+1}/${total}`);
    if(label)label.textContent=`Kaynak ${state.sourceIndex+1}/${total}`;
  }else{
    btn.title='Bu kanal için başka kaynak yok';
    btn.setAttribute('aria-label','Bu kanal için başka kaynak yok');
    if(label)label.textContent='Kaynak';
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
loadUpdateStatus();loadHistory();loadEpg();loadDefault().catch(e=>{setStatus('Liste yüklenemedi');showError(`Başlangıç listesi yüklenemedi: ${e.message}`);});

window.addEventListener('online',()=>{if(state.current)setConnectionStatus('connecting','Bağlantı geri geldi');});
window.addEventListener('offline',()=>setConnectionStatus('error','İnternet yok'));

// Initial UI state
updateFavoriteUi();
renderSourceTrustList();
