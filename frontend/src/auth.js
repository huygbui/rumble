// Tiny auth helper. The Passport access token lives in localStorage and is
// attached as a Bearer header to every Laravel call.

const KEY = 'access_token';

export function setToken(token) {
    localStorage.setItem(KEY, token);
}

export function getToken() {
    return localStorage.getItem(KEY);
}

export function clearToken() {
    localStorage.removeItem(KEY);
}

export function isLoggedIn() {
    return !!getToken();
}

export function requireLogin() {
    if (!isLoggedIn()) {
        window.location.href = '/';
    }
}
