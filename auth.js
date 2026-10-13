const KULAKTV_AUTH_API = 'https://kulaktv-auth.sametkulak96.workers.dev';
const AUTH_TOKEN_KEY = 'kulaktv-auth-token-v1';
const AUTH_USER_KEY = 'kulaktv-auth-user-v1';
const LEGACY_ADMIN_SESSION_KEY = 'kulaktv-admin-auth-v1';

const authState = {
  token: null,
  user: null,
  loginRequired: false
};

let resolveAuthReady;
const authReady = new Promise(resolve => { resolveAuthReady = resolve; });

function getAuthToken(){
  try{return localStorage.getItem(AUTH_TOKEN_KEY)||'';}catch{return '';}
}
function getStoredUser(){
  try{
    const raw=localStorage.getItem(AUTH_USER_KEY);
    return raw?JSON.parse(raw):null;
  }catch{return null;}
}
function saveAuth(data){
  authState.token=String(data?.token||'');
  authState.user=data?.user||null;
  try{
    if(authState.token)localStorage.setItem(AUTH_TOKEN_KEY,authState.token);
    if(authState.user)localStorage.setItem(AUTH_USER_KEY,JSON.stringify(authState.user));
  }catch{}
  if(authState.user?.role==='admin'){
    try{sessionStorage.setItem(LEGACY_ADMIN_SESSION_KEY,'1');}catch{}
  }
}
function clearAuth(){
  authState.token='';
  authState.user=null;
  try{
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
    sessionStorage.removeItem(LEGACY_ADMIN_SESSION_KEY);
  }catch{}
}

async function authApi(path, options={}){
  const headers={
    Accept:'application/json',
    ...(options.headers||{})
  };
  if(options.body!==undefined && !headers['Content-Type']){
    headers['Content-Type']='application/json';
  }
  if(authState.token){
    headers.Authorization='Bearer '+authState.token;
  }

  const res=await fetch(KULAKTV_AUTH_API+path,{
    ...options,
    headers
  });

  let data={};
  try{data=await res.json();}catch{}

  if(!res.ok){
    const error=new Error(String(data?.error||('HTTP '+res.status)));
    error.status=res.status;
    throw error;
  }

  return data;
}

async function validateStoredSession(){
  const token=getAuthToken();
  if(!token){
    authState.token='';
    authState.user=null;
    return null;
  }

  authState.token=token;
  authState.user=getStoredUser();

  try{
    const data=await authApi('/api/session');
    if(data?.authenticated && data?.user){
      authState.user=data.user;
      try{localStorage.setItem(AUTH_USER_KEY,JSON.stringify(data.user));}catch{}
      if(data.user.role==='admin'){
        try{sessionStorage.setItem(LEGACY_ADMIN_SESSION_KEY,'1');}catch{}
      }
      return data.user;
    }
  }catch{}

  clearAuth();
  return null;
}

function ensureSiteLoginModal(){
  let modal=document.getElementById('siteAuthGate');
  if(modal)return modal;

  modal=document.createElement('div');
  modal.id='siteAuthGate';
  modal.className='site-auth-gate';
  modal.hidden=true;
  modal.innerHTML=
    '<div class="site-auth-card" role="dialog" aria-modal="true" aria-labelledby="siteAuthTitle">'+
      '<div class="site-auth-logo"><span>S</span></div>'+
      '<div class="site-auth-title" id="siteAuthTitle">KulakTV</div>'+
      '<div class="site-auth-subtitle">İzlemek için giriş yap</div>'+
      '<form id="siteAuthForm" class="site-auth-form">'+
        '<label>Kullanıcı adı<input id="siteAuthUsername" type="text" autocomplete="username" required></label>'+
        '<label>Şifre<div class="site-password-wrap"><input id="siteAuthPassword" type="password" autocomplete="current-password" required><button type="button" class="site-password-toggle" id="siteAuthPasswordToggle" aria-label="Şifreyi göster" title="Şifreyi göster">◉</button></div></label>'+
        '<div id="siteAuthError" class="site-auth-error" hidden></div>'+
        '<button class="primary-btn" id="siteAuthSubmit" type="submit">Giriş yap</button>'+
      '</form>'+
    '</div>';

  document.body.prepend(modal);

  const passwordInput=modal.querySelector('#siteAuthPassword');
  const passwordToggle=modal.querySelector('#siteAuthPasswordToggle');
  passwordToggle?.addEventListener('click',()=>{
    const visible=passwordInput?.type==='text';
    if(passwordInput)passwordInput.type=visible?'password':'text';
    if(passwordToggle){
      passwordToggle.textContent=visible?'◉':'◌';
      passwordToggle.setAttribute('aria-label',visible?'Şifreyi göster':'Şifreyi gizle');
      passwordToggle.title=visible?'Şifreyi göster':'Şifreyi gizle';
    }
  });

  modal.querySelector('#siteAuthForm')?.addEventListener('submit',async event=>{
    event.preventDefault();
    const username=String(modal.querySelector('#siteAuthUsername')?.value||'').trim();
    const password=String(modal.querySelector('#siteAuthPassword')?.value||'');
    const error=modal.querySelector('#siteAuthError');
    const button=modal.querySelector('#siteAuthSubmit');

    if(error)error.hidden=true;
    if(button){
      button.disabled=true;
      button.textContent='Giriş yapılıyor…';
    }

    try{
      const data=await authApi('/api/login',{
        method:'POST',
        body:JSON.stringify({username,password})
      });
      saveAuth(data);
      modal.hidden=true;
      try{window.dispatchEvent(new CustomEvent('kulaktv-auth-changed',{detail:authState.user}));}catch{}
      resolveAuthReady({
        authenticated:true,
        user:authState.user,
        loginRequired:authState.loginRequired
      });
    }catch(err){
      if(error){
        error.textContent=err?.message||'Giriş yapılamadı.';
        error.hidden=false;
      }
    }finally{
      if(button){
        button.disabled=false;
        button.textContent='Giriş yap';
      }
    }
  });

  return modal;
}

