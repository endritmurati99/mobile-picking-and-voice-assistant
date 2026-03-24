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
    listeners.forEach(fn => fn(state));
}

export function subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
}

// ── UI-Rendering ────────────────────────────────────────────

export function renderPickCard(move) {
    return `
        <div class="pick-card">
            <div class="product">${move.product_name || 'Produkt'}</div>
            <div class="location">📍 ${move.location_src || 'Lagerort'}</div>
            <div class="quantity">${move.quantity_demand || 0} Stk.</div>
            <div style="font-size:0.8rem; color:var(--text-muted); margin-top:4px;" aria-hidden="true">
                Barcode: ${move.product_barcode || '—'}
            </div>
            <button class="btn-confirm" data-line-id="${move.id}">
                ✅ Bestätigen
            </button>
        </div>
    `;
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
    requestAnimationFrame(() => { toast.style.opacity = '1'; });
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
