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
    assistVoice,
    claimPicking,
    clearActivePicker,
    clearStoredPicker,
    confirmLine,
    confirmClusterLine,
    createBatch,
    createIdempotencyKey,
    createQualityAlert,
    getBatch,
    getClusterSuggestions,
    validateBatch,
    getActivePicker,
    getActiveInstance,
    getAuthInstances,
    getCurrentSession,
    getDeviceId,
    getLineStock,
    getPickingDetail,
    getPickings,
    getTraceabilityDemo,
    getStoredDarkModeEnabled,
    getStoredPreferredZone,
    getStoredSearchQuery,
    loginPickerSession,
    logoutPickerSession,
    requestReplenishment,
    releasePicking,
    setActiveInstance,
    setStoredDarkModeEnabled,
    setStoredPreferredZone,
    setStoredSearchQuery,
    setTraceabilityDemoMode,
    switchPickerInstance,
    heartbeatPicking,
} from './api.js';
import { feedbackSuccess, feedbackError } from './feedback.js';
import { buildClusterStops, resolveClusterScan, setState, getState, subscribe, renderLoading, renderError, renderProductVisual, showToast } from './ui.js';
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
    setVoiceRequestContextProvider,
    setVoiceStatusListener,
} from './voice.js';
import {
    SCAN_OUTCOME,
    buildReadbackPrompt,
    buildSpeechPrompt,
    buildVoiceAssistPayload,
    buildVoiceRequestContext,
    classifyVoiceResult,
    describeScanOutcome,
    formatLocationForSpeech,
    getVoiceStatusPresentation,
} from './voice-runtime.mjs';
import { createFileInput } from './camera.js';
import { initPWA } from './pwa.js';

const CLAIM_HEARTBEAT_MS = 30_000;
const VOICE_LONG_PRESS_MS = 350;
const DEFAULT_FILTER = 'all';
const ZONE_FILTER = 'zone';
const VOICE_ASSIST_SHORTAGE_RE = /\b(fehlt|fehlmenge|mangel|nachschub|leer|restbestand)\b/i;
const DEFAULT_THEME_COLOR = '#F6F8FC';
const DARK_THEME_COLOR = '#0F1728';
const LIFECYCLE_REFRESH_DEBOUNCE_MS = 900;
const lineStockCache = new Map();

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

function getPickingKitName(picking) {
    return String(picking?.kit_name || '').trim();
}

function getPickingTypeLabel(picking) {
    const rawLabel = picking?.picking_type_id?.[1] || '';
    return rawLabel.split(':').pop().trim();
}

function getPickingPrimaryLabel(picking) {
    return picking?.primary_item_display || getPickingReference(picking);
}

function getPickingHeadline(picking) {
    return getPickingKitName(picking) || getPickingPrimaryLabel(picking);
}

function getPickingOpeningPrompt(picking) {
    const intro = String(picking?.voice_intro || '').trim();
    if (intro) return intro;
    const firstLine = picking?.move_lines?.[0];
    return getLineSpeechPrompt(firstLine);
}

function getOpenLineLabel(count) {
    const safeCount = Number(count || 0);
    return safeCount === 1 ? '1 Position offen' : `${safeCount} Positionen offen`;
}

function getTotalLineCount(picking) {
    const total = Number(picking?.total_line_count ?? 0);
    return Number.isFinite(total) ? total : 0;
}

function getCompletedLineCount(picking) {
    const completed = Number(picking?.completed_line_count ?? 0);
    return Number.isFinite(completed) ? completed : 0;
}

function getProgressRatio(picking) {
    const raw = Number(picking?.progress_ratio ?? 0);
    const fallbackTotal = getTotalLineCount(picking);
    const fallbackCompleted = getCompletedLineCount(picking);
    const fallbackRatio = fallbackTotal > 0 ? fallbackCompleted / fallbackTotal : 0;
    const safeRatio = Number.isFinite(raw) ? raw : fallbackRatio;
    return Math.max(0, Math.min(1, safeRatio));
}

function getProgressLabel(picking) {
    const total = getTotalLineCount(picking);
    const completed = getCompletedLineCount(picking);
    if (total <= 0) return '0 / 0 Positionen';
    return `${completed} / ${total} Positionen`;
}

function formatZoneLabel(zoneKey) {
    if (!zoneKey) return 'Ohne Bereich';
    return zoneKey
        .split('-')
        .filter(Boolean)
        .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
        .join(' ');
}

function getPrimaryZoneLabel(picking) {
    return formatZoneLabel(picking?.primary_zone_key || '');
}

function getPickingPrimaryProductId(picking) {
    if (picking?.primary_product_id) return picking.primary_product_id;
    const firstLineWithProduct = (picking?.move_lines || []).find((line) => line?.product_id);
    return firstLineWithProduct?.product_id || null;
}

function getPrimaryItemSku(picking) {
    return picking?.primary_item_sku || '';
}

function getNextPickingCandidate(pickings = [], { excludeId = null } = {}) {
    const candidates = (pickings || []).filter((picking) => picking?.id && picking.id !== excludeId);
    return candidates.find((picking) => picking.priority === '1') || candidates[0] || null;
}

