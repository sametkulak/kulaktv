
# KulakTV

KulakTV, Türkiye'deki televizyon kanallarını canlı izlemek için hazırlanmış statik **M3U / M3U8 / HLS web player** projesidir.

Frontend **GitHub Pages** üzerinde çalışır. Kanal listesi, yayın sağlık kontrolü, kaynak kalite puanlama ve EPG güncellemeleri **GitHub Actions** üzerinden yürütülür. İsteğe bağlı site erişimi, kullanıcı yönetimi, oturum takibi ve player telemetry ise ayrı bir **Cloudflare Worker + D1** servisi üzerinden çalışır.

> Sistem, public HLS/M3U yayın uçlarına bağlıdır. Bu nedenle tek tek yayınların sürekliliği garanti edilemez; KulakTV'nin amacı bozuk kaynakları mümkün olduğunca erken tespit edip daha iyi alternatifleri öne çıkarmaktır.

**Son sistem incelemesi:** 2 Kasım 2026

---

## 1. Genel mimari

~~~text
                         ┌─────────────────────────┐
                         │       GitHub Repo       │
                         │     sametkulak/kulaktv  │
                         └────────────┬────────────┘
                                      │
                   ┌──────────────────┼──────────────────┐
                   │                  │                  │
                   ▼                  ▼                  ▼
          GitHub Pages         GitHub Actions      GitHub Actions
             Frontend          Günlük veri akışı    Kod / smoke test
                   │                  │
                   │                  ├── M3U kaynaklarını indir
                   │                  ├── Kanal filtrele / birleştir
                   │                  ├── HLS health-check
                   │                  ├── Kaynak kalite puanı
                   │                  ├── Player telemetry harmanla
                   │                  ├── EPG güncelle
                   │                  └── Watchdog / guardrail
                   │
                   ▼
          ┌─────────────────────────────────────────┐
          │ index.html / app.js / auth.js / CSS    │
          │ HLS.js + native HLS + PWA               │
          └───────────────┬─────────────────────────┘
                          │ HTTPS
             ┌────────────┴────────────┐
             ▼                         ▼
   Public HLS/M3U yayınları     Cloudflare Worker
                                  │
                                  ▼
                               D1 Database
                         ├── users
                         ├── sessions
                         ├── login_history
                         ├── settings
                         └── telemetry aggregation
~~~

GitHub Pages yalnızca statik frontend'i servis eder. Worker tarafındaki kimlik doğrulama ve telemetry servisi repodan bağımsızdır.

---

## 2. Oynatıcı

### Temel özellikler

- Hazır Türkiye kanal listesi
- Kanal arama
- Favoriler
- Harici M3U URL'si yükleme
- Yerel .m3u, .m3u8, .txt açma
- HLS.js ile Chromium tabanlı tarayıcılar ve Firefox
- Safari / iOS için native HLS
- Özel oynatıcı kontrol çubuğu
- Önceki / sonraki kanal
- Kaynak değiştirme
- Kaynak bağlantı durumu
- Tam ekran
- Media Session API
- TV Rehberi / EPG
- Mobil ve masaüstü uyumlu arayüz
- PWA olarak kurulabilme
- Service Worker uygulama kabuğu önbellekleme

### Kanal açılış akışı

Bir kanal seçildiğinde oynatıcı aşağıdaki yolu izler:

1. Kanalın ana URL'si, M3U içindeki yedek URL'leri ve aynı isimdeki alternatif kanal kayıtları toplanır.
2. HTTPS sayfada HTTP medya adresleri filtrelenir.
3. Ortak source-quality.json verisi hazırsa adaylar kaliteye göre sıralanır.
4. En fazla **10 aday** oynatıcı tarafında tutulur.
5. Yayın sunucusu için preconnect / dns-prefetch başlatılır.
6. HLS.js manifesti yüklenir.
7. İlk görüntünün mümkün olduğunca erken gelmesi için başlangıç ayarları uygulanır.
8. İlk playing olayı geldiğinde kullanıcı arayüzü hemen canlı duruma geçirilir.
9. Stabilite kontrolü ve telemetry arka planda devam eder.
10. Kaynak gerçekten açılamazsa sıradaki aday otomatik denenir.

