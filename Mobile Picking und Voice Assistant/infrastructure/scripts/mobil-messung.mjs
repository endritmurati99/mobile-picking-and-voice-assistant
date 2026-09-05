/**
 * Misst die Auftragsliste auf einem Telefon-Viewport (Pixel 7, 412 px).
 *
 * Aufruf aus dem Projektverzeichnis:
 *   ZIEL=https://localhost/ SHOT=/tmp/mobil.png node infrastructure/scripts/mobil-messung.mjs
 *
 * Hintergrund: mobile Fehler sind am Schreibtisch unsichtbar. Am 2026-09-05
 * zeigte diese Messung, dass der Kopf den Lagerumschalter auf "Lag"
 * abschnitt, der Ueberfaellig-Hinweis zweimal je Karte stand und die erste
 * Auftragskarte erst bei 514 von 839 Pixeln begann. Wer am Layout arbeitet,
 * laesst das Skript vorher und nachher laufen und vergleicht die Zahlen.
 */
import { chromium, devices } from 'playwright';

const ZIEL = process.env.ZIEL || 'https://localhost/';
const browser = await chromium.launch();
const context = await browser.newContext({
    ...devices['Pixel 7'],
    ignoreHTTPSErrors: true,
});
const page = await context.newPage();
page.on('console', (m) => { if (m.type() === 'error') console.log('  [konsole]', m.text().slice(0, 160)); });

await page.goto(ZIEL, { waitUntil: 'networkidle' });

// Anmelden
await page.waitForTimeout(1200);
const hatLogin = await page.locator('#login-password, input[type="password"]').count();
if (hatLogin) {
    await page.fill('#login-name, input[name="login"], input[type="text"]', 'admin').catch(() => {});
    await page.fill('#login-password, input[type="password"]', 'admin');
    await page.click('button[type="submit"]');
    await page.waitForTimeout(3500);
}

const viewport = page.viewportSize();
console.log('viewport', viewport);

const karten = await page.locator('.pick-list-card').count();
console.log('karten sichtbar:', karten);

const messung = await page.evaluate(() => {
    const doc = document.documentElement;
    const karte = document.querySelector('.pick-list-card');
    const rect = karte ? karte.getBoundingClientRect() : null;
    const cluster = document.querySelector('.cluster-entry-btn');
    const zahl = document.querySelector('.pick-list-card__count-number');
    const box = document.querySelector('.pick-list-card__location-box');
    const spalte = document.querySelector('.queue-overview');
    const zuBreit = [...document.querySelectorAll('body *')]
        .filter((el) => el.getBoundingClientRect().right > doc.clientWidth + 1)
        .slice(0, 6)
        .map((el) => `${el.className || el.tagName}: ${Math.round(el.getBoundingClientRect().right)}px`);
    return {
        seitenbreite: doc.clientWidth,
        scrollbreite: doc.scrollWidth,
        kartenhoehe: rect ? Math.round(rect.height) : null,
        kartenbreite: rect ? Math.round(rect.width) : null,
        clusterHoehe: cluster ? Math.round(cluster.getBoundingClientRect().height) : null,
        clusterSichtbar: cluster ? cluster.getBoundingClientRect().top < window.innerHeight : null,
        zahlGroesse: zahl ? getComputedStyle(zahl).fontSize : null,
        platzBoxBreite: box ? Math.round(box.getBoundingClientRect().width) : null,
        seitenspalteSichtbar: spalte ? getComputedStyle(spalte).display !== 'none' : null,
        ersteKarteTop: (() => { const k = document.querySelector('.pick-list-card'); return k ? Math.round(k.getBoundingClientRect().top) : null; })(),
        kartenImBild: [...document.querySelectorAll('.pick-list-card')].filter((k) => { const r = k.getBoundingClientRect(); return r.top < window.innerHeight && r.bottom > 0; }).length,
        kopfzeilenHoehe: (() => { const h = document.querySelector('.header-row--top'); return h ? Math.round(h.getBoundingClientRect().height) : null; })(),
        kopfEinzeilig: (() => {
            const reihe = document.querySelector('.header-row--top');
            if (!reihe) return null;
            const kinder = [...reihe.children].map((el) => Math.round(el.getBoundingClientRect().top));
            return new Set(kinder).size === 1;
        })(),
        ueberbreit: zuBreit,
    };
});
console.log(JSON.stringify(messung, null, 2));

await page.screenshot({ path: process.env.SHOT || '/tmp/mobil.png', fullPage: false });
await browser.close();
