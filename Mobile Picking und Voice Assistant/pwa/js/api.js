/**
 * Backend-API-Client.
 * Einziger Kommunikationsweg zwischen PWA und Backend.
 */
const API_BASE = '/api';
const STORAGE_KEYS = {
    picker: 'picking-assistant-picker',
    pickerCatalog: 'picking-assistant-picker-catalog',
    deviceId: 'picking-assistant-device-id',
    preferredZone: 'picking-assistant-preferred-zone',
    highContrastEnabled: 'picking-assistant-high-contrast',
    searchQuery: 'picking-assistant-search-query',
    odooInstance: 'picking-assistant-odoo-instance',
};
let activePicker = null;

export class ApiError extends Error {
    constructor(status, detail) {
        const message = typeof detail === 'string'
            ? detail
            : detail?.message || detail?.claimed_by_name || `HTTP ${status}`;
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.detail = detail;
    }
}

function safeStorageGet(key) {
    try {
        return globalThis.localStorage?.getItem(key) ?? null;
    } catch {
        return null;
    }
}

function safeStorageSet(key, value) {
    try {
        globalThis.localStorage?.setItem(key, value);
    } catch {
        // Ignore storage issues; API calls can still proceed in grace mode.
    }
}

function safeStorageRemove(key) {
    try {
        globalThis.localStorage?.removeItem(key);
    } catch {
        // Ignore storage issues.
    }
}

