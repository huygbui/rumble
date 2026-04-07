// Thin fetch wrapper around the Laravel API. Attaches the Bearer token,
// throws on non-2xx, redirects to login on 401.

import { getToken, clearToken } from './auth.js';

const BASE = import.meta.env.VITE_LARAVEL_URL;

async function request(path, { method = 'GET', body, auth = true } = {}) {
    const headers = { 'Accept': 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth) {
        const token = getToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(BASE + path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (res.status === 401) {
        clearToken();
        if (location.pathname !== '/' && location.pathname !== '/index.html') {
            location.href = '/';
        }
        throw new Error('Unauthorized');
    }

    if (!res.ok) {
        let detail;
        try { detail = await res.json(); } catch { detail = await res.text(); }
        const err = new Error(`HTTP ${res.status}`);
        err.detail = detail;
        throw err;
    }

    if (res.status === 204) return null;
    return await res.json();
}

export const api = {
    login:   (email, password) => request('/api/login',           { method: 'POST', body: { email, password }, auth: false }),
    logout:  ()                => request('/api/logout',          { method: 'POST' }),
    me:      ()                => request('/api/me'),
    aiToken: ()                => request('/api/voice/ai-token',  { method: 'POST' }),
};