async function initializeAuthGate(){
  const modal=ensureSiteLoginModal();

  let settings={loginRequired:false};
  try{
    settings=await authApi('/api/settings');
  }catch{
    // Worker geçici olarak erişilemiyorsa mevcut public davranışı koru.
    settings={loginRequired:false};
  }

  authState.loginRequired=Boolean(settings?.loginRequired);

  const user=await validateStoredSession();

  if(!authState.loginRequired){
    modal.hidden=true;
    resolveAuthReady({
      authenticated:Boolean(user),
      user,
      loginRequired:false
    });
    return;
  }

  if(user){
    modal.hidden=true;
    resolveAuthReady({
      authenticated:true,
      user,
      loginRequired:true
    });
    return;
  }

  modal.hidden=false;
  setTimeout(()=>modal.querySelector('#siteAuthUsername')?.focus(),50);
}

function showAdminLogin(){
  const modal=document.getElementById('adminLogin');
  if(!modal)return;
  modal.hidden=false;
  const form=document.getElementById('adminLoginForm');
  form?.reset();
  const err=document.getElementById('adminLoginError');
  if(err)err.hidden=true;
  setTimeout(()=>document.getElementById('adminUsername')?.focus(),50);
}

async function handleCentralAdminLogin(event){
  event.preventDefault();
  const username=String(document.getElementById('adminUsername')?.value||'').trim();
  const password=String(document.getElementById('adminPassword')?.value||'');
  const err=document.getElementById('adminLoginError');

  if(err)err.hidden=true;

  try{
    const data=await authApi('/api/login',{
      method:'POST',
      body:JSON.stringify({username,password})
    });

    saveAuth(data);

    if(authState.user?.role!=='admin'){
      clearAuth();
      throw new Error('Bu hesap için yönetici yetkisi yok.');
    }

    const modal=document.getElementById('adminLogin');
    if(modal)modal.hidden=true;

    try{
      sessionStorage.setItem(LEGACY_ADMIN_SESSION_KEY,'1');
    }catch{}

    if(typeof window.openSettings==='function'){
      window.openSettings();
      setTimeout(loadAdminManagement,100);
    }
  }catch(error){
    if(err){
      err.textContent=error?.message||'Hatalı kullanıcı adı veya şifre.';
      err.hidden=false;
    }
    document.getElementById('adminPassword')?.focus();
  }
}

async function requireAdminSession(){
  const user=await validateStoredSession();
  return user?.role==='admin';
}

function getAdminMessageElement(){
  return document.getElementById('adminUserManagementMessage');
}

function setAdminMessage(text,type=''){
  const el=getAdminMessageElement();
  if(!el)return;
  el.textContent=text||'';
  el.className='admin-user-message'+(type?' '+type:'');
}

