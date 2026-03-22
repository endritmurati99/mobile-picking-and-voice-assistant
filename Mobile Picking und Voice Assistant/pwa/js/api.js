/**
 * Backend-API-Client.
 * Einziger Kommunikationsweg zwischen PWA und Backend.
 */
const API_BASE = '/api';

async function request(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);

    const resp = await fetch(`${API_BASE}${path}`, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
}

export async function getPickings() {
    return request('GET', '/pickings');
}

export async function getPickingDetail(id) {
    return request('GET', `/pickings/${id}`);
}

export async function confirmLine(pickingId, data) {
    return request('POST', `/pickings/${pickingId}/confirm-line`, data);
}

export async function createQualityAlert(formData) {
    // FormData für Foto-Upload — kein JSON
    const resp = await fetch(`${API_BASE}/quality-alerts`, {
        method: 'POST',
        body: formData,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

export async function recognizeVoice(audioBlob) {
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');
    const resp = await fetch(`${API_BASE}/voice/recognize`, {
        method: 'POST',
        body: formData,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

export async function healthCheck() {
    return request('GET', '/health');
}
