# KulakTV Proje Notları ve Harici Servisler

Bu dosya, proje ileride devralındığında veya aylar sonra yeniden açıldığında "hangi servis ne işe yarıyordu?" sorusunun cevabını kaybetmemek için tutulur.

## Yayın ve frontend

### GitHub Pages
- Ana frontend burada yayınlanır.
- Repository: `sametkulak/kulaktv`
- `main` branch statik siteyi besler.
- Frontend tarafında gizli anahtar, GitHub PAT veya D1 erişim bilgisi tutulmamalıdır.

### jsDelivr
- `index.html` içinde HLS.js dış CDN üzerinden yüklenir.
- Kullanılan paket: HLS.js 1.5.20.
- CDN adresi:
  `https://cdn.jsdelivr.net/npm/hls.js@1.5.20/dist/hls.min.js`
- HLS.js sürümü değiştirilecekse kontrollü şekilde güncellenmeli ve oynatma testleri yapılmalıdır.

## Kimlik doğrulama ve kullanıcı sistemi

### Cloudflare Workers
- Worker adı: `kulaktv-auth`
- API adresi:
  `https://kulaktv-auth.sametkulak96.workers.dev`
- Kullanıcı girişleri, session'lar ve admin API'leri burada çalışır.
- Worker kodu şu an GitHub repository'sinde tutulmuyor; Cloudflare dashboard üzerinden yönetiliyor.
- Worker'da kullanılan hassas değerler README veya bu dosyaya yazılmamalıdır.

### Cloudflare D1
- Veritabanı: `kulaktv-users`
- Temel tablolar:
  - `users`
  - `sessions`
  - `login_history`
  - `settings`
- D1 doğrudan frontend'e açılmaz. Erişim Worker üzerinden yapılır.

### Oturum takibi
- Frontend yaklaşık 30 saniyede bir heartbeat gönderir.
- Worker `sessions.last_seen_at` alanını günceller.
- Yaklaşık 90 saniyeden uzun süre heartbeat gelmeyen session timeout kabul edilir.
- Cloudflare Worker Cron Trigger her dakika `cleanupSessions()` çalıştırır.
- Normal çıkış, timeout ve admin tarafından kapatma login geçmişinde ayrı nedenlerle tutulur.

## Günlük otomasyon ve dış zamanlayıcı

### cron-job.org
- GitHub Actions'ın yerleşik schedule tetikleyicisi bu repository için güvenilir çalışmadığı için günlük kanal/EPG güncellemesi dış scheduler üzerinden tetiklenir.
- cron-job.org, GitHub Actions workflow'unun `workflow_dispatch` tetikleyicisini çağırmak için kullanılır.
- Günlük kanal + EPG + watchdog akışı:
  `.github/workflows/update-channels.yml`
- Zamanlama cron-job.org panelinde yönetilir. Buradaki dokümana yalnızca mantık yazılır; gerçek schedule ve credential değerleri repoya konulmamalıdır.
- GitHub Actions içindeki `schedule:` satırını yeniden eklemeden önce gerçekten çalıştığı doğrulanmalıdır.

### GitHub Actions
- `update-channels.yml`: kanal listesi, sağlık kontrolü, EPG ve watchdog akışını tek günlük pipeline içinde yürütür.
- `update-epg.yml`: EPG'yi gerektiğinde manuel olarak yenilemek için ayrıca bulunur.
- `player-telemetry.yml`: eski telemetry iş akışını içerir; frontend telemetry şu anda kapalıdır.
- Veri güncelleme sırasında guardrail'ler çalışır; toplu bozulma durumunda güvenli liste korunur.

## Kanal kaynakları

`scripts/update_channels.py` çeşitli public M3U kaynaklarını değerlendirir, Türk TV kanallarını filtreler ve sağlık kontrolünden geçirir. Kaynak listesi değiştirilebilir; script içindeki URL'ler bunun teknik kaynağıdır.

Başlıca referanslar:
- iptv-org Türkiye: `https://iptv-org.github.io/iptv/countries/tr.m3u`
- dearbulut Türkiye: `https://dearbulut.github.io/iptv/playlists/language/tur.m3u`
- tv-logo logo deposu: `https://github.com/tv-logo/tv-logos`

Kaynaklardan gelen her şeyi olduğu gibi almıyoruz; filtre, doğrulama, Türk TV seçimi ve yayın sağlık kontrolü uygulanır.

## EPG kaynakları

`scripts/update_epg.py` tarafında öncelik Türksat verilerindedir. Gerekirse XMLTV kaynaklarına fallback yapılır.

Önemli kaynaklar:
- Türksat Kablo yayın akışı / EPG: `https://www.turksatkablo.com.tr/`
- iptv-org EPG: `https://iptv-org.github.io/epg/`
- dearbulut EPG: `https://dearbulut.github.io/iptv/epg/guide.xml.gz`
- tvcdn EPG: `https://epg.tvcdn.net/guide/tr-guide.xml`

EPG tarafında alias eşleştirme ve anomaly guardrail vardır. Kaynaklardan biri bozulduğunda tüm EPG'nin körlemesine silinmesine izin verilmemelidir.

## Neler repoda tutulmamalı?

- GitHub PAT / access token
- Cloudflare API token
- cron-job.org API anahtarı veya webhook secret
- Kullanıcıların gerçek şifreleri
- D1 erişim sırrı
- Herhangi bir özel servis credential'ı

Bu bilgiler gerekiyorsa platformun secret/config alanlarında tutulmalıdır.

## Bakım notu

Yeni bir harici servis eklenirse bu dosyaya:
1. servis adı,
2. ne için kullanıldığı,
3. ilgili URL,
4. hangi dosya/akış tarafından kullanıldığı
eklenmelidir.

Servis kaldırılırsa bu dosyadan da silinmelidir.

> Amaç: Proje sahibi gelecekte "Bu cron nereden geliyordu, Cloudflare neden vardı, EPG hangi siteden çekiliyordu?" diye arkeolojik kazı yapmak zorunda kalmasın.