function renderAdminUsers(users){
  const root=document.getElementById('adminUserList');
  if(!root)return;

  root.innerHTML='';

  if(!Array.isArray(users)||!users.length){
    root.innerHTML='<div class="mini-muted">Henüz kullanıcı bulunmuyor.</div>';
    return;
  }

  users.forEach(user=>{
    const row=document.createElement('div');
    row.className='admin-user-row';

    const identity=document.createElement('div');
    identity.className='admin-user-identity';

    const name=document.createElement('b');
    name.textContent=user.username||'-';

    const meta=document.createElement('span');
    meta.textContent=(user.active===1?'Aktif':'Pasif')+' • '+(user.role==='admin'?'Yönetici':'Kullanıcı');

    identity.append(name,meta);

    const controls=document.createElement('div');
    controls.className='admin-user-controls';

    const role=document.createElement('select');
    role.className='admin-user-select';
    role.innerHTML='<option value="user">Kullanıcı</option><option value="admin">Yönetici</option>';
    role.value=user.role==='admin'?'admin':'user';
    const isProtectedAdmin=String(user.username||'').trim().toLowerCase()==='admin';
    role.disabled=isProtectedAdmin;
    role.title=isProtectedAdmin?'admin hesabının rolü değiştirilemez':'Rol';
    role.addEventListener('change',async()=>{
      try{
        await authApi('/api/admin/users/'+Number(user.id),{
          method:'PUT',
          body:JSON.stringify({role:role.value})
        });
        setAdminMessage('Rol güncellendi.','success');
        await loadAdminManagement();
      }catch(error){
        role.value=user.role==='admin'?'admin':'user';
        setAdminMessage(error?.message||'Rol güncellenemedi.','error');
      }
    });

    const active=document.createElement('button');
    active.type='button';
    active.className='admin-user-small-btn'+(user.active===1?' active':'');
    active.textContent=user.active===1?'Aktif':'Pasif';
    const protectedAdmin=isProtectedAdmin;
    active.disabled=protectedAdmin;
    active.title=protectedAdmin?'admin hesabının durumu değiştirilemez':'Aktif / pasif';
    active.addEventListener('click',async()=>{
      try{
        await authApi('/api/admin/users/'+Number(user.id),{
          method:'PUT',
          body:JSON.stringify({active:user.active!==1})
        });
        setAdminMessage('Kullanıcı durumu güncellendi.','success');
        await loadAdminManagement();
      }catch(error){
        setAdminMessage(error?.message||'Kullanıcı durumu güncellenemedi.','error');
      }
    });

    const password=document.createElement('button');
    password.type='button';
    password.className='admin-user-small-btn';
    password.textContent='Şifre';
    const canChangeProtectedAdminPassword =
      !isProtectedAdmin ||
      String(authState.user?.username||'').trim().toLowerCase()==='admin';
    password.disabled=!canChangeProtectedAdminPassword;
    password.title=canChangeProtectedAdminPassword
      ? 'Şifre değiştir'
      : 'admin hesabının şifresini yalnızca admin kullanıcısı değiştirebilir';
    password.addEventListener('click',async()=>{
      if(password.disabled)return;
      const next=window.prompt(user.username+' için yeni şifre:');
      if(next===null)return;
      if(next.length<3){
        setAdminMessage('Şifre en az 3 karakter olmalı.','error');
        return;
      }
      try{
        await authApi('/api/admin/users/'+Number(user.id),{
          method:'PUT',
          body:JSON.stringify({password:next})
        });
        setAdminMessage('Şifre güncellendi.','success');
      }catch(error){
        setAdminMessage(error?.message||'Şifre güncellenemedi.','error');
      }
    });

    const remove=document.createElement('button');
    remove.type='button';
    remove.className='admin-user-small-btn danger';
    remove.textContent='Sil';
    remove.disabled=authState.user?.id===user.id || isProtectedAdmin;
    remove.title=authState.user?.id===user.id?'Kendi hesabını silemezsin':isProtectedAdmin?'admin hesabı silinemez':'Kullanıcıyı sil';
    remove.addEventListener('click',async()=>{
      if(remove.disabled)return;
      if(!window.confirm(user.username+' kullanıcısı silinsin mi?'))return;
      try{
        await authApi('/api/admin/users/'+Number(user.id),{method:'DELETE'});
        setAdminMessage('Kullanıcı silindi.','success');
        await loadAdminManagement();
      }catch(error){
        setAdminMessage(error?.message||'Kullanıcı silinemedi.','error');
      }
    });

    controls.append(role,active,password,remove);
    row.append(identity,controls);
    root.append(row);
  });
}

