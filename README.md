# KulakTV

KulakTV, Türkiye'deki televizyon kanallarını canlı izlemek için hazırlanmış statik **M3U / M3U8 / HLS web player** projesidir. Site **GitHub Pages** üzerinde yayınlanır; kimlik doğrulama ve kullanıcı yönetimi ise ayrı bir **Cloudflare Worker + D1** servisi üzerinden yürütülür.

## Özellikler

### Oynatıcı
- Yerleşik Türkiye kanal listesi
- Harici M3U URL'si yükleme
- Yerel `.m3u`, `.m3u8` ve `.txt` dosyası açma
- Kanal arama ve favoriler
- HLS.js ile Chrome / Edge / Firefox oynatma
- Safari / iOS için native HLS desteği
- Özel oynatıcı kontrol çubuğu
- Kanal değiştirirken yedek kaynaklar arasında geçiş
- Yayın bağlantısı ve bağlantı durumu göstergeleri
- TV Rehberi (EPG) bilgileri
- Tam ekran desteği
- Media Session desteği
- Mobil ve masaüstü uyumlu arayüz

### Kaynak ve sağlık sistemi
- Birden fazla public M3U kaynağının birleştirilmesi
- Türk TV kanallarına yönelik filtreleme
- HLS manifesti + en az bir medya segmenti ile yayın sağlık kontrolü
- Başarılı kaynakları önce deneyen kaynak sıralaması
- Kaynak kalite puanları
- Bozulan kaynaklar için yeniden deneme ve güvenlik eşikleri
- Kanal güncelleme guardrail'leri ile toplu hatalarda listenin korunması
- Günlük kanal, kaynak ve EPG güncellemeleri
- Güncelleme geçmişi ve sistem özeti

### EPG
- Öncelikli Türksat EPG verisi
- Gerekirse XMLTV fallback
- Kanal adları için alias eşleştirme
- Güncel + sonraki gün programları
- EPG veri kaybına karşı anomaly guardrail

### Kullanıcı ve yönetim sistemi
KulakTV'nin isteğe bağlı giriş sistemi ayrı bir Cloudflare Worker + D1 servisinde tutulur.

- Kullanıcı adı / şifre ile giriş
- `admin` ve `user` rolleri
- Yönetici kullanıcı yönetimi
- Kullanıcı ekleme, silme, aktif/pasif yapma
- Şifre değiştirme
- Bir kullanıcının tüm aktif oturumlarını kapatma
- Aktif kullanıcı ve son görülme bilgisi
- Heartbeat tabanlı çevrimiçi durum
- Oturum timeout ve otomatik temizlik
- Giriş / çıkış geçmişi
- Yönetim panelinde kanal, kaynak, sağlık URL'si, EPG ve çevrimiçi kullanıcı özeti
- Birincil `admin` hesabı için özel korumalar

Kimlik doğrulama API'si GitHub Pages frontend'inden ayrı çalışır. Parolalar düz metin olarak saklanmaz; veritabanında hash'lenmiş olarak tutulur.

> Not: Bu proje küçük ve kontrollü bir kullanıcı grubu için tasarlanmıştır. Cloudflare Worker tarafındaki kimlik doğrulama servisi, GitHub Pages üzerindeki statik frontend'den ayrı tutulur.

### PWA / uygulama olarak kullanım
KulakTV bir **Progressive Web App (PWA)** olarak da kurulabilir.

- Chrome / Edge üzerinde uygulama olarak yükleme
- Masaüstüne uygulama kısayolu
- Mobil cihazlarda ana ekrana ekleme
- Standalone görünüm
- Service Worker ile temel uygulama kabuğu önbelleği
- Dinamik kanal, EPG ve durum verileri ağ üzerinden alınır

iPhone / iPad üzerinde Safari'de **Paylaş → Ana Ekrana Ekle** kullanılabilir.

## Dosya yapısı

```text
kulaktv/
├── index.html
├── app.js
├── auth.js
├── style.css
├── manifest.json
├── sw.js
├── channels.m3u
├── epg.json
├── epg-status.json
├── source-quality.json
├── health-state.json
├── update-status.json
├── update-history.json
├── telemetry-config.js
├── player-telemetry.json
├── logo.png
├── favicon.svg
├── .nojekyll
├── _headers
├── .github/workflows/
├── scripts/
└── README.md
```

## Proje notları ve harici servisler

GitHub Pages, Cloudflare Worker + D1, cron-job.org, jsDelivr ve kanal/EPG kaynaklarının ne amaçla kullanıldığını unutmamak için [PROJECT_NOTES.md](PROJECT_NOTES.md) dosyasını inceleyin. Bu dosyada hiçbir secret, token veya gerçek kullanıcı şifresi tutulmamalıdır.

## Mimari

```text
GitHub Pages
    │
    ├── index.html
    ├── app.js
    ├── auth.js
    ├── style.css
    ├── manifest.json
    └── sw.js
             │
             │ HTTPS API
             ▼
Cloudflare Worker
    │
    └── D1: kulaktv-users
         ├── users
         ├── sessions
         ├── login_history
         └── settings
```

