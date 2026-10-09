# KulakTV - Static M3U / HLS Web Player

KulakTV, build gerektirmeyen statik bir M3U/M3U8 web player'dır. Proje doğrudan **GitHub Pages**, **Cloudflare Pages** veya herhangi bir statik web sunucusunda yayınlanabilir.

## Özellikler

- Yerleşik `channels.m3u` Türkiye listesi
- Harici M3U URL'si yükleme
- Yerel `.m3u`, `.m3u8`, `.txt` dosyası açma
- Kanal arama
- Kategori/grup filtresi
- HLS.js ile Chrome / Edge / Firefox oynatma
- Safari / iOS için native HLS desteği
- Oynatma durumu göstergesi
- Yayın URL'sini panoya kopyalama
- JavaScript / CSS build süreci yok

## Dosya yapısı

```text
kulaktv-player/
├── index.html
├── app.js
├── style.css
├── channels.m3u
├── .nojekyll
├── _headers
├── logo.png
├── source-quality.json
├── player-telemetry.json
├── telemetry-config.js
├── .github/workflows/
├── scripts/
└── README.md
```

## GitHub Pages ile yayınlama

1. GitHub'da yeni bir repository oluştur.
2. Bu klasördeki **tüm dosyaları** repository kök dizinine yükle.
3. GitHub'da `Settings → Pages` bölümüne gir.
4. `Build and deployment` altında `Deploy from a branch` seç.
5. Branch olarak `main`, klasör olarak `/ (root)` seç.
6. Kaydet.
7. GitHub birkaç dakika içinde sana `https://KULLANICI.github.io/REPO/` benzeri bir adres verir.

`.nojekyll` dosyası özellikle eklenmiştir. Böylece GitHub Pages içeriği Jekyll üzerinden dönüştürmeden doğrudan statik dosyalar olarak servis eder.

## Cloudflare Pages ile yayınlama

### GitHub bağlantısı ile

1. Projeyi GitHub repository'sine yükle.
2. Cloudflare Dashboard → `Workers & Pages` → `Create application` → `Pages` bölümüne gir.
3. GitHub repository'sini bağla.
4. Framework olarak `None` / statik yapı kullan.
5. **Build command:** boş bırak.
6. **Build output directory:** `/` veya repository kökü.
7. Deploy et.

### Direct Upload ile

Cloudflare Pages'in Direct Upload seçeneğinde proje klasörünü veya ZIP içeriğini yükleyebilirsin. Bu projede build komutu gerekmez.

## Yerel test

`file://` üzerinden açmak yerine HTTP sunucusu kullanılması tavsiye edilir:

```bash
python -m http.server 8080
```

Sonra:

```text
http://localhost:8080
```

## Harici M3U URL'si

Harici bir M3U dosyasını tarayıcıdaki `fetch()` ile okuyabilmek için kaynak sunucunun CORS izni vermesi gerekir. CORS kapalıysa:

- M3U dosyasını indirip `M3U Dosyası` ile yerel olarak açabilirsin.
- Ya da kendi sunucunda CORS destekleyen bir kaynak kullanabilirsin.

Aynı durum bazı canlı HLS/M3U8 yayınlarında da geçerlidir. Playlist açılsa bile yayın sunucusu tarayıcıdan gelen medya isteğini engelleyebilir.

## Otomatik günlük kanal güncellemesi

Projede `.github/workflows/update-channels.yml` ve `scripts/update_channels.py` bulunur. GitHub Actions her gün **06:15 Türkiye saati** civarında çalışır ve 5 public M3U kaynağını birleştirir. KulakTV'de zaten bulunan kanallar için yalnızca izin verilen/güvenilir yayın alan adlarındaki URL değişiklikleri uygulanır; kaynakta kaybolan bir kanalın son bilinen URL'si otomatik olarak silinmez. Böylece tek bir upstream hatası yüzünden listenin boşalması engellenir.

İlk yüklemeden sonra ayrıca GitHub'da `Actions → KulakTV kanal listesini güncelle` ekranından `Run workflow` ile elle çalıştırabilirsin. Güncelleme gerçekleştiğinde `channels.m3u`, `update-status.json`, `health-state.json` ve `source-quality.json` güncellenebilir. GitHub Pages ana dalı yayın kaynağı olarak kullanıyorsa bu commit siteyi de yeniden yayınlatır. GitHub Pages, bir branch'ten yayın yapacak şekilde yapılandırıldığında source branch'e yapılan değişiklikleri otomatik olarak yayınlar.

Not: GitHub Actions üzerinden yapılan HTTP kontrolü, Türkiye dışındaki GitHub runner konumu nedeniyle coğrafi kısıtlı yayınları güvenilir şekilde "çalışıyor" diye değerlendiremez. Player, kanalı gerçekten tarayıcıda açarken son durumu ayrıca gösterir.

## Yerleşik kanal listesi

`channels.m3u`, ücretsiz/herkese açık yayın uçlarından oluşturulmuş bir başlangıç listesidir. Yayın URL'leri yayıncı tarafından değiştirilebildiği için canlı yayınların sürekliliği garanti edilemez.

Kaynak olarak iptv-org Türkiye akışı referans alınmıştır:

https://iptv-org.github.io/iptv/countries/tr.m3u

Ana proje:

https://github.com/iptv-org/iptv

## Lisans / içerik sorumluluğu

Bu repository yalnızca player yazılımını ve herkese açık yayın uçlarından oluşturulmuş örnek bir M3U listesini içerir. Telifli veya abonelik gerektiren yayınların izinsiz yeniden dağıtımından kullanıcı sorumludur.


## Oynatma deneyimi ve ortak kaynak kalitesi

KulakTV tarayıcıdaki oynatma sonuçlarını (başarı, başarısızlık, buffering ve başlama gecikmesi) GitHub Issue tabanlı bir telemetry akışıyla toplar. GitHub Actions bu veriyi `player-telemetry.json` içinde biriktirir ve `source-quality.json` içindeki ortak kaynak puanına kademeli olarak dahil eder. Böylece farklı cihazlar aynı kaynak kalite sıralamasını kullanır.

Bu model GitHub Pages üzerinde çalıştığı için tarayıcıdan GitHub API'ye doğrudan yazma yetkisi gerekir. Bu amaçla `telemetry-config.js` içinde repository'ye özel bir Fine-grained token kullanılmaktadır. Bu dosya public olduğundan token gizli kabul edilmemelidir.

Kaynak oynatma tarafında HLS.js ile Chrome/Edge/Firefox, Safari tarafında native HLS desteklenir. Kanal değişimlerinde eski HLS instance'ı, timer'lar ve callback'ler iptal edilir; böylece önceki kanalın gecikmiş olaylarının yeni kanala karışması engellenir.
