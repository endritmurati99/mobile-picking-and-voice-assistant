/**
 * Picking Assistant - Haupt-App-Logik
 *
 * Flow:
 *   1. Start -> Picker auswaehlen
 *   2. Picking-Liste laden
 *   3. Picking claimen -> Detail laden
 *   4. HID-Scan oder Touch-Bestaetigung pro Zeile
 *   5. TTS-Feedback nach jeder Aktion
 *   6. Optional: Voice-Kommandos + Quality-Alert-Formular
 */
import {
    ApiError,
    claimPicking,
    clearStoredPicker,
    confirmLine,
    createIdempotencyKey,
    createQualityAlert,
    getDeviceId,
    getPickers,
    getPickingDetail,
    getPickings,
    getStoredPicker,
    releasePicking,
    setStoredPicker,
    heartbeatPicking,
} from './api.js';
import { feedbackSuccess, feedbackError } from './feedback.js';
import { setState, getState, subscribe, renderPickCard, renderLoading, renderError, showToast } from './ui.js';
import { initHIDScanner, showManualInput, openCameraScanner } from './scanner.js';
import {
    speak,
    stopSpeaking,
    isVoiceSupported,
    toggleVoiceMode,
    isVoiceModeActive,
    isPushToTalkActive,
    startPushToTalk,
    stopPushToTalk,
    stopVoiceMode,
} from './voice.js';
import { createFileInput } from './camera.js';
import { initPWA } from './pwa.js';

const CLAIM_HEARTBEAT_MS = 30_000;
const VOICE_LONG_PRESS_MS = 350;

function formatLocationForSpeech(locationPath) {
    if (!locationPath) return '';
    const segments = String(locationPath).split('/').filter(Boolean);
    const relevant = segments.length ? segments[segments.length - 1] : String(locationPath);
    return relevant.replace(/-/g, ' ').replace(/([A-Za-z])(\d)/g, '$1 $2');
}

function formatLocationForDisplay(locationPath, shortCode = '', zone = '') {
    if (shortCode || zone) return [zone, shortCode].filter(Boolean).join(' / ');
    if (!locationPath) return 'Unbekannter Halt';
    return locationPath
        .split('/')
        .filter(Boolean)
        .slice(-2)
        .join(' / ');
}

function formatQuantity(value) {
    const numeric = Number(value ?? 0);
    if (Number.isNaN(numeric)) return '0';
    if (Number.isInteger(numeric)) return String(numeric);
    return numeric.toFixed(2).replace(/\.?0+$/, '');
}

function getPickingReference(picking) {
    return picking?.reference_code || picking?.name || 'Ohne Referenz';
}

function getPickingTypeLabel(picking) {
    const rawLabel = picking?.picking_type_id?.[1] || '';
    return rawLabel.split(':').pop().trim();
}

function getPickingPrimaryLabel(picking) {
    return picking?.primary_item_display || getPickingReference(picking);
}

function getOpenLineLabel(count) {
    const safeCount = Number(count || 0);
    return safeCount === 1 ? '1 Position offen' : `${safeCount} Positionen offen`;
}

function getLineDisplayName(line) {
    return line?.ui_display || line?.product_short_name || line?.product_name || 'Produkt';
}

function getLineQuantityLabel(line) {
    return `${formatQuantity(line?.quantity_demand)} Stueck`;
}

function getLineSpeechPrompt(line) {
    if (!line) return '';
    if (line.voice_instruction_short) return line.voice_instruction_short;
    const locationShort = line.location_src_short || formatLocationForSpeech(line.location_src);
    const product = getLineDisplayName(line);
    return [
        locationShort ? `${locationShort}.` : '',
        `${formatQuantity(line.quantity_demand)} Stueck.`,
        product ? `${product}.` : '',
    ].filter(Boolean).join(' ');
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
            .map((line) => line.location_src_zone || line.location_src_short || '')
            .filter(Boolean)
    )];
    const nextLine = remainingLines[0];
    const nextLocation = formatLocationForDisplay(
        nextLine.location_src,
        nextLine.location_src_short,
        nextLine.location_src_zone,
    );

    return `
        <section class="route-hint" aria-label="Optimierte Routenempfehlung">
            <div class="route-hint__eyebrow">Route Intelligence</div>
            <div class="route-hint__title">Naechster Halt: ${nextLocation}</div>
            <div class="route-hint__meta">
                ${remainingLines.length} Stopps offen - Laufweg-Score ${remainingTravelScore}
            </div>
            <div class="route-hint__chips">
                ${zonePreview.map((zone) => `<span class="route-hint__chip">${zone}</span>`).join('')}
            </div>
        </section>
    `;
}

