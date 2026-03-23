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
import { feedbackSuccess, feedbackError } from './feedback.js';
import { setState, getState, subscribe, renderPickCard, renderLoading, renderError, showToast } from './ui.js';
import { initHIDScanner, showManualInput, openCameraScanner } from './scanner.js';
import { speak, stopSpeaking, captureAndRecognize, isVoiceSupported, toggleVoiceMode, isVoiceModeActive, stopVoiceMode } from './voice.js';
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

function formatLocationForDisplay(locationPath) {
    if (!locationPath) return 'Unbekannter Halt';
    return locationPath
        .split('/')
        .filter(Boolean)
        .slice(-2)
        .join(' · ');
}

function renderRouteHint(picking, currentLineIndex) {
    const routePlan = picking?.route_plan;
    const lines = picking?.move_lines || [];
    if (!routePlan || currentLineIndex >= lines.length) return '';

    const remainingLines = lines.slice(currentLineIndex);
    const remainingTravelScore = (routePlan.stops || [])
        .slice(currentLineIndex)
        .reduce((sum, stop) => sum + (stop.estimated_steps_from_previous || 0), 0);
    const zonePreview = [...new Set(
        remainingLines
            .slice(0, 3)
            .map(line => formatLocationForDisplay(line.location_src).split(' · ')[0])
            .filter(Boolean)
    )];
    const nextLine = remainingLines[0];

    return `
        <section class="route-hint" aria-label="Optimierte Routenempfehlung">
            <div class="route-hint__eyebrow">Route Intelligence</div>
            <div class="route-hint__title">Naechster Halt: ${formatLocationForDisplay(nextLine.location_src)}</div>
            <div class="route-hint__meta">
                ${remainingLines.length} Stopps offen · Laufweg-Score ${remainingTravelScore}
            </div>
            <div class="route-hint__chips">
                ${zonePreview.map(zone => `<span class="route-hint__chip">${zone}</span>`).join('')}
            </div>
        </section>
    `;
}