Eski sürümdeki gibi görüntünün kullanıcıya gösterilmesi için ek bir stabilite bekleme süresi yoktur. Stabilite kontrolü yalnızca kalite/fallback kararını etkiler.

---

## 3. Açılış performansı

KulakTV'de açılış hızı için kaynak kalitesini düşürmeden başlangıç süresi hedeflenir.

### Ortak performans optimizasyonları

- source-quality.json kanal açılışını bloklamadan arka planda yüklenir.
- İlk playing geldiği anda loader kapatılır.
- Kaynak sunucusu için kanal seçimiyle birlikte preconnect başlatılır.
- HLS.js startFragPrefetch kullanır.
- Canlı manifest için initialLiveManifestSize=1 kullanılır.
- HLS düşük gecikme modu lowLatencyMode açıktır.
- İlk segmentin hızlı gelmesi için başlangıç kalite seviyesi özellikle mobilde düşük seviyeden başlatılır.
- Mobilde çözünürlük oyuncu alanının gerçek boyutuna göre sınırlandırılır.
- Mobilde buffer boyutu masaüstüne göre daha düşük tutulur.
- preload=auto ile video öğesinin ağ hazırlığı erkenden başlatılır.
- jsDelivr ve upstream kaynaklar için bağlantı hazırlığı kullanılır.
- Service Worker cache sürümü değiştiğinde eski player kabuğu temizlenir.

### HLS başlangıç ayarları

Genel:

~~~text
enableWorker: true
lowLatencyMode: true
initialLiveManifestSize: 1
startFragPrefetch: true
backBufferLength: 30
maxBufferLength: 20
manifestLoadingTimeOut: 10000
fragLoadingTimeOut: 10000
~~~

Mobil:

~~~text
startLevel: 0
capLevelToPlayerSize: true
ignoreDevicePixelRatio: true
backBufferLength: 15
maxBufferLength: 12
maxBufferSize: 24 MB
~~~

Bu ayarlar ilk görüntüyü hızlandırmayı hedefler. Yayının gerçek bitrate'i ve ilk segmentin CDN tarafından hazırlanma süresi yine upstream kaynağa bağlıdır.

---

## 4. Kaynak yönetimi

KulakTV tek bir M3U kaynağına güvenmez. Güncel kaynak seti script içinde tanımlı **7 public kaynaktan** oluşur:

~~~text
1. OnurEröz Türkiye
2. ByteFix Repairs
3. iptv-org Türkiye
4. discevisita
5. iptv-turk-tr
6. qazim/IPTV
7. dearbulut Türkiye
~~~

Kaynaklar zamanla değişebilir. Bu nedenle README'deki liste yalnızca mevcut yapı hakkında referanstır; gerçek kaynak URL'leri scripts/update_channels.py içindedir.

### Kaynak birleştirme

Aynı kanal birden fazla kaynakta bulunuyorsa:

- Kanal adı normalize edilir.
- İlk uygun URL ana kaynak olarak tutulur.
- Diğer URL'ler Yedek1, Yedek2, ... şeklinde saklanır.
- Oynatıcı alternatifleri otomatik deneyebilir.
- Aynı kanal için farklı M3U kayıtlarından gelen URL'ler tek kanal altında birleştirilir.

Kalite değerlendirmesi için kanal başına en fazla **12 aday** test edilir; son playlist'e en iyi **10 aday** yazılır.

### Kaynak filtreleme

Özellikle dearbulut Türkiye gibi geniş listelerden gelen içeriklerde Türk TV'ye ait olmayan kayıtlar ayrıca filtrelenir.

Eliminasyon örnekleri:

~~~text
Radio / Radyo
Podcast / Audio
Webcam / Camera / IP Cam
Adult / XXX / Porn
Bazı yabancı veya hedef dışı yayın kategorileri
~~~

Filtre sonucu update-status.json içinde metadata olarak tutulur ve watchdog tarafından kontrol edilir.

---

## 5. Yayın sağlık kontrolü

Günlük kanal pipeline'ı yalnızca M3U dosyasının indirilebilmesine bakmaz.

Bir HLS kaynağının başarılı kabul edilmesi için:

