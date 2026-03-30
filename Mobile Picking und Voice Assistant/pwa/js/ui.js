/**
 * UI-Komponenten und State Management.
 * Einfaches State-Pattern ohne Framework.
 */

const state = {
    pickings: [],
    currentPicking: null,
    currentLineIndex: 0,
    currentPicker: null,
    deviceId: '',
    voiceActive: false,
    loading: false,
};

const listeners = new Set();

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

export function getState() {
    return { ...state };
}

export function setState(updates) {
    Object.assign(state, updates);
    listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
}

function getProductVisualInitials(label) {
    return String(label || 'PK')
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase() || '')
        .join('') || 'PK';
}

export function renderProductVisual({ productId, label, className = '', loading = 'lazy', size = 256 }) {
    const initials = getProductVisualInitials(label);
    const normalizedSize = Number.isFinite(Number(size)) ? Math.max(128, Math.min(1920, Number(size))) : 256;
    const imageHtml = productId
        ? `<img src="/api/products/${productId}/image?size=${normalizedSize}" alt="" loading="${loading}" decoding="async" onload="this.parentElement.classList.add('product-visual--has-image')" onerror="this.remove()">`
        : '';

    return `
        <div class="${className}" aria-hidden="true">
            ${imageHtml}
            <span class="product-visual__fallback">${escapeHtml(initials)}</span>
        </div>
    `;
}

function renderOperationalPickCard({ move, productLabel, locationLabel, zoneLabel, quantityLabel }) {
    const productSku = move.product_sku || move.product_barcode || 'Keine SKU';

    return `
        <section class="pick-card" aria-label="Aktueller Pick">
            ${renderProductVisual({
                productId: move.product_id,
                label: productLabel,
                className: 'pick-card__media product-visual product-visual--card',
                size: 512,
            })}
            <div class="pick-card__content">
                <div class="pick-card__eyebrow">${zoneLabel}</div>
                <div class="pick-card__product">${productLabel}</div>
                <div class="pick-card__meta">
                    <span class="pick-card__sku">${productSku}</span>
                    <span class="pick-card__barcode">Barcode: ${move.product_barcode || '-'}</span>
                </div>
                <div class="pick-card__quantity">${quantityLabel} Stück</div>
            </div>
            <div class="pick-card__location-box">
                <div class="pick-card__location-label">Platz</div>
                <div class="pick-card__location">${locationLabel}</div>
            </div>
            <button class="btn-confirm" data-line-id="${move.id}">
                Bestätigen
            </button>
        </section>
    `;
}

export function renderPickCard(move) {
    const productLabel = move.ui_display || move.product_short_name || move.product_name || 'Produkt';
    const locationLabel = move.location_src_short || move.location_src || 'Lagerort';
    const zoneLabel = move.location_src_zone || 'Nächster Platz';
    const quantity = Number(move.quantity_demand ?? 0);
    const quantityLabel = Number.isInteger(quantity)
        ? String(quantity)
        : quantity.toFixed(2).replace(/\.?0+$/, '');

    return renderOperationalPickCard({
        move,
        productLabel,
        locationLabel,
        zoneLabel,
        quantityLabel,
    });
}

export function renderLoading() {
    return `
        <div class="state-panel state-panel--loading" role="status" aria-live="polite">
            <div class="state-panel__eyebrow">Synchronisiert</div>
            <div class="state-panel__title">Lagerdaten werden vorbereitet</div>
            <div class="state-panel__meta">Session, Profilstatus und offene Aufträge werden geladen.</div>
            <div class="state-panel__track" aria-hidden="true">
                <span class="state-panel__bar"></span>
            </div>
        </div>
    `;
}

export function renderError(message) {
    return `
        <div class="state-panel state-panel--error" role="alert">
            <div class="state-panel__eyebrow">Störung</div>
            <div class="state-panel__title">Fehler</div>
            <div class="state-panel__meta">${escapeHtml(message)}</div>
        </div>
    `;
}

export function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.setAttribute('role', 'status');
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(() => {
        toast.classList.add('toast--visible');
    });
    setTimeout(() => {
        toast.classList.remove('toast--visible');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