function ensureAdminManagementUi(){
  const card=document.querySelector('.admin-management-card');
  if(!card||document.getElementById('adminUserManagement'))return;

  const panel=document.createElement('div');
  panel.id='adminUserManagement';
  panel.className='admin-user-management';
  panel.innerHTML=
    '<div class="admin-subtitle">Site erişimi</div>'+
    '<label class="admin-toggle-row"><input id="loginRequiredToggle" type="checkbox"><span><b>Giriş zorunlu</b><small>Kapalıysa herkes siteyi doğrudan izleyebilir.</small></span></label>'+
    '<div id="loginRequiredState" class="admin-access-state">Kontrol ediliyor…</div>'+
    '<div class="admin-subtitle admin-users-subtitle">Kullanıcı yönetimi</div>'+
    '<form id="adminAddUserForm" class="admin-add-user-form">'+
      '<input id="newUserUsername" type="text" placeholder="Kullanıcı adı" maxlength="32" autocomplete="off" required>'+
      '<input id="newUserPassword" type="password" placeholder="Şifre" minlength="3" autocomplete="new-password" required>'+
      '<select id="newUserRole"><option value="user">Kullanıcı</option><option value="admin">Yönetici</option></select>'+
      '<button class="primary-btn" type="submit">Kullanıcı ekle</button>'+
    '</form>'+
    '<div id="adminUserManagementMessage" class="admin-user-message" aria-live="polite"></div>'+
    '<div id="adminUserList" class="admin-user-list"><div class="mini-muted">Kullanıcılar yükleniyor…</div></div>'+
    '<div class="admin-subtitle admin-users-subtitle">Giriş / çıkış geçmişi</div>'+
    '<div id="adminLoginHistory" class="admin-login-history"><div class="mini-muted">Geçmiş yükleniyor…</div></div>';

  card.append(panel);

  document.getElementById('loginRequiredToggle')?.addEventListener('change',async event=>{
    const toggle=event.currentTarget;
    toggle.disabled=true;
    try{
      const data=await authApi('/api/settings',{
        method:'PUT',
        body:JSON.stringify({loginRequired:Boolean(toggle.checked)})
      });
      authState.loginRequired=Boolean(data?.loginRequired);
      const state=document.getElementById('loginRequiredState');
      if(state)state.textContent=authState.loginRequired?'🔐 Giriş zorunlu':'🌐 Herkese açık';
      setAdminMessage(authState.loginRequired?'Site artık giriş istiyor.':'Site herkese açık.','success');
    }catch(error){
      toggle.checked=!toggle.checked;
      setAdminMessage(error?.message||'Site erişim ayarı değiştirilemedi.','error');
    }finally{
      toggle.disabled=false;
    }
  });

  document.getElementById('adminAddUserForm')?.addEventListener('submit',async event=>{
    event.preventDefault();
    const form=event.currentTarget;
    const username=String(document.getElementById('newUserUsername')?.value||'').trim();
    const password=String(document.getElementById('newUserPassword')?.value||'');
    const role=String(document.getElementById('newUserRole')?.value||'user');
    const submit=form?.querySelector('button[type="submit"]');

    if(username.length<2){
      setAdminMessage('Kullanıcı adı en az 2 karakter olmalı.','error');
      return;
    }
    if(password.length<3){
      setAdminMessage('Şifre en az 3 karakter olmalı.','error');
      return;
    }

    if(submit){submit.disabled=true;submit.textContent='Ekleniyor…';}

    try{
      await authApi('/api/admin/users',{
        method:'POST',
        body:JSON.stringify({username,password,role})
      });
      form?.reset();
      setAdminMessage('Kullanıcı eklendi.','success');
      await loadAdminManagement();
    }catch(error){
      setAdminMessage(error?.message||'Kullanıcı eklenemedi.','error');
    }finally{
      if(submit){submit.disabled=false;submit.textContent='Kullanıcı ekle';}
    }
  });
}

function formatLoginDate(value){
  const d=value?new Date(value):null;
  return d&&!Number.isNaN(d.getTime())?d.toLocaleString('tr-TR',{dateStyle:'short',timeStyle:'short'}):'-';
}

function formatDuration(loginAt,logoutAt){
  const start=new Date(loginAt||'');
  const end=logoutAt?new Date(logoutAt):new Date();
  if(Number.isNaN(start.getTime())||Number.isNaN(end.getTime())||end<start)return '';
  const total=Math.max(0,Math.round((end-start)/1000));
  const hours=Math.floor(total/3600);
  const minutes=Math.floor((total%3600)/60);
  const seconds=total%60;
  if(hours)return hours+' sa '+minutes+' dk';
  if(minutes)return minutes+' dk '+seconds+' sn';
  return seconds+' sn';
}

