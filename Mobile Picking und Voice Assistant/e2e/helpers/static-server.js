// Minimaler statischer Server fuer die PWA in e2e-Tests.
// Keine neue Abhaengigkeit: reines Node http/fs, nur fuer `pwa/` als Web-Root.
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..', 'pwa');
const PORT = Number(process.env.PORT) || 4173;

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.wav': 'audio/wav',
};

function resolveFilePath(urlPath) {
  const decoded = decodeURIComponent(urlPath.split('?')[0]);
  const safePath = path.normalize(decoded).replace(/^(\.\.[/\\])+/, '');
  let filePath = path.join(ROOT, safePath);
  if (!filePath.startsWith(ROOT)) filePath = ROOT;
  return filePath;
}

const server = http.createServer((req, res) => {
  let filePath = resolveFilePath(req.url || '/');

  fs.stat(filePath, (statErr, stats) => {
    if (!statErr && stats.isDirectory()) {
      filePath = path.join(filePath, 'index.html');
    } else if (statErr) {
      // SPA-Fallback: unbekannte Pfade -> index.html (kein Router mit eigenen
      // Routen in dieser App, aber schadet nicht und deckt z.B. /icons/x ab).
      filePath = path.join(ROOT, 'index.html');
    }

    fs.readFile(filePath, (readErr, content) => {
      if (readErr) {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('Not found');
        return;
      }
      const ext = path.extname(filePath).toLowerCase();
      res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
      res.end(content);
    });
  });
});

server.listen(PORT, () => {
  console.log(`static-server: listening on http://127.0.0.1:${PORT} (root: ${ROOT})`);
});