let activeFilter = 'all';
let claimHeartbeatTimer = null;
let claimedPickingId = null;
let voiceLongPressTimer = null;
let voiceLongPressStarted = false;
let suppressNextVoiceClick = false;

const mainEl = () => document.getElementById('main');
const statusEl = () => document.getElementById('status-indicator');
const pickerEl = () => document.getElementById('picker-indicator');
const btnVoice = () => document.getElementById('btn-voice');
const btnScan = () => document.getElementById('btn-scan');
const btnAlert = () => document.getElementById('btn-alert');

function updateToolbar(view) {
    const buttons = [btnVoice(), btnScan(), btnAlert()];
    const show = view === 'detail';
    buttons.forEach((button) => {
        if (button) button.classList.toggle('hidden', !show);
    });
    if (!show) {
        btnVoice()?.classList.remove('nav-btn--ptt');
        if (isVoiceModeActive()) stopVoiceMode();
    }
}

function updatePickerIndicator() {
    const indicator = pickerEl();
    if (!indicator) return;
    const picker = getState().currentPicker;
    if (picker?.name) {
        indicator.textContent = picker.name;
        indicator.classList.remove('picker-indicator--empty');
    } else {
        indicator.textContent = 'Picker waehlen';
        indicator.classList.add('picker-indicator--empty');
    }
}

function updateVoiceButtonState(active) {
    const voiceButton = btnVoice();
    if (!voiceButton) return;

    if (active) {
        voiceButton.style.background = 'var(--danger)';
        voiceButton.setAttribute('aria-label', 'Sprachmodus beenden');
        return;
    }

    voiceButton.style.background = '';
    voiceButton.setAttribute('aria-label', 'Sprachmodus starten');
}

function getVoiceErrorMessage(error) {
    return error?.name === 'NotAllowedError'
        ? 'Mikrofonzugriff verweigert. Bitte in den Browser-Einstellungen erlauben.'
        : `Mikrofon-Fehler: ${error?.message || error}`;
}

function renderClaimConflict(conflict, pickingId) {
    updateToolbar('locked');
    const owner = conflict?.claimed_by_name || 'einem anderen Picker';
    const expiresAt = conflict?.claim_expires_at
        ? new Date(conflict.claim_expires_at).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })
        : 'bald';

    mainEl().innerHTML = `
        <div class="picker-screen">
            <section class="picker-card">
                <div class="picker-card__eyebrow">Claim-Konflikt</div>
                <h2 class="picker-card__title">Dieses Picking ist gerade gesperrt.</h2>
                <p class="picker-card__text">
                    Aktuell arbeitet <strong>${owner}</strong> daran.
                    Ablauf des Claims: <strong>${expiresAt}</strong>.
                </p>
                <div class="picker-card__actions">
                    <button id="claim-retry" class="picker-option picker-option--primary">Erneut pruefen</button>
                    <button id="claim-back" class="picker-option">Zurueck zur Liste</button>
                </div>
            </section>
        </div>
    `;

    document.getElementById('claim-retry')?.addEventListener('click', () => loadPickingDetail(pickingId));
    document.getElementById('claim-back')?.addEventListener('click', () => loadPickingList({ skipRelease: true }));
}

function stopClaimHeartbeat() {
    if (!claimHeartbeatTimer) return;
    window.clearInterval(claimHeartbeatTimer);
    claimHeartbeatTimer = null;
}

function buildOperationKey(scope, parts = [], { unique = false } = {}) {
    const pickerId = getState().currentPicker?.id || getStoredPicker()?.id || 'anon';
    return createIdempotencyKey(scope, [pickerId, ...parts], { unique });
}

