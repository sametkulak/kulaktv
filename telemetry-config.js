window.KULAKTV_TELEMETRY_CONFIG = {
  // GitHub Pages tarafında doğrudan çalışan model.
  // Aşağıdaki token, yalnızca bu public repo için "Issues: Read and write"
  // yetkili fine-grained GitHub token olmalıdır.
  enabled: true,
  githubToken: 'PASTE_FINE_GRAINED_TOKEN_HERE',
  issueNumber: 1,
  flushEvery: 6,
  flushIntervalMs: 15000,
  maxBatchEvents: 12
};
