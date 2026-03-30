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
    createIdempotencyKey,
    createQualityAlert,
    getActivePicker,
    getCachedPickers,
    getDeviceId,
    getPickers,
    getPickingDetail,
    getPickings,
    getStoredHighContrastEnabled,
    getStoredPreferredZone,
    getStoredSearchQuery,
    releasePicking,
    setActivePicker,
    setCachedPickers,
    setStoredHighContrastEnabled,
    setStoredPreferredZone,
    setStoredSearchQuery,
    heartbeatPicking,
} from './api.js';
import { feedbackSuccess, feedbackError } from './feedback.js';
import { setState, getState, subscribe, renderPickCard, renderLoading, renderError, renderProductVisual, showToast } from './ui.js';
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
    buildVoiceAssistPayload,
    buildVoiceRequestContext,
    classifyVoiceResult,
    getVoiceStatusPresentation,
} from './voice-runtime.mjs';
import { createFileInput } from './camera.js';
import { initPWA } from './pwa.js';

const CLAIM_HEARTBEAT_MS = 30_000;
const VOICE_LONG_PRESS_MS = 350;
const DEFAULT_FILTER = 'all';
const ZONE_FILTER = 'zone';
const VOICE_ASSIST_SHORTAGE_RE = /\b(fehlt|fehlmenge|mangel|nachschub|leer|restbestand)\b/i;
const DARK_THEME_COLOR = '#091014';
const LIGHT_THEME_COLOR = '#F5F5F5';
const LIFECYCLE_REFRESH_DEBOUNCE_MS = 900;

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