~~~text
1. Manifest HTTP olarak alınabilmeli
2. Manifest geçerli #EXTM3U olmalı
3. Gerekli child playlist'ler takip edilebilmeli
4. En az bir medya segmenti gerçekten alınabilmeli
~~~

Kontrol ayarlarında:

~~~text
Health check timeout : 12 sn
Worker sayısı        : 12
Maksimum kontrol URL  : 900
Manifest derinliği   : 2
~~~

Segment kontrolü için küçük veri parçaları okunur. Range desteklemeyen sunucular için normal GET ile ikinci deneme yapılır.

### Kaynak kaldırma politikası

Bir URL tek seferlik hata verdi diye hemen listeden atılmaz.

Mevcut sistemde:

~~~text
2 ardışık başarısızlık → kaldırma adayı
~~~

ve aşağıdaki global korumalar uygulanır:

~~~text
Minimum kaynak başarı oranı : %60
Minimum kanal retention     : %55
Maksimum kanal büyümesi     : 2.0x
Global minimum health oranı : %20
~~~

Ana kanalların varlığı ayrıca kontrol edilir:

~~~text
ATV
KANAL D
STAR TV
TRT 1
SHOW TV
NOW
TV8
~~~

Aşırı bozulmuş bir upstream kaynak, mevcut sağlam listeyi körlemesine ezemez.

---

## 6. Kaynak kalite puanlama

source-quality.json iki sinyali birleştirir:

~~~text
Server health
      +
Gerçek kullanıcı oynatma telemetry
      ↓
Final source score
~~~

### Server health score

Temel skor geçmiş sağlık kontrollerinden hesaplanır:

~~~text
((successes + 4) / (successes + failures + 8)) × 100
~~~

Ayrıca:

- tekrar deneme ile kurtarılan yayınlara ceza uygulanır,
- son durum ok ise bonus,
- son durum bad ise ceza uygulanır.

### Player score

Gerçek tarayıcı oynatmalarından:

~~~text
successes
failures
stalls
latency
~~~

kullanılır.

Stall olayları başarısızlıktan daha hafif ağırlıkla değerlendirilir. Ortalama açılma süresi çok iyiyse bonus, çok kötüyse ceza uygulanır.

### Player telemetry ağırlığı

Gerçek kullanıcı verisi doğrudan server-health skorunun yerine geçmez.

Player verisinin ağırlığı:

~~~text
minimum : %10
maksimum : %35
~~~

Aradaki değer olay sayısına göre kademeli artar.

Böylece birkaç kullanıcının deneyimi tek başına geçmiş server-health skorunu anında tersine çeviremez.

source-quality.json içinde buna bağlı olarak şu alanlar bulunabilir:

~~~text
healthScore
playerScore
playerEvents
playerSuccesses
playerFailures
playerStalls
playerWeight
score
label
~~~

### Oynatıcı kaynak seçimi

Kanal açılırken adaylar öncelikle:

~~~text
Kalite verisi bulunanlar
↓
Son health durumu OK olanlar
↓
Daha yüksek score
↓
Daha fazla geçmiş kontrolü
↓
Orijinal M3U sırası
~~~

mantığıyla sıralanır.

---

## 7. Player telemetry

Player telemetry aktif olarak **Cloudflare Worker** üzerinden çalışır.

Akış:

~~~text
Tarayıcı
   │
   ├── success
   ├── failure
   ├── stall
   └── latencyMs
        │
        ▼
Cloudflare Worker
POST /api/telemetry
        │
        ▼
Toplu kaynak istatistikleri
        │
        ▼
GET /api/telemetry/quality
        │
        ▼
GitHub Actions
scripts/update_channels.py
        │
        ▼
source-quality.json
~~~

İstemcinin gönderdiği uygulama payload'ı:

~~~text
type
url
channel
latencyMs
~~~

Frontend tarafında ham cihaz kimliği, kullanıcı şifresi veya GitHub token'ı telemetry payload'ına eklenmez.

### Telemetry gönderim davranışı

- Olaylar küçük batch'ler halinde gönderilir.
- Varsayılan flush eşiği: 6 olay
- Periyodik flush: 15 saniye
- Maksimum batch: 12 olay
- Sayfa kapanırken/gizlenirken keepalive ile gönderim denenir.
- Worker erişilemezse telemetry geçici olarak localStorage kuyruğunda tutulabilir.