GitHub Pages yalnızca statik web uygulamasını sunar. Kullanıcı, session ve site erişim ayarları Cloudflare tarafındaki API tarafından yönetilir.

## GitHub Pages ile yayınlama

1. Repository'yi GitHub'a yükle.
2. GitHub → **Settings → Pages** bölümüne gir.
3. **Build and deployment** altında **Deploy from a branch** seç.
4. Branch olarak `main`, klasör olarak `/(root)` seç.
5. Kaydet.
6. GitHub Pages birkaç dakika içinde siteyi yayınlar.

`.nojekyll` dosyası statik dosyaların doğrudan servis edilmesini sağlar.

## Cloudflare Auth API

Kullanıcı sistemi için ayrı bir Cloudflare Worker gerekir.

Temel API uçları:

```text
POST /api/login
POST /api/logout
GET  /api/session
POST /api/session/heartbeat

GET  /api/settings
PUT  /api/settings

GET  /api/admin/users
POST /api/admin/users
PUT  /api/admin/users/:id
DELETE /api/admin/users/:id

POST /api/admin/users/:id/logout-all
GET  /api/admin/login-history
```

D1 tarafındaki temel tablolar:

```text
users
sessions
login_history
settings
```

Worker'ın GitHub Pages üzerinde doğrudan şifre veya oturum verisi bulundurmasına gerek yoktur.

## Oturum takibi

Kullanıcı giriş yaptığında bir session kaydı oluşturulur ve istemci periyodik heartbeat gönderir. Worker, `last_seen_at` bilgisini günceller.

Yakın zamanda heartbeat göndermeyen session'lar otomatik olarak aktif kullanıcı sayımından çıkarılır. Scheduled cleanup, süresi veya heartbeat zaman aşımı dolan session'ları temizler ve uygun durumlarda login geçmişini kapatır.

Normal tarayıcı kapatmalarında tarayıcıdan güvenilir bir "çıkış yaptım" sinyali beklenmez. Bu nedenle sistem gerçek çevrimiçi durumu heartbeat + timeout mantığıyla takip eder.

## Otomatik günlük kanal güncellemesi

`scripts/update_channels.py` kanal kaynaklarını değerlendirir ve sağlıklı Türk TV kanallarını günceller. EPG ve watchdog kontrolleri de günlük otomasyon akışının parçasıdır.

Güncelleme sonucunda aşağıdaki dosyalar değişebilir:

```text
channels.m3u
health-state.json
source-quality.json
epg.json
epg-status.json
update-status.json
update-history.json
```

Günlük otomasyon için GitHub Actions akışları kullanılır; zamanlama dış scheduler üzerinden tetiklenebilir. Ayrıca GitHub'daki **Actions → KulakTV kanal listesini güncelle** akışından manuel çalıştırma yapılabilir.

Kaynak başarı oranı, kanal sayısı ve ana kanalların korunması için guardrail kontrolleri bulunur. Aşırı bozulmuş bir upstream kaynağın tüm listeyi silmesine izin verilmez.

> Not: GitHub Actions runner'larının bulunduğu coğrafya bazı bölgesel yayınları yanıltıcı şekilde başarısız gösterebilir. Bu nedenle player tarafındaki gerçek tarayıcı oynatımı ayrıca önemlidir.

## Yerleşik kanal listesi

`channels.m3u`, başlangıç olarak public yayın uçlarından oluşturulmuş Türkiye kanal listesidir. Yayıncılar URL'lerini değiştirebildiği için tek tek yayınların sürekliliği garanti edilemez.

Türkiye kanal listesi oluşturma sürecinde iptv-org Türkiye akışı referans alınabilir:

`https://iptv-org.github.io/iptv/countries/tr.m3u`

Ana proje:

`https://github.com/iptv-org/iptv`

## EPG

EPG tarafında öncelik resmi Türksat verilerindedir. Mevcut ve sonraki gün için program verileri hazırlanır; kanal alias'larıyla eşleşme yapılır ve hatalı derecede küçülen EPG çıktıları guardrail ile durdurulur.

## Yerel test

`file://` yerine HTTP sunucusu kullanılması tavsiye edilir:

```bash
python -m http.server 8080
```

Sonra:

```text
http://localhost:8080
```

## Harici M3U URL'si

Harici bir M3U listesini tarayıcıdaki `fetch()` ile okuyabilmek için kaynak sunucusunun CORS izni vermesi gerekir.

CORS kapalıysa:
- M3U dosyasını indirip yerel olarak açabilirsin.
- CORS destekleyen başka bir kaynak kullanabilirsin.

Aynı durum bazı canlı HLS/M3U8 yayınlarında da geçerlidir.

## Telemetry

Player telemetry şu an **devre dışıdır**.

Public frontend içine GitHub yazma yetkisi veya hassas token bırakılmadığı için eski Issue tabanlı telemetry yaklaşımı kullanılmaz. `telemetry-config.js` içinde aktif bir yazma token'ı bulunmamalıdır.

## Lisans / içerik sorumluluğu

Bu repository player yazılımını ve public yayın uçlarından oluşturulmuş örnek bir kanal listesini içerir. Telifli veya abonelik gerektiren yayınların izinsiz yeniden dağıtımından kullanıcı sorumludur.
