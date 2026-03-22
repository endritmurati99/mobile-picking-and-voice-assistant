/**
 * Picking Assistant — Haupt-App-Logik
 *
 * Flow:
 *   1. Start → Picking-Liste laden
 *   2. Picking auswählen → Move-Lines anzeigen
 *   3. HID-Scan oder Touch-Bestätigung pro Zeile
 *   4. TTS-Feedback nach jeder Aktion
 *   5. Optional: Voice-Kommandos (PTT) + Quality-Alert-Formular
 */
import { getPickings, getPickingDetail, confirmLine, createQualityAlert, recognizeVoice } from './api.js';
import { setState, getState, subscribe, renderPickCard, renderLoading, renderError, showToast } from './ui.js';
import { initHIDScanner, showManualInput, openCameraScanner } from './scanner.js';
import { speak, stopSpeaking, captureAndRecognize, isVoiceSupported, toggleVoiceMode, isVoiceModeActive } from './voice.js';
import { startCamera, capturePhoto, stopCamera, createFileInput } from './camera.js';
import { initPWA } from './pwa.js';

// ── Hilfsfunktion: Lagerort für TTS lesbar machen ────────────
// "WH/Stock/Lager Links/L-E1-P1" → "Lager Links, E 1, P 1"
function formatLocationForSpeech(locationPath) {
    if (!locationPath) return '';
    const parts = locationPath.split('/');
    // Letzten zwei relevanten Teile nehmen (z.B. "Lager Links" + "L-E1-P1")
    const relevant = parts.slice(-2).join(', ');
    // Bindestriche durch Leerzeichen ersetzen, Großbuchstaben mit Leerzeichen trennen
    return relevant.replace(/-/g, ' ').replace(/([A-Z])(\d)/g, '$1 $2');
}

// ── DOM-Referenzen ────────────────────────────────────────────
const mainEl = () => document.getElementById('main');
const statusEl = () => document.getElementById('status-indicator');
const btnVoice = () => document.getElementById('btn-voice');
const btnScan = () => document.getElementById('btn-scan');
const btnAlert = () => document.getElementById('btn-alert');

// ── Toolbar-Steuerung ────────────────────────────────────────
// Zeigt/versteckt die Nav-Buttons je nach aktuellem View.
// 'detail' → alle sichtbar, sonst alle versteckt.
function updateToolbar(view) {
    const buttons = [btnVoice(), btnScan(), btnAlert()];
    const show = view === 'detail';
    buttons.forEach(b => { if (b) b.classList.toggle('hidden', !show); });
}

// ── Picking-Liste ────────────────────────────────────────────

async function loadPickingList() {
    stopSpeaking();
    updateToolbar('list');
    mainEl().innerHTML = renderLoading();
    try {
        const pickings = await getPickings();
        setState({ pickings, currentPicking: null, currentLineIndex: 0 });

        if (!pickings.length) {
            mainEl().innerHTML = '<p style="padding:20px;color:var(--text-muted)">Keine offenen Aufträge.</p>';
            return;
        }

        mainEl().innerHTML = `<div class="pick-list-grid">${pickings.map(p => {
            const date = p.scheduled_date
                ? new Date(p.scheduled_date).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
                : '';
            const partner = p.partner_id ? p.partner_id[1] : '—';
            const typeName = p.picking_type_id ? p.picking_type_id[1] : '';
            return `
            <div class="pick-list-card" data-id="${p.id}">
                <div class="plc-header">
                    <span class="plc-name">${p.name}</span>
                    ${typeName ? `<span class="plc-badge">${typeName}</span>` : ''}
                </div>
                <div class="plc-partner">${partner}</div>
                ${date ? `<div class="plc-date">📅 ${date}</div>` : ''}
            </div>`;
        }).join('')}</div>`;

        mainEl().querySelectorAll('.pick-list-card[data-id]').forEach(card => {
            card.addEventListener('click', () => loadPickingDetail(Number(card.dataset.id)));
        });
    } catch (e) {
        mainEl().innerHTML = renderError('Verbindung fehlgeschlagen: ' + e.message);
        statusEl().textContent = 'Offline';
        statusEl().className = 'status offline';
    }
}

// ── Picking-Detail ────────────────────────────────────────────