Eski GitHub Issue tabanlı telemetry sistemi artık kullanılmamaktadır.

---

## 8. EPG

EPG üretimi scripts/update_epg.py ile yapılır.

Öncelikli kaynak:

~~~text
Türksat
~~~

Gerekli durumlarda XMLTV kaynaklarına fallback uygulanır.

Kullanılan referans kaynaklar arasında:

~~~text
https://www.turksatkablo.com.tr/
https://iptv-org.github.io/epg/
https://dearbulut.github.io/iptv/epg/guide.xml.gz
https://epg.tvcdn.net/guide/tr-guide.xml
~~~

### EPG işleme

- Kanal adı normalize edilir.
- Alias eşleştirme yapılır.
- Geçmişe ve geleceğe ait belirli zaman penceresi korunur.
- Kanal başına program sınırı uygulanır.
- Birden fazla EPG kaynağından veri birleştirilebilir.
- EPG aşırı küçülürse guardrail devreye girer.
- Son geçerli EPG korunabilir.

Çıktılar:

~~~text
epg.json
epg-status.json
~~~

---

## 9. Kullanıcı, oturum ve admin sistemi

Site erişimi isteğe bağlı olarak merkezi Worker üzerinden kontrol edilir.

Yönetim panelinden:

- Giriş zorunluluğu açılıp kapatılabilir.
- Kullanıcı eklenebilir.
- Kullanıcı silinebilir.
- Kullanıcı aktif/pasif yapılabilir.
- Rol user / admin olarak yönetilebilir.
- Şifre değiştirilebilir.
- Kullanıcının aktif oturumları kapatılabilir.
- Giriş / çıkış geçmişi görüntülenebilir.
- Çevrimiçi kullanıcı sayısı görülebilir.

### Oturum sistemi

Frontend, Cloudflare Worker ile session doğrular ve giriş yapmış kullanıcı için heartbeat gönderir.

Mevcut davranış:

~~~text
Heartbeat aralığı : yaklaşık 30 sn
Çevrimiçi eşiği   : yaklaşık 90 sn
~~~

Tarayıcı kapatıldığında güvenilir bir çıkış olayı beklenmediği için gerçek çevrimiçi durum heartbeat + timeout mantığıyla belirlenir.

### Auth API

~~~text
POST /api/login
POST /api/logout
GET  /api/session
POST /api/session/heartbeat

GET  /api/settings
PUT  /api/settings

GET    /api/admin/users
POST   /api/admin/users
PUT    /api/admin/users/:id
DELETE /api/admin/users/:id

POST /api/admin/users/:id/logout-all
GET  /api/admin/login-history
~~~

Cloudflare Worker:

~~~text
https://kulaktv-auth.sametkulak96.workers.dev
~~~

Worker kodu şu anda bu repository içinde tutulmamaktadır.

---

## 10. PWA ve cache

KulakTV PWA olarak kurulabilir.

Desteklenen kullanım:

- Chrome / Edge masaüstü
- Android ana ekran
- iPhone / iPad Safari → **Paylaş → Ana Ekrana Ekle**
- Standalone görünüm

Service Worker:

~~~text
Uygulama kabuğu: cache
Dinamik M3U: network
Dinamik JSON: network
M3U8: network
~~~

channels.m3u, EPG, source-quality ve benzeri dinamik veriler eski cache ile sabitlenmez.

Frontend sürümü değiştiğinde Service Worker cache adı da sürümlendirilir.

---

## 11. GitHub Actions

Repository'deki ana otomasyonlar:

### update-channels.yml

Ana veri pipeline'ıdır.

Sıra:

~~~text
1. Repository checkout
2. Kod doğrulama
3. M3U mevcut yapı kontrolü
4. scripts/update_channels.py
5. scripts/update_epg.py
6. automation_watchdog.py
7. JSON çıktı kontrolleri
8. Değişiklik varsa git commit + push
~~~

Günlük çalıştırma için repository'nin GitHub schedule backend'ine güvenilmemektedir. Mevcut tasarımda günlük tetikleme **cron-job.org → workflow_dispatch** üzerinden yapılır.

Aynı workflow:

