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

function renderOperationalPickCard({ move, productLabel, locationLabel, zoneLabel, quantityLabel }) {
    return `
        <div class="pick-card">
            <div class="pick-card__eyebrow">${zoneLabel}</div>
            <div class="pick-card__product">${productLabel}</div>
            <div class="pick-card__location">${locationLabel}</div>
            <div class="pick-card__meta">
                <div class="pick-card__quantity">${quantityLabel} Stueck</div>
                <div class="pick-card__barcode" aria-hidden="true">
                    Barcode: ${move.product_barcode || '-'}
                </div>
            </div>
            <button class="btn-confirm" data-line-id="${move.id}">
                Bestaetigen
            </button>
        </div>
    `;
}

export function renderPickCard(move) {
    const productLabel = move.ui_display || move.product_short_name || move.product_name || 'Produkt';
    const locationLabel = move.location_src_short || move.location_src || 'Lagerort';
    const zoneLabel = move.location_src_zone || 'Naechster Platz';
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
    return '<div style="text-align:center; padding:40px; color:var(--text-muted);">Laden...</div>';
}

export function renderError(message) {
    return `<div style="text-align:center; padding:40px; color:var(--danger);">${message}</div>`;
}

export function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    const colors = { info: '#0f3460', success: '#4caf50', error: '#f44336', warning: '#ff9800' };
    toast.style.cssText = `
        position:fixed; bottom:80px; left:50%; transform:translateX(-50%);
        background:${colors[type]}; color:#fff; padding:12px 24px; border-radius:8px;
        font-size:0.9rem; z-index:1000; opacity:0; transition:opacity 0.3s;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
    });
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