async function loadPickingDetail(pickingId) {
    mainEl().innerHTML = renderLoading();
    try {
        const picking = await getPickingDetail(pickingId);
        if (picking.error) {
            mainEl().innerHTML = renderError(picking.error);
            return;
        }

        setState({ currentPicking: picking, currentLineIndex: 0 });
        renderCurrentLine();

        // TTS: ersten Schritt ansagen
        const lines = picking.move_lines || [];
        if (lines.length > 0) {
            const l = lines[0];
            speak(`Gehe zu ${formatLocationForSpeech(l.location_src)}. Artikel: ${l.product_name}. Menge: ${l.quantity_demand}`);
        }
    } catch (e) {
        mainEl().innerHTML = renderError('Fehler beim Laden: ' + e.message);
    }
}

// ── Aktuelle Move-Line anzeigen ───────────────────────────────

function renderCurrentLine() {
    const { currentPicking, currentLineIndex } = getState();
    if (!currentPicking) return;
    updateToolbar('detail');

    const lines = currentPicking.move_lines || [];
    if (currentLineIndex >= lines.length) {
        updateToolbar('complete');
        mainEl().innerHTML = `
            <div style="padding:20px;text-align:center">
                <div style="font-size:2rem;margin-bottom:12px">✅</div>
                <div style="font-size:1.1rem;font-weight:600">${currentPicking.name}</div>
                <div style="color:var(--text-muted);margin-top:8px">Alle Artikel erfasst.</div>
                <button onclick="window._app.loadPickingList()"
                        style="margin-top:20px;padding:12px 24px;background:var(--accent);color:#000;border:none;border-radius:8px;font-size:1rem;font-weight:600">
                    Zurück zur Liste
                </button>
            </div>`;
        return;
    }

    const line = lines[currentLineIndex];
    const progress = `${currentLineIndex + 1} / ${lines.length}`;

    mainEl().innerHTML = `
        <div style="padding:12px">
            <div style="color:var(--text-muted);font-size:0.85rem;margin-bottom:12px">
                ${currentPicking.name} · ${progress}
                <span style="float:right">
                    <button onclick="window._app.loadPickingList()"
                            style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:0.85rem">← Liste</button>
                </span>
            </div>
            ${renderPickCard({
                ...line,
                quantity_demand: line.quantity_demand,
            })}
            <div id="scan-input-area" style="margin-top:12px"></div>
        </div>`;

    // Touch-Bestätigung via Button (renderPickCard erstellt .btn-confirm)
    const btnConfirm = mainEl().querySelector('.btn-confirm');
    if (btnConfirm) {
        btnConfirm.addEventListener('click', () => handleScan(line.product_barcode || ''));
    }

    // Manuelle Barcode-Eingabe als Fallback
    const scanArea = document.getElementById('scan-input-area');
    if (scanArea) {
        const manualInput = showManualInput((barcode) => handleScan(barcode));
        scanArea.appendChild(manualInput);
    }
}

// ── Scan-Handler ──────────────────────────────────────────────

async function handleScan(barcode) {
    const { currentPicking, currentLineIndex } = getState();
    if (!currentPicking) return;

    const lines = currentPicking.move_lines || [];
    if (currentLineIndex >= lines.length) return;

    const line = lines[currentLineIndex];

    // Prüfe Barcode (leer = Touch-Bestätigung ohne Scan)
    if (barcode && line.product_barcode && barcode !== line.product_barcode) {
        speak(`Falscher Artikel. Erwartet: ${line.product_name}`);
        showToast('Falscher Barcode', 'error');
        return;
    }

    try {
        const result = await confirmLine(currentPicking.id, {
            move_line_id: line.id,
            scanned_barcode: barcode || line.product_barcode || '',
            quantity: line.quantity_demand,
        });

        if (!result.success) {
            speak(result.message || 'Fehler beim Bestätigen.');
            showToast(result.message || 'Fehler', 'error');
            return;
        }

        showToast(result.message, 'success');

        if (result.picking_complete) {
            speak('Auftrag abgeschlossen.');
            setState({ currentLineIndex: lines.length }); // zeigt Abschluss-Ansicht
            renderCurrentLine();
        } else {
            const nextIdx = currentLineIndex + 1;
            setState({ currentLineIndex: nextIdx });
            renderCurrentLine();

            if (nextIdx < lines.length) {
                const next = lines[nextIdx];
                speak(`Nächster Artikel. Gehe zu ${formatLocationForSpeech(next.location_src)}. ${next.product_name}. Menge: ${next.quantity_demand}`);
            }
        }
    } catch (e) {
        showToast('Verbindungsfehler', 'error');
        speak('Verbindungsfehler. Bitte erneut versuchen.');
    }
}

// ── Voice-Toggle-Modus ───────────────────────────────────────