~~~text
workflow_dispatch
push (update_channels.py değişirse)
~~~

ile de çalışabilir.

### update-epg.yml

EPG'yi manuel yenilemek için kullanılır.

~~~text
workflow_dispatch
push (update_epg.py değişirse)
~~~

### code-quality.yml

Kod doğrulamalarını yapar:

- Python syntax
- JavaScript syntax
- DOM id referansları
- duplicate DOM id kontrolü
- statik güvenlik kontrolleri
- GitHub token benzeri secret taraması
- JSON yapı kontrolleri
- M3U yapı kontrolü

Kontrol edilen ana dosyalar:

~~~text
app.js
auth.js
telemetry-config.js
scripts/update_channels.py
scripts/update_epg.py
channels.m3u
epg.json
source-quality.json
update-history.json
~~~

### automation-watchdog.yml

Manuel çalıştırılabilen bağımsız pipeline denetleyicisidir.

Kontrol ettiği başlıklar:

~~~text
Kanal verisi güncelliği
Kaynak oranı
Health oranı
Ana kanallar
Türk TV filtre metadata'sı
EPG güncelliği
EPG kanal/program sayıları
Source-quality
Update history
~~~

### live-smoke-test.yml

GitHub runner üzerinden gerçek dış bağlantı testi yapar.

Kontroller:

~~~text
GitHub Pages ana sayfası
TRT 1 HLS
NOW TV HLS
DREAM TÜRK HLS
~~~

Test yalnızca manifesti değil, manifestten sonraki ilk child playlist / medya segmentini de kontrol eder.

Çıktının sonunda:

~~~text
LIVE SMOKE TEST: PASS
~~~

görülmesi beklenir.

### GitHub Pages deployment

Pages deployment GitHub tarafından yönetilen sistem workflow'u üzerinden yapılır. Repository'nin kendi kaynak akışlarından ayrı olarak Pages çıktısını yayınlar.

---

## 12. Üretilen veri dosyaları

| Dosya | Amaç |
|---|---|
| channels.m3u | Frontend'in kullandığı birleşik kanal listesi |
| source-quality.json | Server health + player telemetry kaynak kalite verisi |
| health-state.json | URL sağlık geçmişi ve kaldırma durumu |
| update-status.json | Son kanal pipeline özeti |
| update-history.json | Güncelleme geçmişi |
| epg.json | Frontend EPG verisi |
| epg-status.json | Son EPG işlem durumu |
| telemetry-config.js | Player telemetry Worker ayarları |
| manifest.json | PWA manifesti |
| sw.js | Service Worker |
| auth.js | Merkezi auth/session/admin entegrasyonu |
| app.js | Player, kanal yönetimi, telemetry ve ana frontend mantığı |
| index.html | Ana kullanıcı arayüzü |
| style.css | Görsel tasarım |

---

## 13. Proje dosya yapısı

~~~text
kulaktv/
├── index.html
├── app.js
├── auth.js
├── style.css
├── manifest.json
├── sw.js
├── telemetry-config.js
│
├── channels.m3u
├── epg.json
├── epg-status.json
├── source-quality.json
├── health-state.json
├── update-status.json
├── update-history.json
│
├── logo.png
├── favicon.svg
├── .nojekyll
├── _headers
│
├── .github/
│   └── workflows/
│       ├── automation-watchdog.yml
│       ├── code-quality.yml
│       ├── live-smoke-test.yml
│       ├── update-channels.yml
│       └── update-epg.yml
│
├── scripts/
│   ├── automation_watchdog.py
│   ├── update_channels.py
│   └── update_epg.py
│
├── PROJECT_NOTES.md
└── README.md
~~~

---

## 14. Yerel test

file:// yerine HTTP sunucusu kullanılması önerilir.

Python ile:

~~~bash
python -m http.server 8080
~~~

Sonra:

~~~text
http://localhost:8080
~~~

adresinden açılabilir.

JavaScript sözdizimi:

~~~bash
node --check app.js
node --check auth.js
node --check telemetry-config.js
~~~

Python sözdizimi:

~~~bash
python -m py_compile scripts/update_channels.py scripts/update_epg.py
~~~

---

## 15. Harici M3U kullanımı

