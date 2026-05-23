import { db } from "./db.js";

export function getSetting(key: string, fallback = "") {
  const row = db.prepare("SELECT value FROM app_settings WHERE key = ?").get(key) as { value: string } | undefined;
  return row?.value ?? fallback;
}

export function setSetting(key: string, value: string) {
  const now = new Date().toISOString();
  db.prepare(
    `INSERT INTO app_settings (key, value, updated_at)
     VALUES (?, ?, ?)
     ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`
  ).run(key, value, now);
}

export function isPublicVideoModeEnabled() {
  return getSetting("public_video_mode", "false") === "true";
}