function generateUuid() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    // The fallback MUST still be a syntactic UUID. `PickerSessionLoginRequest`
    // types `device_id` as `UUID`, so `1730villig-a3f2`-style ids are rejected
    // with a 422 and the login is unusable. `crypto.randomUUID` needs a secure
    // context, so this path is exactly the http:// LAN case -- the one where
    // nobody would look for a login bug.
    const bytes = new Uint8Array(16);
    if (globalThis.crypto?.getRandomValues) {
        globalThis.crypto.getRandomValues(bytes);
    } else {
        for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;  // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80;  // variant 10
    const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function normalizePicker(picker) {
    if (!picker || typeof picker !== 'object') return null;
    const id = Number(picker.id);
    const name = String(picker.name || '').trim();
    if (!Number.isInteger(id) || id <= 0 || !name) return null;
    return { id, name };
}

export function getDeviceId() {
    let deviceId = safeStorageGet(STORAGE_KEYS.deviceId);
    if (!deviceId) {
        deviceId = generateUuid();
        safeStorageSet(STORAGE_KEYS.deviceId, deviceId);
    }
    return deviceId;
}

function normalizeInstanceName(name) {
    return String(name || 'local').trim().toLowerCase() || 'local';
}

export function getActiveInstance() {
    return normalizeInstanceName(safeStorageGet(STORAGE_KEYS.odooInstance));
}

export function setActiveInstance(name) {
    const value = normalizeInstanceName(name);
    if (value === 'local') {
        safeStorageRemove(STORAGE_KEYS.odooInstance);
        return;
    }
    safeStorageSet(STORAGE_KEYS.odooInstance, value);
}

export function getActivePicker() {
    return activePicker;
}

export function setActivePicker(picker) {
    activePicker = normalizePicker(picker);
}

export function clearActivePicker() {
    activePicker = null;
}

export function clearStoredPicker() {
    safeStorageRemove(STORAGE_KEYS.picker);
}

export function getCachedPickers() {
    const raw = safeStorageGet(STORAGE_KEYS.pickerCatalog);
    if (!raw) return [];
    try {
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed.map(normalizePicker).filter(Boolean);
    } catch {
        return [];
    }
}

export function setCachedPickers(pickers) {
    const normalized = Array.isArray(pickers)
        ? pickers.map(normalizePicker).filter(Boolean)
        : [];
    safeStorageSet(STORAGE_KEYS.pickerCatalog, JSON.stringify(normalized));
}

export function getStoredPreferredZone() {
    const raw = safeStorageGet(STORAGE_KEYS.preferredZone);
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch {
        return null;
    }
}

export function setStoredPreferredZone(zone) {
    if (!zone) {
        safeStorageRemove(STORAGE_KEYS.preferredZone);
        return;
    }
    safeStorageSet(STORAGE_KEYS.preferredZone, JSON.stringify({
        key: zone.key,
        label: zone.label,
    }));
}

export function getStoredHighContrastEnabled() {
    return safeStorageGet(STORAGE_KEYS.highContrastEnabled) === 'true';
}

export function setStoredHighContrastEnabled(enabled) {
    safeStorageSet(STORAGE_KEYS.highContrastEnabled, enabled ? 'true' : 'false');
}

export function getStoredSearchQuery() {
    return safeStorageGet(STORAGE_KEYS.searchQuery) || '';
}

export function setStoredSearchQuery(value) {
    const normalized = String(value || '').trim();
    if (!normalized) {
        safeStorageRemove(STORAGE_KEYS.searchQuery);
        return;
    }
    safeStorageSet(STORAGE_KEYS.searchQuery, normalized);
}

// Das Backend-Gate (`dependencies.validate_idempotency_key`) laesst nur
// `[\x21-\x7e]{1,128}` durch: sichtbares ASCII, KEIN Leerzeichen, hoechstens
// 128 Zeichen. Ein roh zusammengefuegter Schluessel verletzt das, sobald
// Freitext hineingeht -- "Artikel beschädigt" scheitert am Leerzeichen UND am
// `ä`, ein Dateiname treibt die Laenge ueber 128. Der Schluessel MUSS den
// Freitext aber enthalten: zwei Meldungen mit verschiedener Beschreibung sind
// verschiedene Anfragen, und ein gemeinsamer Schluessel liesse die zweite als
// Wiederholung der ersten durchfallen.
const IDEMPOTENCY_KEY_MAX = 128;

function encodeKeyPart(value) {
    // Prozentkodierung liefert per Definition nur sichtbares ASCII.
    return encodeURIComponent(String(value));
}

function foldKeyParts(text) {
    // FNV-1a auf zwei 32-Bit-Bahnen mit verschiedenen Mischkonstanten, also
    // 64 Bit Ergebnis. Deterministisch -- das ist die eine Eigenschaft, die
    // ein Idempotenzschluessel braucht; ein Zufallswert waere hier falsch.
    let a = 0x811c9dc5;
    let b = 0xcbf29ce4;
    for (let i = 0; i < text.length; i += 1) {
        const c = text.charCodeAt(i);
        a = Math.imul(a ^ c, 0x01000193) >>> 0;
        b = Math.imul(b ^ c, 0x85ebca6b) >>> 0;
    }
    return a.toString(16).padStart(8, '0') + b.toString(16).padStart(8, '0');
}

export function createIdempotencyKey(scope, parts = [], { unique = false } = {}) {
    const safeScope = encodeKeyPart(scope);
    const keyParts = [safeScope, getDeviceId(), ...parts.map(encodeKeyPart)];
    if (unique) keyParts.push(generateUuid());
    const key = keyParts.join(':');
    if (key.length <= IDEMPOTENCY_KEY_MAX) return key;
    // Praefix bleibt lesbar (Scope + Geraet, zusammen unter 60 Zeichen), der
    // variable Rest wird gefaltet. Ergebnis immer <= 76 Zeichen.
    return `${safeScope}:${getDeviceId()}:${foldKeyParts(key)}`;
}

const CSRF_STORAGE_KEY = 'picking-assistant-csrf';

export function getCsrfToken() {
    try {
        return globalThis.sessionStorage?.getItem(CSRF_STORAGE_KEY) ?? null;
    } catch {
        return null;
    }
}

export function setCsrfToken(token) {
    try {
        if (token) {
            globalThis.sessionStorage?.setItem(CSRF_STORAGE_KEY, token);
        } else {
            globalThis.sessionStorage?.removeItem(CSRF_STORAGE_KEY);
        }
    } catch {
        // Session remains server-authoritative when storage is unavailable.
    }
}

function clearSessionClientState() {
    setCsrfToken(null);
    clearActivePicker();
}

// Die PWA sendet KEINE Identitaetsheader mehr. `X-Picker-User-Id`,
// `X-Device-Id` und `X-Odoo-Instance` waren der Legacy-Pfad
// (`resolve_legacy_header_identity`), den das Backend nur noch im Grace-Mode
// liest -- also nie in production. Das Session-Cookie ist die einzige
// Identitaet, `getDeviceId()` reist ausschliesslich im Login-Body mit.
// Ein Client, der beides schickt, verdeckt genau den Fall, den man testen
// will: er sieht funktionsfaehig aus, solange der Grace-Mode an ist, und
// faellt beim Umschalten auf production um.
function getReadHeaders() {
    return {};
}

function getWriteHeaders(idempotencyKey) {
    const headers = {};
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
    const csrfToken = getCsrfToken();
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
    return headers;
}

async function request(method, path, body = null, options = {}) {
    const headers = { ...(options.headers || {}) };
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    if (body && !isFormData) headers['Content-Type'] = 'application/json';

    const opts = {
        method,
        headers,
        credentials: 'same-origin',
        cache: options.cache || 'no-store',
        keepalive: options.keepalive || false,
        signal: options.signal,
    };
    if (body) opts.body = isFormData ? body : JSON.stringify(body);

    const resp = await fetch(`${API_BASE}${path}`, opts);
    if (!resp.ok) {
        if (resp.status === 401) clearSessionClientState();
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new ApiError(resp.status, err.detail ?? err);
    }
    if (resp.status === 204) return null;
    return resp.json();
}

export async function loginPickerSession({ login, password, odoo_instance }, options = {}) {
    const result = await request('POST', '/auth/picker-session', {
        login,
        password,
        device_id: getDeviceId(),
        odoo_instance: normalizeInstanceName(odoo_instance),
    }, { signal: options.signal });
    setCsrfToken(result.csrf_token);
    setActivePicker({
        id: result.principal.picker_user_id,
        name: result.principal.picker_name,
    });
    setActiveInstance(result.principal.odoo_instance);
    return result;
}

export async function getCurrentSession(options = {}) {
    const principal = await request('GET', '/auth/me', null, {
        signal: options.signal,
    });
    setActivePicker({
        id: principal.picker_user_id,
        name: principal.picker_name,
    });
    setActiveInstance(principal.odoo_instance);
    return principal;
}

export async function rotateCsrfToken(options = {}) {
    const result = await request('POST', '/auth/csrf', null, {
        signal: options.signal,
    });
    setCsrfToken(result.csrf_token);
    return result.csrf_token;
}

export async function logoutPickerSession(options = {}) {
    try {
        return await request('POST', '/auth/logout', null, {
            headers: getWriteHeaders(),
            keepalive: options.keepalive || false,
            signal: options.signal,
        });
    } finally {
        clearSessionClientState();
    }
}

export async function getPickers(options = {}) {
    return request('GET', '/pickers', null, { signal: options.signal });
}

export async function getAuthInstances(options = {}) {
    // `/api/auth/instances` is on the pre-auth allowlist; `/api/instances` is a
    // development-only router that `create_app` does not even include in
    // production. The login screen must use this one -- it is the only instance
    // list a client without a session can read.
    return request('GET', '/auth/instances', null, { signal: options.signal });
}

export async function getInstances(options = {}) {
    return request('GET', '/instances', null, { signal: options.signal });
}

export async function getTraceabilityDemo(options = {}) {
    return request('GET', '/demo/traceability', null, {
        headers: getReadHeaders(),
        signal: options.signal,
    });
}

export async function setTraceabilityDemoMode(mode, options = {}) {
    return request('POST', '/demo/traceability', { mode }, {
        headers: getWriteHeaders(options.idempotencyKey),
        signal: options.signal,
    });
}

export async function getPickings(options = {}) {
    return request('GET', '/pickings', null, {
        headers: getReadHeaders(),
        signal: options.signal,
    });
}

export async function getPickingDetail(id, options = {}) {
    return request('GET', `/pickings/${id}`, null, {
        headers: getReadHeaders(),
        signal: options.signal,
    });
}

export async function claimPicking(pickingId, options = {}) {
    return request('POST', `/pickings/${pickingId}/claim`, null, {
        headers: getWriteHeaders(options.idempotencyKey),
        signal: options.signal,
    });
}

export async function heartbeatPicking(pickingId, options = {}) {
    return request('POST', `/pickings/${pickingId}/heartbeat`, null, {
        headers: getWriteHeaders(options.idempotencyKey),
        signal: options.signal,
    });
}

export async function releasePicking(pickingId, options = {}) {
    return request('POST', `/pickings/${pickingId}/release`, null, {
        headers: getWriteHeaders(options.idempotencyKey),
        keepalive: options.keepalive || false,
        signal: options.signal,
    });
}

export async function confirmLine(pickingId, data, options = {}) {
    return request('POST', `/pickings/${pickingId}/confirm-line`, data, {
        headers: getWriteHeaders(options.idempotencyKey),
        signal: options.signal,
    });
}

export async function getLineStock(pickingId, productId, locationId, options = {}) {
    const params = new URLSearchParams({
        product_id: String(productId),
        location_id: String(locationId),
    });
    return request('GET', `/pickings/${pickingId}/stock?${params.toString()}`, null, {
        headers: getReadHeaders(),
        signal: options.signal,
    });
}

export async function requestReplenishment(pickingId, data, options = {}) {
    return request('POST', `/pickings/${pickingId}/replenishment-request`, data, {
        headers: getWriteHeaders(options.idempotencyKey),
        signal: options.signal,
    });
}

export async function createQualityAlert(formData, options = {}) {
    return request('POST', '/quality-alerts', formData, {
        headers: getWriteHeaders(options.idempotencyKey),
        signal: options.signal,
    });
}

export async function recognizeVoice(audioBlob, options = {}) {
    // Derive a correct file extension from the blob's MIME type so the
    // server (ffmpeg/Whisper) can detect the container reliably.
    // iOS sends audio/mp4 - if we send it as .webm ffmpeg may mis-parse it.
    const ext = audioBlob.type.includes('mp4') ? 'mp4'
              : audioBlob.type.includes('ogg')  ? 'ogg'
              : 'webm';
    const formData = new FormData();
    formData.append('audio', audioBlob, `recording.${ext}`);
    if (options.context) formData.append('context', options.context);
    if (options.surface) formData.append('surface', options.surface);
    if (typeof options.remaining_line_count === 'number') {
        formData.append('remaining_line_count', String(options.remaining_line_count));
    }
    if (typeof options.active_line_present === 'boolean') {
        formData.append('active_line_present', options.active_line_present ? 'true' : 'false');
    }
    // Task 16: the app-wide gate now demands session + Origin/CSRF on every
    // mutating browser route. This POST used to send no headers at all and
    // would get a 403. `/api/voice/recognize` is idempotency-exempt
    // (`route_policy.IDEMPOTENCY_EXEMPT_ROUTES` -- pure transcription, no
    // business write), so no key is passed.
    return request('POST', '/voice/recognize', formData, {
        headers: getWriteHeaders(),
        signal: options.signal,
    });
}

export async function assistVoice(payload, options = {}) {
    return request('POST', '/voice/assist', payload, {
        headers: getWriteHeaders(options.idempotencyKey),
        signal: options.signal,
    });
}

// --- Cluster-/Batch-Picking ---------------------------------------------

export async function getClusterSuggestions(options = {}) {
    return request('GET', '/cluster/suggestions', null, {
        headers: getReadHeaders(), signal: options.signal });
}

export async function createBatch(pickingIds, options = {}) {
    return request('POST', '/cluster/batches', { picking_ids: pickingIds }, {
        headers: getWriteHeaders(options.idempotencyKey), signal: options.signal });
}

export async function getBatch(batchId, options = {}) {
    return request('GET', `/cluster/batches/${batchId}`, null, {
        headers: getReadHeaders(), signal: options.signal });
}

export async function confirmClusterLine(batchId, data, options = {}) {
    return request('POST', `/cluster/batches/${batchId}/confirm-line`, data, {
        headers: getWriteHeaders(options.idempotencyKey), signal: options.signal });
}

export async function validateBatch(batchId, options = {}) {
    return request('POST', `/cluster/batches/${batchId}/validate`, null, {
        headers: getWriteHeaders(options.idempotencyKey), signal: options.signal });
}

export async function healthCheck() {
    // `/api/health` does not exist -- `health.py` defines `/health/live` only,
    // and that is the path on the pre-auth allowlist. `/api/health` was a 404
    // that every caller read as "backend down".
    return request('GET', '/health/live');
}