// ── Filter-State ─────────────────────────────────────────────
let activeFilter = 'all'; // 'all' | 'high'

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
    if (!show && isVoiceModeActive()) stopVoiceMode();
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

        const visiblePickings = activeFilter === 'high'
            ? pickings.filter(p => p.priority === '1')
            : pickings;

        const countText = activeFilter === 'high'
            ? `${visiblePickings.length} von ${pickings.length}`
            : `${pickings.length} Aufträge`;

        const filterBar = `
    <div class="filter-bar" role="toolbar" aria-label="Aufträge filtern">
        <button class="filter-btn ${activeFilter === 'all' ? 'filter-btn--active' : ''}"
                onclick="window._app.setFilter('all')" aria-pressed="${activeFilter === 'all'}">Alle</button>
        <button class="filter-btn ${activeFilter === 'high' ? 'filter-btn--active' : ''}"
                onclick="window._app.setFilter('high')" aria-pressed="${activeFilter === 'high'}">⚡ Dringend</button>
        <span class="filter-count">${countText}</span>
    </div>`;

        if (visiblePickings.length === 0) {
            mainEl().innerHTML = filterBar + '<p style="padding:20px;color:var(--text-muted)">Keine dringenden Aufträge.</p>';
            return;
        }

        mainEl().innerHTML = filterBar + `<div class="pick-list-grid">${visiblePickings.map(p => {
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

function setFilter(value) {
    activeFilter = value;
    loadPickingList();
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
            speak(`Optimierte Route aktiv. Gehe zu ${formatLocationForSpeech(l.location_src)}. Artikel: ${l.product_name}. Menge: ${l.quantity_demand}`);
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
            ${renderRouteHint(currentPicking, currentLineIndex)}
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
        feedbackError();
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
            feedbackError();
            speak(result.message || 'Fehler beim Bestätigen.');
            showToast(result.message || 'Fehler', 'error');
            return;
        }

        feedbackSuccess();
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
    }, (err) => {
        const msg = err?.name === 'NotAllowedError'
            ? 'Mikrofonzugriff verweigert. Bitte in iOS-Einstellungen erlauben: Einstellungen → Datenschutz → Mikrofon → Safari'
            : `Mikrofon-Fehler: ${err?.message || err}`;
        showToast(msg, 'warning');
    });
}

async function handleVoiceIntent(result) {
    if (!result || result.intent === 'error') return;

    // Visuelles Feedback: was wurde erkannt
    if (result.text) {
        const intentLabel = result.intent !== 'unknown' ? ` → ${result.intent}` : ' → nicht erkannt';
        showToast(`"${result.text}"${intentLabel}`, result.intent !== 'unknown' ? 'info' : 'warning');
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
        case 'photo':
            openCameraScanner((barcode) => handleScan(barcode));
            break;
        case 'pause':
            if (isVoiceModeActive()) {
                stopVoiceMode();
                const voiceBtn = btnVoice();
                if (voiceBtn) voiceBtn.classList.remove('voice-active');
            }
            break;
        case 'done': {
            const remaining = lines.filter(l => !l.picked).length;
            if (remaining === 0) {
                await speak('Auftrag abgeschlossen.');
                loadPickingList();
            } else {
                speak(`Noch ${remaining} Artikel ausstehend.`);
            }
            break;
        }
        case 'help':
            speak('Verfügbare Kommandos: bestätigen, weiter, zurück, wiederholen, Problem, fertig.');
            break;
        case 'filter_high':
            if (currentPicking !== null) break;
            activeFilter = 'high';
            await loadPickingList();
            speak('Gefiltert. Zeige nur dringende Aufträge.');
            break;
        case 'filter_normal':
            if (currentPicking !== null) break;
            activeFilter = 'all';
            await loadPickingList();
            speak('Filter zurückgesetzt. Alle Aufträge.');
            break;
        case 'status': {
            if (currentPicking !== null) break;
            const { pickings } = getState();
            const all = pickings?.length || 0;
            const high = pickings?.filter(p => p.priority === '1').length || 0;
            if (high > 0) speak(`${all} offene Aufträge. ${high} davon dringend.`);
            else speak(`${all} offene Aufträge.`);
            break;
        }
        case 'stock_query': {
            if (!line) break;
            const productId = line.product_id;
            // location_id is not carried in move_line; use 0 to query across all locations
            speak(`Ich prüfe den Bestand für ${line.product_name}.`);
            try {
                const resp = await fetch(`/api/pickings/${currentPicking.id}/stock?product_id=${productId}&location_id=0`);
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.quantity_available > 0) {
                        speak(`Laut System sind ${data.quantity_available} Stück verfügbar.`);
                    } else {
                        speak(`Laut System ist kein Bestand vorhanden. Soll ich einen Qualitätsalarm auslösen?`);
                    }
                }
            } catch {
                speak('Bestand konnte nicht abgerufen werden.');
            }
            break;
        }
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
    const contextLabel = currentPicking
        ? `${currentPicking.name}${line?.product_name ? ` · ${line.product_name}` : ''}`
        : 'Allgemeine Meldung';

    mainEl().innerHTML = `
        <div class="qa-shell">
            <section class="qa-card" aria-labelledby="qa-title">
                <div class="qa-header">
                    <h2 id="qa-title" class="qa-title">Problem melden</h2>
                    <p class="qa-context">${contextLabel}</p>
                </div>

                <div class="qa-field-group">
                    <label for="qa-description" class="qa-label">Beschreibung</label>
                    <textarea id="qa-description"
                        class="qa-field qa-textarea"
                        placeholder="Beschreibung des Problems..."
                        aria-describedby="qa-description-help"></textarea>
                    <p id="qa-description-help" class="qa-help">
                        Kurz und konkret beschreiben, was am Artikel, Lagerort oder Zustand auffällt.
                    </p>
                    <p id="qa-description-error" class="qa-field-error" role="alert" hidden></p>
                </div>

                <div class="qa-field-group">
                    <label for="qa-priority" class="qa-label">Priorität</label>
                    <select id="qa-priority" class="qa-field qa-select">
                        <option value="0">Normal</option>
                        <option value="2">Hoch</option>
                        <option value="3">Kritisch</option>
                    </select>
                </div>

                <div id="photo-area" class="qa-photo-area"></div>
            </section>

            <p id="qa-inline-error" class="qa-inline-error" role="alert" hidden></p>

            <div class="qa-actions">
                <button id="qa-submit" class="qa-submit">Absenden</button>
                <button id="qa-cancel" class="qa-cancel">Abbrechen</button>
            </div>
        </div>`;

    // Foto-Input mit Vorschau
    const photoArea = document.getElementById('photo-area');
    const descriptionEl = document.getElementById('qa-description');
    const descriptionErrorEl = document.getElementById('qa-description-error');
    const inlineErrorEl = document.getElementById('qa-inline-error');
    const cancelBtn = document.getElementById('qa-cancel');
    let photoFiles = [];

    const clearDescriptionError = () => {
        descriptionErrorEl.hidden = true;
        descriptionErrorEl.textContent = '';
        descriptionEl.removeAttribute('aria-invalid');
        descriptionEl.setAttribute('aria-describedby', 'qa-description-help');
    };

    const setDescriptionError = (message) => {
        descriptionErrorEl.textContent = message;
        descriptionErrorEl.hidden = false;
        descriptionEl.setAttribute('aria-invalid', 'true');
        descriptionEl.setAttribute('aria-describedby', 'qa-description-help qa-description-error');
    };

    const clearInlineError = () => {
        inlineErrorEl.hidden = true;
        inlineErrorEl.textContent = '';
    };

    const setInlineError = (message) => {
        inlineErrorEl.textContent = message;
        inlineErrorEl.hidden = false;
    };

    const fileInput = createFileInput((files) => {
        photoFiles = photoFiles.concat(files);
        renderPhotoPreview();
        clearInlineError();
        showToast(`${files.length} Foto${files.length > 1 ? 's' : ''} hinzugefügt`, 'success');
    });

    const photoLabel = document.createElement('p');
    photoLabel.className = 'qa-label';
    photoLabel.textContent = 'Fotos';

    const photoHelp = document.createElement('p');
    photoHelp.className = 'qa-help';
    photoHelp.textContent = 'Optional: 1 oder mehrere Fotos hinzufügen.';

    const photoBtn = document.createElement('button');
    photoBtn.type = 'button';
    photoBtn.textContent = '📷 Fotos hinzufügen';
    photoBtn.setAttribute('aria-label', 'Fotos hinzufügen');
    photoBtn.className = 'qa-photo-button';
    photoBtn.addEventListener('click', () => fileInput.click());

    const previewGrid = document.createElement('div');
    previewGrid.id = 'photo-preview-grid';
    previewGrid.className = 'qa-photo-preview-grid';

    function renderPhotoPreview() {
        previewGrid.innerHTML = '';
        photoFiles.forEach((file, idx) => {
            const url = URL.createObjectURL(file);
            const wrapper = document.createElement('div');
            wrapper.className = 'qa-photo-thumb';

            const img = document.createElement('img');
            img.src = url;
            img.className = 'qa-photo-image';
            img.alt = `Ausgewähltes Foto ${idx + 1}`;

            const del = document.createElement('button');
            del.type = 'button';
            del.textContent = '✕';
            del.setAttribute('aria-label', `Foto ${idx + 1} entfernen`);
            del.className = 'qa-photo-remove';
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
    photoArea.appendChild(photoLabel);
    photoArea.appendChild(photoHelp);
    photoArea.appendChild(photoBtn);
    photoArea.appendChild(previewGrid);

    descriptionEl.addEventListener('input', () => {
        if (descriptionEl.value.trim()) clearDescriptionError();
        clearInlineError();
    });

    cancelBtn.addEventListener('click', () => {
        if (currentPicking) loadPickingDetail(currentPicking.id);
        else loadPickingList();
    });

    const submitBtn = document.getElementById('qa-submit');
    submitBtn.addEventListener('click', async () => {
        const description = descriptionEl.value.trim();
        clearInlineError();

        if (!description) {
            setDescriptionError('Bitte Beschreibung eingeben.');
            descriptionEl.focus();
            showToast('Bitte Beschreibung eingeben', 'warning');
            return;
        }

        clearDescriptionError();

        // Doppelklick-Schutz
        submitBtn.disabled = true;
        cancelBtn.disabled = true;
        photoBtn.disabled = true;
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
            cancelBtn.disabled = false;
            photoBtn.disabled = false;
            submitBtn.textContent = 'Absenden';
            setInlineError(`Fehler beim Erstellen: ${e.message}`);
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

    // Proaktive Begrüssung nach dem ersten Laden
    const { pickings } = getState();
    const total = pickings?.length || 0;
    const urgent = pickings?.filter(p => p.priority === '1').length || 0;
    if (total === 0) {
        speak('Keine offenen Aufträge.');
    } else if (urgent > 0) {
        speak(`${total} Aufträge offen. ${urgent} davon dringend.`);
    } else {
        speak(`${total} Aufträge offen.`);
    }
}

// Globaler Zugriff für inline-onclick-Handlers
window._app = { loadPickingList, loadPickingDetail, setFilter };

document.addEventListener('DOMContentLoaded', init);
