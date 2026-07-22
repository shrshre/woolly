// Anonymous session id: generated once and persisted in localStorage so every
// search from this browser shares one id for analytics attribution.

const STORAGE_KEY = "woolly_session_id";

export function getSessionId(): string {
  try {
    let id = localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  } catch {
    // localStorage unavailable (private mode, etc.) — fall back to a fresh id.
    return crypto.randomUUID();
  }
}