Harici bir M3U listesinin tarayıcı tarafından fetch() ile okunabilmesi için kaynak sunucusunun CORS izinleri uygun olmalıdır.

CORS yoksa:

- M3U dosyası indirilebilir ve yerel olarak yüklenebilir.
- CORS destekleyen başka bir liste kullanılabilir.

Aynı durum bazı HLS/M3U8 yayınlarının doğrudan tarayıcıdan oynatılmasında da geçerlidir.

---

## 16. Güvenlik ve gizli bilgiler

Repository'ye kesinlikle konulmaması gerekenler:

~~~text
GitHub PAT / token
Cloudflare API token
cron-job.org credential / secret
D1 erişim sırrı
gerçek kullanıcı şifreleri
özel servis API anahtarları
~~~

telemetry-config.js içindeki Worker URL'si gizli bilgi değildir; burada token tutulmaz.

GitHub Pages frontend'i üzerinde gerçek secret saklanmamalıdır.

---

## 17. Harici servisler

| Servis | Kullanım |
|---|---|
| GitHub Pages | Statik frontend yayını |
| GitHub Actions | Kanal, EPG, health, watchdog ve kod doğrulama |
| cron-job.org | Günlük workflow dispatch tetiklemesi |
| Cloudflare Worker | Auth + session + admin + telemetry API |
| Cloudflare D1 | Kullanıcı/session/history/settings ve telemetry aggregation |
| jsDelivr | HLS.js 1.5.20 CDN |
| Public M3U kaynakları | TV kanal URL'leri |
| Public / resmi EPG kaynakları | Program bilgileri |

---

## 18. Proje notları

Harici servislerin ayrıntıları, kullanılan kaynak URL'leri ve bakım notları için [PROJECT_NOTES.md](PROJECT_NOTES.md) dosyasına bakılmalıdır.

Özellikle aşağıdaki değişikliklerde PROJECT_NOTES.md de güncellenmelidir:

- yeni harici servis eklenmesi
- servis kaldırılması
- Worker URL değişikliği
- cron/job yapısının değiştirilmesi
- EPG kaynağı değişmesi
- source pipeline mimarisinin değişmesi

---

## 19. Bilinen sınırlar

KulakTV'nin performansı yalnızca uygulama koduna bağlı değildir.

Özellikle:

- upstream yayın sunucusunun yanıt süresi,
- HLS manifest yapısı,
- ilk media segmentinin hazırlanma süresi,
- CDN yoğunluğu,
- bölgesel erişim / geo-block,
- internet bağlantısı,
- tarayıcının native HLS davranışı

ilk görüntü süresini doğrudan etkileyebilir.

Bu nedenle KulakTV'deki kaynak kalite sistemi yalnızca "URL HTTP 200 döndü mü?" sorusuna değil, mümkün olduğunca gerçek oynatma sonucuna da bakar.

---

## 20. İçerik ve kullanım sorumluluğu

Bu repository player yazılımını ve public yayın uçlarından oluşturulmuş örnek bir kanal listesini içerir.

Yayınların telif, lisans veya bölgesel kullanım şartlarına uygun şekilde izlenmesi kullanıcının sorumluluğundadır.

---

## 21. Kısa özet

KulakTV'nin mevcut çalışma modeli:

~~~text
Public M3U kaynakları
        │
        ▼
scripts/update_channels.py
        │
        ├── normalize / merge
        ├── Türk TV filtresi
        ├── HLS manifest + segment health-check
        ├── server health score
        │
        └── Cloudflare player telemetry
                   │
                   ▼
             final source score
                   │
                   ▼
             source-quality.json
                   │
                   ▼
              GitHub Pages
                   │
                   ▼
             KulakTV Player
                   │
                   ├── hızlı source preconnect
                   ├── hızlı HLS başlangıcı
                   ├── alternatif kaynak fallback
                   ├── runtime recovery
                   ├── telemetry
                   └── EPG / Media Session / PWA
~~~

KulakTV'nin temel yaklaşımı **"önce çalışan yayın, sonra mümkün olan en iyi kaynak"** şeklindedir. Sistem günlük otomasyon, sağlık kontrolü, gerçek kullanıcı geri bildirimi ve fallback mekanizmalarını birlikte kullanır.
