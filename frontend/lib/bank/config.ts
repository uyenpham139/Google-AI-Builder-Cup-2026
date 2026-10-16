export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? API_URL.replace(/^http/, 'ws');

// Channel the bank portal subscribes to for Echo enforcement events.
export const GUARD_CHANNEL = 'bank-portal';
