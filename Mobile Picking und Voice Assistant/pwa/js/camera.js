/**
 * Foto-Upload für Quality Alerts.
 * Nutzt <input type="file"> statt Live-Kamera-Preview.
 */

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