function getPickingSupportingLabel(picking) {
    if (!getPickingKitName(picking)) return '';
    return getPickingPrimaryLabel(picking);
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

function getPrimaryItemSku(picking) {
    return picking?.primary_item_sku || '';
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
    if (!line) return '';
    if (line.voice_instruction_short) return line.voice_instruction_short;
    const locationShort = line.location_src_short || formatLocationForSpeech(line.location_src);
    const product = getLineDisplayName(line);
    return [
        locationShort ? `${locationShort}.` : '',
        `${formatQuantity(line.quantity_demand)} Stück.`,
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

let activeFilter = DEFAULT_FILTER;
let claimHeartbeatTimer = null;
let claimedPickingId = null;
let voiceLongPressTimer = null;
let voiceLongPressStarted = false;
let suppressNextVoiceClick = false;
let voiceStatusResetTimer = null;
let searchQuery = getStoredSearchQuery();
let mobileSearchOpen = Boolean(searchQuery);
let preferredZone = getStoredPreferredZone();
let highContrastEnabled = getStoredHighContrastEnabled();
let sessionState = 'profile_required';
let pickerCatalog = getCachedPickers();
let lastLifecycleRefreshAt = 0;
let lifecycleRefreshPromise = null;
const pendingRequestControllers = new Set();

const mainEl = () => document.getElementById('main');
const headerEl = () => document.getElementById('header');
const statusEl = () => document.getElementById('status-indicator');
const voiceStatusEl = () => document.getElementById('voice-status-indicator');
const pickerEl = () => document.getElementById('picker-indicator');
const headerSearchEl = () => document.querySelector('.header-search');
const searchInputEl = () => document.getElementById('search-input');
const taskCounterEl = () => document.getElementById('task-counter');
const filterChipsEl = () => document.getElementById('filter-chips');
const filterRowEl = () => document.querySelector('.header-row--filters');
const highContrastToggleEl = () => document.getElementById('high-contrast-toggle');
const searchToggleEl = () => document.getElementById('search-toggle');
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

async function withManagedRequest(task) {
    const controller = createManagedAbortController();
    try {
        return await task(controller.signal);
    } finally {
        pendingRequestControllers.delete(controller);
    }
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
    const themeColor = highContrastEnabled ? LIGHT_THEME_COLOR : DARK_THEME_COLOR;
    document.documentElement.style.colorScheme = highContrastEnabled ? 'light' : 'dark';
    themeColorMetaEl()?.setAttribute('content', themeColor);
    statusBarMetaEl()?.setAttribute('content', highContrastEnabled ? 'default' : 'black-translucent');
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
    sessionState = view;
    const buttons = [btnVoice(), btnScan(), btnAlert()];
    const visualView = view === 'search_expanded' ? 'list' : view;
    const show = visualView === 'detail';
    buttons.forEach((button) => {
        if (button) button.classList.toggle('hidden', !show);
    });
    const nav = navEl();
    if (nav) nav.classList.toggle('hidden', !show);
    if (!show) {
        btnVoice()?.classList.remove('nav-btn--ptt');
        if (isVoiceModeActive()) stopVoiceMode();
    }

    document.body.dataset.view = visualView;
    document.body.dataset.sessionState = view;
    const searchInput = searchInputEl();
    const searchEnabled = view === 'list' || view === 'search_expanded';
    if (searchInput) searchInput.disabled = !searchEnabled;
    headerSearchEl()?.toggleAttribute('hidden', !searchEnabled);
    filterRowEl()?.toggleAttribute('hidden', !searchEnabled);
    searchToggleEl()?.toggleAttribute('hidden', !searchEnabled);
    headerEl()?.classList.toggle('header--picker-only', view === 'profile_required');
}

function updatePickerIndicator() {
    const indicator = pickerEl();
    if (!indicator) return;
    const picker = getState().currentPicker;
    if (picker?.name) {
        indicator.textContent = picker.name;
        indicator.title = picker.name;
        indicator.setAttribute('aria-label', picker.name);
        indicator.dataset.shortLabel = getPickerShortLabel(picker);
        indicator.classList.remove('picker-indicator--empty');
    } else {
        indicator.textContent = 'Profil';
        indicator.title = 'Profil wählen';
        indicator.setAttribute('aria-label', 'Profil wählen');
        indicator.dataset.shortLabel = '+';
        indicator.classList.add('picker-indicator--empty');
    }
}

function updateConnectivityStatus({ loading = false } = {}) {
    const indicator = statusEl();
    if (!indicator) return;

    if (loading) {
        indicator.textContent = 'Sync';
        indicator.className = 'status status--sync';
        indicator.dataset.shortLabel = getStatusShortLabel('sync');
        indicator.title = 'Synchronisiert';
        return;
    }

    if (navigator.onLine) {
        indicator.textContent = 'Online';
        indicator.className = 'status online';
        indicator.dataset.shortLabel = getStatusShortLabel('online');
        indicator.title = 'Online';
        return;
    }

    indicator.textContent = 'Offline';
    indicator.className = 'status offline';
    indicator.dataset.shortLabel = getStatusShortLabel('offline');
    indicator.title = 'Offline';
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

function applyHighContrastTheme() {
    document.body.classList.toggle('high-contrast', highContrastEnabled);
    syncThemeChrome();
    const toggle = highContrastToggleEl();
    if (!toggle) return;
    toggle.setAttribute('aria-pressed', highContrastEnabled ? 'true' : 'false');
    toggle.classList.toggle('status-toggle--active', highContrastEnabled);
    toggle.dataset.shortLabel = 'AA';
    toggle.title = highContrastEnabled ? 'Kontrast aktiv' : 'Kontrast';
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
        renderCurrentLine();
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
                await showProfileSelection({ preferCache: true });
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
        renderPickingsView(pickings);
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

function renderQueueOverview(visiblePickings) {
    const urgentCount = visiblePickings.filter((picking) => picking.priority === '1').length;
    const pickerName = getState().currentPicker?.name || 'Kein Profil aktiv';

    return `
        <section class="queue-overview" aria-label="Arbeitsbereich">
            <div class="queue-overview__eyebrow">Arbeitsbereich</div>
            <div class="queue-overview__title">${visiblePickings.length} offene Aufträge</div>
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
        </section>
    `;
}

function renderPickingListCard(picking) {
    const reference = getPickingReference(picking);
    const typeName = getPickingTypeLabel(picking);
    const primaryLabel = getPickingHeadline(picking);
    const supportingLabel = getPickingSupportingLabel(picking);
    const partner = picking.partner_id ? picking.partner_id[1] : 'Ohne Partner';
    const scheduledDate = picking.scheduled_date
        ? new Date(picking.scheduled_date).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
        : 'Ohne Termin';
    const progressPercent = Math.round(getProgressRatio(picking) * 100);
    const progressLabel = getProgressLabel(picking);
    const sku = getPrimaryItemSku(picking);
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
                    productId: picking.primary_product_id,
                    label: primaryLabel,
                    className: 'pick-list-card__thumb product-visual product-visual--thumb',
                    size: 256,
                })}
                <div class="pick-list-card__content">
                    <div class="pick-list-card__product">${escapeHtml(primaryLabel)}</div>
                    ${supportingLabel ? `<div class="pick-list-card__context">${escapeHtml(supportingLabel)}</div>` : ''}
                    <div class="pick-list-card__meta">
                        ${sku ? `<span>${escapeHtml(sku)}</span>` : ''}
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

function renderPickingsView(pickings) {
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
                ${renderQueueOverview([])}
                ${renderListEmptyState(
                    'Keine Treffer für diese Suche.',
                    'Suche nach Auftrag, Produkt, SKU, Platz oder Partner.'
                )}
            </div>
        `);
        return;
    }

    if (!visiblePickings.length) {
        const filterMessage = activeFilter === 'high'
            ? 'Keine dringenden Aufträge für diese Suche.'
            : 'In deinem Bereich gibt es aktuell keine passenden Aufträge.';
        setMainContent(`
            <div class="queue-shell">
                ${renderQueueOverview([])}
                ${renderListEmptyState(filterMessage)}
            </div>
        `);
        return;
    }

    setMainContent(`
        <div class="queue-shell">
            ${renderQueueOverview(visiblePickings)}
            <section class="pick-list-grid" aria-label="Offene Picking-Aufträge">
                ${visiblePickings.map((picking) => renderPickingListCard(picking)).join('')}
            </section>
        </div>
    `);

    mainEl().querySelectorAll('.pick-list-card[data-id]').forEach((card) => {
        card.addEventListener('click', () => loadPickingDetail(Number(card.dataset.id)));
    });
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

function renderPickerUnavailable({ message, detail = 'Bitte prüfe die Verbindung und versuche es erneut.' } = {}) {
    updateToolbar('profile_required');
    renderFilterChips([]);
    updateTaskCounter(0);
    setMainContent(`
        <div class="picker-screen">
            <section class="picker-card">
                <div class="picker-card__eyebrow">Session-Start</div>
                <h2 class="picker-card__title">Profile konnten nicht geladen werden</h2>
                <p class="picker-card__text">${escapeHtml(message)}</p>
                <p class="picker-card__text">${escapeHtml(detail)}</p>
                <div class="picker-device">Gerät: ${getDeviceId()}</div>
                <div class="picker-card__actions">
                    <button id="picker-retry" class="picker-option picker-option--primary">Erneut versuchen</button>
                </div>
            </section>
        </div>
    `);

    document.getElementById('picker-retry')?.addEventListener('click', () => {
        showProfileSelection({ preferCache: false });
    });
}

function renderPickerOption(picker) {
    return `
        <button class="picker-option picker-option--profile" data-picker-id="${picker.id}">
            <span class="picker-option__avatar" aria-hidden="true">${escapeHtml(getPickerShortLabel(picker))}</span>
            <span class="picker-option__copy">
                <span class="picker-option__name">${escapeHtml(picker.name)}</span>
                <span class="picker-option__meta">Odoo Benutzer</span>
            </span>
        </button>
    `;
}

function renderPickerSelection(
    pickers,
    {
        title = 'Profil auswählen',
        intro = 'Bitte wähle deinen Odoo-Benutzer für diese Session.',
        statusNote = '',
    } = {},
) {
    updateToolbar('profile_required');
    renderFilterChips([]);
    updateTaskCounter(0);
    setMainContent(`
        <div class="picker-screen">
            <section class="picker-card">
                <div class="picker-card__eyebrow">Session-Start</div>
                <h2 class="picker-card__title">${escapeHtml(title)}</h2>
                <p class="picker-card__text">${escapeHtml(intro)}</p>
                ${statusNote ? `<p class="picker-card__text">${escapeHtml(statusNote)}</p>` : ''}
                <div class="picker-device">Gerät: ${getDeviceId()}</div>
                <div class="picker-options">
                    ${pickers.map((picker) => renderPickerOption(picker)).join('')}
                </div>
            </section>
        </div>
    `);

    mainEl().querySelectorAll('[data-picker-id]').forEach(button => {
        button.addEventListener('click', async () => {
            const pickerId = Number(button.dataset.pickerId);
            const picker = pickers.find(item => item.id === pickerId);
            if (!picker) return;
            setActivePicker(picker);
            setState({ currentPicker: picker, deviceId: getDeviceId() });
            updatePickerIndicator();
            await loadPickingList({ skipRelease: true });
        });
    });
}

async function refreshPickerCatalogInBackground() {
    try {
        const pickers = await withManagedRequest((signal) => getPickers({ signal }));
        if (!Array.isArray(pickers) || !pickers.length) return;
        pickerCatalog = pickers;
        setCachedPickers(pickers);
        if (sessionState === 'profile_required') {
            renderPickerSelection(pickerCatalog);
        }
    } catch (error) {
        if (!isAbortError(error)) {
            console.warn('Picker-Refresh fehlgeschlagen:', error);
        }
    }
}

async function showProfileSelection({ preferCache = true } = {}) {
    updateToolbar('profile_required');
    renderFilterChips([]);
    updateTaskCounter(0);

    const cachedPickers = preferCache ? getCachedPickers() : [];
    if (cachedPickers.length) {
        pickerCatalog = cachedPickers;
        renderPickerSelection(
            pickerCatalog,
            navigator.onLine
                ? {}
                : {
                    statusNote: 'Offline: Verwende zuletzt geladene Profile. Die Auftragsliste braucht wieder Netz.',
                },
        );
        if (navigator.onLine) {
            void refreshPickerCatalogInBackground();
        }
        return false;
    }

    setMainContent(renderLoading());
    try {
        const pickers = await withManagedRequest((signal) => getPickers({ signal }));
        if (!Array.isArray(pickers) || !pickers.length) {
            renderPickerUnavailable({
                message: 'Keine aktiven Picker in Odoo gefunden.',
                detail: 'Lege mindestens einen internen Benutzer in Odoo an.',
            });
            return false;
        }
        pickerCatalog = pickers;
        setCachedPickers(pickers);
        renderPickerSelection(pickers);
        return false;
    } catch (error) {
        if (isAbortError(error)) return false;
        renderPickerUnavailable({
            message: navigator.onLine
                ? `Picker konnten nicht geladen werden: ${error.message}`
                : 'Es besteht aktuell keine Verbindung zum Server.',
            detail: navigator.onLine
                ? 'Bitte erneut versuchen.'
                : 'Ohne bereits gecachte Profile ist keine Profilauswahl möglich.',
        });
        return false;
    }
}

async function ensurePickerSelection() {
    const existingPicker = getActivePicker() || getState().currentPicker;
    if (existingPicker?.id) {
        setState({ currentPicker: existingPicker, deviceId: getDeviceId() });
        updatePickerIndicator();
        return true;
    }

    await showProfileSelection();
    return false;
}

async function switchProfile() {
    updateToolbar('switching_profile');
    abortPendingRequests();
    stopSpeaking();
    closeOverlay();
    stopClaimHeartbeat();
    if (isVoiceModeActive()) stopVoiceMode();
    btnVoice()?.classList.remove('nav-btn--ptt');
    await releaseCurrentClaim();
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
    await showProfileSelection();
}

async function loadPickingList({ skipRelease = false } = {}) {
    stopSpeaking();
    closeOverlay();
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

        renderPickingsView(pickings);
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
        renderCurrentLine();

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

function renderCurrentLine() {
    const { currentPicking, currentLineIndex } = getState();
    if (!currentPicking) return;
    updateToolbar('detail');
    closeOverlay();

    const lines = currentPicking.move_lines || [];
    if (currentLineIndex >= lines.length) {
        updateToolbar('complete');
        setMainContent(`
            <section class="detail-shell detail-shell--complete" aria-label="Picking abgeschlossen">
                <div class="detail-complete-icon">OK</div>
                <div class="detail-complete-title">${escapeHtml(getPickingReference(currentPicking))}</div>
                <div class="detail-complete-copy">Alle Artikel erfasst und synchronisiert.</div>
                <button onclick="window._app.loadPickingList()" class="detail-complete-button">
                    Zurück zur Liste
                </button>
            </section>`);
        return;
    }

    const line = lines[currentLineIndex];
    const progress = `${currentLineIndex + 1} / ${lines.length}`;
    const detailZone = line.location_src_zone || 'Nächster Bereich';
    const detailLocation = line.location_src_short || formatLocationForDisplay(line.location_src);
    const detailProduct = getLineDisplayName(line);
    const detailSku = line.product_sku || line.product_barcode || 'Keine SKU';
    const detailPartner = currentPicking.partner_id ? currentPicking.partner_id[1] : 'Aktives Picking';
    const progressPercent = Math.round(((currentLineIndex + 1) / Math.max(lines.length, 1)) * 100);
    const kitName = getPickingKitName(currentPicking);
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
            <section class="detail-product-hero" aria-label="Artikelbild">
                <div class="detail-product-hero__head">
                    <div class="detail-product-hero__eyebrow">Artikelbild</div>
                    <div class="detail-product-hero__chip">${escapeHtml(detailSku)}</div>
                </div>
                ${detailHero}
            </section>
            ${kitName ? `
                <section class="detail-context" aria-label="Modellkontext">
                    <div class="detail-context__eyebrow">Modellkontext</div>
                    <div class="detail-context__title">${escapeHtml(kitName)}</div>
                    <div class="detail-context__meta">${escapeHtml(detailPartner)}</div>
                </section>
            ` : ''}
            <section class="detail-summary" aria-label="Picking Übersicht">
                <div class="detail-summary__eyebrow">${escapeHtml(kitName ? 'Aktueller Griff' : 'Aktueller Pick')}</div>
                <div class="detail-summary__location">${escapeHtml(detailLocation)}</div>
                <div class="detail-summary__title">${escapeHtml(detailProduct)}</div>
                <div class="detail-summary__subline">
                    <span class="detail-summary__quantity">${escapeHtml(getLineQuantityLabel(line))}</span>
                    <span>${escapeHtml(detailZone)}</span>
                    <span>${escapeHtml(detailPartner)}</span>
                    <span>${escapeHtml(detailSku)}</span>
                </div>
                <div class="detail-summary__progress-track" aria-hidden="true">
                    <span class="detail-summary__progress-bar" style="width:${progressPercent}%"></span>
                </div>
                <div class="detail-summary__helper">Scanne den Artikel oder bestätige den Griff per Touch.</div>
            </section>
            ${renderRouteHint(currentPicking, currentLineIndex)}
            ${currentPicking.has_pending_quality_ai ? '<div class="ai-pending-banner">KI analysiert Qualitätsfall</div>' : ''}
            ${renderPickCard({
                ...line,
                quantity_demand: line.quantity_demand,
            })}
            <div id="scan-input-area" class="detail-scan-area"></div>
        </div>`);

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
        const result = await withManagedRequest((signal) => confirmLine(
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
                signal,
            },
        ));

        if (!result.success) {
            feedbackError();
            speak(result.message || 'Fehler beim Bestätigen.');
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
            speak('Dieses Picking wurde inzwischen von jemand anderem übernommen.');
            return;
        }
        if (isAbortError(error)) return;

        showToast(error.message || 'Verbindungsfehler', 'error');
        speak('Verbindungsfehler. Bitte erneut versuchen.');
    }
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

async function handleVoiceIntent(result) {
    const classification = classifyVoiceResult(result);
    if (classification.kind === 'error') {
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        return;
    }

    const { currentPicking, currentLineIndex } = getState();

    if (result?.text) {
        const intentLabel = result.intent !== 'unknown' ? ` -> ${result.intent}` : ' -> nicht erkannt';
        showToast(`"${result.text}"${intentLabel}`, result.intent !== 'unknown' ? 'info' : 'warning');
    }

    if (classification.kind === 'unknown') {
        if (await maybeHandleVoiceAssist(result, currentPicking, currentLineIndex)) return;
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        return;
    }

    if (classification.kind === 'uncertain') {
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        showToast(classification.promptText, 'warning');
        speak(classification.promptText);
        return;
    }

    updateVoiceStatusIndicator('recognized', { temporary: true });

    if (await maybeHandleVoiceAssist(result, currentPicking, currentLineIndex)) return;

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
            speak('Kommandos: bestätigen, weiter, zurück, wiederholen, Problem, fertig.');
            break;
        case 'filter_high':
            if (currentPicking !== null) break;
            activeFilter = 'high';
            await loadPickingList({ skipRelease: true });
            speak('Gefiltert. Zeige nur dringende Aufträge.');
            break;
        case 'filter_normal':
            if (currentPicking !== null) break;
            activeFilter = DEFAULT_FILTER;
            await loadPickingList({ skipRelease: true });
            speak('Filter zurückgesetzt. Alle Aufträge.');
            break;
        case 'status': {
            if (currentPicking !== null) break;
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
            break;
        }
        default:
            break;
    }
}

