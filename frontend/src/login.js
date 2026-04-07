import { api } from './api.js';
import { setToken, isLoggedIn } from './auth.js';

// Already logged in? skip straight to voice.
if (isLoggedIn()) location.href = '/voice.html';

const form     = document.getElementById('loginForm');
const emailEl  = document.getElementById('email');
const passEl   = document.getElementById('password');
const submit   = document.getElementById('submitBtn');
const errorEl  = document.getElementById('error');

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorEl.textContent = '';
    submit.disabled = true;
    submit.textContent = 'Signing in…';
    try {
        const res = await api.login(emailEl.value, passEl.value);
        setToken(res.access_token);
        location.href = '/voice.html';
    } catch (err) {
        const msg = err.detail?.message
            || err.detail?.errors?.email?.[0]
            || err.message
            || 'Login failed';
        errorEl.textContent = msg;
        submit.disabled = false;
        submit.textContent = 'Sign in';
    }
});