function renderLoginHistory(rows){
  const root=document.getElementById('adminLoginHistory');
  if(!root)return;
  if(!Array.isArray(rows)||!rows.length){
    root.innerHTML='<div class="mini-muted">Henüz giriş / çıkış kaydı yok.</div>';
    return;
  }

root.innerHTML=rows.map(item=>{
  const loginAt=item.loginAt ?? item.login_at;
  const logoutAt=item.logoutAt ?? item.logout_at;

  const open=!logoutAt;
  const status=open?'active':'closed';
  const statusText=open?'Oturum açık':'Çıkış yapıldı';
  const duration=formatDuration(loginAt,logoutAt);

  return '<div class="login-history-item">'+
    '<div class="login-history-head">'+
      '<b>'+escapeHtml(item.username||'-')+'</b>'+
      '<span class="login-history-badge '+status+'">'+statusText+'</span>'+
    '</div>'+
    '<div class="login-history-times">'+
      '<span>Giriş: '+escapeHtml(formatLoginDate(loginAt))+'</span>'+
      '<span>Çıkış: '+escapeHtml(logoutAt?formatLoginDate(logoutAt):'—')+'</span>'+
      (duration?'<span>Süre: '+escapeHtml(duration)+'</span>':'')+
    '</div>'+
  '</div>';
}).join('');
}

async function loadLoginHistory(){
  const root=document.getElementById('adminLoginHistory');
  if(!root)return;
  try{
    const data=await authApi('/api/admin/login-history?limit=50');
    renderLoginHistory(data?.sessions||[]);
  }catch(error){
    root.innerHTML='<div class="mini-muted">'+escapeHtml(error?.message||'Giriş geçmişi alınamadı.')+'</div>';
  }
}

async function loadAdminManagement(){
  if(!(await requireAdminSession()))return;
  ensureAdminManagementUi();

  try{
    const [settings,users]=await Promise.all([
      authApi('/api/settings'),
      authApi('/api/admin/users')
    ]);

    const toggle=document.getElementById('loginRequiredToggle');
    if(toggle)toggle.checked=Boolean(settings?.loginRequired);

    const state=document.getElementById('loginRequiredState');
    if(state)state.textContent=settings?.loginRequired?'🔐 Giriş zorunlu':'🌐 Herkese açık';

    renderAdminUsers(users?.users||[]);
    await loadLoginHistory();
  }catch(error){
    setAdminMessage(error?.message||'Yönetim verileri alınamadı.','error');
  }
}

async function logoutCentralAuth(){
  try{await authApi('/api/logout',{method:'POST'});}catch{}
  clearAuth();
  const gate=document.getElementById('siteAuthGate');
  if(authState.loginRequired){
    if(gate)gate.hidden=false;
    document.getElementById('siteAuthUsername')?.focus();
  }
  if(typeof window.closeSettings==='function')window.closeSettings();
}

function initCentralAuth(){
  ensureAdminManagementUi();

  document.addEventListener('click',async event=>{
    const settingsButton=event.target.closest('#openSettings');
    if(settingsButton){
      event.preventDefault();
      event.stopImmediatePropagation();

      const admin=await requireAdminSession();
      if(admin){
        try{sessionStorage.setItem(LEGACY_ADMIN_SESSION_KEY,'1');}catch{}
        if(typeof window.openSettings==='function'){
          window.openSettings();
          setTimeout(loadAdminManagement,100);
        }
      }else{
        showAdminLogin();
      }
      return;
    }

    const logout=event.target.closest('#logoutAdminBtn');
    if(logout){
      event.preventDefault();
      event.stopImmediatePropagation();
      await logoutCentralAuth();
    }
  },true);

  document.addEventListener('submit',event=>{
    if(event.target?.id==='adminLoginForm'){
      event.preventDefault();
      event.stopImmediatePropagation();
      void handleCentralAdminLogin(event);
    }
  },true);

  document.getElementById('refreshAdminBtn')?.addEventListener('click',()=>{
    void loadAdminManagement();
  });

  document.getElementById('adminLogin')?.addEventListener('click',event=>{
    if(event.target.id==='adminLogin')event.currentTarget.hidden=true;
  });
}

initializeAuthGate().finally(()=>{
  initCentralAuth();
});

window.KULAKTV_AUTH = authState;
window.KULAKTV_AUTH.ready = authReady;
window.KULAKTV_AUTH.api = authApi;
window.KULAKTV_AUTH.logout = logoutCentralAuth;