function startClaimHeartbeat(pickingId) {
    stopClaimHeartbeat();
    claimHeartbeatTimer = window.setInterval(async () => {
        const picker = getState().currentPicker;
        if (!picker?.id || claimedPickingId !== pickingId) return;
        try {
            await heartbeatPicking(pickingId, {
                idempotencyKey: buildOperationKey('heartbeat', [pickingId, Date.now()], { unique: true }),
            });
        } catch (error) {
            if (error instanceof ApiError && error.status === 409) {
                claimedPickingId = null;
                stopClaimHeartbeat();
                renderClaimConflict(error.detail, pickingId);
                return;
            }
            console.warn('Claim heartbeat fehlgeschlagen:', error);
        }
    }, CLAIM_HEARTBEAT_MS);
}

async function releaseCurrentClaim(options = {}) {
    if (!claimedPickingId) return;
    const pickingId = claimedPickingId;
    claimedPickingId = null;
    stopClaimHeartbeat();

    const picker = getState().currentPicker || getStoredPicker();
    if (!picker?.id) return;

    try {
        await releasePicking(pickingId, {
            idempotencyKey: buildOperationKey('release', [pickingId, Date.now()], { unique: true }),
            keepalive: options.keepalive || false,
        });
    } catch (error) {
        console.warn('Claim release fehlgeschlagen:', error);
    }
}

function renderPickerSelection(pickers, { title = 'Picker auswaehlen', intro = 'Bitte waehle deinen Odoo-Benutzer fuer diese Session.' } = {}) {
    updateToolbar('picker');
    mainEl().innerHTML = `
        <div class="picker-screen">
            <section class="picker-card">
                <div class="picker-card__eyebrow">Session-Start</div>
                <h2 class="picker-card__title">${title}</h2>
                <p class="picker-card__text">${intro}</p>
                <div class="picker-device">Geraet: ${getDeviceId()}</div>
                <div class="picker-options">
                    ${pickers.map(picker => `
                        <button class="picker-option" data-picker-id="${picker.id}">
                            ${picker.name}
                        </button>
                    `).join('')}
                </div>
            </section>
        </div>
    `;

    mainEl().querySelectorAll('[data-picker-id]').forEach(button => {
        button.addEventListener('click', async () => {
            const pickerId = Number(button.dataset.pickerId);
            const picker = pickers.find(item => item.id === pickerId);
            if (!picker) return;
            setStoredPicker(picker);
            setState({ currentPicker: picker, deviceId: getDeviceId() });
            updatePickerIndicator();
            await loadPickingList({ skipRelease: true });
        });
    });
}

async function ensurePickerSelection({ forceSelection = false } = {}) {
    const existingPicker = forceSelection ? null : getStoredPicker();
    const deviceId = getDeviceId();

    if (existingPicker?.id) {
        setState({ currentPicker: existingPicker, deviceId });
        updatePickerIndicator();
        return true;
    }

    mainEl().innerHTML = renderLoading();
    try {
        const pickers = await getPickers();
        if (!pickers.length) {
            mainEl().innerHTML = renderError('Keine aktiven Picker in Odoo gefunden.');
            return false;
        }

        if (!forceSelection && pickers.length === 1) {
            setStoredPicker(pickers[0]);
            setState({ currentPicker: pickers[0], deviceId });
            updatePickerIndicator();
            return true;
        }

        renderPickerSelection(pickers);
        return false;
    } catch (error) {
        mainEl().innerHTML = renderError(`Picker konnten nicht geladen werden: ${error.message}`);
        return false;
    }
}

