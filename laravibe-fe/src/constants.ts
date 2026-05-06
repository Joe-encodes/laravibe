export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
// Session token — set by LoginView after /api/auth/login exchange. NEVER hardcoded.
export const getSessionToken = (): string | null => localStorage.getItem('laravibe_session_token');
// Legacy compat alias — use getSessionToken() for new code
export const MASTER_REPAIR_TOKEN = getSessionToken() ?? '';

export const INITIAL_PHP_CODE = ``;