function getListScopeLabel() {
    if (activeFilter === 'high') return 'Nur dringende Aufträge';
    if (activeFilter === ZONE_FILTER && preferredZone?.label) return preferredZone.label;
    return 'Alle Bereiche';
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function normalizeSearchText(value) {
    return String(value || '')
        .toLowerCase()
        .replace(/ä/g, 'ae')
        .replace(/ö/g, 'oe')
        .replace(/ü/g, 'ue')
        .replace(/ß/g, 'ss')
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .trim();
}

function buildSearchHaystack(picking) {
    return normalizeSearchText([
        getPickingKitName(picking),
        getPickingReference(picking),
        getPickingPrimaryLabel(picking),
        getPrimaryItemSku(picking),
        picking?.next_location_short,
        picking?.partner_id?.[1] || '',
        getPrimaryZoneLabel(picking),
    ].join(' '));
}

function filterBySearch(pickings, query) {
    const normalizedQuery = normalizeSearchText(query);
    if (!normalizedQuery) return pickings;
    return pickings.filter((picking) => buildSearchHaystack(picking).includes(normalizedQuery));
}

function filterByActiveChip(pickings) {
    if (activeFilter === 'high') {
        return pickings.filter((picking) => picking.priority === '1');
    }
    if (activeFilter === ZONE_FILTER) {
        return pickings.filter((picking) => picking.primary_zone_key === preferredZone?.key);
    }
    return pickings;
}

function collectZoneOptions(pickings) {
    const counts = new Map();
    for (const picking of pickings) {
        const key = picking.primary_zone_key;
        if (!key) continue;
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts.entries()]
        .map(([key, count]) => ({
            key,
            count,
            label: formatZoneLabel(key),
        }))
        .sort((left, right) => left.label.localeCompare(right.label, 'de-DE'));
}

function getLineDisplayName(line) {
    return line?.ui_display || line?.product_short_name || line?.product_name || 'Produkt';
}

function getLineQuantityLabel(line) {
    return `${formatQuantity(line?.quantity_demand)} Stück`;
}

function getLineSpeechPrompt(line) {
    // Concise, natural speech: product, qty, short location. Never spells out a
    // raw fach code. See buildSpeechPrompt in voice-runtime.mjs.
    return buildSpeechPrompt(line);
}

function renderRouteHint(picking, currentLineIndex) {
    const routePlan = picking?.route_plan;
    const lines = picking?.move_lines || [];
    if (!routePlan || currentLineIndex >= lines.length) return '';

    const remainingLines = lines.slice(currentLineIndex + 1);
    if (!remainingLines.length) return '';
    const remainingTravelScore = (routePlan.stops || [])
        .slice(currentLineIndex + 1)
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
        <section class="route-hint" aria-label="Naechster Halt auf der Route">
            <div class="route-hint__eyebrow">Danach auf der Route</div>
            <div class="route-hint__title">Nächster Halt: ${nextLocation}</div>
            <div class="route-hint__meta">
                ${remainingLines.length} Stopps offen - Laufweg-Score ${remainingTravelScore}
            </div>
            <div class="route-hint__chips">
                ${zonePreview.map((zone) => `<span class="route-hint__chip">${zone}</span>`).join('')}
            </div>
        </section>
    `;
}

function renderDetailLineList(lines, currentLineIndex) {
    if (!Array.isArray(lines) || lines.length <= 1) return '';

    return `
        <section class="detail-line-list" aria-label="Positionen im Auftrag">
            <div class="detail-line-list__header">
                <div>
                    <div class="detail-line-list__eyebrow">Auftragspositionen</div>
                    <div class="detail-line-list__title">${lines.length} Positionen im Ablauf</div>
                </div>
                <div class="detail-line-list__count">${currentLineIndex + 1} / ${lines.length}</div>
            </div>
            <div class="detail-line-list__items">
                ${lines.map((entry, idx) => {
                    const entryName = getLineDisplayName(entry);
                    const entryMeta = [
                        getLineQuantityLabel(entry),
                        entry.product_sku || entry.location_src_zone || '',
                    ].filter(Boolean).join(' · ');
                    const entryLocation = entry.location_src_short || formatLocationForDisplay(entry.location_src);

                    return `
                        <button class="detail-line-item ${idx === currentLineIndex ? 'detail-line-item--active' : ''}"
                                onclick="window._app.goToLine(${idx})">
                            ${renderProductVisual({
                                productId: entry.product_id || null,
                                label: entryName,
                                className: 'detail-line-item__thumb product-visual product-visual--thumb',
                                loading: 'eager',
                                size: 256,
                            })}
                            <span class="detail-line-item__copy">
                                <span class="detail-line-item__idx">${idx + 1}</span>
                                <span class="detail-line-item__name">${escapeHtml(entryName)}</span>
                                <span class="detail-line-item__meta">${escapeHtml(entryMeta)}</span>
                            </span>
                            <span class="detail-line-item__loc">${escapeHtml(entryLocation)}</span>
                        </button>
                    `;
                }).join('')}
            </div>
        </section>
    `;
}

let activeFilter = DEFAULT_FILTER;
let claimHeartbeatTimer = null;
let claimedPickingId = null;
let serialPromptActive = false;
let serialPromptCleanup = null;
let cartonPromptActive = false;
let cartonPromptCleanup = null;
let confirmAllInProgress = false;
let voiceLongPressTimer = null;
let voiceLongPressStarted = false;
let suppressNextVoiceClick = false;
let voiceStatusResetTimer = null;
let searchQuery = getStoredSearchQuery();
let mobileSearchOpen = Boolean(searchQuery);
let preferredZone = getStoredPreferredZone();
let darkModeEnabled = getStoredDarkModeEnabled();
let sessionState = 'profile_required';
let verifiedClusterStopKey = '';
let verifiedClusterProductBarcode = '';
let clusterConfirmPending = false;
let lastLifecycleRefreshAt = 0;
let lifecycleRefreshPromise = null;
const pendingRequestControllers = new Set();

const mainEl = () => document.getElementById('main');
const headerEl = () => document.getElementById('header');
const statusEl = () => document.getElementById('status-indicator');
const statusBtnEl = () => document.getElementById('status-btn');
const statusDotEl = () => document.getElementById('status-dot');
const voiceStatusEl = () => document.getElementById('voice-status-indicator');
const pickerEl = () => document.getElementById('picker-indicator');
const pickerNameEl = () => document.getElementById('picker-name');
const pickerAvatarEl = () => document.getElementById('picker-avatar');
const greetingNameEl = () => document.getElementById('greeting-name');
const searchRowEl = () => document.querySelector('.search-row');
const searchInputEl = () => document.getElementById('search-input');
const taskCounterEl = () => document.getElementById('task-counter');
const filterChipsEl = () => document.getElementById('filter-chips');
const filterRowEl = () => document.querySelector('.header-row--filters');
const themeToggleEl = () => document.getElementById('theme-toggle');
const searchToggleEl = () => document.getElementById('search-toggle');
const instanceSwitchEl = () => document.getElementById('instance-switch');
const demoTraceabilityModeEl = () => document.getElementById('demo-traceability-mode');
const overlayEl = () => document.getElementById('app-overlay');
const navEl = () => document.getElementById('nav');
const btnVoice = () => document.getElementById('btn-voice');
const btnScan = () => document.getElementById('btn-scan');
const btnAlert = () => document.getElementById('btn-alert');
const themeColorMetaEl = () => document.querySelector('meta[name="theme-color"]');
const statusBarMetaEl = () => document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]');

function getPickerShortLabel(picker) {
    const normalizedName = String(picker?.name || '')
        .trim()
        .replace(/\s+/g, ' ');
    if (!normalizedName) return '?';
    return normalizedName
        .split(' ')
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase() || '')
        .join('') || '?';
}

function createManagedAbortController() {
    const controller = new AbortController();
    pendingRequestControllers.add(controller);
    controller.signal.addEventListener('abort', () => {
        pendingRequestControllers.delete(controller);
    }, { once: true });
    return controller;
}

// A session can expire mid-shift, and every gated route then answers 401. This
// is the one seam every API call in this module passes through, so the fallback
// to the login screen lives here rather than in ~30 catch blocks that would each
// have to remember it.
//
// `handleExpiry: false` is mandatory for the calls that are ALLOWED to see a
// 401 as their own answer -- the login itself (wrong password) and the session
// probe (no session yet). Without that they would recurse into this handler.
let sessionExpiryPending = false;

async function withManagedRequest(task, { handleExpiry = true } = {}) {
    const controller = createManagedAbortController();
    try {
        return await task(controller.signal);
    } catch (error) {
        if (handleExpiry && error instanceof ApiError && error.status === 401) {
            handleSessionExpired();
        }
        throw error;
    } finally {
        pendingRequestControllers.delete(controller);
    }
}

function handleSessionExpired() {
    if (sessionExpiryPending || sessionState === 'profile_required') return;
    sessionExpiryPending = true;
    // `api.js` has already dropped the CSRF token and the active picker on the
    // 401 itself; this clears the view state that mirrors them.
    clearStoredPicker();
    setState({
        currentPicker: null,
        currentPicking: null,
        currentLineIndex: 0,
        pickings: [],
    });
    stopClaimHeartbeat();
    void showLoginScreen({
        statusNote: 'Die Sitzung ist abgelaufen. Bitte melde dich erneut an.',
    }).finally(() => {
        sessionExpiryPending = false;
    });
}

function abortPendingRequests() {
    for (const controller of Array.from(pendingRequestControllers)) {
        controller.abort();
    }
    pendingRequestControllers.clear();
}

function isAbortError(error) {
    return error?.name === 'AbortError';
}

function resetMainScroll() {
    const main = mainEl();
    if (main) main.scrollTop = 0;
}

function setMainContent(markup, { resetScroll = true } = {}) {
    const main = mainEl();
    if (!main) return;
    main.innerHTML = markup;
    if (resetScroll) resetMainScroll();
}

function syncThemeChrome() {
    const themeColor = darkModeEnabled ? DARK_THEME_COLOR : DEFAULT_THEME_COLOR;
    document.documentElement.style.colorScheme = darkModeEnabled ? 'dark' : 'light';
    themeColorMetaEl()?.setAttribute('content', themeColor);
    statusBarMetaEl()?.setAttribute('content', darkModeEnabled ? 'black-translucent' : 'default');
}

function resetSearchUi() {
    searchQuery = '';
    mobileSearchOpen = false;
    setStoredSearchQuery('');
    const input = searchInputEl();
    if (input) input.value = '';
    applyMobileSearchState();
}

function resetOperatorUiState() {
    activeFilter = DEFAULT_FILTER;
    preferredZone = null;
    setStoredPreferredZone(null);
    resetSearchUi();
    setState({
        pickings: [],
        currentPicking: null,
        currentLineIndex: 0,
    });
}

function getStatusShortLabel(kind) {
    switch (kind) {
        case 'online':
            return 'ON';
        case 'offline':
            return 'OFF';
        case 'sync':
            return '...';
        case 'listening':
            return 'MIC';
        case 'speaking':
            return 'TTS';
        case 'recognized':
            return 'OK';
        case 'uncertain':
            return '??';
        case 'idle':
        default:
            return 'MIC';
    }
}

function updateToolbar(view) {
    const previousView = sessionState;
    sessionState = view;
    const visualView = view === 'search_expanded' ? 'list' : view;
    const showDetailTools = visualView === 'detail';
    const showClusterScan = visualView === 'cluster_walk';
    btnVoice()?.classList.toggle('hidden', !showDetailTools);
    btnAlert()?.classList.toggle('hidden', !showDetailTools);
    btnScan()?.classList.toggle('hidden', !(showDetailTools || showClusterScan));
    const nav = navEl();
    if (nav) nav.classList.toggle('hidden', !(showDetailTools || showClusterScan));
    if (!showDetailTools) {
        btnVoice()?.classList.remove('nav-btn--ptt');
        if (isVoiceModeActive()) stopVoiceMode();
    }
    if (previousView === 'cluster_walk' && view !== 'cluster_walk') {
        resetClusterScanState();
    }

    const scanButton = btnScan();
    if (scanButton) {
        scanButton.setAttribute(
            'aria-label',
            showClusterScan ? 'Cluster-Barcode mit Kamera scannen' : 'Kamera-Scan starten',
        );
        const meta = scanButton.querySelector('.nav-btn__meta');
        if (meta) meta.textContent = showClusterScan ? 'Artikel / Karton' : 'Kamera';
    }

    document.body.dataset.view = visualView;
    document.body.dataset.sessionState = view;
    const searchInput = searchInputEl();
    const searchEnabled = view === 'list' || view === 'search_expanded';
    const compactHeader = !searchEnabled && view !== 'profile_required';
    if (searchInput) searchInput.disabled = !searchEnabled;
    searchRowEl()?.toggleAttribute('hidden', !searchEnabled);
    filterRowEl()?.toggleAttribute('hidden', !searchEnabled);
    searchToggleEl()?.toggleAttribute('hidden', !searchEnabled);
    headerEl()?.classList.toggle('header--picker-only', view === 'profile_required');
    headerEl()?.classList.toggle('header--compact', compactHeader);
}

function updatePickerIndicator() {
    const indicator = pickerEl();
    if (!indicator) return;
    const picker = getState().currentPicker;
    if (picker?.name) {
        const shortLabel = getPickerShortLabel(picker);
        const firstName = picker.name.split(/\s+/)[0] || picker.name;
        if (pickerNameEl()) pickerNameEl().textContent = picker.name;
        if (pickerAvatarEl()) pickerAvatarEl().textContent = shortLabel;
        if (greetingNameEl()) greetingNameEl().textContent = firstName;
        indicator.title = picker.name;
        indicator.setAttribute('aria-label', picker.name);
        indicator.dataset.shortLabel = shortLabel;
        indicator.classList.remove('picker-indicator--empty');
    } else {
        if (pickerNameEl()) pickerNameEl().textContent = 'Profil wählen';
        if (pickerAvatarEl()) pickerAvatarEl().textContent = 'PW';
        if (greetingNameEl()) greetingNameEl().textContent = 'Picker';
        indicator.title = 'Profil wählen';
        indicator.setAttribute('aria-label', 'Profil wählen');
        indicator.dataset.shortLabel = '+';
        indicator.classList.add('picker-indicator--empty');
    }
}

async function initInstanceSwitch() {
    const select = instanceSwitchEl();
    if (!select) return;

    let instances = [];
    try {
        // `/instances` haengt am Entwicklungs-Router: `create_app` schliesst
        // ihn unter RUNTIME_PROFILE=production gar nicht ein, die Anfrage
        // endet dort mit 404. Der Umschalter fiel deshalb auf die
        // Ein-Lager-Liste zurueck und blendete sich aus -- am 2026-09-05 im
        // Produktionsprofil gemessen. `/auth/instances` liefert dieselben
        // Felder (Name, Anzeigename, keine Secrets) und existiert in beiden
        // Profilen; der Loginscreen liest schon von dort.
        instances = await withManagedRequest((signal) => getAuthInstances({ signal }));
    } catch (error) {
        if (!isAbortError(error)) {
            console.warn('Odoo-Instanzen konnten nicht geladen werden:', error);
        }
        instances = [{ name: 'local', display_name: 'Lager 1' }];
    }

    const validInstances = Array.isArray(instances)
        ? instances
            .map((item) => ({
                name: String(item?.name || '').trim().toLowerCase(),
                display_name: String(item?.display_name || item?.name || '').trim(),
            }))
            .filter((item) => item.name)
        : [];

    if (validInstances.length <= 1) {
        setActiveInstance('local');
        select.hidden = true;
        return;
    }

    const validNames = new Set(validInstances.map((item) => item.name));
    let active = getActiveInstance();
    if (!validNames.has(active)) {
        active = 'local';
        setActiveInstance(active);
    }

    select.innerHTML = '';
    for (const instance of validInstances) {
        const option = document.createElement('option');
        option.value = instance.name;
        option.textContent = instance.display_name || instance.name;
        option.selected = instance.name === active;
        select.appendChild(option);
    }

    select.hidden = false;
    // Ein Lagerwechsel ist ein neuer LOGIN, keine Umschaltung einer Anzeige.
    // Das Backend liest die Instanz ausschliesslich aus dem Sitzungs-Cookie
    // (`v1.<instanz>.<token>`, `parse_session_token`), und die Sitzung selbst
    // liegt in der Odoo-Datenbank JENER Instanz. Ein Klick kann sie nicht
    // umbiegen -- die alte Sitzung muss enden und eine neue entstehen.
    //
    // Vorher schrieb dieser Zweig nur den localStorage und lud neu. Das Cookie
    // blieb bestehen, `getCurrentSession()` holte die alte Instanz zurueck und
    // ueberschrieb die Auswahl (`setActiveInstance(principal.odoo_instance)`,
    // api.js). Sichtbar stand danach "Lager 2", geliefert wurde Lager 1 --
    // am 2026-08-16 gemessen: nach dem Wechsel derselbe Auftragsbestand.
    //
    // Kein `{ once: true }` mehr: ohne den Reload muss der Zuhoerer den
    // zweiten Wechsel ueberleben.
    select.addEventListener('change', () => {
        void switchInstance(select.value);
    });
}

// Haelt die Anzeige an der WIRKLICH angemeldeten Instanz. Die Liste entsteht
// vor der Sitzungspruefung, also aus dem Speicher; erst `/auth/me` sagt, was
// gilt. Ohne diesen Abgleich kann das Feld etwas anderes behaupten als das
// Cookie -- genau die Luege, die den Fehler so zaeh gemacht hat.
function syncInstanceSwitch() {
    const select = instanceSwitchEl();
    if (!select || select.hidden) return;
    const aktiv = getActiveInstance();
    if (select.value !== aktiv) select.value = aktiv;
}

// Tauscht die Sitzung gegen eine im anderen Lager, ohne nach dem Passwort zu
// fragen: dieselben Menschen bedienen beide Lager, und das Backend prueft, ob
// derselbe Anmeldename dort eine Rolle traegt (`/auth/switch-instance`).
// Verweigert es das, bleibt der ehrliche Weg ueber den Login-Schirm.
async function switchInstance(name) {
    const gewaehlt = String(name || '').trim().toLowerCase();
    if (!gewaehlt || gewaehlt === getActiveInstance()) return;

    // Der Anspruch auf einen Auftrag gehoert dem ALTEN Lager und braucht die
    // alte Sitzung -- also zurueckgeben, solange sie noch gilt.
    updateToolbar('switching_profile');
    abortPendingRequests();
    stopSpeaking();
    closeOverlay();
    lineStockCache.clear();
    stopClaimHeartbeat();
    if (isVoiceModeActive()) stopVoiceMode();
    btnVoice()?.classList.remove('nav-btn--ptt');
    await releaseCurrentClaim();

    try {
        await withManagedRequest(
            (signal) => switchPickerInstance(gewaehlt, { signal }),
            { handleExpiry: false },
        );
    } catch (error) {
        if (isAbortError(error)) return;
        // Kein Konto dieses Namens im Ziel-Lager, keine Rolle dort, oder die
        // Sitzung ist abgelaufen. Dann zaehlt die Wahl trotzdem -- sie steht
        // auf dem Login-Schirm vorausgewaehlt bereit.
        console.warn('Lagerwechsel ohne Anmeldung nicht moeglich:', error);
        setActiveInstance(gewaehlt);
        try {
            await switchProfile();
        } catch (abmeldefehler) {
            console.warn('Lagerwechsel: Abmelden fehlgeschlagen:', abmeldefehler);
            await showLoginScreen();
        }
        syncInstanceSwitch();
        return;
    }

    setState({ currentPicking: null, currentLineIndex: 0, pickings: [] });
    updatePickerIndicator();
    syncInstanceSwitch();
    // `skipRelease`, weil der Anspruch oben schon zurueckgegeben wurde -- ein
    // zweiter Versuch liefe gegen das neue Lager, wo es ihn nie gab.
    await loadPickingList({ skipRelease: true });
}

async function initDemoTraceabilitySwitch() {
    const select = demoTraceabilityModeEl();
    if (!select) return;

    let status = null;
    try {
        status = await withManagedRequest((signal) => getTraceabilityDemo({ signal }));
    } catch (error) {
        if (!isAbortError(error)) {
            console.warn('Traceability-Demo konnte nicht geladen werden:', error);
        }
        select.hidden = true;
        return;
    }

    if (!status?.enabled || !Array.isArray(status.modes)) {
        select.hidden = true;
        return;
    }

    select.innerHTML = '';
    for (const mode of status.modes) {
        const option = document.createElement('option');
        option.value = String(mode.name || '');
        option.textContent = String(mode.label || mode.name || '');
        option.title = String(mode.description || '');
        option.selected = option.value === status.mode;
        select.appendChild(option);
    }
    select.hidden = false;

    select.addEventListener('change', async () => {
        const mode = select.value;
        select.disabled = true;
        showToast('Traceability-Demo wird umgeschaltet...', 'info');
        try {
            const result = await withManagedRequest((signal) => setTraceabilityDemoMode(mode, {
                idempotencyKey: buildOperationKey('demo-traceability', [getActiveInstance(), mode], { unique: true }),
                signal,
            }));
            showToast(`Traceability: ${result.message || mode}`, 'success');
            await loadPickingList();
        } catch (error) {
            showToast(error.message || 'Demo-Modus konnte nicht gesetzt werden.', 'error');
        } finally {
            select.disabled = false;
        }
    });
}

function updateConnectivityStatus({ loading = false } = {}) {
    const indicator = statusEl();
    if (!indicator) return;

    if (loading) {
        indicator.textContent = 'Sync';
        indicator.className = 'status status--sync';
        indicator.dataset.shortLabel = getStatusShortLabel('sync');
        indicator.title = 'Synchronisiert';
        statusBtnEl()?.setAttribute('title', 'Synchronisiert');
        statusDotEl()?.classList.remove('offline');
        return;
    }

    if (navigator.onLine) {
        indicator.textContent = 'Online';
        indicator.className = 'status online';
        indicator.dataset.shortLabel = getStatusShortLabel('online');
        indicator.title = 'Online';
        statusBtnEl()?.setAttribute('title', 'Online');
        statusDotEl()?.classList.remove('offline');
        return;
    }

    indicator.textContent = 'Offline';
    indicator.className = 'status offline';
    indicator.dataset.shortLabel = getStatusShortLabel('offline');
    indicator.title = 'Offline';
    statusBtnEl()?.setAttribute('title', 'Offline');
    statusDotEl()?.classList.add('offline');
}

function clearVoiceStatusReset() {
    if (!voiceStatusResetTimer) return;
    window.clearTimeout(voiceStatusResetTimer);
    voiceStatusResetTimer = null;
}

function updateVoiceStatusIndicator(kind = 'idle', { temporary = false } = {}) {
    const indicator = voiceStatusEl();
    if (!indicator) return;

    const presentation = getVoiceStatusPresentation(kind);
    indicator.textContent = presentation.label;
    indicator.className = `status voice-status voice-status--${presentation.tone}`;
    indicator.dataset.shortLabel = getStatusShortLabel(presentation.tone);
    indicator.title = presentation.label;

    clearVoiceStatusReset();
    if (temporary) {
        voiceStatusResetTimer = window.setTimeout(() => {
            voiceStatusResetTimer = null;
            updateVoiceStatusIndicator(isVoiceModeActive() || isPushToTalkActive() ? 'listening' : 'idle');
        }, 1400);
    }
}

function getCurrentVoiceView() {
    return document.body.dataset.view || 'list';
}

function getCurrentVoiceRequestContext() {
    const { currentPicking, currentLineIndex } = getState();
    return buildVoiceRequestContext({
        view: getCurrentVoiceView(),
        currentPicking,
        currentLineIndex,
    });
}

function updateTaskCounter(count) {
    const counter = taskCounterEl();
    if (!counter) return;
    const safeCount = Number(count || 0);
    counter.textContent = safeCount === 1 ? '1 Aufgabe offen' : `${safeCount} Aufgaben offen`;
}

function applyDarkTheme() {
    document.documentElement.dataset.theme = darkModeEnabled ? 'dark' : 'light';
    syncThemeChrome();
    const toggle = themeToggleEl();
    if (!toggle) return;
    toggle.setAttribute('aria-pressed', darkModeEnabled ? 'true' : 'false');
    toggle.classList.toggle('status-toggle--active', darkModeEnabled);
    toggle.title = darkModeEnabled ? 'Light Mode einschalten' : 'Dark Mode einschalten';
    toggle.setAttribute('aria-label', toggle.title);
}

function applyMobileSearchState() {
    document.body.dataset.searchOpen = mobileSearchOpen ? 'true' : 'false';
    const toggle = searchToggleEl();
    if (!toggle) return;
    toggle.setAttribute('aria-pressed', mobileSearchOpen ? 'true' : 'false');
    toggle.classList.toggle('status-toggle--active', mobileSearchOpen);
    toggle.title = mobileSearchOpen ? 'Suche geöffnet' : 'Suche';
}

function openMobileSearch({ focus = false } = {}) {
    if (sessionState !== 'list' && sessionState !== 'search_expanded') return;
    mobileSearchOpen = true;
    updateToolbar('search_expanded');
    applyMobileSearchState();
    if (focus) {
        window.requestAnimationFrame(() => {
            searchInputEl()?.focus();
        });
    }
}

async function closeMobileSearch() {
    mobileSearchOpen = false;
    if (sessionState === 'search_expanded') updateToolbar('list');
    applyMobileSearchState();
    if (!searchQuery && !getState().currentPicking) {
        await loadPickingList({ skipRelease: true });
    }
}

function shouldActivateServiceWorkerUpdate() {
    return sessionState !== 'alert';
}

function handleServiceWorkerUpdateReady() {
    if (sessionState === 'alert') {
        showToast('App-Update bereit. Nach dem Absenden bitte neu öffnen.', 'info');
    }
}

function handleServiceWorkerControllerRefresh() {
    if (sessionState === 'alert') {
        showToast('App aktualisiert. Nach dem Absenden neu laden.', 'info');
        return;
    }
    window.location.reload();
}

function shouldRunLifecycleRefresh() {
    const now = Date.now();
    if (now - lastLifecycleRefreshAt < LIFECYCLE_REFRESH_DEBOUNCE_MS) return false;
    lastLifecycleRefreshAt = now;
    return true;
}

async function refreshActivePickingDetail() {
    const { currentPicking, currentLineIndex, currentPicker } = getState();
    if (!currentPicking?.id || !currentPicker?.id) return;

    try {
        if (claimedPickingId === currentPicking.id) {
            await withManagedRequest((signal) => heartbeatPicking(currentPicking.id, {
                idempotencyKey: buildOperationKey('heartbeat-refresh', [currentPicking.id, Date.now()], { unique: true }),
                signal,
            }));
            startClaimHeartbeat(currentPicking.id);
        }

        const refreshedPicking = await withManagedRequest((signal) => getPickingDetail(currentPicking.id, { signal }));
        const nextLineIndex = Math.min(
            currentLineIndex,
            Math.max((refreshedPicking.move_lines || []).length - 1, 0),
        );

        setState({
            currentPicking: refreshedPicking,
            currentLineIndex: nextLineIndex,
        });
        renderResponsiveCurrentLine();
    } catch (error) {
        if (isAbortError(error)) return;
        if (error instanceof ApiError && error.status === 409 && typeof error.detail === 'object') {
            claimedPickingId = null;
            stopClaimHeartbeat();
            renderClaimConflict(error.detail, currentPicking.id);
            return;
        }
        if (error instanceof ApiError && (error.status === 400 || error.status === 403)) {
            showToast('Profil bitte neu wählen.', 'warning');
            await switchProfile();
            return;
        }
        showToast(`Ansicht konnte nicht aktualisiert werden: ${error.message}`, 'warning');
        updateConnectivityStatus();
    }
}

async function refreshCurrentView() {
    if (!navigator.onLine || !shouldRunLifecycleRefresh()) return;
    if (lifecycleRefreshPromise) return lifecycleRefreshPromise;

    lifecycleRefreshPromise = (async () => {
        if (sessionState === 'alert') return;

        if (!getState().currentPicker) {
            if (sessionState === 'profile_required') {
                await showLoginScreen();
            }
            return;
        }

        if (sessionState === 'detail') {
            await refreshActivePickingDetail();
            return;
        }

        if (sessionState === 'complete' || sessionState === 'locked') {
            await loadPickingList({ skipRelease: true });
            return;
        }

        if (sessionState === 'list' || sessionState === 'search_expanded') {
            await loadPickingList({ skipRelease: true });
        }
    })().finally(() => {
        lifecycleRefreshPromise = null;
    });

    return lifecycleRefreshPromise;
}

function renderFilterChips(basePickings) {
    const chipsHost = filterChipsEl();
    if (!chipsHost) return;

    const urgentCount = basePickings.filter((picking) => picking.priority === '1').length;
    const zoneCount = preferredZone?.key
        ? basePickings.filter((picking) => picking.primary_zone_key === preferredZone.key).length
        : 0;
    const zoneLabel = preferredZone?.label || 'Mein Bereich';

    chipsHost.innerHTML = `
        <button type="button" class="filter-chip ${activeFilter === DEFAULT_FILTER ? 'filter-chip--active' : ''}" data-filter="${DEFAULT_FILTER}" aria-pressed="${activeFilter === DEFAULT_FILTER}">
            Alle (${basePickings.length})
        </button>
        <button type="button" class="filter-chip ${activeFilter === 'high' ? 'filter-chip--active' : ''}" data-filter="high" aria-pressed="${activeFilter === 'high'}">
            Dringend (${urgentCount})
        </button>
        <button type="button" class="filter-chip ${activeFilter === ZONE_FILTER ? 'filter-chip--active' : ''}" data-filter="${ZONE_FILTER}" aria-pressed="${activeFilter === ZONE_FILTER}">
            ${zoneLabel} (${zoneCount})
        </button>
    `;

    chipsHost.querySelectorAll('[data-filter]').forEach((button) => {
        button.addEventListener('click', async () => {
            await setFilter(button.dataset.filter);
        });
    });
}

function closeOverlay() {
    const overlay = overlayEl();
    if (!overlay) return;
    // Wird das Overlay extern geschlossen (z. B. Navigation), einen offenen
    // Seriennummer-/Karton-Prompt sauber als "Ueberspringen" aufloesen statt haengen zu lassen.
    if (serialPromptCleanup) serialPromptCleanup();
    if (cartonPromptCleanup) cartonPromptCleanup();
    overlay.onclick = null;
    overlay.hidden = true;
    overlay.innerHTML = '';
}

function openZonePicker(pickings) {
    const overlay = overlayEl();
    if (!overlay) return;

    const zones = collectZoneOptions(pickings);
    if (!zones.length) {
        showToast('Aktuell sind keine Bereiche verfügbar.', 'warning');
        activeFilter = DEFAULT_FILTER;
        renderResponsivePickingsView(pickings);
        return;
    }

    overlay.hidden = false;
    overlay.innerHTML = `
        <div class="modal-sheet" role="dialog" aria-modal="true" aria-labelledby="zone-picker-title">
            <div class="modal-sheet__eyebrow">Mein Bereich</div>
            <h2 id="zone-picker-title" class="modal-sheet__title">Bevorzugten Bereich wählen</h2>
            <p class="modal-sheet__text">
                Der Filter zeigt danach Aufträge, deren nächster Halt in diesem Bereich liegt.
            </p>
            <div class="modal-sheet__actions modal-sheet__actions--stack">
                ${zones.map((zone) => `
                    <button type="button" class="picker-option" data-zone-key="${escapeHtml(zone.key)}" data-zone-label="${escapeHtml(zone.label)}">
                        ${escapeHtml(zone.label)} <span class="picker-option__meta">${zone.count} Aufträge</span>
                    </button>
                `).join('')}
            </div>
            <div class="modal-sheet__footer">
                <button type="button" id="zone-picker-cancel" class="picker-option">Abbrechen</button>
                ${preferredZone?.key ? '<button type="button" id="zone-picker-clear" class="picker-option">Bereich löschen</button>' : ''}
            </div>
        </div>
    `;

    overlay.onclick = (event) => {
        if (event.target === overlay) closeOverlay();
    };

    overlay.querySelectorAll('[data-zone-key]').forEach((button) => {
        button.addEventListener('click', async () => {
            preferredZone = {
                key: button.dataset.zoneKey,
                label: button.dataset.zoneLabel,
            };
            setStoredPreferredZone(preferredZone);
            activeFilter = ZONE_FILTER;
            closeOverlay();
            await loadPickingList({ skipRelease: true });
        });
    });

    overlay.querySelector('#zone-picker-cancel')?.addEventListener('click', () => {
        closeOverlay();
    });

    overlay.querySelector('#zone-picker-clear')?.addEventListener('click', async () => {
        preferredZone = null;
        setStoredPreferredZone(null);
        activeFilter = DEFAULT_FILTER;
        closeOverlay();
        await loadPickingList({ skipRelease: true });
    });
}

function renderListEmptyState(message, detail = 'Passe Suche oder Filter an, um weitere Aufträge einzublenden.') {
    return `
        <div class="state-panel">
            <div class="state-panel__eyebrow">Listenstatus</div>
            <div class="state-panel__title">${escapeHtml(message)}</div>
            <div class="state-panel__meta">${escapeHtml(detail)}</div>
        </div>
    `;
}

function renderWorkspaceQueueOverview(visiblePickings, { variant = 'main' } = {}) {
    const urgentCount = visiblePickings.filter((picking) => picking.priority === '1').length;
    const pickerName = getState().currentPicker?.name || 'Kein Profil aktiv';
    const activePicking = getState().currentPicking;
    const nextPicking = activePicking || getNextPickingCandidate(visiblePickings);
    const ctaLabel = activePicking
        ? `Fortsetzen: ${escapeHtml(getPickingReference(activePicking))}`
        : urgentCount > 0
            ? `N\u00e4chsten Prio-Pick starten (${urgentCount} dringend)`
            : 'Picking starten';
    const helperCopy = activePicking
        ? 'Aktives Picking ist bereits vorbereitet.'
        : urgentCount > 0
            ? 'Dringende Auftr\u00e4ge werden zuerst vorgeschlagen.'
            : 'Starte direkt mit dem n\u00e4chsten offenen Auftrag.';
    const ctaHtml = nextPicking
        ? `<button class="btn-big btn-big--primary queue-cta" data-queue-cta="true" data-id="${nextPicking.id}">${ctaLabel}</button>`
        : '';

    return `
        <section class="queue-overview queue-overview--${variant}" aria-label="Arbeitsbereich">
            <div class="queue-overview__eyebrow">Arbeitsbereich</div>
            <div class="queue-overview__title">${visiblePickings.length} offene Auftr\u00e4ge</div>
            <div class="queue-overview__meta">${escapeHtml(pickerName)}</div>
            <div class="queue-overview__stats">
                <div class="queue-stat ${urgentCount > 0 ? 'queue-stat--warning' : ''}">
                    <span class="queue-stat__label">Dringend</span>
                    <span class="queue-stat__value">${urgentCount}</span>
                </div>
                <div class="queue-stat">
                    <span class="queue-stat__label">Bereich</span>
                    <span class="queue-stat__value">${escapeHtml(getListScopeLabel())}</span>
                </div>
                <div class="queue-stat">
                    <span class="queue-stat__label">Suche</span>
                    <span class="queue-stat__value">${searchQuery ? 'Aktiv' : 'Aus'}</span>
                </div>
            </div>
            <div class="queue-overview__helper">${helperCopy}</div>
            ${ctaHtml}
            <button type="button" class="cluster-entry-btn" data-cluster-start>
                Mehrere Aufträge bündeln (Cluster-Picking)
            </button>
        </section>
    `;
}

function bindQueueCtaButtons() {
    mainEl().querySelectorAll('[data-queue-cta="true"]').forEach((button) => {
        button.addEventListener('click', () => loadPickingDetail(Number(button.dataset.id)));
    });
}

function renderPickingListCard(picking) {
    const reference = getPickingReference(picking);
    const typeName = getPickingTypeLabel(picking);
    const primaryLabel = getPickingHeadline(picking);
    // Artikelbezeichnung und Artikelnummer der ERSTEN Position standen frueher
    // unter der Ueberschrift. Sie lasen sich wie der Inhalt des Auftrags, waren
    // aber nur eine von mehreren Positionen -- bei "Erwin" stand dort "8x Brick
    // 2x2 blau", obwohl der Auftrag zwei Positionen hat. Die Karte nennt jetzt
    // nur noch den Bausatz; die Positionen zeigt die Detailansicht.
    const partner = picking.partner_id ? picking.partner_id[1] : 'Ohne Partner';
    const scheduledDate = picking.scheduled_date
        ? new Date(picking.scheduled_date).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
        : 'Ohne Termin';
    const progressPercent = Math.round(getProgressRatio(picking) * 100);
    const progressLabel = getProgressLabel(picking);
    const zoneLabel = getPrimaryZoneLabel(picking);

    return `
        <article class="pick-list-card ${claimedPickingId === picking.id ? 'pick-list-card--active' : ''} ${picking.priority === '1' ? 'pick-list-card--urgent' : ''}" data-id="${picking.id}" aria-label="${escapeHtml(primaryLabel)}">
            <div class="pick-list-card__header">
                <span class="pick-list-card__reference">${escapeHtml(reference)}</span>
                <div class="pick-list-card__badges">
                    ${typeName ? `<span class="pick-list-card__badge">${escapeHtml(typeName)}</span>` : ''}
                    ${picking.priority === '1' ? '<span class="pick-list-card__badge pick-list-card__badge--warning">Dringend</span>' : ''}
                </div>
            </div>
            <div class="pick-list-card__body">
                ${renderProductVisual({
                    productId: getPickingPrimaryProductId(picking),
                    label: primaryLabel,
                    className: 'pick-list-card__thumb product-visual product-visual--thumb',
                    loading: 'eager',
                    size: 256,
                })}
                <div class="pick-list-card__content">
                    <div class="pick-list-card__product">${escapeHtml(primaryLabel)}</div>
                    <div class="pick-list-card__meta">
                        <span>${escapeHtml(partner)}</span>
                        <span>${escapeHtml(zoneLabel)}</span>
                    </div>
                    <div class="pick-list-card__quantity">${escapeHtml(getOpenLineLabel(picking.open_line_count))}</div>
                </div>
                <div class="pick-list-card__location-box">
                    <div class="pick-list-card__location-label">Nächster Platz</div>
                    <div class="pick-list-card__location">${escapeHtml(picking.next_location_short || 'Offen')}</div>
                    <div class="pick-list-card__date">${escapeHtml(scheduledDate)}</div>
                </div>
            </div>
            <div class="pick-list-card__footer">
                <div class="pick-list-card__progress-copy">${escapeHtml(progressLabel)}</div>
                <div class="pick-list-card__progress-track" aria-hidden="true">
                    <span class="pick-list-card__progress-bar" style="width:${progressPercent}%"></span>
                </div>
            </div>
        </article>
    `;
}

function renderResponsivePickingsView(pickings) {
    const searchedPickings = filterBySearch(pickings, searchQuery);

    if (activeFilter === ZONE_FILTER && preferredZone?.key) {
        const availableZones = collectZoneOptions(searchedPickings);
        if (!availableZones.some((zone) => zone.key === preferredZone.key)) {
            preferredZone = null;
            setStoredPreferredZone(null);
            activeFilter = DEFAULT_FILTER;
        }
    }

    renderFilterChips(searchedPickings);
    const visiblePickings = filterByActiveChip(searchedPickings);
    updateTaskCounter(visiblePickings.length);

    if (!searchedPickings.length) {
        setMainContent(`
            <div class="queue-shell">
                ${renderWorkspaceQueueOverview([], { variant: 'main' })}
                ${renderListEmptyState(
                    'Keine Treffer f\u00fcr diese Suche.',
                    'Suche nach Auftrag, Produkt, SKU, Platz oder Partner.'
                )}
            </div>
        `);
        return;
    }

    if (!visiblePickings.length) {
        const filterMessage = activeFilter === 'high'
            ? 'Keine dringenden Auftr\u00e4ge f\u00fcr diese Suche.'
            : 'In deinem Bereich gibt es aktuell keine passenden Auftr\u00e4ge.';
        setMainContent(`
            <div class="queue-shell">
                ${renderWorkspaceQueueOverview([], { variant: 'main' })}
                ${renderListEmptyState(filterMessage)}
            </div>
        `);
        return;
    }

    setMainContent(`
        <div class="list-workspace">
            <div class="list-main">
                ${renderWorkspaceQueueOverview(visiblePickings, { variant: 'main' })}
                <section class="pick-list pick-list-grid" aria-label="Offene Picking-Auftr\u00e4ge">
                    ${visiblePickings.map((picking) => renderPickingListCard(picking)).join('')}
                </section>
            </div>
            <aside class="list-summary" aria-label="Desktop-Zusammenfassung">
                ${renderWorkspaceQueueOverview(visiblePickings, { variant: 'rail' })}
            </aside>
        </div>
    `);

    mainEl().querySelectorAll('.pick-list-card[data-id]').forEach((card) => {
        card.addEventListener('click', () => loadPickingDetail(Number(card.dataset.id)));
    });
    bindQueueCtaButtons();
}

function renderDetailSideRail({ picking, lines, currentLineIndex, line, detailSku, detailPartner, stockState }) {
    const pickerName = getState().currentPicker?.name || 'Kein Profil aktiv';
    const totalCount = getTotalLineCount(picking) || lines.length;
    const completedCount = Math.min(currentLineIndex, totalCount);
    const remainingCount = Math.max(totalCount - currentLineIndex - 1, 0);
    const routeHint = renderRouteHint(picking, currentLineIndex);
    const stockBanner = stockState?.status === 'out_of_stock' ? getOutOfStockBanner(stockState) : '';
    const aiBanner = picking.has_pending_quality_ai
        ? '<div class="ai-pending-banner">KI analysiert Qualit\u00e4tsfall</div>'
        : '';

    return `
        <aside class="detail-side">
            <section class="detail-side-card detail-side-card--progress">
                <div class="detail-side-card__eyebrow">Fortschritt</div>
                <div class="detail-side-card__title">Schritt ${currentLineIndex + 1} von ${lines.length}</div>
                <div class="detail-summary__progress-track" aria-hidden="true">
                    <span class="detail-summary__progress-bar" style="width:${Math.round(((currentLineIndex + 1) / Math.max(lines.length, 1)) * 100)}%"></span>
                </div>
                <div class="detail-side-card__facts">
                    <div>
                        <span>Erfasst</span>
                        <strong>${completedCount}</strong>
                    </div>
                    <div>
                        <span>Offen</span>
                        <strong>${remainingCount}</strong>
                    </div>
                    <div>
                        <span>Picker</span>
                        <strong>${escapeHtml(pickerName)}</strong>
                    </div>
                    <div>
                        <span>Referenz</span>
                        <strong>${escapeHtml(getPickingReference(picking))}</strong>
                    </div>
                </div>
            </section>
            <section class="detail-side-card detail-side-card--facts">
                <div class="detail-side-card__eyebrow">Schnellinfos</div>
                <div class="detail-side-card__facts">
                    <div>
                        <span>Partner</span>
                        <strong>${escapeHtml(detailPartner)}</strong>
                    </div>
                    <div>
                        <span>SKU</span>
                        <strong>${escapeHtml(detailSku)}</strong>
                    </div>
                    <div>
                        <span>Bereich</span>
                        <strong>${escapeHtml(line.location_src_zone || 'Ohne Bereich')}</strong>
                    </div>
                    <div>
                        <span>Menge</span>
                        <strong>${escapeHtml(formatQuantity(line.quantity_demand))} St\u00fcck</strong>
                    </div>
                </div>
            </section>
            ${routeHint}
            ${stockBanner}
            ${aiBanner}
        </aside>
    `;
}

function renderCompletionView(picking, lines) {
    const pickerName = getState().currentPicker?.name || 'Kein Profil aktiv';
    const totalCount = getTotalLineCount(picking) || lines.length;
    const nextPicking = getNextPickingCandidate(getState().pickings || [], { excludeId: picking.id });
    const partner = picking.partner_id?.[1] || 'Aktives Picking';
    const kitName = getPickingKitName(picking);

    setMainContent(`
        <section class="detail-shell detail-shell--complete" aria-label="Picking abgeschlossen">
            <div class="completion-card">
                <div class="detail-complete-icon">OK</div>
                <div class="completion-card__eyebrow">Auftrag abgeschlossen</div>
                <div class="detail-complete-title">${escapeHtml(getPickingReference(picking))}</div>
                ${kitName ? `<div class="completion-card__kit">${escapeHtml(kitName)}</div>` : ''}
                <div class="detail-complete-copy">Alle Artikel wurden erfasst und synchronisiert.</div>
                <div class="completion-summary">
                    <div class="completion-summary__item">
                        <span>Positionen</span>
                        <strong>${totalCount}</strong>
                    </div>
                    <div class="completion-summary__item">
                        <span>Picker</span>
                        <strong>${escapeHtml(pickerName)}</strong>
                    </div>
                    <div class="completion-summary__item">
                        <span>Partner</span>
                        <strong>${escapeHtml(partner)}</strong>
                    </div>
                </div>
                <div class="completion-actions">
                    <button id="completion-list-btn" class="detail-complete-button">
                        Zur\u00fcck zur Liste
                    </button>
                    ${nextPicking ? `
                        <button id="completion-next-btn" class="detail-complete-button detail-complete-button--secondary" data-id="${nextPicking.id}">
                            N\u00e4chsten Auftrag starten
                        </button>
                    ` : ''}
                </div>
            </div>
        </section>
    `);

    document.getElementById('completion-list-btn')?.addEventListener('click', () => loadPickingList());
    document.getElementById('completion-next-btn')?.addEventListener('click', (event) => {
        loadPickingDetail(Number(event.currentTarget.dataset.id));
    });
}

function renderResponsiveCurrentLine() {
    const { currentPicking, currentLineIndex } = getState();
    if (!currentPicking) return;
    updateToolbar('detail');
    // Ein offenes Seriennummer-Modal nicht durch ein Hintergrund-Re-Render schliessen.
    if (!serialPromptActive) closeOverlay();

    const lines = currentPicking.move_lines || [];
    if (currentLineIndex >= lines.length) {
        updateToolbar('complete');
        renderCompletionView(currentPicking, lines);
        return;
    }

    const line = lines[currentLineIndex];
    const progress = `${currentLineIndex + 1} / ${lines.length}`;
    const detailZone = line.location_src_zone || 'N\u00e4chster Bereich';
    const detailLocation = line.location_src_short || formatLocationForDisplay(line.location_src);
    const detailProduct = getLineDisplayName(line);
    const detailSku = line.product_sku || line.product_barcode || 'Keine SKU';
    const detailPartner = currentPicking.partner_id ? currentPicking.partner_id[1] : 'Aktives Picking';
    const progressPercent = Math.round(((currentLineIndex + 1) / Math.max(lines.length, 1)) * 100);
    const kitName = getPickingKitName(currentPicking);
    const stockState = ensureCurrentLineStockState(currentPicking.id, line);
    const detailHero = renderProductVisual({
        productId: line.product_id,
        label: detailProduct,
        className: 'detail-product-hero__media product-visual product-visual--hero',
        loading: 'eager',
        size: 1024,
    });

    setMainContent(`
        <div class="detail-shell">
            <div class="detail-meta">
                <button onclick="window._app.loadPickingList()" class="detail-back">Zur Liste</button>
                <span class="detail-reference">${escapeHtml(getPickingReference(currentPicking))}</span>
                <span class="detail-progress">Schritt ${escapeHtml(progress)}</span>
            </div>
            <div class="detail-workspace">
                <div class="detail-main">
                    <section class="detail-compact" aria-label="Picking \u00dcbersicht">
                        <div class="detail-compact__top">
                            <div class="detail-compact__image">
                                ${detailHero}
                            </div>
                            <div class="detail-compact__info">
                                <div class="detail-compact__eyebrow">${escapeHtml(detailZone)}</div>
                                <div class="detail-compact__location">${escapeHtml(detailLocation)}</div>
                                <div class="detail-compact__product">${escapeHtml(detailProduct)}</div>
                                <div class="detail-compact__chips">
                                    <span class="detail-compact__qty">${escapeHtml(formatQuantity(line.quantity_demand))} St\u00fcck</span>
                                    ${kitName ? `<span>${escapeHtml(kitName)}</span>` : ''}
                                    <span>${escapeHtml(detailPartner)}</span>
                                    <span>${escapeHtml(detailSku)}</span>
                                </div>
                            </div>
                        </div>
                        <div class="detail-compact__progress">
                            <div class="detail-compact__hint">Scannen, touch-best\u00e4tigen oder Fehlbestand melden.</div>
                            <div class="detail-summary__progress-track" aria-hidden="true">
                                <span class="detail-summary__progress-bar" style="width:${progressPercent}%"></span>
                            </div>
                        </div>
                        <div class="detail-compact__actions">
                            <button class="btn-confirm" data-line-id="${line.id}">
                                Best\u00e4tigen
                            </button>
                            <button class="btn-short-pick" data-line-id="${line.id}">
                                Fehlbestand
                            </button>
                        </div>
                        <div class="detail-compact__barcode">
                            <div class="detail-compact__barcode-label">Barcode</div>
                            <div class="detail-compact__barcode-copy">${line.product_barcode ? `Soll-Barcode: ${escapeHtml(line.product_barcode)}` : 'Barcode manuell eingeben oder Kamera verwenden'}</div>
                            <div id="scan-input-area" class="detail-scan-area"></div>
                        </div>
                    </section>
                    ${renderDetailLineList(lines, currentLineIndex)}
                </div>
                ${renderDetailSideRail({
                    picking: currentPicking,
                    lines,
                    currentLineIndex,
                    line,
                    detailSku,
                    detailPartner,
                    stockState,
                })}
            </div>
        </div>
    `);

    const confirmButton = mainEl().querySelector('.btn-confirm');
    if (confirmButton) {
        const stockUnknown = !stockState || stockState.status === 'checking';
        const lineBlocked = stockState?.status === 'out_of_stock';
        confirmButton.disabled = stockUnknown || lineBlocked;
        confirmButton.textContent = stockUnknown
            ? 'Bestand wird gepr\u00fcft...'
            : lineBlocked
                ? 'Nicht erf\u00fcllbar'
                : 'Best\u00e4tigen';
        if (!stockUnknown && !lineBlocked) {
            confirmButton.addEventListener('click', () => handleScan(line.product_barcode || ''));
        }
    }

    const shortageButton = mainEl().querySelector('.btn-short-pick');
    if (shortageButton) {
        shortageButton.addEventListener('click', () => {
            if (stockState?.status === 'out_of_stock') {
                showOutOfStockModal({ picking: currentPicking, line, stockState });
                return;
            }
            openQualityAlertForm({
                initialDescription: `Physisch kein Bestand gefunden. ${getLineDisplayName(line)} pruefen.`,
                returnToListOnSuccess: true,
            });
        });
    }

    const scanArea = document.getElementById('scan-input-area');
    if (scanArea) {
        const manualInput = showManualInput((barcode) => handleScan(barcode));
        scanArea.appendChild(manualInput);
    }
}

function updateVoiceButtonState(active) {
    const voiceButton = btnVoice();
    if (!voiceButton) return;
    const voiceMeta = voiceButton.querySelector('.nav-btn__meta');

    voiceButton.classList.toggle('nav-btn--active', Boolean(active));
    voiceButton.setAttribute('aria-label', 'Sprachmodus starten');
    if (active) {
        voiceButton.setAttribute('aria-label', 'Sprachmodus beenden');
    }
    if (voiceMeta) voiceMeta.textContent = active ? 'Aktiv' : 'Kommando';
}

function getVoiceErrorMessage(error) {
    return error?.name === 'NotAllowedError'
        ? 'Mikrofonzugriff verweigert. Bitte in den Browser-Einstellungen erlauben.'
        : `Mikrofon-Fehler: ${error?.message || error}`;
}

function renderClaimConflict(conflict, pickingId) {
    updateToolbar('locked');
    updateTaskCounter(0);
    const owner = conflict?.claimed_by_name || 'einem anderen Picker';
    const expiresAt = conflict?.claim_expires_at
        ? new Date(conflict.claim_expires_at).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })
        : 'bald';

    setMainContent(`
        <div class="picker-screen">
            <section class="picker-card">
                <div class="picker-card__eyebrow">Claim-Konflikt</div>
                <h2 class="picker-card__title">Dieses Picking ist gerade gesperrt.</h2>
                <p class="picker-card__text">
                    Aktuell arbeitet <strong>${escapeHtml(owner)}</strong> daran.
                    Ablauf des Claims: <strong>${escapeHtml(expiresAt)}</strong>.
                </p>
                <div class="picker-card__actions">
                    <button id="claim-retry" class="picker-option picker-option--primary">Erneut prüfen</button>
                    <button id="claim-back" class="picker-option">Zurück zur Liste</button>
                </div>
            </section>
        </div>
    `);

    document.getElementById('claim-retry')?.addEventListener('click', () => loadPickingDetail(pickingId));
    document.getElementById('claim-back')?.addEventListener('click', () => loadPickingList({ skipRelease: true }));
}

function stopClaimHeartbeat() {
    if (!claimHeartbeatTimer) return;
    window.clearInterval(claimHeartbeatTimer);
    claimHeartbeatTimer = null;
}

function buildOperationKey(scope, parts = [], { unique = false } = {}) {
    const pickerId = getState().currentPicker?.id || 'anon';
    return createIdempotencyKey(scope, [pickerId, ...parts], { unique });
}

function startClaimHeartbeat(pickingId) {
    stopClaimHeartbeat();
    claimHeartbeatTimer = window.setInterval(async () => {
        const picker = getState().currentPicker;
        if (!picker?.id || claimedPickingId !== pickingId) return;
        try {
            await withManagedRequest((signal) => heartbeatPicking(pickingId, {
                idempotencyKey: buildOperationKey('heartbeat', [pickingId, Date.now()], { unique: true }),
                signal,
            }));
        } catch (error) {
            if (isAbortError(error)) return;
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

    const picker = getState().currentPicker;
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

// ---------------------------------------------------------------------------
// Anmeldung.
//
// Bis Foundation-Task 16 war der "Login" eine Kachelauswahl: ein Tipp auf ein
// Profil setzte `activePicker`, und die Identitaet reiste als
// `X-Picker-User-Id` mit. Dieser Pfad ist tot. Das App-weite Gate haengt an
// `get_current_principal`, und das kennt nur das `pwr_session`-Cookie -- ohne
// Cookie 401, unabhaengig vom Runtime-Profil. Der Katalog `/api/pickers` liegt
// selbst hinter dem Gate und ist vor der Anmeldung gar nicht lesbar, weshalb
// es hier keine Kacheln mehr geben KANN.
// ---------------------------------------------------------------------------

function renderLoginScreen({ instances, statusNote = '', errorText = '', login = '' } = {}) {
    updateToolbar('profile_required');
    renderFilterChips([]);
    updateTaskCounter(0);

    const selected = getActiveInstance();
    const options = instances.map(instance => `
        <option value="${escapeHtml(instance.name)}"${instance.name === selected ? ' selected' : ''}>
            ${escapeHtml(instance.display_name || instance.name)}
        </option>
    `).join('');

    setMainContent(`
        <div class="picker-screen">
            <section class="picker-card">
                <div class="picker-card__eyebrow">Anmeldung</div>
                <h2 class="picker-card__title">Mit Odoo-Benutzer anmelden</h2>
                <p class="picker-card__text">Bitte melde dich mit deinen Odoo-Zugangsdaten an.</p>
                ${statusNote ? `<p class="picker-card__text">${escapeHtml(statusNote)}</p>` : ''}
                <form id="login-form" class="login-form" autocomplete="on">
                    <label class="login-field">
                        <span class="login-field__label">Instanz</span>
                        <select id="login-instance" class="login-field__input" ${instances.length > 1 ? '' : 'disabled'}>
                            ${options}
                        </select>
                    </label>
                    <label class="login-field">
                        <span class="login-field__label">Benutzer</span>
                        <input id="login-user" class="login-field__input" type="text"
                               name="username" autocomplete="username" autocapitalize="none"
                               spellcheck="false" required value="${escapeHtml(login)}">
                    </label>
                    <label class="login-field">
                        <span class="login-field__label">Passwort</span>
                        <input id="login-password" class="login-field__input" type="password"
                               name="password" autocomplete="current-password" required>
                    </label>
                    <p id="login-error" class="login-error" role="alert" aria-live="assertive">${escapeHtml(errorText)}</p>
                    <button id="login-submit" type="submit" class="picker-option picker-option--primary">
                        Anmelden
                    </button>
                </form>
                <div class="picker-device">Gerät: ${getDeviceId()}</div>
            </section>
        </div>
    `);

    // `instances.length <= 1` disables the select, and a disabled control has no
    // form value -- so the submit handler reads the instance from here, not from
    // the element, or a single-instance deployment would post an empty string.
    const fallbackInstance = instances[0]?.name || selected;
    document.getElementById('login-form')?.addEventListener('submit', (event) => {
        event.preventDefault();
        void submitLogin(fallbackInstance);
    });
    document.getElementById('login-user')?.focus();
}

async function submitLogin(fallbackInstance) {
    const userEl = document.getElementById('login-user');
    const passwordEl = document.getElementById('login-password');
    const instanceEl = document.getElementById('login-instance');
    const submitEl = document.getElementById('login-submit');
    const errorEl = document.getElementById('login-error');
    if (!userEl || !passwordEl) return;

    const login = userEl.value.trim();
    const password = passwordEl.value;
    const odooInstance = (instanceEl && !instanceEl.disabled ? instanceEl.value : '') || fallbackInstance;
    if (!login || !password) {
        if (errorEl) errorEl.textContent = 'Benutzer und Passwort werden benötigt.';
        return;
    }

    if (submitEl) {
        submitEl.disabled = true;
        submitEl.textContent = 'Melde an …';
    }
    if (errorEl) errorEl.textContent = '';

    try {
        const session = await withManagedRequest((signal) => loginPickerSession(
            { login, password, odoo_instance: odooInstance },
            { signal },
        ), { handleExpiry: false });
        // The password never outlives the request: it is not stored, not put in
        // state, and the field is cleared before the next view renders.
        passwordEl.value = '';
        const picker = {
            id: session.principal.picker_user_id,
            name: session.principal.picker_name,
        };
        setState({ currentPicker: picker, deviceId: getDeviceId() });
        updatePickerIndicator();
        // Die Anmeldung hat die Instanz festgelegt; die Auswahl oben zieht nach.
        syncInstanceSwitch();
        const firstName = picker.name?.split(/\s+/)[0] || picker.name || '';
        const hour = new Date().getHours();
        const salutation = hour < 12 ? 'Guten Morgen' : hour < 18 ? 'Guten Tag' : 'Guten Abend';
        speak(`${salutation} ${firstName}.`);
        await loadPickingList({ skipRelease: true });
    } catch (error) {
        if (isAbortError(error)) return;
        passwordEl.value = '';
        if (submitEl) {
            submitEl.disabled = false;
            submitEl.textContent = 'Anmelden';
        }
        if (errorEl) {
            // The backend answers a wrong password and an unknown user with the
            // same 401 and the same text, deliberately. Do not embellish it here
            // -- a client-side "user does not exist" would hand back exactly the
            // enumeration the backend refuses to give.
            errorEl.textContent = error instanceof ApiError
                ? error.message
                : 'Anmeldung fehlgeschlagen. Besteht eine Verbindung zum Server?';
        }
        document.getElementById('login-password')?.focus();
    }
}

async function showLoginScreen({ statusNote = '', errorText = '', login = '' } = {}) {
    updateToolbar('profile_required');
    renderFilterChips([]);
    updateTaskCounter(0);
    setMainContent(renderLoading());

    let instances = [];
    try {
        instances = await withManagedRequest((signal) => getAuthInstances({ signal }));
    } catch (error) {
        if (isAbortError(error)) return false;
        // A login screen without a reachable instance list is still better than
        // an error page: the stored selection is enough to post a login.
        instances = [];
    }
    if (!Array.isArray(instances) || !instances.length) {
        const fallback = getActiveInstance();
        instances = [{ name: fallback, display_name: fallback }];
        statusNote = statusNote || (navigator.onLine
            ? 'Instanzliste nicht erreichbar — verwende die zuletzt gewählte Instanz.'
            : 'Offline: Die Anmeldung braucht eine Verbindung zum Server.');
    }

    renderLoginScreen({ instances, statusNote, errorText, login });
    return false;
}

async function ensurePickerSelection() {
    const existingPicker = getActivePicker() || getState().currentPicker;
    if (existingPicker?.id) {
        setState({ currentPicker: existingPicker, deviceId: getDeviceId() });
        updatePickerIndicator();
        return true;
    }

    // A `pwr_session` cookie outlives a reload, so ask the server before
    // demanding a password. `getCurrentSession()` is the only thing that can
    // answer this: the client-side picker is a display value and proves nothing.
    try {
        const principal = await withManagedRequest(
            (signal) => getCurrentSession({ signal }),
            { handleExpiry: false },
        );
        setState({
            currentPicker: {
                id: principal.picker_user_id,
                name: principal.picker_name,
            },
            deviceId: getDeviceId(),
        });
        updatePickerIndicator();
        return true;
    } catch (error) {
        if (isAbortError(error)) return false;
        // 401 is the ordinary "no session yet" case and needs no message.
        if (!(error instanceof ApiError && error.status === 401)) {
            console.warn('Sitzungspruefung fehlgeschlagen:', error);
        }
    }

    await showLoginScreen();
    return false;
}

async function switchProfile() {
    updateToolbar('switching_profile');
    abortPendingRequests();
    stopSpeaking();
    closeOverlay();
    lineStockCache.clear();
    stopClaimHeartbeat();
    if (isVoiceModeActive()) stopVoiceMode();
    btnVoice()?.classList.remove('nav-btn--ptt');
    await releaseCurrentClaim();
    // Ends the session SERVER-side too. Without this the cookie stays valid and
    // the next person on this handheld inherits the previous picker's session
    // by pressing reload -- the profile switch would be cosmetic.
    await logoutPickerSession();
    clearActivePicker();
    clearStoredPicker();
    setState({
        currentPicker: null,
        currentPicking: null,
        currentLineIndex: 0,
        pickings: [],
    });
    resetOperatorUiState();
    updatePickerIndicator();
    await showLoginScreen();
}

async function loadPickingList({ skipRelease = false } = {}) {
    stopSpeaking();
    closeOverlay();
    lineStockCache.clear();
    if (!skipRelease) await releaseCurrentClaim();
    updateToolbar('list');

    const pickerReady = await ensurePickerSelection();
    if (!pickerReady) return;

    setMainContent(renderLoading());
    try {
        const pickings = await withManagedRequest((signal) => getPickings({ signal }));
        setState({ pickings, currentPicking: null, currentLineIndex: 0 });
        updateConnectivityStatus();

        if (!pickings.length) {
            renderFilterChips([]);
            updateTaskCounter(0);
            setMainContent(renderListEmptyState(
                'Keine offenen Aufträge.',
                'Sobald Odoo neue Aufgaben freigibt, erscheinen sie hier.'
            ));
            return;
        }

        renderResponsivePickingsView(pickings);
    } catch (error) {
        if (isAbortError(error)) return;
        if (error instanceof ApiError && (error.status === 400 || error.status === 403)) {
            showToast('Profil bitte neu wählen.', 'warning');
            await switchProfile();
            return;
        }
        setMainContent(renderError(`Verbindung fehlgeschlagen: ${error.message}`));
        renderFilterChips([]);
        updateTaskCounter(0);
        updateConnectivityStatus();
    }
}

async function setFilter(value) {
    if (value === ZONE_FILTER && !preferredZone?.key) {
        openZonePicker(getState().pickings || []);
        return;
    }

    activeFilter = value || DEFAULT_FILTER;
    await loadPickingList({ skipRelease: true });
}

async function loadPickingDetail(pickingId) {
    stopSpeaking();
    closeOverlay();
    lineStockCache.clear();
    setMainContent(renderLoading());

    const pickerReady = await ensurePickerSelection();
    if (!pickerReady) return;

    if (claimedPickingId && claimedPickingId !== pickingId) {
        await releaseCurrentClaim();
    }

    try {
        await withManagedRequest((signal) => claimPicking(pickingId, {
            idempotencyKey: buildOperationKey('claim', [pickingId, Date.now()], { unique: true }),
            signal,
        }));
        claimedPickingId = pickingId;
        startClaimHeartbeat(pickingId);

        const picking = await withManagedRequest((signal) => getPickingDetail(pickingId, { signal }));
        if (picking.error) {
            await releaseCurrentClaim();
            setMainContent(renderError(picking.error));
            return;
        }

        setState({ currentPicking: picking, currentLineIndex: 0 });
        updateConnectivityStatus();
        renderResponsiveCurrentLine();

        const openingPrompt = getPickingOpeningPrompt(picking);
        if (openingPrompt) {
            speak(openingPrompt);
        }
    } catch (error) {
        if (isAbortError(error)) return;
        if (error instanceof ApiError && error.status === 409 && typeof error.detail === 'object') {
            renderClaimConflict(error.detail, pickingId);
            return;
        }
        if (error instanceof ApiError && (error.status === 400 || error.status === 403)) {
            showToast('Profil bitte neu wählen.', 'warning');
            await switchProfile();
            return;
        }
        await releaseCurrentClaim();
        setMainContent(renderError(`Fehler beim Laden: ${error.message}`));
        updateConnectivityStatus();
    }
}

function getOutOfStockBanner(stockState) {
    if (!stockState || stockState.status !== 'out_of_stock') return '';

    const recommendation = stockState.recommendation;
    const recommendationText = recommendation?.recommended_location
        ? `Nachschub möglich aus ${recommendation.recommended_location}.`
        : 'Kein Alternativbestand laut System gefunden.';

    return `
        <section class="state-panel state-panel--warning" aria-label="Position nicht erfüllbar">
            <div class="state-panel__eyebrow">Nicht Erfüllbar</div>
            <div class="state-panel__title">Kein Bestand am aktuellen Lagerplatz</div>
            <div class="state-panel__meta">
                Verfügbar: ${escapeHtml(formatQuantity(stockState.quantity_available))}. ${escapeHtml(recommendationText)}
            </div>
        </section>
    `;
}

async function loadCurrentLineStockState(pickingId, line) {
    try {
        const stockState = await withManagedRequest((signal) => getLineStock(
            pickingId,
            line.product_id,
            line.location_src_id,
            { signal },
        ));
        lineStockCache.set(line.id, stockState);
    } catch (error) {
        if (isAbortError(error)) return;
        console.warn('Bestandspruefung fehlgeschlagen:', error);
        lineStockCache.set(line.id, {
            status: 'unknown',
            quantity_available: null,
            recommendation: null,
        });
    }

    const { currentPicking, currentLineIndex } = getState();
    const currentLine = currentPicking?.move_lines?.[currentLineIndex];
    if (!currentPicking || currentPicking.id !== pickingId || currentLine?.id !== line.id) return;

    renderResponsiveCurrentLine();
    const stockState = lineStockCache.get(line.id);
    if (stockState?.status === 'out_of_stock') {
        showOutOfStockModal({ picking: currentPicking, line, stockState });
    }
}

function ensureCurrentLineStockState(pickingId, line) {
    const cached = lineStockCache.get(line.id);
    if (cached) return cached;

    const checkingState = {
        status: 'checking',
        quantity_available: null,
        recommendation: null,
    };
    lineStockCache.set(line.id, checkingState);
    void loadCurrentLineStockState(pickingId, line);
    return checkingState;
}

function buildOutOfStockDescription(line) {
    const location = line.location_src_short || formatLocationForDisplay(line.location_src);
    return `Lagerfach leer. ${getLineDisplayName(line)} an ${location} nicht verfuegbar.`;
}

function showOutOfStockModal({ picking, line, stockState }) {
    const overlay = overlayEl();
    if (!overlay) return;

    const recommendation = stockState?.recommendation;
    const altText = recommendation?.recommended_location
        ? `Nachschub möglich aus ${recommendation.recommended_location}.`
        : 'Kein Alternativbestand laut System vorhanden.';

    overlay.hidden = false;
    overlay.innerHTML = `
        <div class="modal-sheet" role="dialog" aria-modal="true" aria-labelledby="stockout-title">
            <div class="modal-sheet__eyebrow">Exception Flow</div>
            <h2 id="stockout-title" class="modal-sheet__title">Kein Bestand</h2>
            <p class="modal-sheet__text">
                Produkt: ${escapeHtml(getLineDisplayName(line))}<br>
                Soll: ${escapeHtml(formatQuantity(line.quantity_demand))}<br>
                Verfügbar: ${escapeHtml(formatQuantity(stockState?.quantity_available ?? 0))}
            </p>
            <p class="modal-sheet__text">${escapeHtml(altText)}</p>
            <p id="stockout-inline-error" class="qa-inline-error" role="alert" hidden></p>
            <div class="modal-sheet__actions modal-sheet__actions--stack">
                <button type="button" id="stockout-report" class="picker-option picker-option--primary">Problem melden</button>
                <button type="button" id="stockout-replenish" class="picker-option">Nachschub anfordern</button>
                <button type="button" id="stockout-skip" class="picker-option">Überspringen</button>
            </div>
        </div>
    `;

    const setInlineError = (message) => {
        const inlineErrorEl = document.getElementById('stockout-inline-error');
        if (!inlineErrorEl) return;
        inlineErrorEl.hidden = false;
        inlineErrorEl.textContent = message;
    };

    document.getElementById('stockout-report')?.addEventListener('click', () => {
        closeOverlay();
        openQualityAlertForm({
            initialDescription: buildOutOfStockDescription(line),
            returnToListOnSuccess: true,
        });
    });

    document.getElementById('stockout-replenish')?.addEventListener('click', async () => {
        const replenishBtn = document.getElementById('stockout-replenish');
        const skipBtn = document.getElementById('stockout-skip');
        const reportBtn = document.getElementById('stockout-report');
        if (replenishBtn) replenishBtn.disabled = true;
        if (skipBtn) skipBtn.disabled = true;
        if (reportBtn) reportBtn.disabled = true;

        try {
            const result = await withManagedRequest((signal) => requestReplenishment(
                picking.id,
                {
                    move_line_id: line.id,
                    reason: buildOutOfStockDescription(line),
                },
                {
                    idempotencyKey: buildOperationKey('replenishment-request', [
                        picking.id,
                        line.id,
                        stockState?.recommendation?.recommended_location_id || 'none',
                    ]),
                    signal,
                },
            ));

            if (!result.success) {
                if (replenishBtn) replenishBtn.disabled = false;
                if (skipBtn) skipBtn.disabled = false;
                if (reportBtn) reportBtn.disabled = false;
                setInlineError(result.message || 'Nachschub konnte nicht angefordert werden.');
                return;
            }

            closeOverlay();
            showToast(result.message || 'Nachschub angefordert.', 'success');
            await speak(result.message || 'Nachschub angefordert.');
            await releaseCurrentClaim();
            await loadPickingList({ skipRelease: true });
        } catch (error) {
            if (isAbortError(error)) return;
            if (replenishBtn) replenishBtn.disabled = false;
            if (skipBtn) skipBtn.disabled = false;
            if (reportBtn) reportBtn.disabled = false;
            setInlineError(error.message || 'Nachschub konnte nicht angefordert werden.');
        }
    });

    document.getElementById('stockout-skip')?.addEventListener('click', async () => {
        closeOverlay();
        showToast('Position zur späteren Bearbeitung zurückgestellt.', 'warning');
        await speak('Übersprungen.');
        await releaseCurrentClaim();
        await loadPickingList({ skipRelease: true });
    });
}


/**
 * Show a modal prompt for serial number entry and resolve with the entered value.
 * Returns '' if the user skips/cancels an optional prompt.
 */
function askSerialNumber(productName, { required = false, tracking = 'serial' } = {}) {
    return new Promise((resolve) => {
        const overlay = overlayEl();
        if (!overlay) { resolve(''); return; }
        const isLot = tracking === 'lot';
        const kind = isLot ? 'Charge' : 'Seriennummer';
        const title = isLot ? 'Chargennummer scannen oder eingeben' : 'Seriennummer scannen oder eingeben';

        // Solange der Prompt offen ist, darf ein asynchrones Re-Render
        // (Heartbeat-/Detail-Refresh) das Modal nicht wegschliessen.
        serialPromptActive = true;
        overlay.hidden = false;
        // Build static HTML structure (no user content interpolated here)
        overlay.innerHTML = [
            '<div class="modal-sheet" role="dialog" aria-modal="true" aria-labelledby="serial-title">',
            '<div class="modal-sheet__eyebrow" id="serial-eyebrow"></div>',
            '<h2 id="serial-title" class="modal-sheet__title"></h2>',
            '<p id="serial-product-name" class="modal-sheet__text"></p>',
            '<input type="text" id="serial-input" class="manual-barcode-entry__input"',
            '       inputmode="text" autocomplete="off"',
            '       style="margin:0.75rem 0;width:100%;box-sizing:border-box;">',
            '<p id="serial-warning" class="cluster-carton-warning" role="alert" hidden></p>',
            '<div class="modal-sheet__actions modal-sheet__actions--stack">',
            '<button type="button" id="serial-confirm" class="picker-option picker-option--primary">Bestätigen</button>',
            required ? '' : '<button type="button" id="serial-skip" class="picker-option">Überspringen</button>',
            '</div></div>',
        ].join('');

        // Set user-visible product name safely via textContent (no XSS risk)
        const eyebrowEl = overlay.querySelector('#serial-eyebrow');
        if (eyebrowEl) eyebrowEl.textContent = kind;
        const titleEl = overlay.querySelector('#serial-title');
        if (titleEl) titleEl.textContent = title;
        const nameEl = overlay.querySelector('#serial-product-name');
        if (nameEl) nameEl.textContent = productName;

        const input = overlay.querySelector('#serial-input');
        if (input) input.placeholder = kind;
        const warning = overlay.querySelector('#serial-warning');
        input?.focus();

        const warnRequired = () => {
            if (warning) {
                warning.textContent = `${kind} erforderlich.`;
                warning.hidden = false;
            }
            feedbackError();
        };

        // Escape schliesst das Modal als "Ueberspringen" (capture-Phase, damit es
        // auch bei Fokus im Eingabefeld greift).
        const onKeydown = (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                if (required) warnRequired();
                else finish('');
            }
        };

        // settle() loest das Promise genau einmal auf und raeumt den Listener weg.
        // Es wird sowohl von finish() (User-Aktion) als auch von closeOverlay()
        // (externes Schliessen, z. B. Navigation) ueber serialPromptCleanup gerufen.
        const settle = (value) => {
            if (!serialPromptActive) return;
            serialPromptActive = false;
            serialPromptCleanup = null;
            document.removeEventListener('keydown', onKeydown, true);
            if (required && !value) {
                resolve(null);
                return;
            }
            resolve(value || '');
        };
        const finish = (value) => {
            settle(value);
            closeOverlay();
        };
        serialPromptCleanup = () => settle('');

        document.addEventListener('keydown', onKeydown, true);
        // Klick auf den Backdrop = Ueberspringen, konsistent zum Zone-Picker.
        overlay.onclick = (event) => {
            if (event.target !== overlay) return;
            if (required) warnRequired();
            else finish('');
        };

        const submit = () => {
            const value = input?.value.trim() || '';
            if (required && !value) {
                warnRequired();
                return;
            }
            finish(value);
        };

        overlay.querySelector('#serial-confirm')?.addEventListener('click', submit);
        overlay.querySelector('#serial-skip')?.addEventListener('click', () => finish(''));
        input?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submit();
        });
    });
}

/**
 * Empfaengerkarton-Bestaetigung (Put-to-Box / Verwechslungsschutz, Akzeptanz #3+#4).
 * Zeigt alle Kartons des Batches; der Picker bestaetigt den RICHTIGEN per Tippen
 * ODER Scannen/Eingabe der Karton-Referenz. Falscher Karton -> Inline-Warnung, Modal
 * bleibt offen (kein Confirm). Resolve mit der Karton-Referenz (Package-Name/-ID) des
 * erwarteten Kartons, oder '' bei Abbruch. Nur fuer Cluster-Lines mit Ziel-Package.
 */
function askCartonConfirm(line, boxes) {
    return new Promise((resolve) => {
        const overlay = overlayEl();
        if (!overlay) { resolve(''); return; }

        const boxList = Array.isArray(boxes) ? boxes : [];
        const expectedPickingId = line.picking_id;
        const expectedName = line.package_name || '';
        const expectedId = line.package_id;
        const expectedBoxIndex = line.box_index;
        const expectedRef = expectedName || (expectedId != null ? String(expectedId) : '');

        cartonPromptActive = true;
        overlay.hidden = false;

        const chipsHtml = boxList.map((box) => `
            <button type="button" class="cluster-carton-choice" data-carton-pick="${safeInt(box.picking_id)}"
                style="--box-color:${safeColor(box.box_color)}">
                <span class="cluster-box-chip" style="--box-color:${safeColor(box.box_color)}">${safeInt(box.box_index, '?')}</span>
                <span class="cluster-carton-choice__body">
                    <span class="cluster-carton-choice__order">${escapeHtml(box.picking_name || '')}</span>
                    ${box.package_name ? `<span class="cluster-box-pkg">${escapeHtml(box.package_name)}</span>` : ''}
                </span>
            </button>`).join('');

        overlay.innerHTML = [
            '<div class="modal-sheet" role="dialog" aria-modal="true" aria-labelledby="carton-title">',
            '<div class="modal-sheet__eyebrow">Empfängerkarton</div>',
            '<h2 id="carton-title" class="modal-sheet__title">In welchen Karton?</h2>',
            '<p id="carton-hint" class="modal-sheet__text"></p>',
            `<div class="cluster-carton-choices">${chipsHtml}</div>`,
            '<input type="text" id="carton-input" class="manual-barcode-entry__input"',
            '       inputmode="text" placeholder="Karton scannen oder eingeben" autocomplete="off"',
            '       style="margin:0.75rem 0;width:100%;box-sizing:border-box;">',
            '<p id="carton-warning" class="cluster-carton-warning" role="alert" hidden></p>',
            '<div class="modal-sheet__actions modal-sheet__actions--stack">',
            '<button type="button" id="carton-confirm" class="picker-option picker-option--primary">Karton bestätigen</button>',
            '<button type="button" id="carton-skip" class="picker-option">Abbrechen</button>',
            '</div></div>',
        ].join('');

        const hintEl = overlay.querySelector('#carton-hint');
        if (hintEl) {
            hintEl.textContent = `${formatClusterQty(line.quantity_demand)} Stück → Auftrag `
                + `${line.picking_name || ''} · Karton `
                + `${expectedBoxIndex ?? '?'}${expectedName ? ' (' + expectedName + ')' : ''}`;
        }
        const warnEl = overlay.querySelector('#carton-warning');
        const input = overlay.querySelector('#carton-input');

        // Nur gegen das matchen, was der Backend-Check (_carton_matches) akzeptiert:
        // Package-Name oder Package-ID. Kein loseres UI-Gate (kein Box-Index/Auftragsnr.),
        // damit Client- und Server-Pruefung deckungsgleich bleiben.
        const isCorrect = (value) => {
            const v = String(value || '').trim().toLowerCase();
            if (!v) return false;
            if (expectedName && v === expectedName.toLowerCase()) return true;
            if (expectedId != null && v === String(expectedId)) return true;
            return false;
        };
        const warn = (msg) => {
            if (warnEl) { warnEl.textContent = msg; warnEl.hidden = false; }
            feedbackError();
        };

        const onKeydown = (e) => { if (e.key === 'Escape') { e.preventDefault(); finish(''); } };
        const settle = (value) => {
            if (!cartonPromptActive) return;
            cartonPromptActive = false;
            cartonPromptCleanup = null;
            document.removeEventListener('keydown', onKeydown, true);
            resolve(value || '');
        };
        const finish = (value) => { settle(value); closeOverlay(); };
        cartonPromptCleanup = () => settle('');

        // Den TATSAECHLICH gescannten/eingegebenen Token weiterreichen (nicht expectedRef),
        // damit der Backend-Check _carton_matches echt re-validiert (Defense-in-depth) statt
        // eine bereits "gewaschene" Soll-Referenz zu erhalten.
        const tryValue = (value) => {
            const v = String(value || '').trim();
            if (isCorrect(v)) finish(v);
            else warn('Falscher Karton! Bitte den empfohlenen Karton bestätigen.');
        };

        document.addEventListener('keydown', onKeydown, true);
        overlay.onclick = (event) => { if (event.target === overlay) finish(''); };

        overlay.querySelectorAll('[data-carton-pick]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const pid = Number(btn.dataset.cartonPick);
                const box = boxList.find((b) => b.picking_id === pid);
                if (pid === expectedPickingId) {
                    // Den getippten Karton mit SEINER eigenen Referenz bestaetigen, damit das
                    // Backend den tatsaechlich gewaehlten Karton re-validiert (nicht expectedRef).
                    finish((box && box.package_name)
                        || (box && box.package_id != null ? String(box.package_id) : expectedRef));
                } else {
                    warn(`Falscher Karton! Gehört zu ${box?.picking_name || 'einem anderen Auftrag'}.`);
                }
            });
        });
        overlay.querySelector('#carton-confirm')?.addEventListener('click', () => tryValue(input?.value));
        overlay.querySelector('#carton-skip')?.addEventListener('click', () => finish(''));
        input?.addEventListener('keydown', (e) => { if (e.key === 'Enter') tryValue(input.value); });
        input?.focus();
    });
}

// Sagt nach einer Buchung nur das, was handleScan nicht schon gesagt hat.
// Frueher stand hier ein festes "Gebucht." hinter jedem Aufruf. Das war in
// elf von vierzehn Faellen falsch, und weil speak() die laufende Ansage
// abbricht, loeschte dieses Wort auch noch die wahre Meldung -- der Picker
// hoerte "Gebucht", wo "Falscher Artikel" gesprochen worden war.
function announceScanOutcome(outcome) {
    const sentence = describeScanOutcome(outcome);
    if (!sentence) return;
    // Einen Satz gibt es nur, wenn nicht gebucht wurde -- der Erfolg meldet
    // sich in handleScan selbst, mit der naechsten Position oder "Fertig.".
    speak(sentence);
    showToast(sentence, 'warning');
}

// Meldet ueber den Rueckgabewert, was mit der Position geschehen ist. Der
// Aufrufer darf niemals aus dem blossen Zuruecklaufen auf eine Buchung
// schliessen -- nur SCAN_OUTCOME.BOOKED heisst gebucht. Siehe
// describeScanOutcome in voice-runtime.mjs fuer die Ansage danach.
async function handleScan(barcode) {
    stopSpeaking();
    const { currentPicking, currentLineIndex, currentPicker } = getState();
    if (!currentPicking) return SCAN_OUTCOME.NO_LINE;

    const lines = currentPicking.move_lines || [];
    if (currentLineIndex >= lines.length) return SCAN_OUTCOME.NO_LINE;

    const line = lines[currentLineIndex];
    const stockState = lineStockCache.get(line.id);

    if (stockState?.status === 'checking') {
        showToast('Bestand wird noch geprueft.', 'warning');
        return SCAN_OUTCOME.STOCK_CHECKING;
    }

    if (stockState?.status === 'out_of_stock') {
        showOutOfStockModal({ picking: currentPicking, line, stockState });
        return SCAN_OUTCOME.OUT_OF_STOCK;
    }

    if (barcode && line.product_barcode && barcode !== line.product_barcode) {
        feedbackError();
        speak(`Falscher Artikel. ${getLineDisplayName(line)}.`);
        showToast('Falscher Barcode', 'error');
        return SCAN_OUTCOME.WRONG_BARCODE;
    }

    // For tracked products, ask for the lot/serial number before confirming.
    // Untracked lines are completely unaffected (serialNumber stays '').
    let serialNumber = '';
    if (line.tracking === 'serial' || line.tracking === 'lot') {
        serialNumber = await askSerialNumber(getLineDisplayName(line), {
            required: true,
            tracking: line.tracking,
        });
        if (!serialNumber) return SCAN_OUTCOME.SERIAL_CANCELLED;
    }

    try {
        const result = await withManagedRequest((signal) => confirmLine(
            currentPicking.id,
            {
                move_line_id: line.id,
                scanned_barcode: barcode || line.product_barcode || '',
                quantity: line.quantity_demand,
                serial_number: serialNumber,
            },
            {
                idempotencyKey: buildOperationKey('confirm-line', [
                    currentPicking.id,
                    currentPicker?.id || 'anon',
                    currentLineIndex,
                    line.id,
                    barcode || line.product_barcode || '',
                    line.quantity_demand,
                    serialNumber,
                ]),
                signal,
            },
        ));

        if (!result.success) {
            feedbackError();
            if (result.blocked_reason === 'out_of_stock') {
                const blockingState = result.stock_context || stockState || { status: 'out_of_stock', quantity_available: 0 };
                lineStockCache.set(line.id, blockingState);
                renderResponsiveCurrentLine();
                showOutOfStockModal({ picking: currentPicking, line, stockState: blockingState });
                return SCAN_OUTCOME.OUT_OF_STOCK;
            }
            speak(result.message || 'Fehler beim Bestätigen.');
            showToast(result.message || 'Fehler', 'error');
            return SCAN_OUTCOME.REJECTED;
        }

        feedbackSuccess();

        if (result.picking_complete) {
            showToast(result.message, 'success');
            await releaseCurrentClaim();
            speak('Fertig.');
            setState({ currentLineIndex: lines.length });
            renderResponsiveCurrentLine();
            return SCAN_OUTCOME.BOOKED;
        } else {
            const nextIdx = currentLineIndex + 1;

            if (nextIdx >= lines.length) {
                // Letzte Position gebucht, der Auftrag ist trotzdem NICHT
                // abgeschlossen -- Odoo hat `button_validate` abgelehnt (etwa
                // wegen eines fehlenden Loses auf einer anderen Zeile).
                //
                // Frueher lief hier derselbe Zweig wie sonst, und weil
                // `renderResponsiveCurrentLine` allein auf
                // `currentLineIndex >= lines.length` schaut, erschien der
                // Abschluss-Screen. Der Picker las "Auftrag abgeschlossen",
                // legte das Geraet weg, und der Auftrag blieb in Odoo offen.
                // Der Bildschirm darf nie mehr behaupten als der Server.
                showToast(result.message, 'error');
                feedbackError();
                speak('Auftrag nicht abgeschlossen.');
                // Der Server ist die Wahrheit: neu laden statt aus dem lokalen
                // Zustand weiterraten. `refreshActivePickingDetail` klemmt den
                // Index zusaetzlich auf die letzte gueltige Zeile, der
                // Abschluss-Screen kann also gar nicht erscheinen.
                await refreshActivePickingDetail();
                return SCAN_OUTCOME.BOOKED;
            }

            showToast(result.message, 'success');
            setState({ currentLineIndex: nextIdx });
            renderResponsiveCurrentLine();
            speak(getLineSpeechPrompt(lines[nextIdx]));
            return SCAN_OUTCOME.BOOKED;
        }
    } catch (error) {
        if (error instanceof ApiError && error.status === 409 && typeof error.detail === 'object') {
            claimedPickingId = null;
            stopClaimHeartbeat();
            renderClaimConflict(error.detail, currentPicking.id);
            speak('Schon vergeben.');
            return SCAN_OUTCOME.CONFLICT;
        }
        if (isAbortError(error)) return SCAN_OUTCOME.ABORTED;

        showToast(error.message || 'Verbindungsfehler', 'error');
        speak('Verbindungsfehler.');
        return SCAN_OUTCOME.NETWORK_ERROR;
    }
}

function dispatchScan(barcode) {
    if (sessionState === 'cluster_walk') return handleClusterScan(barcode);
    return handleScan(barcode);
}

function onVoiceToggle() {
    if (!isVoiceSupported()) {
        showToast('Mikrofon nicht verfügbar', 'warning');
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

/**
 * Programmatischer Einstieg fuer "alle verbleibenden Positionen bestaetigen".
 * Wird vom Voice-Intent confirm_all genutzt und ueber window._app exponiert,
 * damit der Bulk-(Serial-)Pfad in E2E-Tests deterministisch fahrbar ist.
 */
function triggerConfirmAll() {
    const { currentPicking, currentLineIndex } = getState();
    // Re-Entry verhindern: ein zweiter confirm_all-Trigger waehrend eines
    // laufenden Bulk-Laufs wuerde ein offenes Serial-Modal-DOM ueberschreiben.
    if (!currentPicking || confirmAllInProgress) return Promise.resolve();
    confirmAllInProgress = true;
    const lines = currentPicking.move_lines || [];
    return Promise.resolve(handleConfirmAll(currentPicking, lines, currentLineIndex))
        .finally(() => { confirmAllInProgress = false; });
}

async function openNextOrderFromVoice() {
    const { currentPicking, pickings } = getState();
    const nextPicking = getNextPickingCandidate(pickings || [], {
        excludeId: currentPicking?.id ?? null,
    });

    if (nextPicking?.id) {
        await loadPickingDetail(nextPicking.id);
        speak('Nächster Auftrag.');
        return;
    }

    await loadPickingList({ skipRelease: true });
    speak('Kein weiterer Auftrag.');
}

/**
 * Bestätigt alle verbleibenden Pick-Positionen auf einmal.
 * Serien-getrackte Positionen erzwingen dabei den Seriennummer-Modal-Flow.
 */
async function handleConfirmAll(picking, lines, startIndex) {
    const remaining = lines.slice(startIndex);
    if (!remaining.length) {
        speak('Alle Positionen bereits erledigt.');
        return;
    }

    // Serien-getrackte Positionen werden NICHT uebersprungen: fuer jede wird der
    // gleiche Seriennummer-Modal-Flow wie beim Einzel-Scan erzwungen, damit die
    // Rueckverfolgbarkeit hochwertiger Gueter auch im "Alle bestaetigen"-Pfad
    // erhalten bleibt. Nicht-getrackte Positionen werden direkt bestaetigt.
    const serialCount = remaining.filter((l) => l.tracking === 'serial' || l.tracking === 'lot').length;
    // Kein speak() vor der Schleife: die Vorab-Ansage kostete 0,9-1,9 s Synthese
    // plus 1,6-3,3 s Wiedergabe und schaltete waehrenddessen das Mikrofon stumm,
    // bevor ueberhaupt eine Buchung lief. Der Toast direkt darunter transportiert
    // dieselbe Information sofort und ohne Mikrofon-Sperre. Quittiert wird am
    // Ende, wenn es etwas zu quittieren gibt.
    showToast(
        serialCount > 0
            ? `Bestätige ${remaining.length} Positionen - ${serialCount} mit Charge/Seriennummer.`
            : `Bestätige ${remaining.length} Positionen...`,
        'info',
    );

    let pickingWasCompleted = false;
    let lastMessage = '';
    let bookedCount = 0;

    for (const [offset, pickLine] of remaining.entries()) {
        const lineIdx = startIndex + offset;

        let serialNumber = '';
        if (pickLine.tracking === 'serial' || pickLine.tracking === 'lot') {
            serialNumber = await askSerialNumber(getLineDisplayName(pickLine), {
                required: true,
                tracking: pickLine.tracking,
            });
            if (!serialNumber) return;
        }

        try {
            const result = await withManagedRequest((signal) => confirmLine(
                picking.id,
                {
                    move_line_id: pickLine.id,
                    scanned_barcode: pickLine.product_barcode || '',
                    quantity: pickLine.quantity_demand,
                    serial_number: serialNumber,
                },
                {
                    idempotencyKey: buildOperationKey('confirm-all', [
                        picking.id,
                        pickLine.id,
                        lineIdx,
                        pickLine.quantity_demand,
                        serialNumber,
                    ]),
                    signal,
                },
            ));

            if (!result.success) {
                feedbackError();
                speak(`Position ${offset + 1} konnte nicht bestätigt werden.`);
                showToast(result.message || 'Fehler bei Bulk-Bestätigung', 'error');
                return;
            }

            bookedCount += 1;
            setState({ currentLineIndex: lineIdx + 1 });
            renderResponsiveCurrentLine();

            if (result.picking_complete) {
                pickingWasCompleted = true;
                break;
            }
            lastMessage = result.message || '';
        } catch (error) {
            if (isAbortError(error)) return;
            speak('Verbindungsfehler.');
            showToast(error.message || 'Verbindungsfehler', 'error');
            return;
        }
    }

    if (!pickingWasCompleted) {
        // Alle Positionen durch, und der Server hat den Auftrag trotzdem nie
        // als abgeschlossen gemeldet -- dieselbe Lage wie beim
        // Einzelbestaetigen: Odoo hat `button_validate` abgelehnt. Frueher lief
        // dieser Zweig unbedingt und behauptete "Alles erledigt.", woraufhin
        // der Abschluss-Screen erschien und der Auftrag offen liegen blieb.
        feedbackError();
        speak('Auftrag nicht abgeschlossen.');
        showToast(
            lastMessage || 'Positionen gebucht, aber der Auftrag ist nicht abgeschlossen.',
            'error',
        );
        await refreshActivePickingDetail();
        return;
    }

    await releaseCurrentClaim();
    // Menge mitquittieren, damit der Picker ohne Blick aufs Display weiss, was
    // gebucht wurde. Bleibt unter PIPER_MIN_TEXT_LENGTH und laeuft damit ueber
    // die schnelle Browser-Stimme.
    speak(`Fertig, ${bookedCount} gebucht.`);
    setState({ currentLineIndex: lines.length });
    renderResponsiveCurrentLine();
}

// A write intent recognized below its direct threshold is held here until the
// next affirmative confirms it, so a single misrecognition never books.
let pendingWriteConfirm = null; // { intent, expiresAt, retries }
// 25 s statt 8 s. Gemessen im Live-Log: zwischen der gestellten Rueckfrage und
// der eintreffenden Antwort lagen 10 s -- Ansage vorlesen, Cooldown, sprechen,
// Stillefenster, Transkription, und der Mensch ueberlegt auch noch. Mit 8 s war
// die Rueckfrage bereits verfallen, als die Antwort kam, und die Buchung fiel
// STUMM unter den Tisch. Genau das Verhalten, das als "erkennt confirm_all,
// fuehrt es aber nicht aus" gemeldet wurde.
const READBACK_TTL_MS = 25000;
const READBACK_MAX_RETRIES = 2;

// Eine wartende Buchung darf NUR durch eine ausdrueckliche Zustimmung ausgeloest
// werden. Vorher genuegte irgendein `confirm`-Intent -- und weil die Engine
// beilaeufige Floskeln ("alles gut", "super") als confirm auswertete, konnte ein
// Nebensatz aus dem Hintergrund einen ganzen Auftrag buchen. Der Prompt fragt
// eine geschlossene Ja/Nein-Frage, also wird auch nur darauf gehoert.
const READBACK_YES = new Set([
    'ja', 'jawohl', 'genau', 'richtig', 'stimmt', 'ok', 'okay',
    'bestaetigen', 'bestaetige', 'buchen', 'jep', 'jup', 'passt',
]);
const READBACK_NO = new Set([
    'nein', 'abbrechen', 'stopp', 'stop', 'abbruch', 'nicht', 'kein', 'keine',
]);

function normalizeSpokenAnswer(text) {
    return String(text || '')
        .toLowerCase()
        .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')
        .replace(/[^a-z0-9]+/g, ' ')
        .trim();
}

// Whisper liefert selten ein blankes "Ja". Real gemessen kam auf die Rueckfrage
// "3 Positionen buchen?" das Transkript "Kommt's raus, oh, ja, ist so." zurueck.
// Ein Vergleich der GANZEN Aeusserung gegen eine Ja-Liste scheitert daran, und
// die Buchung verschwand wortlos. Deshalb wird tokenweise gesucht -- aber ein
// Abbruchwort schlaegt immer eine Zustimmung, damit ein "nein, doch nicht"
// niemals als Ja durchgeht.
function readbackAnswer(text) {
    const words = normalizeSpokenAnswer(text).split(' ').filter(Boolean);
    if (!words.length) return null;
    if (words.some((word) => READBACK_NO.has(word))) return 'no';
    if (words.some((word) => READBACK_YES.has(word))) return 'yes';
    return null;
}

// Stufe 3: kein Zweig in `handleVoiceIntent` darf mehr ohne Rueckmeldung enden.
// Ein `break` ohne Ansage ist fuer den Nutzer nicht davon zu unterscheiden, dass
// der Befehl gar nicht angekommen ist -- gemessen 15 solcher stillen No-Ops im
// 108-Satz-Korpus. Alle Texte bleiben bewusst unter PIPER_MIN_TEXT_LENGTH (24
// Zeichen) und laufen damit ueber die schnelle Browser-Stimme; laengere Ansagen
// gingen an Piper und holten den Latenzgewinn aus Stufe 1 wieder ein.
const NO_ACTIVE_LINE = 'Keine aktive Position.';
const NO_OPEN_LINE = 'Keine Position offen.';
const LAST_LINE = 'Letzte Position.';
const FIRST_LINE = 'Erste Position.';
const LIST_ONLY = 'Nur in der Liste.';
const VOICE_ALREADY_OFF = 'Sprachmodus ist aus.';
const NOT_UNDERSTOOD = 'Nicht verstanden.';

function announceNoActiveLine() {
    speak(NO_ACTIVE_LINE);
    showToast(NO_ACTIVE_LINE, 'warning');
}

// Verteidigung in der Tiefe: nach dem Surface-Filter in der Intent-Engine
// erreichen filter_*/status die Detailansicht gar nicht mehr. Kommt doch eines
// durch, wird es benannt statt verschluckt.
function announceListOnly() {
    speak(LIST_ONLY);
    showToast(LIST_ONLY, 'warning');
}

async function handleVoiceIntent(result) {
    // STT returned nothing (Whisper down, or a hallucination dropped upstream):
    // give audible + visible feedback instead of a silent drop.
    if (!result || (!result.text && (result.intent === 'unknown' || result.intent === 'error'))) {
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        showToast('Nicht verstanden, bitte nochmal.', 'warning');
        speak('Nicht verstanden, bitte nochmal.');
        return;
    }

    const classification = classifyVoiceResult(result);
    if (classification.kind === 'error') {
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        return;
    }

    const { currentPicking, currentLineIndex } = getState();
    const lines = currentPicking?.move_lines || [];
    const line = lines[currentLineIndex];

    if (result?.text) {
        const intentLabel = result.intent !== 'unknown' ? ` -> ${result.intent}` : ' -> nicht erkannt';
        showToast(`"${result.text}"${intentLabel}`, result.intent !== 'unknown' ? 'info' : 'warning');
    }

    // Eine wartende Rueckfrage aufloesen. Solange sie laeuft, wird die
    // Aeusserung AUSSCHLIESSLICH als Antwort auf die gestellte Ja/Nein-Frage
    // gelesen -- nicht als neues Kommando. Vorher fiel eine nicht eindeutige
    // Antwort durch, verwarf die Buchung wortlos und lief als frischer Befehl
    // weiter; der Nutzer sah nur, dass nichts passierte.
    if (pendingWriteConfirm && Date.now() >= pendingWriteConfirm.expiresAt) {
        pendingWriteConfirm = null;
    }

    if (pendingWriteConfirm) {
        const answer = readbackAnswer(result?.text);

        if (answer === 'no') {
            pendingWriteConfirm = null;
            updateVoiceStatusIndicator('recognized', { temporary: true });
            showToast('Abgebrochen.', 'info');
            speak('Abgebrochen.');
            return;
        }

        if (answer === 'yes') {
            const toRun = pendingWriteConfirm.intent;
            pendingWriteConfirm = null;
            updateVoiceStatusIndicator('recognized', { temporary: true });
            if (toRun === 'submit_alert') {
                document.getElementById('qa-submit')?.click();
            } else if (toRun === 'confirm_all') {
                await triggerConfirmAll();
            } else if (line) {
                announceScanOutcome(await handleScan(line.product_barcode || ''));
            }
            return;
        }

        // Weder Ja noch Nein: nachfragen statt schweigen. Nach zwei
        // erfolglosen Versuchen wird die Buchung ausdruecklich verworfen,
        // damit die Rueckfrage nicht endlos scharf bleibt.
        pendingWriteConfirm.retries = (pendingWriteConfirm.retries || 0) + 1;
        if (pendingWriteConfirm.retries > READBACK_MAX_RETRIES) {
            pendingWriteConfirm = null;
            showToast('Abgebrochen.', 'warning');
            speak('Abgebrochen.');
            return;
        }
        pendingWriteConfirm.expiresAt = Date.now() + READBACK_TTL_MS;
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        showToast('Bitte Ja oder Nein.', 'warning');
        speak('Bitte Ja oder Nein.');
        return;
    }

    if (classification.kind === 'unknown') {
        if (await maybeHandleVoiceAssist(result, currentPicking, currentLineIndex)) return;
        // Frueher endete dieser Zweig hier ohne Ton und ohne Text: der Nutzer
        // sprach, und es passierte sichtbar nichts. Ein nicht verstandener
        // Befehl muss als solcher hoerbar sein -- kurz, damit er nicht selbst
        // zur Bremse wird.
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        showToast('Nicht verstanden.', 'warning');
        speak('Nicht verstanden.');
        return;
    }

    if (classification.kind === 'uncertain') {
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        showToast(classification.promptText, 'warning');
        speak(classification.promptText);
        return;
    }

    if (classification.kind === 'readback') {
        pendingWriteConfirm = {
            intent: result.intent,
            expiresAt: Date.now() + READBACK_TTL_MS,
            retries: 0,
        };
        const prompt = buildReadbackPrompt(result.intent, {
            line,
            remainingCount: Math.max(lines.length - currentLineIndex, 0),
        });
        updateVoiceStatusIndicator('recognized', { temporary: true });
        showToast(prompt, 'info');
        speak(prompt);
        return;
    }

    updateVoiceStatusIndicator('recognized', { temporary: true });

    if (await maybeHandleVoiceAssist(result, currentPicking, currentLineIndex)) return;

    switch (result.intent) {
        case 'submit_alert':
            document.getElementById('qa-submit')?.click();
            break;
        case 'confirm_all':
            await triggerConfirmAll();
            break;
        case 'confirm':
            if (line) {
                announceScanOutcome(await handleScan(line.product_barcode || ''));
            } else {
                speak(NO_OPEN_LINE);
                showToast(NO_OPEN_LINE, 'warning');
            }
            break;
        case 'whats_next':
            if (line) speak(buildSpeechPrompt(line));
            else announceNoActiveLine();
            break;
        case 'where':
            if (line) speak(formatLocationForSpeech(line) || 'Kein Ort hinterlegt.');
            else announceNoActiveLine();
            break;
        case 'how_many_left': {
            const remaining = Math.max(lines.length - currentLineIndex - 1, 0);
            speak(`Noch ${remaining}.`);
            break;
        }
        case 'next_order':
            await openNextOrderFromVoice();
            break;
        case 'next':
            if (line && currentLineIndex < lines.length - 1) {
                const nextIndex = currentLineIndex + 1;
                setState({ currentLineIndex: nextIndex });
                renderResponsiveCurrentLine();
                speak(getLineSpeechPrompt(lines[nextIndex]));
            } else if (!lines.length) {
                announceNoActiveLine();
            } else {
                // Am Ende der Liste passierte bisher nichts -- ununterscheidbar
                // davon, dass der Befehl gar nicht ankam.
                speak(LAST_LINE);
                showToast(LAST_LINE, 'info');
            }
            break;
        case 'previous':
            if (currentLineIndex > 0) {
                const previousIndex = currentLineIndex - 1;
                setState({ currentLineIndex: previousIndex });
                renderResponsiveCurrentLine();
                speak(getLineSpeechPrompt(lines[previousIndex]));
            } else if (!lines.length) {
                announceNoActiveLine();
            } else {
                speak(FIRST_LINE);
                showToast(FIRST_LINE, 'info');
            }
            break;
        case 'repeat':
            if (line) speak(getLineSpeechPrompt(line));
            else announceNoActiveLine();
            break;
        case 'problem':
            if (line) {
                const stockState = lineStockCache.get(line.id);
                if (stockState?.status === 'out_of_stock' || VOICE_ASSIST_SHORTAGE_RE.test(result.text || '')) {
                    showOutOfStockModal({ picking: currentPicking, line, stockState: stockState || { status: 'out_of_stock', quantity_available: 0 } });
                    break;
                }
            }
            openQualityAlertForm();
            break;
        case 'photo':
            openCameraScanner((barcode) => dispatchScan(barcode));
            break;
        case 'abort':
            // Neue Aktion aus dem Negations-Guard: "Stopp, nicht weiter",
            // "kein Foto". Ohne diesen Zweig fiele sie in `default` und der
            // Nutzer bekaeme keine Rueckmeldung auf eine ausdrueckliche
            // Verneinung. Eine wartende Buchung wird dabei verworfen.
            pendingWriteConfirm = null;
            showToast('Abgebrochen.', 'info');
            speak('Abgebrochen.');
            break;
        case 'pause':
            if (isVoiceModeActive()) {
                stopVoiceMode();
                updateVoiceButtonState(false);
            } else {
                // Push-to-Talk: der Sprachmodus laeuft gar nicht, "Pause" hatte
                // also nichts abzuschalten und blieb stumm.
                speak(VOICE_ALREADY_OFF);
                showToast(VOICE_ALREADY_OFF, 'info');
            }
            break;
        case 'done': {
            const remaining = Math.max(lines.length - currentLineIndex - 1, 0);
            if (remaining === 0) {
                await speak('Fertig.');
                loadPickingList();
            } else {
                speak(`Noch ${remaining} Artikel ausstehend.`);
            }
            break;
        }
        case 'help':
            speak('Sag bestätigen, weiter, zurück, Problem oder fertig.');
            break;
        case 'filter_high':
            if (currentPicking !== null) { announceListOnly(); break; }
            activeFilter = 'high';
            await loadPickingList({ skipRelease: true });
            speak('Nur Dringendes.');
            break;
        case 'filter_normal':
            if (currentPicking !== null) { announceListOnly(); break; }
            activeFilter = DEFAULT_FILTER;
            await loadPickingList({ skipRelease: true });
            speak('Alle Aufträge.');
            break;
        case 'status': {
            if (currentPicking !== null) { announceListOnly(); break; }
            const { pickings } = getState();
            const searched = filterBySearch(pickings || [], searchQuery);
            const visible = filterByActiveChip(searched);
            const all = visible.length;
            const high = visible.filter((picking) => picking.priority === '1').length;
            if (high > 0) speak(`${all} offene Aufträge. ${high} davon dringend.`);
            else speak(`${all} offene Aufträge.`);
            break;
        }
        case 'stock_query': {
            // Normalerweise unerreichbar: `maybeHandleVoiceAssist` faengt
            // stock_query oben ab und kehrt mit true zurueck. Faellt der
            // Assist-Pfad weg, darf hier trotzdem keine Stille stehen.
            speak(NOT_UNDERSTOOD);
            showToast(NOT_UNDERSTOOD, 'warning');
            break;
        }
        default:
            // Kein `break` ohne Rueckmeldung: ein erkanntes, aber hier nicht
            // behandeltes Intent sah fuer den Nutzer aus wie "nicht gehoert".
            showToast('Nicht verstanden.', 'warning');
            speak('Nicht verstanden.');
            break;
    }
}

function shouldUseVoiceAssist(result) {
    if (!result?.text) return false;
    // NUR bei einer ausdruecklichen Bestandsfrage. Frueher stand hier auch
    // `unknown` -- dadurch loeste JEDER nicht verstandene Satz einen
    // n8n-Roundtrip aus, die App sagte "Ich pruefe die Datenbank" und las
    // anschliessend vor, was auch immer zurueckkam. Ein missverstandenes
    // Kommando muss "nicht verstanden" ergeben, keine Datenbankabfrage.
    if (result.intent === 'stock_query') return true;
    return false;
}

async function maybeHandleVoiceAssist(result, currentPicking, currentLineIndex) {
    if (!shouldUseVoiceAssist(result)) return false;

    const payload = buildVoiceAssistPayload({
        result,
        view: getCurrentVoiceView(),
        currentPicking,
        currentLineIndex,
    });

    updateVoiceStatusIndicator('speaking');
    showToast('Ich prüfe die Datenbank...', 'info');

    const assistPromise = withManagedRequest((signal) => assistVoice(payload, { signal }));
    await speak('Ich prüfe die Datenbank.');

    try {
        const response = await assistPromise;
        const tone = response?.status === 'fallback' ? 'warning' : 'info';
        if (response?.tts_text) {
            showToast(response.tts_text, tone);
            await speak(response.tts_text);
        }
    } catch (error) {
        if (isAbortError(error)) return true;
        const message = error?.message || 'Ich kann das gerade nicht sicher beantworten.';
        showToast(message, 'warning');
        await speak(message);
    }
    return true;
}

function openQualityAlertForm({ initialDescription = '', returnToListOnSuccess = false } = {}) {
    stopSpeaking();
    updateToolbar('alert');

    const { currentPicking, currentLineIndex } = getState();
    const lines = currentPicking?.move_lines || [];
    const line = lines[currentLineIndex];
    const contextLabel = currentPicking
        ? `${getPickingReference(currentPicking)}${line ? ` | ${getLineDisplayName(line)}` : ''}`
        : 'Allgemeine Meldung';

    setMainContent(`
        <div class="qa-shell">
            <section class="qa-card" aria-labelledby="qa-title">
                <div class="qa-header">
                    <h2 id="qa-title" class="qa-title">Problem melden</h2>
                    <p class="qa-context">${escapeHtml(contextLabel)}</p>
                </div>

                <div class="qa-field-group">
                    <label for="qa-description" class="qa-label">Schnellauswahl</label>
                    <div class="qa-chips" role="group" aria-label="Problem-Kategorie">
                        <button type="button" class="qa-chip" data-chip="Verpackung defekt">Verpackung defekt</button>
                        <button type="button" class="qa-chip" data-chip="Artikel beschädigt">Artikel beschädigt</button>
                        <button type="button" class="qa-chip" data-chip="Menge falsch">Menge falsch</button>
                        <button type="button" class="qa-chip" data-chip="Sonstiges">Sonstiges</button>
                    </div>
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
        </div>
    `);

    const photoArea = document.getElementById('photo-area');
    const descriptionEl = document.getElementById('qa-description');
    const descriptionErrorEl = document.getElementById('qa-description-error');

    if (initialDescription) {
        descriptionEl.value = initialDescription;
    }

    // Quick-Select Chips: toggle active state + update textarea
    document.querySelectorAll('.qa-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            chip.classList.toggle('qa-chip--active');
            const activeChips = [...document.querySelectorAll('.qa-chip--active')]
                .map(c => c.dataset.chip);
            descriptionEl.value = activeChips.join(', ');
            clearDescriptionError?.();
        });
    });
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
    photoBtn.className = 'qa-photo-button';
    photoBtn.textContent = 'Fotos hinzufügen';
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
            image.alt = `Ausgewähltes Foto ${index + 1}`;
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
        if (returnToListOnSuccess) {
            loadPickingList();
            return;
        }
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
        if (line?.location_src_id) formData.append('location_id', String(line.location_src_id));
        photoFiles.forEach(file => formData.append('photos', file));

        try {
            const result = await withManagedRequest((signal) => createQualityAlert(
                formData,
                {
                    idempotencyKey: buildOperationKey('quality-alert', [
                        currentPicking?.id || 'none',
                        line?.id || 'none',
                        priority,
                        description,
                        ...photoFiles.map(file => `${file.name}:${file.size}`),
                    ]),
                    signal,
                },
            ));
            speak('Problem gemeldet. Die KI-Bewertung läuft.');
            showToast(`Alert ${result.name} erstellt - KI-Bewertung läuft...`, 'success');
            if (returnToListOnSuccess) {
                await releaseCurrentClaim();
                await loadPickingList({ skipRelease: true });
                return;
            }
            if (currentPicking) {
                await loadPickingDetail(currentPicking.id);
                return;
            }
            await loadPickingList({ skipRelease: true });
        } catch (error) {
            if (isAbortError(error)) return;
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
    initPWA({
        onConnectivityChange: () => updateConnectivityStatus(),
        onOnline: async () => {
            updateConnectivityStatus();
            await refreshCurrentView();
        },
        onResume: async () => {
            await refreshCurrentView();
        },
        shouldActivateUpdate: shouldActivateServiceWorkerUpdate,
        onUpdateReady: handleServiceWorkerUpdateReady,
        onControllerRefresh: handleServiceWorkerControllerRefresh,
    });
    clearStoredPicker();
    clearActivePicker();
    resetOperatorUiState();
    setState({ deviceId: getDeviceId() });
    applyDarkTheme();
    updatePickerIndicator();
    updateTaskCounter(0);
    updateVoiceStatusIndicator('idle');
    renderFilterChips([]);
    setVoiceRequestContextProvider(getCurrentVoiceRequestContext);
    setVoiceStatusListener((state) => {
        updateVoiceStatusIndicator(state);
    });

    const searchInput = searchInputEl();
    if (searchInput) {
        searchInput.value = searchQuery;
        searchInput.addEventListener('input', async (event) => {
            if (!getState().currentPicker) return;
            searchQuery = event.target.value || '';
            setStoredSearchQuery(searchQuery);
            if (searchQuery && !mobileSearchOpen) {
                openMobileSearch();
            }
            if (getState().currentPicking) return;
            await loadPickingList({ skipRelease: true });
        });
        searchInput.addEventListener('search', async () => {
            if (!getState().currentPicker) return;
            searchQuery = searchInput.value || '';
            setStoredSearchQuery(searchQuery);
            if (searchQuery) {
                openMobileSearch();
                return;
            }
            await closeMobileSearch();
        });
    }

    applyMobileSearchState();

    const themeToggle = themeToggleEl();
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            darkModeEnabled = !darkModeEnabled;
            setStoredDarkModeEnabled(darkModeEnabled);
            applyDarkTheme();
        });
    }

    const searchToggle = searchToggleEl();
    if (searchToggle) {
        searchToggle.addEventListener('click', async () => {
            if (!getState().currentPicker) return;
            if (!mobileSearchOpen) {
                openMobileSearch({ focus: true });
                return;
            }

            if (searchQuery) {
                openMobileSearch({ focus: true });
                return;
            }

            await closeMobileSearch();
        });
    }

    initHIDScanner((barcode) => dispatchScan(barcode));

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
            openCameraScanner((barcode) => dispatchScan(barcode));
        });
    }

    const alertButton = btnAlert();
    if (alertButton) alertButton.addEventListener('click', openQualityAlertForm);

    const pickerButton = pickerEl();
    if (pickerButton) {
        pickerButton.addEventListener('click', async () => {
            await switchProfile();
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
    window.addEventListener('online', () => updateConnectivityStatus());
    window.addEventListener('offline', () => updateConnectivityStatus());

    subscribe((state) => {
        updatePickerIndicator();
        updateConnectivityStatus({ loading: state.loading });
    });

    try {
        // `/api/health` does not exist -- `health.py` defines `/health/live`
        // only. This probe answered 404 and `response.ok` was false, so the
        // connectivity indicator took the same path online and offline.
        const response = await fetch('/api/health/live', { cache: 'no-store' });
        if (response.ok) {
            updateConnectivityStatus();
        }
    } catch {
        updateConnectivityStatus();
    }

    await initInstanceSwitch();
    await initDemoTraceabilitySwitch();
    updateToolbar('profile_required');
    // Restores an existing cookie session; only falls through to the login
    // screen when the server refuses it.
    const angemeldet = await ensurePickerSelection();
    // Erst hier steht fest, welche Instanz die Sitzung wirklich traegt. Die
    // Auswahl oben wurde aus dem Speicher gebaut und kann daneben liegen.
    syncInstanceSwitch();
    if (angemeldet) {
        await loadPickingList({ skipRelease: true });
    }
}

function goToLine(idx) {
    const { currentPicking } = getState();
    if (!currentPicking) return;
    const lines = currentPicking.move_lines || [];
    if (idx < 0 || idx >= lines.length) return;
    setState({ currentLineIndex: idx });
    renderResponsiveCurrentLine();
}

// === Cluster-/Batch-Picking ============================================
// Additive Views: mehrere Auftraege gebuendelt in einem Rundgang. Nutzt den
// echten Odoo stock.picking.batch ueber /api/cluster/*. Beruehrt den Einzel-
// Picking-Flow (handleConfirmAll/handleScan) nicht.

const CLUSTER_MIN_ORDERS = 2;
const CLUSTER_RECOMMENDED_MIN_ORDERS = 4;
const CLUSTER_MAX_ORDERS = 8;

function resetClusterScanState() {
    verifiedClusterStopKey = '';
    verifiedClusterProductBarcode = '';
    clusterConfirmPending = false;
}

function clusterStopStateKey(batch, stop) {
    if (!batch?.batch_id || !stop?.stop_key) return '';
    return `${batch.batch_id}:${stop.stop_key}`;
}

function getCurrentClusterStop(batch) {
    return buildClusterStops(batch?.lines).find((stop) => !stop.picked) || null;
}

function syncClusterScanState(batch, currentStop) {
    const key = clusterStopStateKey(batch, currentStop);
    const expectedBarcode = String(currentStop?.product_barcode || '').trim();
    const verified = Boolean(
        key
        && currentStop?.tracking === 'none'
        && verifiedClusterStopKey === key
        && verifiedClusterProductBarcode
        && verifiedClusterProductBarcode === expectedBarcode
    );
    if (!verified && (verifiedClusterStopKey || verifiedClusterProductBarcode)) {
        verifiedClusterStopKey = '';
        verifiedClusterProductBarcode = '';
    }
    return verified;
}

function verifiedClusterBarcodeForLine(batch, line) {
    const currentStop = getCurrentClusterStop(batch);
    if (!currentStop || !syncClusterScanState(batch, currentStop)) return '';
    const belongsToStop = (currentStop.allocations || [currentStop])
        .some((allocation) => Number(allocation.id) === Number(line?.id));
    return belongsToStop ? verifiedClusterProductBarcode : '';
}

async function handleClusterScan(barcode) {
    stopSpeaking();
    const scanned = String(barcode || '').trim();
    if (!scanned) return;
    if (clusterConfirmPending) {
        showToast('Die vorige Kartonbuchung läuft noch.', 'warning');
        return;
    }

    const batch = getState().batch;
    const currentStop = getCurrentClusterStop(batch);
    if (!batch || !currentStop) {
        showToast('Kein offener Cluster-Halt.', 'warning');
        return;
    }

    const verified = syncClusterScanState(batch, currentStop);
    const decision = resolveClusterScan(
        currentStop,
        scanned,
        verified ? verifiedClusterProductBarcode : '',
    );

    if (decision.kind === 'product_ok') {
        verifiedClusterStopKey = clusterStopStateKey(batch, currentStop);
        verifiedClusterProductBarcode = decision.barcode;
        feedbackSuccess();
        showToast('Artikel geprüft. Jetzt den Zielkarton scannen.', 'success');
        renderClusterWalk(batch);
        document.querySelector('.cluster-stop--current [data-stop-confirm]:not([disabled])')?.focus();
        return;
    }
    if (decision.kind === 'allocation_ok') {
        await submitClusterAllocation(batch, decision.allocation, {
            scannedBarcode: verifiedClusterProductBarcode,
            scannedPackage: decision.scanned_package,
        });
        return;
    }
    if (decision.kind === 'product_already_ok') {
        showToast('Artikel ist bereits geprüft. Bitte den Zielkarton scannen.', 'info');
        return;
    }

    feedbackError();
    if (decision.kind === 'tracked') {
        showToast('Charge oder Serie bitte über „Manuell bestätigen“ erfassen.', 'warning');
    } else if (decision.kind === 'product_missing') {
        showToast('Für diesen Artikel fehlt der Produktbarcode in Odoo.', 'error');
    } else if (decision.kind === 'wrong_package') {
        showToast('Falscher Karton. Es wurde nichts gebucht.', 'error');
    } else {
        showToast('Falscher Artikel. Es wurde nichts gebucht.', 'error');
    }
}

function getClusterSelected() {
    const selected = getState().clusterSelected;
    return selected instanceof Set ? selected : new Set();
}

function getClusterSelectedSuggestions() {
    const selected = getState().clusterSelectedSuggestions;
    return selected instanceof Set ? selected : new Set();
}

function selectedPickingIds(suggestionIndexes, suggestions) {
    return new Set(Array.from(suggestionIndexes).flatMap((index) => suggestions[index]?.picking_ids || []));
}

function formatClusterQty(value) {
    const num = Number(value ?? 0);
    return Number.isInteger(num) ? String(num) : num.toFixed(2).replace(/\.?0+$/, '');
}

function resolveClusterPackageToken(line, boxes = []) {
    if (line?.package_name) return String(line.package_name);
    if (line?.package_id != null) return String(line.package_id);
    const box = (boxes || []).find((item) => Number(item.picking_id) === Number(line?.picking_id));
    if (box?.package_name) return String(box.package_name);
    if (box?.package_id != null) return String(box.package_id);
    return '';
}

function getClusterSelectionStatus(selectedIds) {
    const count = selectedIds.length;
    if (count < CLUSTER_MIN_ORDERS) {
        return { ok: false, message: `Mindestens ${CLUSTER_MIN_ORDERS} Aufträge wählen.` };
    }
    if (count > CLUSTER_MAX_ORDERS) {
        return { ok: false, message: `Maximal ${CLUSTER_MAX_ORDERS} Aufträge pro Wagen.` };
    }
    if (count < CLUSTER_RECOMMENDED_MIN_ORDERS) {
        return { ok: true, message: `Gültig; empfohlen sind ${CLUSTER_RECOMMENDED_MIN_ORDERS}-${CLUSTER_MAX_ORDERS}.` };
    }
    return { ok: true, message: `${count}/${CLUSTER_MAX_ORDERS} Aufträge im Wagen.` };
}

// Nur sichere Farbwerte in inline-styles zulassen (CSS-Injection-Schutz):
// Hex-Farben oder var(--token). Alles andere faellt auf den Primaerton zurueck.
function safeColor(value) {
    const str = String(value ?? '').trim();
    if (/^#[0-9a-fA-F]{3,8}$/.test(str)) return str;
    if (/^var\(--[a-z0-9-]+\)$/i.test(str)) return str;
    return 'var(--primary)';
}

// Ganzzahl fuer data-Attribute/Anzeige (verhindert Attribut-Ausbruch/XSS).
function safeInt(value, fallback = 0) {
    const num = Number.parseInt(value, 10);
    return Number.isFinite(num) ? num : fallback;
}

async function enterClusterMode() {
    stopSpeaking();
    closeOverlay();
    const pickerReady = await ensurePickerSelection();
    if (!pickerReady) return;
    updateToolbar('cluster_select');
    setMainContent(renderLoading());
    let suggestions;
    try {
        suggestions = await withManagedRequest((signal) => getClusterSuggestions({ signal }));
    } catch (error) {
        if (isAbortError(error)) return;
        setMainContent(renderError(`Cluster-Vorschläge konnten nicht geladen werden: ${error.message}`));
        return;
    }
    setState({
        clusterSuggestions: Array.isArray(suggestions) ? suggestions : [],
        clusterSelectedSuggestions: new Set(),
        clusterSelected: new Set(),
    });
    renderClusterSelect();
}

function renderClusterSelect() {
    const { clusterSuggestions = [] } = getState();
    const selectedSuggestions = getClusterSelectedSuggestions();
    const selected = getClusterSelected();
    const ids = Array.from(selected);
    const status = getClusterSelectionStatus(ids);
    const selectedDates = Array.from(selectedSuggestions)
        .map((index) => clusterSuggestions[index]?.delivery_date)
        .filter(Boolean);
    const selectedDate = selectedDates[0] || '';

    const suggestionsHtml = clusterSuggestions.length
        ? clusterSuggestions.map((group, index) => {
            const groupIds = Array.isArray(group.picking_ids) ? group.picking_ids.map(Number).filter(Boolean) : [];
            const isSelected = selectedSuggestions.has(index);
            const combinedCount = new Set([...ids, ...groupIds]).size;
            const incompatibleDate = !isSelected && selectedDate && group.delivery_date && group.delivery_date !== selectedDate;
            const exceedsCapacity = !isSelected && combinedCount > CLUSTER_MAX_ORDERS;
            const unavailable = incompatibleDate || exceedsCapacity;
            const reasonChips = Array.isArray(group.reasons)
                ? group.reasons.map((reason) => `<span class="cluster-rule-chip">${escapeHtml(reason)}</span>`).join('')
                : '';
            const orders = Array.isArray(group.picking_names)
                ? group.picking_names.map((name) => `<span>${escapeHtml(name)}</span>`).join('')
                : '';
            const score = Number.isFinite(Number(group.score)) ? `${safeInt(group.score)}% Passung` : 'Passende Route';
            const buttonLabel = isSelected
                ? 'Ausgewählt · Entfernen'
                : incompatibleDate
                    ? 'Anderer Liefertag'
                    : exceedsCapacity
                        ? 'Wagen voll'
                        : 'Vorschlag wählen';
            return `
            <article class="cluster-suggestion ${isSelected ? 'cluster-suggestion--selected' : ''} ${unavailable ? 'cluster-suggestion--unavailable' : ''}"
                data-suggestion-index="${index}" data-suggestion-zone="${escapeHtml(group.zone)}">
                <div class="cluster-suggestion__head">
                    <span class="cluster-suggestion__number" aria-hidden="true">${index + 1}</span>
                    <div class="cluster-suggestion__info">
                        <div class="cluster-suggestion__label">Vorschlag ${index + 1}</div>
                        <div class="cluster-suggestion__zone">${escapeHtml(group.zone)}</div>
                    </div>
                    <span class="cluster-suggestion__score">${score}</span>
                </div>
                <div class="cluster-suggestion__metrics">
                    <span><strong>${safeInt(group.order_count)}</strong> Aufträge</span>
                    <span><strong>${safeInt(group.line_count)}</strong> Positionen</span>
                    ${group.delivery_date ? `<span><strong>${escapeHtml(group.delivery_date)}</strong> Ausliefertag</span>` : ''}
                </div>
                ${orders ? `<div class="cluster-suggestion__orders">${orders}</div>` : ''}
                <div class="cluster-suggestion__footer">
                    ${reasonChips ? `<div class="cluster-rule-chips">${reasonChips}</div>` : ''}
                    <button type="button" class="cluster-suggestion__apply"
                        data-toggle-suggestion="${index}" aria-pressed="${isSelected ? 'true' : 'false'}"
                        ${unavailable ? 'disabled' : ''}>${buttonLabel}</button>
                </div>
            </article>`;
        }).join('')
        : '<p class="cluster-empty">Aktuell gibt es keine automatisch passenden Cluster.</p>';

    const count = ids.length;
    setMainContent(`
        <section class="cluster-select">
            <header class="cluster-select__intro" aria-label="Cluster-Picking">
                <div class="cluster-select__eyebrow">Gemeinsame Lagerroute</div>
                <h1>Cluster zusammenstellen</h1>
                <p>Wähle einen oder mehrere passende Vorschläge. Gleicher Ausliefertag, maximal acht Aufträge, separater Karton je Auftrag.</p>
            </header>

            <div class="cluster-section">
                <div class="cluster-section__head">
                    <h2>Empfohlene Cluster</h2>
                    <span>${clusterSuggestions.length} Vorschläge</span>
                </div>
                <div class="cluster-suggestions">${suggestionsHtml}</div>
            </div>
        </section>

        <div class="cluster-start-bar">
            <button type="button" class="cluster-back" data-cluster-back>Zurück</button>
            <div class="cluster-capacity ${status.ok ? 'cluster-capacity--ok' : 'cluster-capacity--bad'}">
                ${escapeHtml(status.message)}
            </div>
            <button type="button" class="btn-big btn-big--primary cluster-start"
                data-cluster-confirm ${status.ok ? '' : 'disabled'}>
                Batch starten${count ? ` (${count}/${CLUSTER_MAX_ORDERS})` : ''}
            </button>
        </div>
    `);
    bindClusterSelect();
}

function bindClusterSelect() {
    const root = mainEl();
    if (!root) return;

    root.querySelectorAll('[data-toggle-suggestion]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const index = Number(btn.dataset.toggleSuggestion);
            const { clusterSuggestions = [] } = getState();
            const suggestionIndexes = new Set(getClusterSelectedSuggestions());
            if (suggestionIndexes.has(index)) suggestionIndexes.delete(index);
            else suggestionIndexes.add(index);
            const selected = selectedPickingIds(suggestionIndexes, clusterSuggestions);
            if (selected.size > CLUSTER_MAX_ORDERS) {
                showToast(`Maximal ${CLUSTER_MAX_ORDERS} Aufträge pro Wagen.`, 'warning');
                return;
            }
            setState({ clusterSelectedSuggestions: suggestionIndexes, clusterSelected: selected });
            renderClusterSelect();
        });
    });

    document.querySelector('[data-cluster-back]')?.addEventListener('click', () => loadPickingList());
    document.querySelector('[data-cluster-confirm]')?.addEventListener('click', createClusterBatch);
}

async function createClusterBatch() {
    const ids = Array.from(getClusterSelected());
    if (!ids.length) return;
    const status = getClusterSelectionStatus(ids);
    if (!status.ok) {
        showToast(status.message, 'error');
        return;
    }
    const startBtn = document.querySelector('[data-cluster-confirm]');
    if (startBtn) startBtn.disabled = true;  // Doppel-Tap-Schutz (kein Server-Idempotenz im PoC)
    try {
        const batch = await withManagedRequest((signal) => createBatch(ids, {
            idempotencyKey: buildOperationKey('cluster-create', [...ids, Date.now()], { unique: true }),
            signal,
        }));
        if (batch?.error) {
            showToast(batch.error, 'error');
            if (startBtn) startBtn.disabled = false;
            return;
        }
        resetClusterScanState();
        setState({ batch });
        renderClusterWalk(batch);
        updateToolbar('cluster_walk');
    } catch (error) {
        if (isAbortError(error)) return;
        if (startBtn) startBtn.disabled = false;
        const detail = error instanceof ApiError ? error.message : 'Batch konnte nicht angelegt werden.';
        showToast(detail, 'error');
    }
}

async function loadBatch(batchId) {
    setMainContent(renderLoading());
    updateToolbar('cluster_walk');
    try {
        const batch = await withManagedRequest((signal) => getBatch(batchId, { signal }));
        if (batch?.error) {
            setMainContent(renderError(batch.error));
            return;
        }
        setState({ batch });
        renderClusterWalk(batch);
    } catch (error) {
        if (isAbortError(error)) return;
        setMainContent(renderError(`Batch konnte nicht geladen werden: ${error.message}`));
    }
}

function renderClusterWalk(batch) {
    const lines = Array.isArray(batch.lines) ? batch.lines : [];
    const stops = buildClusterStops(lines);
    const progress = batch.progress || { total: lines.length, done: 0, ratio: 0 };
    const doneCount = safeInt(progress.done);
    const totalCount = safeInt(progress.total);
    const pct = Math.max(0, Math.min(100, Math.round((Number(progress.ratio) || 0) * 100)));
    const allDone = totalCount > 0 && doneCount >= totalCount;
    if (allDone && sessionState === 'cluster_walk') updateToolbar('cluster_ready');
    const currentStopIndex = stops.findIndex((stop) => !stop.picked);
    const currentStop = currentStopIndex >= 0 ? stops[currentStopIndex] : null;
    const currentStopVerified = syncClusterScanState(batch, currentStop);

    const legendHtml = (batch.boxes || []).map((box) => `
        <span class="cluster-box-legend__item">
            <span class="cluster-box-chip" style="--box-color:${safeColor(box.box_color)}">${safeInt(box.box_index)}</span>
            ${escapeHtml(box.picking_name)}${box.package_name ? `<span class="cluster-box-pkg">${escapeHtml(box.package_name)}</span>` : ''}
        </span>`).join('');

    const linesHtml = stops.map((line, stopIndex) => {
        const done = Boolean(line.picked);
        const current = stopIndex === currentStopIndex;
        const loc = line.location_src_short || line.location_src || 'Lagerort';
        const qty = formatClusterQty(line.quantity_demand);
        const name = line.product_name || 'Produkt';
        const allocations = Array.isArray(line.allocations) ? line.allocations : [line];
        const grouped = allocations.length > 1;
        const untracked = line.tracking === 'none';
        const stopVerified = current && currentStopVerified;
        const openAllocations = allocations.filter((allocation) => !allocation.picked);
        const nextAllocation = openAllocations[0] || null;
        const trackingBadge = line.tracking === 'serial'
            ? '<span class="cluster-stop__serial">Serial</span>'
            : line.tracking === 'lot'
                ? '<span class="cluster-stop__serial">Charge</span>'
                : '';
        const lineId = safeInt(line.id);
        const allocationHtml = grouped ? allocations.map((allocation) => {
            const allocationDone = Boolean(allocation.picked);
            const allocationQty = formatClusterQty(allocation.quantity_demand);
            const boxIndex = safeInt(allocation.box_index, '?');
            const confirmLabel = `${allocationQty} Stück ${name} in Karton ${boxIndex}`
                + ` für Auftrag ${allocation.picking_name || ''} manuell bestätigen`;
            const allocationDisabled = !current || (untracked && !stopVerified) || clusterConfirmPending;
            const allocationAction = !current
                ? 'Warten'
                : stopVerified
                    ? 'Manuell'
                    : 'Gesperrt';
            return `
                <div class="cluster-stop__allocation ${allocationDone ? 'cluster-stop__allocation--done' : ''}">
                    <span class="cluster-box-chip" style="--box-color:${safeColor(allocation.box_color)}">${boxIndex}</span>
                    <span class="cluster-stop__allocation-body">
                        <strong>${escapeHtml(allocationQty)} Stück → Karton&nbsp;${boxIndex}</strong>
                        <span>${escapeHtml(allocation.picking_name || '')}</span>
                        ${allocation.package_name ? `<span class="cluster-box-pkg">${escapeHtml(allocation.package_name)}</span>` : ''}
                    </span>
                    ${allocationDone
                        ? '<span class="cluster-stop__allocation-check" aria-label="Verteilt">✓</span>'
                        : `<button type="button" class="btn-confirm cluster-stop__confirm cluster-stop__allocation-confirm"
                            data-stop-confirm="${safeInt(allocation.id)}" aria-label="${escapeHtml(confirmLabel)}"
                            ${allocationDisabled ? 'disabled' : ''}>${allocationAction}</button>`}
                </div>`;
        }).join('') : '';
        const doneQty = Number(line.quantity_done || 0);
        const distributionLabel = done
            ? 'vollständig verteilt'
            : doneQty > 0
                ? `${formatClusterQty(doneQty)} von ${qty} verteilt`
                : 'gesamt entnehmen';
        const productBarcode = String(line.product_barcode || '').trim();
        const nextBox = nextAllocation ? safeInt(nextAllocation.box_index, '?') : '?';
        const scanStatusHtml = current && !done
            ? line.tracking === 'serial' || line.tracking === 'lot'
                ? `<div class="cluster-scan-status cluster-scan-status--tracked" role="status">
                    <span class="cluster-scan-status__icon" aria-hidden="true">#</span>
                    <span><strong>${line.tracking === 'serial' ? 'Seriennummer' : 'Charge'} erfassen</strong>
                    <small>Über „Bestätigen“ atomar diesem Auftrag zuordnen.</small></span>
                </div>`
                : `<div class="cluster-scan-status ${stopVerified ? 'cluster-scan-status--verified' : ''} ${clusterConfirmPending ? 'cluster-scan-status--busy' : ''}"
                    role="${productBarcode ? 'status' : 'alert'}" aria-live="polite">
                    <span class="cluster-scan-status__icon" aria-hidden="true">${stopVerified ? '✓' : '▦'}</span>
                    <span class="cluster-scan-status__copy">
                        <strong>${clusterConfirmPending
                            ? 'Karton wird gebucht'
                            : stopVerified
                                ? 'Artikel geprüft'
                                : productBarcode
                                    ? 'Jetzt Artikel scannen'
                                    : 'Produktbarcode fehlt in Odoo'}</strong>
                        <small>${stopVerified
                            ? `Jetzt Karton ${nextBox} scannen · ${openAllocations.length} offen.`
                            : productBarcode
                                ? `Produktcode ${escapeHtml(productBarcode)} · danach Zielkarton scannen.`
                                : 'Nur die deutlich markierte manuelle Ausnahme ist möglich.'}</small>
                    </span>
                    ${nextAllocation && !clusterConfirmPending
                        ? `<button type="button" class="cluster-scan-status__manual" data-stop-manual="${safeInt(nextAllocation.id)}">
                            ${stopVerified ? 'Karton manuell wählen' : 'Ohne Scan manuell'}
                        </button>`
                        : ''}
                </div>`
            : '';
        const singleConfirmDisabled = !current || (untracked && !stopVerified) || clusterConfirmPending;
        const singleConfirmLabel = !current
            ? 'Warten'
            : untracked
                ? stopVerified ? 'Manuell' : 'Gesperrt'
                : 'Bestätigen';
        return `
            <article class="cluster-stop ${done ? 'cluster-stop--done' : ''} ${current ? 'cluster-stop--current' : ''}"
                style="--box-color:${grouped ? 'var(--primary)' : safeColor(line.box_color)}"
                data-stop-line="${lineId}" data-stop-picking="${safeInt(line.picking_id)}"
                data-stop-key="${escapeHtml(line.stop_key || '')}"
                ${current ? 'aria-current="step"' : ''}>
                <div class="cluster-stop__location">${escapeHtml(loc)}</div>
                <div class="cluster-stop__identity">
                    ${current ? renderProductVisual({
                        productId: line.product_id,
                        label: name,
                        className: 'cluster-stop__visual product-visual product-visual--card',
                        loading: 'eager',
                        size: 512,
                    }) : ''}
                    <div class="cluster-stop__body">
                        <div class="cluster-stop__product">${escapeHtml(name)} ${trackingBadge}</div>
                        ${grouped ? `
                        <div class="cluster-stop__total">
                            <strong>${escapeHtml(qty)} Stück</strong>
                            <span>${escapeHtml(distributionLabel)} · ${allocations.length} Aufträge</span>
                        </div>` : `<div class="cluster-stop__box">
                            <span class="cluster-box-chip" style="--box-color:${safeColor(line.box_color)}">${safeInt(line.box_index, '?')}</span>
                            <span class="cluster-stop__order">${escapeHtml(line.picking_name || '')}</span>
                            <span class="cluster-stop__qty">${escapeHtml(qty)} Stück</span>
                            ${line.package_name ? `<span class="cluster-box-pkg">${escapeHtml(line.package_name)}</span>` : ''}
                        </div>`}
                    </div>
                </div>
                ${grouped ? `<div class="cluster-stop__allocations" aria-label="Aufteilung auf ${allocations.length} Kartons">${allocationHtml}</div>` : ''}
                ${scanStatusHtml}
                <div class="cluster-stop__actions">
                    <button type="button" class="icon-btn cluster-stop__voice" data-stop-voice="${lineId}"
                        aria-label="Anweisung für ${escapeHtml(name)} an ${escapeHtml(loc)} vorlesen">🔊</button>
                    ${done
                        ? '<span class="cluster-stop__check" aria-label="Erledigt">✓</span>'
                        : grouped
                            ? ''
                            : `<button type="button" class="btn-confirm cluster-stop__confirm" data-stop-confirm="${lineId}"
                                ${singleConfirmDisabled ? 'disabled' : ''}>${singleConfirmLabel}</button>`}
                </div>
            </article>`;
    }).join('');

    setMainContent(`
        <section class="cluster-walk">
            <header class="cluster-progress" aria-label="Batch-Fortschritt">
                <div class="cluster-progress__head">
                    <div class="cluster-progress__title">${escapeHtml(batch.name || 'Batch')}</div>
                    <div class="cluster-progress__count" aria-label="${doneCount} von ${totalCount} Aufteilungen erledigt">${doneCount} / ${totalCount}</div>
                </div>
                <div class="cluster-progress__helper">Gesamtmenge entnehmen, danach auf die Auftragskartons verteilen.</div>
                <div class="cluster-progress__track" aria-hidden="true">
                    <span class="cluster-progress__bar" style="width:${pct}%"></span>
                </div>
                <div class="cluster-box-legend">${legendHtml}</div>
            </header>

            <div class="cluster-stops">${linesHtml || renderListEmptyState('Keine Positionen im Batch.')}</div>
        </section>

        <div class="cluster-start-bar">
            <button type="button" class="cluster-back" data-cluster-walk-back>Liste</button>
            <button type="button" class="btn-big btn-big--primary cluster-start"
                data-cluster-validate ${allDone ? '' : 'disabled'}>
                Batch abschließen
            </button>
        </div>
    `);
    bindClusterWalk(batch, stops);
}

function bindClusterWalk(batch, stops) {
    const root = mainEl();
    if (!root) return;
    const lineById = new Map((batch.lines || []).map((line) => [String(line.id), line]));
    const stopById = new Map((stops || []).map((stop) => [String(stop.id), stop]));

    root.querySelectorAll('[data-stop-voice]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const stop = stopById.get(String(btn.dataset.stopVoice));
            if (!stop) return;
            if (!stop.grouped) {
                if (stop.voice_instruction_short) speak(stop.voice_instruction_short);
                return;
            }
            const openAllocations = stop.allocations.filter((allocation) => !allocation.picked);
            const remaining = formatClusterQty(stop.quantity_remaining);
            const total = formatClusterQty(stop.quantity_demand);
            const location = stop.location_src_short || stop.location_src || 'Lagerort';
            const action = stop.quantity_done > 0
                ? `Noch ${remaining} Stück verteilen`
                : `${total} Stück entnehmen`;
            const distribution = openAllocations.map((allocation) =>
                `${formatClusterQty(allocation.quantity_demand)} in Karton ${safeInt(allocation.box_index, '?')}`
            ).join(', ');
            speak(`${location}. ${action}. ${stop.product_name || 'Produkt'}. ${distribution}.`);
        });
    });

    root.querySelectorAll('[data-stop-confirm]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const line = lineById.get(String(btn.dataset.stopConfirm));
            if (line) handleClusterConfirm(batch, line, btn);
        });
    });

    root.querySelectorAll('[data-stop-manual]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const line = lineById.get(String(btn.dataset.stopManual));
            if (line) handleClusterConfirm(batch, line, btn);
        });
    });

    document.querySelector('[data-cluster-walk-back]')?.addEventListener('click', () => loadPickingList());
    document.querySelector('[data-cluster-validate]')?.addEventListener('click', () => validateClusterBatch(batch));
}

async function handleClusterConfirm(batch, line, btn) {
    stopSpeaking();
    if (clusterConfirmPending) {
        showToast('Die vorige Kartonbuchung läuft noch.', 'warning');
        return;
    }
    if (btn) btn.disabled = true;

    // #11: Helper that re-enables the button only when it is still in the document.
    // After loadBatch() re-renders the DOM the original btn reference is detached;
    // attempting to mutate it is a no-op but also never needed on the success path.
    function reenableBtn() {
        if (btn && btn.isConnected) btn.disabled = false;
    }

    // Empfaengerkarton-Bestaetigung zuerst (Put-to-Box / Verwechslungsschutz, Akzeptanz #3+#4):
    // Hat die Position einen Ziel-Karton, muss der Picker den RICHTIGEN bestaetigen
    // (Tippen oder Scannen) - falscher Karton -> Inline-Warnung; Abbruch -> kein Confirm.
    const packageToken = resolveClusterPackageToken(line, batch.boxes);
    if (!packageToken) {
        showToast('Zielkarton fehlt. Batch bitte neu laden oder neu bilden.', 'error');
        reenableBtn();
        return;
    }
    const scannedPackage = await askCartonConfirm({ ...line, package_name: packageToken }, batch.boxes);
    if (!scannedPackage) {
        reenableBtn();
        return;
    }

    let serialNumber = '';
    if (line.tracking === 'serial' || line.tracking === 'lot') {
        serialNumber = await askSerialNumber(
            line.product_name || 'Produkt',
            { required: true, tracking: line.tracking },
        );
        if (!serialNumber) {
            reenableBtn();
            return;
        }
    }

    await submitClusterAllocation(batch, line, {
        scannedBarcode: verifiedClusterBarcodeForLine(batch, line),
        scannedPackage,
        serialNumber,
        btn,
    });
}

async function submitClusterAllocation(
    batch,
    line,
    { scannedBarcode = '', scannedPackage = '', serialNumber = '', btn = null } = {},
) {
    if (clusterConfirmPending) return false;
    clusterConfirmPending = true;
    if (btn) btn.disabled = true;
    if (sessionState === 'cluster_walk') renderClusterWalk(batch);

    try {
        const result = await withManagedRequest((signal) => confirmClusterLine(
            batch.batch_id,
            {
                picking_id: line.picking_id,
                move_line_id: line.id,
                scanned_barcode: scannedBarcode,
                quantity: line.quantity_demand,
                serial_number: serialNumber,
                scanned_package: scannedPackage,
            },
            {
                idempotencyKey: buildOperationKey('cluster-confirm', [
                    batch.batch_id,
                    line.id,
                    line.quantity_demand,
                    scannedBarcode,
                    scannedPackage,
                    serialNumber,
                ]),
                signal,
            },
        ));
        if (!result?.success) {
            clusterConfirmPending = false;
            feedbackError();
            showToast(result?.message || 'Bestätigung fehlgeschlagen.', 'error');
            if (btn?.isConnected) btn.disabled = false;
            if (sessionState === 'cluster_walk') renderClusterWalk(getState().batch || batch);
            return false;
        }
        clusterConfirmPending = false;
        feedbackSuccess();
        await loadBatch(batch.batch_id);
        return true;
    } catch (error) {
        clusterConfirmPending = false;
        if (isAbortError(error)) return false;
        feedbackError();
        if (btn?.isConnected) btn.disabled = false;
        const detail = error instanceof ApiError ? error.message : 'Bestätigung fehlgeschlagen.';
        showToast(detail, 'error');
        if (sessionState === 'cluster_walk') renderClusterWalk(getState().batch || batch);
        return false;
    }
}

async function validateClusterBatch(batch) {
    const validateBtn = document.querySelector('[data-cluster-validate]');
    if (validateBtn) validateBtn.disabled = true;
    try {
        const result = await withManagedRequest((signal) => validateBatch(batch.batch_id, {
            idempotencyKey: buildOperationKey('cluster-validate', [batch.batch_id, Date.now()], { unique: true }),
            signal,
        }));
        if (!result?.batch_complete) {
            // #8: Distinguish Odoo wizard / pending_action from a plain failure.
            // Backend signals this via result.pending_action (e.g. "stock.backorder.confirmation").
            // The picker cannot resolve this in the app; they must escalate to a supervisor.
            if (result?.pending_action) {
                feedbackError();
                showToast(
                    'Batch konnte nicht automatisch abgeschlossen werden. Bitte Vorgesetzte:n informieren (Odoo-Aktion erforderlich).',
                    'error',
                );
                if (validateBtn) validateBtn.disabled = false;
                return;
            }
            feedbackError();
            showToast(result?.message || 'Batch konnte nicht abgeschlossen werden.', 'error');
            if (validateBtn) validateBtn.disabled = false;
            return;
        }
        if (result.integration_status === 'degraded') {
            showToast('Batch abgeschlossen, n8n-Folgeprozess degradiert.', 'warning');
        }
        renderClusterComplete(batch);
    } catch (error) {
        if (isAbortError(error)) return;
        if (validateBtn) validateBtn.disabled = false;
        const detail = error instanceof ApiError ? error.message : 'Abschluss fehlgeschlagen.';
        showToast(detail, 'error');
    }
}

function renderClusterComplete(batch) {
    const orders = (batch.boxes || []).length;
    const positions = (batch.lines || []).length;
    updateToolbar('cluster_complete');
    setMainContent(`
        <section class="cluster-complete state-panel" role="status">
            <div class="state-panel__eyebrow">Abgeschlossen</div>
            <div class="state-panel__title">Batch ${escapeHtml(batch.name || '')} fertig</div>
            <div class="state-panel__meta">${orders} Aufträge · ${positions} Positionen gesammelt validiert.</div>
            <div class="cluster-complete__actions">
                <button type="button" class="btn-big btn-big--primary" data-cluster-to-list>Zur Liste</button>
                <button type="button" class="picker-option" data-cluster-new>Neuer Batch</button>
            </div>
        </section>
    `);
    document.querySelector('[data-cluster-to-list]')?.addEventListener('click', () => loadPickingList());
    document.querySelector('[data-cluster-new]')?.addEventListener('click', () => enterClusterMode());
}

// Einstiegspunkt: Klick auf den "Batch starten"-Button in der Listenansicht.
// Delegation am Document, damit die Listen-Render-/Bind-Funktionen unberuehrt bleiben.
document.addEventListener('click', (event) => {
    if (event.target?.closest?.('[data-cluster-start]')) {
        event.preventDefault();
        enterClusterMode();
    }
});

window._app = {
    loadPickingList,
    loadPickingDetail,
    setFilter,
    goToLine,
    triggerConfirmAll,
    handleVoiceIntent,
    enterClusterMode,
    loadBatch,
};

// Module scripts are always deferred — DOMContentLoaded is not needed.
init();