async function loadPickingList({ skipRelease = false, forcePickerSelection = false } = {}) {
    stopSpeaking();
    if (!skipRelease) await releaseCurrentClaim();
    updateToolbar('list');

    const pickerReady = await ensurePickerSelection({ forceSelection: forcePickerSelection });
    if (!pickerReady) return;

    mainEl().innerHTML = renderLoading();
    try {
        const pickings = await getPickings();
        setState({ pickings, currentPicking: null, currentLineIndex: 0 });

        if (!pickings.length) {
            mainEl().innerHTML = '<p style="padding:20px;color:var(--text-muted)">Keine offenen Auftraege.</p>';
            return;
        }

        const visiblePickings = activeFilter === 'high'
            ? pickings.filter(picking => picking.priority === '1')
            : pickings;

        const countText = activeFilter === 'high'
            ? `${visiblePickings.length} von ${pickings.length}`
            : `${pickings.length} Auftraege`;

        const filterBar = `
            <div class="filter-bar" role="toolbar" aria-label="Auftraege filtern">
                <button class="filter-btn ${activeFilter === 'all' ? 'filter-btn--active' : ''}"
                        onclick="window._app.setFilter('all')" aria-pressed="${activeFilter === 'all'}">Alle</button>
                <button class="filter-btn ${activeFilter === 'high' ? 'filter-btn--active' : ''}"
                        onclick="window._app.setFilter('high')" aria-pressed="${activeFilter === 'high'}">Dringend</button>
                <span class="filter-count">${countText}</span>
            </div>`;

        if (visiblePickings.length === 0) {
            mainEl().innerHTML = `${filterBar}<p style="padding:20px;color:var(--text-muted)">Keine dringenden Auftraege.</p>`;
            return;
        }

        mainEl().innerHTML = filterBar + `
            <div class="pick-list-grid">
                ${visiblePickings.map((picking) => {
                    const date = picking.scheduled_date
                        ? new Date(picking.scheduled_date).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
                        : '';
                    const partner = picking.partner_id ? picking.partner_id[1] : '-';
                    const typeName = getPickingTypeLabel(picking);
                    const reference = getPickingReference(picking);
                    const primaryLabel = getPickingPrimaryLabel(picking);
                    const nextLocation = picking.next_location_short || 'Route offen';
                    const openLineLabel = getOpenLineLabel(picking.open_line_count);

                    return `
                        <article class="pick-list-card" data-id="${picking.id}" aria-label="${primaryLabel}">
                            <div class="plc-header">
                                <span class="plc-reference">${reference}</span>
                                <div class="plc-tags">
                                    ${picking.priority === '1' ? '<span class="plc-priority">Dringend</span>' : ''}
                                    ${typeName ? `<span class="plc-badge">${typeName}</span>` : ''}
                                </div>
                            </div>
                            <div class="plc-primary">${primaryLabel}</div>
                            <div class="plc-partner">${partner}</div>
                            <div class="plc-secondary">
                                ${date ? `<span>${date}</span>` : '<span>Ohne Termin</span>'}
                                <span class="plc-location-pill">${nextLocation}</span>
                            </div>
                            <div class="plc-footer">${openLineLabel}</div>
                        </article>
                    `;
                }).join('')}
            </div>`;

        mainEl().querySelectorAll('.pick-list-card[data-id]').forEach((card) => {
            card.addEventListener('click', () => loadPickingDetail(Number(card.dataset.id)));
        });
    } catch (error) {
        mainEl().innerHTML = renderError(`Verbindung fehlgeschlagen: ${error.message}`);
        statusEl().textContent = 'Offline';
        statusEl().className = 'status offline';
    }
}

function setFilter(value) {
    activeFilter = value;
    loadPickingList({ skipRelease: true });
}

async function loadPickingDetail(pickingId) {
    stopSpeaking();
    mainEl().innerHTML = renderLoading();

    const pickerReady = await ensurePickerSelection();
    if (!pickerReady) return;

    if (claimedPickingId && claimedPickingId !== pickingId) {
        await releaseCurrentClaim();
    }

    try {
        await claimPicking(pickingId, {
            idempotencyKey: buildOperationKey('claim', [pickingId, Date.now()], { unique: true }),
        });
        claimedPickingId = pickingId;
        startClaimHeartbeat(pickingId);

        const picking = await getPickingDetail(pickingId);
        if (picking.error) {
            await releaseCurrentClaim();
            mainEl().innerHTML = renderError(picking.error);
            return;
        }

        setState({ currentPicking: picking, currentLineIndex: 0 });
        renderCurrentLine();

        const lines = picking.move_lines || [];
        if (lines.length > 0) {
            speak(getLineSpeechPrompt(lines[0]));
        }
    } catch (error) {
        if (error instanceof ApiError && error.status === 409 && typeof error.detail === 'object') {
            renderClaimConflict(error.detail, pickingId);
            return;
        }
        await releaseCurrentClaim();
        mainEl().innerHTML = renderError(`Fehler beim Laden: ${error.message}`);
    }
}