function shouldUseVoiceAssist(result, currentPicking) {
    if (!result?.text) return false;
    if (result.intent === 'stock_query' || result.intent === 'unknown') return true;
    if (result.intent === 'problem' && VOICE_ASSIST_SHORTAGE_RE.test(result.text)) return true;
    if (!currentPicking && result.intent === 'help') return false;
    return false;
}

async function maybeHandleVoiceAssist(result, currentPicking, currentLineIndex) {
    if (!shouldUseVoiceAssist(result, currentPicking)) return false;

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

function openQualityAlertForm() {
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
    applyHighContrastTheme();
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

    const highContrastToggle = highContrastToggleEl();
    if (highContrastToggle) {
        highContrastToggle.addEventListener('click', () => {
            highContrastEnabled = !highContrastEnabled;
            setStoredHighContrastEnabled(highContrastEnabled);
            applyHighContrastTheme();
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
        const response = await fetch('/api/health', { cache: 'no-store' });
        if (response.ok) {
            updateConnectivityStatus();
        }
    } catch {
        updateConnectivityStatus();
    }

    updateToolbar('profile_required');
    await showProfileSelection();
}

window._app = {
    loadPickingList,
    loadPickingDetail,
    setFilter,
};

// Module scripts are always deferred — DOMContentLoaded is not needed.
init();