function onVoiceToggle() {
    if (!isVoiceSupported()) {
        showToast('Mikrofon nicht verfügbar', 'warning');
        return;
    }

    toggleVoiceMode(handleVoiceIntent, (active) => {
        const btn = btnVoice();
        if (!btn) return;
        if (active) {
            btn.style.background = 'var(--danger)';
            btn.setAttribute('aria-label', 'Sprachmodus beenden');
            showToast('Sprachmodus aktiv — sprich ein Kommando', 'info');
        } else {
            btn.style.background = '';
            btn.setAttribute('aria-label', 'Sprachmodus starten');
            showToast('Sprachmodus beendet', 'info');
        }
    });
}

async function handleVoiceIntent(result) {
    if (!result || result.intent === 'error') return;

    // Visuelles Feedback: was wurde erkannt
    if (result.text) {
        showToast(`"${result.text}"`, 'info');
    }

    const { currentPicking, currentLineIndex } = getState();
    const lines = currentPicking?.move_lines || [];
    const line = lines[currentLineIndex];

    switch (result.intent) {
        case 'confirm':
            if (line) await handleScan(line.product_barcode || '');
            break;
        case 'next':
            if (line) setState({ currentLineIndex: currentLineIndex + 1 });
            renderCurrentLine();
            break;
        case 'previous':
            if (currentLineIndex > 0) setState({ currentLineIndex: currentLineIndex - 1 });
            renderCurrentLine();
            break;
        case 'repeat':
            if (line) speak(`${formatLocationForSpeech(line.location_src)}. ${line.product_name}. Menge: ${line.quantity_demand}`);
            break;
        case 'problem':
            openQualityAlertForm();
            break;
        case 'done':
            if (currentPicking) speak('Auftrag wird abgeschlossen.');
            break;
        case 'help':
            speak('Verfügbare Kommandos: bestätigen, weiter, zurück, wiederholen, Problem, fertig.');
            break;
        default:
            // Text wurde schon als Toast angezeigt
            break;
    }
}

// ── Quality-Alert-Formular ────────────────────────────────────

function openQualityAlertForm() {
    stopSpeaking();
    updateToolbar('alert');
    const { currentPicking, currentLineIndex } = getState();
    const lines = currentPicking?.move_lines || [];
    const line = lines[currentLineIndex];

    mainEl().innerHTML = `
        <div style="padding:16px">
            <h2 style="margin-bottom:16px;font-size:1rem">Problem melden</h2>
            <label for="qa-description" style="display:block;margin-bottom:4px;font-size:0.85rem;color:var(--text-muted)">Beschreibung</label>
            <textarea id="qa-description" placeholder="Beschreibung des Problems..."
                style="width:100%;height:80px;padding:8px;border-radius:8px;background:var(--surface);color:var(--text-primary);border:1px solid #444;font-size:1rem"></textarea>
            <div style="margin-top:8px">
                <label for="qa-priority" style="font-size:0.85rem;color:var(--text-muted)">Priorität</label>
                <select id="qa-priority" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;background:var(--surface);color:var(--text-primary);border:1px solid #444">
                    <option value="0">Normal</option>
                    <option value="2">Hoch</option>
                    <option value="3">Kritisch</option>
                </select>
            </div>
            <div style="margin-top:12px" id="photo-area"></div>
            <div style="margin-top:16px;display:flex;gap:8px">
                <button id="qa-submit" style="flex:1;padding:14px;background:var(--accent);color:#000;border:none;border-radius:8px;font-weight:600;font-size:1rem">Absenden</button>
                <button id="qa-cancel" style="padding:14px 20px;background:var(--surface);color:var(--text-primary);border:1px solid #444;border-radius:8px;font-size:1rem">Abbrechen</button>
            </div>
        </div>`;

    // Foto-Input mit Vorschau
    const photoArea = document.getElementById('photo-area');
    let photoFiles = [];

    const fileInput = createFileInput((files) => {
        photoFiles = photoFiles.concat(files);
        renderPhotoPreview();
        showToast(`${files.length} Foto${files.length > 1 ? 's' : ''} hinzugefügt`, 'success');
    });

    const photoBtn = document.createElement('button');
    photoBtn.type = 'button';
    photoBtn.textContent = '📷 Fotos hinzufügen';
    photoBtn.setAttribute('aria-label', 'Fotos hinzufügen');
    photoBtn.style.cssText = 'width:100%;padding:10px;background:var(--surface);color:var(--text-primary);border:1px solid #444;border-radius:8px;font-size:0.95rem';
    photoBtn.addEventListener('click', () => fileInput.click());

    const previewGrid = document.createElement('div');
    previewGrid.id = 'photo-preview-grid';
    previewGrid.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;';

    function renderPhotoPreview() {
        previewGrid.innerHTML = '';
        photoFiles.forEach((file, idx) => {
            const url = URL.createObjectURL(file);
            const wrapper = document.createElement('div');
            wrapper.style.cssText = 'position:relative;width:80px;height:80px;';

            const img = document.createElement('img');
            img.src = url;
            img.style.cssText = 'width:80px;height:80px;object-fit:cover;border-radius:6px;border:1px solid #444;';

            const del = document.createElement('button');
            del.type = 'button';
            del.textContent = '✕';
            del.setAttribute('aria-label', `Foto ${idx + 1} entfernen`);
            del.style.cssText = 'position:absolute;top:2px;right:2px;background:rgba(0,0,0,0.6);color:#fff;border:none;border-radius:50%;width:20px;height:20px;font-size:0.7rem;cursor:pointer;padding:0;line-height:20px;';
            del.addEventListener('click', () => {
                photoFiles.splice(idx, 1);
                renderPhotoPreview();
            });

            wrapper.appendChild(img);
            wrapper.appendChild(del);
            previewGrid.appendChild(wrapper);
        });
    }

    photoArea.appendChild(fileInput);
    photoArea.appendChild(photoBtn);
    photoArea.appendChild(previewGrid);

    document.getElementById('qa-cancel').addEventListener('click', () => {
        if (currentPicking) loadPickingDetail(currentPicking.id);
        else loadPickingList();
    });

    const submitBtn = document.getElementById('qa-submit');
    submitBtn.addEventListener('click', async () => {
        const description = document.getElementById('qa-description').value.trim();
        if (!description) { showToast('Bitte Beschreibung eingeben', 'warning'); return; }

        // Doppelklick-Schutz
        submitBtn.disabled = true;
        submitBtn.textContent = 'Wird gesendet…';

        const priority = document.getElementById('qa-priority').value;
        const formData = new FormData();
        formData.append('description', description);
        formData.append('priority', priority);
        if (currentPicking) formData.append('picking_id', String(currentPicking.id));
        if (line?.product_id) formData.append('product_id', String(line.product_id));
        photoFiles.forEach(f => formData.append('photos', f));

        try {
            const result = await createQualityAlert(formData);
            speak('Problem gemeldet. Vielen Dank.');
            showToast(`Alert ${result.name} erstellt`, 'success');
            if (currentPicking) loadPickingDetail(currentPicking.id);
            else loadPickingList();
        } catch (e) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Absenden';
            showToast('Fehler beim Erstellen: ' + e.message, 'error');
        }
    });
}