function renderCurrentLine() {
    const { currentPicking, currentLineIndex } = getState();
    if (!currentPicking) return;
    updateToolbar('detail');

    const lines = currentPicking.move_lines || [];
    if (currentLineIndex >= lines.length) {
        updateToolbar('complete');
        mainEl().innerHTML = `
            <div style="padding:20px;text-align:center">
                <div style="font-size:2rem;margin-bottom:12px">OK</div>
                <div style="font-size:1.1rem;font-weight:600">${getPickingReference(currentPicking)}</div>
                <div style="color:var(--text-muted);margin-top:8px">Alle Artikel erfasst.</div>
                <button onclick="window._app.loadPickingList()"
                        style="margin-top:20px;padding:12px 24px;background:var(--accent);color:#000;border:none;border-radius:8px;font-size:1rem;font-weight:600">
                    Zurueck zur Liste
                </button>
            </div>`;
        return;
    }

    const line = lines[currentLineIndex];
    const progress = `${currentLineIndex + 1} / ${lines.length}`;

    mainEl().innerHTML = `
        <div style="padding:12px">
            <div style="color:var(--text-muted);font-size:0.85rem;margin-bottom:12px">
                ${getPickingReference(currentPicking)} - ${progress}
                <span style="float:right">
                    <button onclick="window._app.loadPickingList()"
                            style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:0.85rem">Zur Liste</button>
                </span>
            </div>
            <section class="detail-summary" aria-label="Picking Uebersicht">
                <div class="detail-summary__eyebrow">${currentPicking.partner_id ? currentPicking.partner_id[1] : 'Aktives Picking'}</div>
                <div class="detail-summary__title">${getLineDisplayName(line)}</div>
                <div class="detail-summary__subline">
                    <span>${getLineQuantityLabel(line)}</span>
                    <span>${line.location_src_short || formatLocationForDisplay(line.location_src)}</span>
                </div>
            </section>
            ${renderRouteHint(currentPicking, currentLineIndex)}
            ${renderPickCard({
                ...line,
                quantity_demand: line.quantity_demand,
            })}
            <div id="scan-input-area" class="detail-scan-area"></div>
        </div>`;

    const confirmButton = mainEl().querySelector('.btn-confirm');
    if (confirmButton) {
        confirmButton.addEventListener('click', () => handleScan(line.product_barcode || ''));
    }

    const scanArea = document.getElementById('scan-input-area');
    if (scanArea) {
        const manualInput = showManualInput((barcode) => handleScan(barcode));
        scanArea.appendChild(manualInput);
    }
}

async function handleScan(barcode) {
    stopSpeaking();
    const { currentPicking, currentLineIndex, currentPicker } = getState();
    if (!currentPicking) return;

    const lines = currentPicking.move_lines || [];
    if (currentLineIndex >= lines.length) return;

    const line = lines[currentLineIndex];

    if (barcode && line.product_barcode && barcode !== line.product_barcode) {
        feedbackError();
        speak(`Falscher Artikel. ${getLineDisplayName(line)}.`);
        showToast('Falscher Barcode', 'error');
        return;
    }

    try {
        const result = await confirmLine(
            currentPicking.id,
            {
                move_line_id: line.id,
                scanned_barcode: barcode || line.product_barcode || '',
                quantity: line.quantity_demand,
            },
            {
                idempotencyKey: buildOperationKey('confirm-line', [
                    currentPicking.id,
                    currentPicker?.id || 'anon',
                    currentLineIndex,
                    line.id,
                    barcode || line.product_barcode || '',
                    line.quantity_demand,
                ]),
            },
        );

        if (!result.success) {
            feedbackError();
            speak(result.message || 'Fehler beim Bestaetigen.');
            showToast(result.message || 'Fehler', 'error');
            return;
        }

        feedbackSuccess();
        showToast(result.message, 'success');

        if (result.picking_complete) {
            await releaseCurrentClaim();
            speak('Auftrag abgeschlossen.');
            setState({ currentLineIndex: lines.length });
            renderCurrentLine();
        } else {
            const nextIdx = currentLineIndex + 1;
            setState({ currentLineIndex: nextIdx });
            renderCurrentLine();

            if (nextIdx < lines.length) {
                const nextLine = lines[nextIdx];
                speak(getLineSpeechPrompt(nextLine));
            }
        }
    } catch (error) {
        if (error instanceof ApiError && error.status === 409 && typeof error.detail === 'object') {
            claimedPickingId = null;
            stopClaimHeartbeat();
            renderClaimConflict(error.detail, currentPicking.id);
            speak('Dieses Picking wurde inzwischen von jemand anderem uebernommen.');
            return;
        }

        showToast(error.message || 'Verbindungsfehler', 'error');
        speak('Verbindungsfehler. Bitte erneut versuchen.');
    }
}

