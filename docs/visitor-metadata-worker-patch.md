# KulakTV Worker: ziyaretçi cihaz bilgileri yaması

Bu yama mevcut Worker'ın ziyaretçi oturum altyapısını genişletir. Önce `migrations/0002_visitor_metadata.sql` dosyasını bağlı D1 veritabanında **bir kez** çalıştır. Ardından aşağıdaki değişiklikleri mevcut Worker koduna uygula ve deploy et.

## 1. Yardımcı fonksiyonu ekle

`visitorHeartbeat` fonksiyonundan hemen önce ekle:

```js
function getVisitorMetadata(request, body) {
  const ua = String(request.headers.get('User-Agent') || '').slice(0, 500);
  const device = body?.device && typeof body.device === 'object' ? body.device : {};
  const cf = request.cf || {};

  let deviceType = 'Desktop';
  if (/ipad|tablet/i.test(ua)) deviceType = 'Tablet';
  else if (/mobile|iphone|ipod|android/i.test(ua)) deviceType = 'Mobile';

  let os = 'Bilinmiyor';
  if (/windows nt 10/i.test(ua)) os = 'Windows 10/11';
  else if (/windows/i.test(ua)) os = 'Windows';
  else if (/iphone|ipad|ipod/i.test(ua)) os = 'iOS/iPadOS';
  else if (/android/i.test(ua)) os = 'Android';
  else if (/mac os x|macintosh/i.test(ua)) os = 'macOS';
  else if (/linux/i.test(ua)) os = 'Linux';

  let browser = 'Bilinmiyor';
  if (/edg\//i.test(ua)) browser = 'Edge';
  else if (/opr\//i.test(ua)) browser = 'Opera';
  else if (/firefox\//i.test(ua)) browser = 'Firefox';
  else if (/chrome\//i.test(ua) && !/edg\//i.test(ua)) browser = 'Chrome';
  else if (/safari\//i.test(ua) && !/chrome\//i.test(ua)) browser = 'Safari';

  const width = Math.min(10000, Math.max(0, Number(device.screenWidth) || 0));
  const height = Math.min(10000, Math.max(0, Number(device.screenHeight) || 0));
  const language = String(device.language || '').slice(0, 20);
  const platform = String(device.platform || '').slice(0, 40);

  return {
    deviceType,
    browser,
    os,
    screenResolution: width && height ? width + 'x' + height : '',
    language,
    platform,
    standalone: device.standalone === true ? 1 : 0,
    country: String(cf.country || '').slice(0, 2),
    city: String(cf.city || '').slice(0, 80)
  };
}
```

## 2. visitorHeartbeat fonksiyonunu değiştir

Mevcut `visitorHeartbeat` fonksiyonunun tamamını bununla değiştir:

```js
async function visitorHeartbeat(request, env) {
  const origin = getOrigin(request);
  let body;
  try { body = await request.json(); }
  catch { return json({ ok: false, error: 'Geçersiz JSON.' }, 400, origin); }

  const visitorId = String(body?.visitorId || '');
  const visitId = String(body?.visitId || '');
  if (!VISITOR_ID_RE.test(visitorId) || !VISITOR_ID_RE.test(visitId)) {
    return json({ ok: false, error: 'Geçersiz ziyaretçi kimliği.' }, 400, origin);
  }

  const meta = getVisitorMetadata(request, body);
  const now = new Date().toISOString();

  await env.DB.prepare(`
    INSERT INTO visitor_sessions (
      visit_id, visitor_id, started_at, last_seen_at, ended_at,
      duration_seconds, end_reason, device_type, browser, os,
      screen_resolution, language, platform, standalone, country, city
    )
    VALUES (?, ?, ?, ?, NULL, 0, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(visit_id) DO UPDATE SET
      last_seen_at = excluded.last_seen_at,
      duration_seconds = MAX(
        visitor_sessions.duration_seconds,
        CAST((julianday(excluded.last_seen_at) - julianday(visitor_sessions.started_at)) * 86400 AS INTEGER)
      ),
      device_type = excluded.device_type,
      browser = excluded.browser,
      os = excluded.os,
      screen_resolution = excluded.screen_resolution,
      language = excluded.language,
      platform = excluded.platform,
      standalone = excluded.standalone,
      country = excluded.country,
      city = excluded.city
    WHERE visitor_sessions.visitor_id = excluded.visitor_id
      AND visitor_sessions.ended_at IS NULL
  `).bind(
    visitId, visitorId, now, now,
    meta.deviceType, meta.browser, meta.os, meta.screenResolution,
    meta.language, meta.platform, meta.standalone, meta.country, meta.city
  ).run();

  return json({ ok: true, lastSeenAt: now }, 200, origin);
}
```

## 3. combinedVisitorStats sorgusunu genişlet

Fonksiyondaki `anonymousRecent` sorgusunu şu hale getir:

```js
env.DB.prepare(`
  SELECT
    visitor_id, started_at, last_seen_at, ended_at, duration_seconds,
    device_type, browser, os, screen_resolution, language, platform,
    standalone, country, city
  FROM visitor_sessions
  WHERE julianday(started_at) >= julianday('now', ?)
  ORDER BY started_at DESC
  LIMIT 50
`).bind(modifier).all(),
```

Ardından `anonRows` map bloğundaki return objesine şu alanları ekle:

```js
deviceType: item.device_type || '',
browser: item.browser || '',
os: item.os || '',
screenResolution: item.screen_resolution || '',
language: item.language || '',
platform: item.platform || '',
standalone: Number(item.standalone || 0) === 1,
country: item.country || '',
city: item.city || '',
```

## Veri kapsamı ve gizlilik

- IP adresi uygulama veritabanına yazılmaz.
- Ülke ve şehir, Cloudflare'ın isteğe eklediği yaklaşık konum bilgisinden gelir; her istekte bulunmayabilir ve kesin adres değildir.
- Tarayıcı ve işletim sistemi User-Agent başlığından sınıflandırılır.
- Ekran boyutu, dil, platform ve PWA bilgisi tarayıcıdan gönderilir.
- Eski oturum kayıtları yeni kolonlarda boş kalır; mevcut oturum süreleri ve sayaçlar korunur.
- Detaylı ziyaret kayıtlarının mevcut 90 günlük saklama temizliği aynen devam eder.
