window.KULAKTV_TELEMETRY_CONFIG = {
  // Player telemetry doğrudan güvenli Cloudflare Worker endpoint'ine gönderilir.
  // Burada gizli anahtar, token veya kullanıcı kimliği tutulmaz.
  enabled: true,
  apiBase: 'https://kulaktv-auth.sametkulak96.workers.dev',
  flushEvery: 6,
  flushIntervalMs: 15000,
  maxBatchEvents: 12
};
