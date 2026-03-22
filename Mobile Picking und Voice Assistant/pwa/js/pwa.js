/**
 * PWA-Installation und Lifecycle.
 */

let deferredPrompt = null;

export function initPWA() {
    // Install-Prompt abfangen
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        showInstallButton();
    });

    // Online/Offline-Status
    window.addEventListener('online', () => updateConnectionStatus(true));
    window.addEventListener('offline', () => updateConnectionStatus(false));
    updateConnectionStatus(navigator.onLine);
}

function updateConnectionStatus(isOnline) {
    const el = document.getElementById('status-indicator');
    if (el) {
        el.textContent = isOnline ? 'Online' : 'Offline';
        el.className = `status ${isOnline ? 'online' : 'offline'}`;
    }
}

function showInstallButton() {
    // Optional: Install-Banner anzeigen
    console.log('PWA kann installiert werden');
}

export async function installPWA() {
    if (!deferredPrompt) return false;
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    deferredPrompt = null;
    return result.outcome === 'accepted';
}