function onVoiceToggle() {
    if (!isVoiceSupported()) {
        showToast('Mikrofon nicht verfuegbar', 'warning');
        return;
    }

    toggleVoiceMode(
        handleVoiceIntent,
        (active) => {
            updateVoiceButtonState(active);
            if (active) showToast('Sprachmodus aktiv - sprich ein Kommando', 'info');
            else showToast('Sprachmodus beendet', 'info');
        },
        (error) => {
            showToast(getVoiceErrorMessage(error), 'warning');
        },
    );
}

async function startVoiceLongPress() {
    if (isVoiceModeActive()) return;

    const started = await startPushToTalk(
        handleVoiceIntent,
        (error) => showToast(getVoiceErrorMessage(error), 'warning'),
    );
    if (!started) return;

    voiceLongPressStarted = true;
    suppressNextVoiceClick = true;
    btnVoice()?.classList.add('nav-btn--ptt');
    showToast('Push-to-Talk aktiv', 'info');
}

async function finishVoiceLongPress() {
    if (!voiceLongPressStarted && !isPushToTalkActive()) return;
    voiceLongPressStarted = false;
    btnVoice()?.classList.remove('nav-btn--ptt');
    await stopPushToTalk();
}

async function handleVoiceIntent(result) {
    if (!result || result.intent === 'error') return;

    if (result.text) {
        const intentLabel = result.intent !== 'unknown' ? ` -> ${result.intent}` : ' -> nicht erkannt';
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
            if (line && currentLineIndex < lines.length - 1) {
                const nextIndex = currentLineIndex + 1;
                setState({ currentLineIndex: nextIndex });
                renderCurrentLine();
                speak(getLineSpeechPrompt(lines[nextIndex]));
            }
            break;
        case 'previous':
            if (currentLineIndex > 0) {
                const previousIndex = currentLineIndex - 1;
                setState({ currentLineIndex: previousIndex });
                renderCurrentLine();
                speak(getLineSpeechPrompt(lines[previousIndex]));
            }
            break;
        case 'repeat':
            if (line) speak(getLineSpeechPrompt(line));
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
                updateVoiceButtonState(false);
            }
            break;
        case 'done': {
            const remaining = Math.max(lines.length - currentLineIndex - 1, 0);
            if (remaining === 0) {
                await speak('Auftrag abgeschlossen.');
                loadPickingList();
            } else {
                speak(`Noch ${remaining} Artikel ausstehend.`);
            }
            break;
        }
        case 'help':
            speak('Kommandos: bestaetigen, weiter, zurueck, wiederholen, Problem, fertig.');
            break;
        case 'filter_high':
            if (currentPicking !== null) break;
            activeFilter = 'high';
            await loadPickingList({ skipRelease: true });
            speak('Gefiltert. Zeige nur dringende Auftraege.');
            break;
        case 'filter_normal':
            if (currentPicking !== null) break;
            activeFilter = 'all';
            await loadPickingList({ skipRelease: true });
            speak('Filter zurueckgesetzt. Alle Auftraege.');
            break;
        case 'status': {
            if (currentPicking !== null) break;
            const { pickings } = getState();
            const all = pickings?.length || 0;
            const high = pickings?.filter(picking => picking.priority === '1').length || 0;
            if (high > 0) speak(`${all} offene Auftraege. ${high} davon dringend.`);
            else speak(`${all} offene Auftraege.`);
            break;
        }
        case 'stock_query': {
            if (!line) break;
            const productId = line.product_id;
            speak(`Bestand fuer ${getLineDisplayName(line)}.`);
            try {
                const response = await fetch(`/api/pickings/${currentPicking.id}/stock?product_id=${productId}&location_id=0`);
                if (response.ok) {
                    const data = await response.json();
                    if (data.quantity_available > 0) {
                        speak(`Laut System sind ${data.quantity_available} Stueck verfuegbar.`);
                    } else {
                        speak('Laut System ist kein Bestand vorhanden. Soll ich einen Qualitaetsalarm ausloesen?');
                    }
                }
            } catch {
                speak('Bestand konnte nicht abgerufen werden.');
            }
            break;
        }
        default:
            break;
    }
}