// ── Initialisierung ───────────────────────────────────────────

async function init() {
    // Service Worker registrieren
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(console.error);
    }

    // PWA-Lifecycle (Install-Prompt, Online/Offline)
    initPWA();

    // HID-Barcode-Scanner (Bluetooth/USB)
    initHIDScanner((barcode) => handleScan(barcode));

    // Voice-Button (Toggle-Modus)
    const voiceBtn = btnVoice();
    if (voiceBtn) {
        voiceBtn.addEventListener('click', onVoiceToggle);
    }

    // Tastenkürzel: M = Voice-Toggle (e.repeat ignorieren bei gehaltenem Taster)
    document.addEventListener('keydown', (e) => {
        if (e.repeat) return;
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
        if (e.key === 'm' || e.key === 'M') {
            e.preventDefault();
            onVoiceToggle();
        }
    });

    // Scan-Button → Kamera-Barcode-Scanner öffnen
    const scanBtn = btnScan();
    if (scanBtn) {
        scanBtn.addEventListener('click', () => {
            openCameraScanner((barcode) => handleScan(barcode));
        });
    }

    // Quality-Alert-Button
    const alertBtn = btnAlert();
    if (alertBtn) {
        alertBtn.addEventListener('click', openQualityAlertForm);
    }

    // State-Änderungen → Header-Status aktualisieren
    subscribe((state) => {
        statusEl().textContent = state.loading ? 'Laden...' : 'Online';
    });

    // Backend erreichbar?
    try {
        const resp = await fetch('/api/health');
        if (resp.ok) {
            statusEl().textContent = 'Online';
            statusEl().className = 'status online';
        }
    } catch {
        statusEl().textContent = 'Offline';
        statusEl().className = 'status offline';
    }

    // Picking-Liste laden
    await loadPickingList();
}

// Globaler Zugriff für inline-onclick-Handlers
window._app = { loadPickingList, loadPickingDetail };

document.addEventListener('DOMContentLoaded', init);
