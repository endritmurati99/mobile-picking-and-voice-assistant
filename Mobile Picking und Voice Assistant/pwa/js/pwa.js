/**
 * PWA-Installation und Lifecycle.
 */

let deferredPrompt = null;
let serviceWorkerRegistration = null;
let hasTriggeredControllerRefresh = false;
let lastResumeSignalAt = 0;

function showInstallButton() {
    // Optional: Install-Banner anzeigen
    console.log('PWA kann installiert werden');
}

function shouldThrottleResumeSignal() {
    const now = Date.now();
    if (now - lastResumeSignalAt < 900) return true;
    lastResumeSignalAt = now;
    return false;
}

async function maybeActivateWaitingWorker(options = {}) {
    const waitingWorker = serviceWorkerRegistration?.waiting;
    if (!waitingWorker) return;

    const canActivate = options.shouldActivateUpdate ? options.shouldActivateUpdate() : true;
    if (!canActivate) {
        options.onUpdateReady?.();
        return;
    }

    waitingWorker.postMessage({ type: 'SKIP_WAITING' });
}

function watchRegistration(registration, options = {}) {
    registration.addEventListener('updatefound', () => {
        const installingWorker = registration.installing;
        if (!installingWorker) return;

        installingWorker.addEventListener('statechange', () => {
            if (installingWorker.state === 'installed' && navigator.serviceWorker.controller) {
                void maybeActivateWaitingWorker(options);
            }
        });
    });
}

async function setupServiceWorker(options = {}) {
    if (!('serviceWorker' in navigator)) return;

    try {
        serviceWorkerRegistration = await navigator.serviceWorker.register('/sw.js', {
            updateViaCache: 'none',
        });

        navigator.serviceWorker.addEventListener('controllerchange', () => {
            if (hasTriggeredControllerRefresh) return;
            hasTriggeredControllerRefresh = true;
            options.onControllerRefresh?.();
        });

        watchRegistration(serviceWorkerRegistration, options);
        await maybeActivateWaitingWorker(options);
    } catch (error) {
        console.warn('Service-Worker-Registrierung fehlgeschlagen:', error);
    }
}

async function refreshServiceWorker(options = {}) {
    if (!serviceWorkerRegistration) return;

    try {
        await serviceWorkerRegistration.update();
        await maybeActivateWaitingWorker(options);
    } catch (error) {
        console.warn('Service-Worker-Update fehlgeschlagen:', error);
    }
}

async function signalResume(reason, options = {}) {
    if (shouldThrottleResumeSignal()) return;
    await refreshServiceWorker(options);
    if (navigator.onLine) {
        await options.onResume?.({ reason });
    }
}

export function initPWA(options = {}) {
    window.addEventListener('beforeinstallprompt', (event) => {
        event.preventDefault();
        deferredPrompt = event;
        showInstallButton();
    });

    window.addEventListener('online', async () => {
        options.onConnectivityChange?.(true);
        await refreshServiceWorker(options);
        await options.onOnline?.();
    });

    window.addEventListener('offline', () => {
        options.onConnectivityChange?.(false);
    });

    window.addEventListener('pageshow', (event) => {
        if (!event.persisted) return;
        void signalResume('pageshow', options);
    });

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState !== 'visible') return;
        void signalResume('visibilitychange', options);
    });

    options.onConnectivityChange?.(navigator.onLine);
    void setupServiceWorker(options);
}

export async function installPWA() {
    if (!deferredPrompt) return false;
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    deferredPrompt = null;
    return result.outcome === 'accepted';
}