function openQualityAlertForm() {
    stopSpeaking();
    updateToolbar('alert');

    const { currentPicking, currentLineIndex } = getState();
    const lines = currentPicking?.move_lines || [];
    const line = lines[currentLineIndex];
    const contextLabel = currentPicking
        ? `${getPickingReference(currentPicking)}${line ? ` | ${getLineDisplayName(line)}` : ''}`
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
                    <textarea
                        id="qa-description"
                        class="qa-field qa-textarea"
                        placeholder="Beschreibung des Problems..."
                        aria-describedby="qa-description-help"
                    ></textarea>
                    <p id="qa-description-help" class="qa-help">
                        Kurz und konkret beschreiben, was am Artikel, Lagerort oder Zustand auffaellt.
                    </p>
                    <p id="qa-description-error" class="qa-field-error" role="alert" hidden></p>
                </div>

                <div class="qa-field-group">
                    <label for="qa-priority" class="qa-label">Prioritaet</label>
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
        </div>
    `;

    const photoArea = document.getElementById('photo-area');
    const descriptionEl = document.getElementById('qa-description');
    const descriptionErrorEl = document.getElementById('qa-description-error');
    const inlineErrorEl = document.getElementById('qa-inline-error');
    const cancelBtn = document.getElementById('qa-cancel');
    const submitBtn = document.getElementById('qa-submit');
    let photoFiles = [];

    const clearDescriptionError = () => {
        descriptionErrorEl.hidden = true;
        descriptionErrorEl.textContent = '';
        descriptionEl.removeAttribute('aria-invalid');
        descriptionEl.setAttribute('aria-describedby', 'qa-description-help');
    };

    const setDescriptionError = (message) => {
        descriptionErrorEl.hidden = false;
        descriptionErrorEl.textContent = message;
        descriptionEl.setAttribute('aria-invalid', 'true');
        descriptionEl.setAttribute('aria-describedby', 'qa-description-help qa-description-error');
    };

    const clearInlineError = () => {
        inlineErrorEl.hidden = true;
        inlineErrorEl.textContent = '';
    };

    const setInlineError = (message) => {
        inlineErrorEl.hidden = false;
        inlineErrorEl.textContent = message;
    };

    const fileInput = createFileInput((files) => {
        photoFiles = photoFiles.concat(files);
        renderPhotoPreview();
        clearInlineError();
        showToast(`${files.length} Foto${files.length > 1 ? 's' : ''} hinzugefuegt`, 'success');
    });

    const photoLabel = document.createElement('p');
    photoLabel.className = 'qa-label';
    photoLabel.textContent = 'Fotos';

    const photoHelp = document.createElement('p');
    photoHelp.className = 'qa-help';
    photoHelp.textContent = 'Optional: 1 oder mehrere Fotos hinzufuegen.';

    const photoBtn = document.createElement('button');
    photoBtn.type = 'button';
    photoBtn.className = 'qa-photo-button';
    photoBtn.textContent = 'Fotos hinzufuegen';
    photoBtn.addEventListener('click', () => fileInput.click());

    const previewGrid = document.createElement('div');
    previewGrid.id = 'photo-preview-grid';
    previewGrid.className = 'qa-photo-preview-grid';

    function renderPhotoPreview() {
        previewGrid.innerHTML = '';
        photoFiles.forEach((file, index) => {
            const url = URL.createObjectURL(file);
            const wrapper = document.createElement('div');
            wrapper.className = 'qa-photo-thumb';

            const image = document.createElement('img');
            image.src = url;
            image.alt = `Ausgewaehltes Foto ${index + 1}`;
            image.className = 'qa-photo-image';

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'qa-photo-remove';
            removeButton.textContent = 'x';
            removeButton.setAttribute('aria-label', `Foto ${index + 1} entfernen`);
            removeButton.addEventListener('click', () => {
                photoFiles.splice(index, 1);
                URL.revokeObjectURL(url);
                renderPhotoPreview();
            });

            wrapper.appendChild(image);
            wrapper.appendChild(removeButton);
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
        if (currentPicking) {
            loadPickingDetail(currentPicking.id);
            return;
        }
        loadPickingList();
    });

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

        submitBtn.disabled = true;
        cancelBtn.disabled = true;
        photoBtn.disabled = true;
        submitBtn.textContent = 'Wird gesendet...';

        const priority = document.getElementById('qa-priority').value;
        const formData = new FormData();
        formData.append('description', description);
        formData.append('priority', priority);
        if (currentPicking) formData.append('picking_id', String(currentPicking.id));
        if (line?.product_id) formData.append('product_id', String(line.product_id));
        photoFiles.forEach(file => formData.append('photos', file));

        try {
            const result = await createQualityAlert(
                formData,
                {
                    idempotencyKey: buildOperationKey('quality-alert', [
                        currentPicking?.id || 'none',
                        line?.id || 'none',
                        priority,
                        description,
                        ...photoFiles.map(file => `${file.name}:${file.size}`),
                    ]),
                },
            );
            speak('Problem gemeldet. Vielen Dank.');
            showToast(`Alert ${result.name} erstellt`, 'success');
            if (currentPicking) {
                await loadPickingDetail(currentPicking.id);
                return;
            }
            await loadPickingList({ skipRelease: true });
        } catch (error) {
            submitBtn.disabled = false;
            cancelBtn.disabled = false;
            photoBtn.disabled = false;
            submitBtn.textContent = 'Absenden';
            setInlineError(`Fehler beim Erstellen: ${error.message}`);
            showToast(`Fehler beim Erstellen: ${error.message}`, 'error');
        }
    });
}

async function init() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(console.error);
    }

    initPWA();
    setState({ deviceId: getDeviceId() });
    updatePickerIndicator();

    initHIDScanner((barcode) => handleScan(barcode));

    const voiceButton = btnVoice();
    if (voiceButton) {
        voiceButton.addEventListener('click', (event) => {
            if (suppressNextVoiceClick) {
                suppressNextVoiceClick = false;
                event.preventDefault();
                return;
            }
            onVoiceToggle();
        });

        voiceButton.addEventListener('pointerdown', () => {
            if (!isVoiceSupported()) return;
            voiceLongPressTimer = window.setTimeout(() => {
                voiceLongPressTimer = null;
                startVoiceLongPress();
            }, VOICE_LONG_PRESS_MS);
        });

        const stopPress = async () => {
            if (voiceLongPressTimer) {
                window.clearTimeout(voiceLongPressTimer);
                voiceLongPressTimer = null;
                return;
            }
            await finishVoiceLongPress();
        };

        voiceButton.addEventListener('pointerup', stopPress);
        voiceButton.addEventListener('pointercancel', stopPress);
        voiceButton.addEventListener('pointerleave', stopPress);
    }

    const scanButton = btnScan();
    if (scanButton) {
        scanButton.addEventListener('click', () => {
            openCameraScanner((barcode) => handleScan(barcode));
        });
    }

    const alertButton = btnAlert();
    if (alertButton) alertButton.addEventListener('click', openQualityAlertForm);

    const pickerButton = pickerEl();
    if (pickerButton) {
        pickerButton.addEventListener('click', async () => {
            clearStoredPicker();
            setState({ currentPicker: null });
            updatePickerIndicator();
            await loadPickingList({ forcePickerSelection: true });
        });
    }

    document.addEventListener('keydown', (event) => {
        if (event.repeat) return;
        const tagName = event.target?.tagName;
        if (tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT') return;
        if (event.key === 'm' || event.key === 'M') {
            event.preventDefault();
            onVoiceToggle();
        }
    });

    window.addEventListener('pagehide', () => {
        releaseCurrentClaim({ keepalive: true });
    });

    subscribe((state) => {
        updatePickerIndicator();
        const status = statusEl();
        if (!status) return;
        if (state.loading) {
            status.textContent = 'Laden...';
        } else if (navigator.onLine) {
            status.textContent = 'Online';
            status.className = 'status online';
        }
    });

    try {
        const response = await fetch('/api/health');
        if (response.ok) {
            statusEl().textContent = 'Online';
            statusEl().className = 'status online';
        }
    } catch {
        statusEl().textContent = 'Offline';
        statusEl().className = 'status offline';
    }

    await loadPickingList();

    const { pickings } = getState();
    const total = pickings?.length || 0;
    const urgent = pickings?.filter(picking => picking.priority === '1').length || 0;
    if (total === 0) {
        speak('Keine offenen Auftraege.');
    } else if (urgent > 0) {
        speak(`${total} Auftraege offen. ${urgent} davon dringend.`);
    } else {
        speak(`${total} Auftraege offen.`);
    }
}

window._app = {
    loadPickingList,
    loadPickingDetail,
    setFilter,
};

document.addEventListener('DOMContentLoaded', init);
