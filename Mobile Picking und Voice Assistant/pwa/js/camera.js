/**
 * Kamera-Capture für Quality Alerts.
 * Nutzt getUserMedia für Live-Preview und Foto-Capture.
 * Fallback: <input type="file" capture="environment">
 */

let stream = null;

/**
 * Kamera-Stream starten.
 * WICHTIG: Erfordert HTTPS (Secure Context) und User-Geste.
 */
export async function startCamera(videoElement) {
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: 'environment',  // Rückkamera
                width: { ideal: 1280 },
                height: { ideal: 720 },
            }
        });
        videoElement.srcObject = stream;
        await videoElement.play();
        return true;
    } catch (e) {
        console.error('Kamera-Zugriff fehlgeschlagen:', e);
        return false;
    }
}

/**
 * Foto aus Video-Stream capturen.
 * Gibt Blob (JPEG) zurück.
 */
export function capturePhoto(videoElement) {
    const canvas = document.createElement('canvas');
    canvas.width = videoElement.videoWidth;
    canvas.height = videoElement.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(videoElement, 0, 0);

    return new Promise((resolve) => {
        canvas.toBlob(resolve, 'image/jpeg', 0.8);
    });
}

/**
 * Kamera-Stream stoppen.
 */
export function stopCamera() {
    if (stream) {
        stream.getTracks().forEach(t => t.stop());
        stream = null;
    }
}

/**
 * File-Input für Foto-Upload (mehrere Fotos möglich).
 * - Kein 'capture'-Attribut: User wählt selbst (Kamera oder Galerie auf Mobile)
 * - multiple: beliebig viele Fotos
 * - onCapture(files: File[]) wird mit Array aller gewählten Dateien aufgerufen
 */
export function createFileInput(onCapture) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.multiple = true;
    input.style.display = 'none';

    input.addEventListener('change', () => {
        if (input.files.length > 0) {
            onCapture(Array.from(input.files));
        }
    });

    return input;
}
