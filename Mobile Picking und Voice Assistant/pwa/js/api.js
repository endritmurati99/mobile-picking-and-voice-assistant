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
    // Derive a correct file extension from the blob's MIME type so the
    // server (ffmpeg/Whisper) can detect the container reliably.
    // iOS sends audio/mp4 — if we send it as .webm ffmpeg may mis-parse it.
    const ext = audioBlob.type.includes('mp4') ? 'mp4'
              : audioBlob.type.includes('ogg')  ? 'ogg'
              : 'webm';
    const formData = new FormData();
    formData.append('audio', audioBlob, `recording.${ext}`);
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
