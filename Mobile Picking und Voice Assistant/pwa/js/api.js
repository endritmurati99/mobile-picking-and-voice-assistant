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
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
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

export function createIdempotencyKey(scope, parts = [], { unique = false } = {}) {
    const keyParts = [scope, getDeviceId(), ...parts.map(String)];
    if (unique) keyParts.push(generateUuid());
    return keyParts.join(':');
}

function getWriteHeaders(idempotencyKey) {
    const headers = getReadHeaders();
    const deviceId = getDeviceId();
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
    if (deviceId) headers['X-Device-Id'] = deviceId;
    return headers;
}

function getReadHeaders() {
    const headers = {};
    const picker = getActivePicker();
    if (picker?.id) headers['X-Picker-User-Id'] = String(picker.id);
    return headers;
}

async function request(method, path, body = null, options = {}) {
    const headers = { ...(options.headers || {}) };
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    if (body && !isFormData) {
        headers['Content-Type'] = 'application/json';
    }

    const opts = {
        method,
        headers,
        cache: options.cache || 'no-store',
        keepalive: options.keepalive || false,
        signal: options.signal,
    };

    if (body) {
        opts.body = isFormData ? body : JSON.stringify(body);
    }

    const resp = await fetch(`${API_BASE}${path}`, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new ApiError(resp.status, err.detail ?? err);
    }
    if (resp.status === 204) return null;
    return resp.json();
}

export async function getPickers(options = {}) {
    return request('GET', '/pickers', null, { signal: options.signal });
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
    return request('POST', '/voice/recognize', formData);
}

export async function assistVoice(payload, options = {}) {
    return request('POST', '/voice/assist', payload, {
        headers: getWriteHeaders(options.idempotencyKey),
        signal: options.signal,
    });
}

export async function healthCheck() {
    return request('GET', '/health');
}
