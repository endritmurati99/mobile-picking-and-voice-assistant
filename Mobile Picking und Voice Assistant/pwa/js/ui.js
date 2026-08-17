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

export function buildClusterStops(lines) {
    const source = Array.isArray(lines) ? lines : [];
    const entries = source.map((line) => {
        const location = line?.location_src_id ?? line?.location_src;
        const lineKey = `line:${line?.id}`;
        const canGroup = line?.tracking === 'none'
            && line?.product_id != null
            && location != null
            && String(location).trim()
            && line?.picking_id != null;
        return {
            line,
            lineKey,
            key: canGroup
                ? JSON.stringify([String(line.product_id), String(location).trim()])
                : lineKey,
        };
    });
    const buckets = new Map();
    entries.forEach(({ key, line }) => {
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push(line);
    });

    const emitted = new Set();
    const quantity = (line) => {
        const value = Number(line?.quantity_demand ?? 0);
        return Number.isFinite(value) ? value : 0;
    };

    return entries.flatMap(({ key, line, lineKey }) => {
        const bucket = buckets.get(key) || [line];
        const pickingIds = new Set(bucket.map((item) => item.picking_id));
        const grouped = bucket.length > 1 && pickingIds.size === bucket.length;
        const allocations = grouped
            ? [...bucket].sort((a, b) => Number(a.box_index ?? Infinity) - Number(b.box_index ?? Infinity))
            : [line];

        if (allocations.length > 1) {
            if (emitted.has(key)) return [];
            emitted.add(key);
        }

        const total = allocations.reduce((sum, item) => sum + quantity(item), 0);
        const done = allocations.reduce(
            (sum, item) => sum + (item.picked ? quantity(item) : 0),
            0,
        );
        return [{
            ...allocations[0],
            stop_key: grouped ? key : lineKey,
            allocations,
            grouped,
            quantity_demand: total,
            quantity_done: done,
            quantity_remaining: total - done,
            picked: allocations.every((item) => Boolean(item.picked)),
        }];
    });
}

export function resolveClusterScan(stop, scannedValue, verifiedProductBarcode = '') {
    const scanned = String(scannedValue ?? '').trim();
    if (stop?.tracking !== 'none') return { kind: 'tracked' };

    const productBarcode = String(stop?.product_barcode ?? '').trim();
    if (!productBarcode) return { kind: 'product_missing' };

    const verifiedBarcode = String(verifiedProductBarcode ?? '').trim();
    if (!verifiedBarcode) {
        return scanned === productBarcode
            ? { kind: 'product_ok', barcode: scanned }
            : { kind: 'wrong_product' };
    }

    const allocations = Array.isArray(stop?.allocations) ? stop.allocations : [stop];
    const normalizedPackage = scanned.toLowerCase();
    const allocation = allocations.find((item) => {
        if (!item || item.picked) return false;
        const packageName = String(item.package_name ?? '').trim().toLowerCase();
        const packageId = item.package_id == null ? '' : String(item.package_id).trim();
        return Boolean(scanned) && (
            (packageName && normalizedPackage === packageName)
            || (packageId && scanned === packageId)
        );
    });

    if (allocation) {
        return { kind: 'allocation_ok', allocation, scanned_package: scanned };
    }
    if (scanned === productBarcode) return { kind: 'product_already_ok' };
    return { kind: 'wrong_package' };
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
            <div class="pick-card__actions">
                <button class="btn-confirm" data-line-id="${move.id}">
                    Bestätigen
                </button>
                <button class="btn-short-pick" data-line-id="${move.id}">
                    Fehlbestand
                </button>
            </div>
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
            <div class="state-panel__meta">Session, Profilstatus und offene Auftraege werden geladen.</div>
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
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
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
