#!/usr/bin/env node
/**
 * n8n credential bootstrap: provisions the three logical PWR v2 credentials
 * (inbound header secret, backend->n8n HMAC, n8n->backend HMAC) from Docker
 * secrets and environment-supplied key IDs, using the n8n CLI's own
 * export:credentials / import:credentials commands so plaintext secrets
 * never touch this repository or its git history.
 *
 * Modes:
 *   provision  - create-or-update all three credentials, preserving any
 *                existing credential ID so downstream workflow bindings stay
 *                stable across re-runs.
 *   verify     - require that exactly one credential already exists for each
 *                of the three (name, type) pairs; never writes anything.
 *   rotate     - like provision, but requires both the new active AND the
 *                previous key/secret to be supplied for the backend->n8n
 *                HMAC credential. The previous key/secret are written
 *                alongside the active ones; this script never removes the
 *                previous key -- that only happens after a live signature
 *                smoke test has passed, which is an operator follow-up step
 *                outside this script's scope.
 *
 * Only metadata (id/name/type) is ever printed to stdout; no secret value is
 * ever logged.
 */
import {randomUUID} from 'node:crypto';
import {constants} from 'node:fs';
import {chmod, mkdtemp, open, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

const MODES = new Set(['provision', 'verify', 'rotate']);

const SECRET_FILES = {
    nativeHeaderSecret: '/run/secrets/pwr_n8n_native_header',
    backendToN8nActiveSecret: '/run/secrets/pwr_backend_to_n8n_active_hmac',
    backendToN8nPreviousSecret: '/run/secrets/pwr_backend_to_n8n_previous_hmac',
    n8nToBackendActiveSecret: '/run/secrets/pwr_n8n_to_backend_active_hmac',
    n8nToBackendLegacyCallbackSecret: '/run/secrets/pwr_n8n_callback_legacy',
};

const key = (name, type) => `${name}\0${type}`;

export function indexCredentials(credentials) {
    const index = new Map();
    for (const credential of credentials) {
        const itemKey = key(credential.name, credential.type);
        index.set(itemKey, [...(index.get(itemKey) || []), credential]);
    }
    return index;
}

export function resolveCredentialId(name, type, existing) {
    const matches = existing.get(key(name, type)) || [];
    if (matches.length > 1) {
        throw new Error(`duplicate credential: ${name} (${type})`);
    }
    return matches[0]?.id || randomUUID();
}

/**
 * Like resolveCredentialId, but for `verify`: never generates an ID, and
 * fails closed unless exactly one credential already exists.
 */
export function requireExistingCredentialId(name, type, existing) {
    const matches = existing.get(key(name, type)) || [];
    if (matches.length !== 1) {
        throw new Error(
            `expected exactly one credential for ${name} (${type}), found ${matches.length}`,
        );
    }
    return matches[0].id;
}

export function buildDefinitions(config) {
    return [
        {
            id: config.ids.inboundHeader,
            name: 'pwr.v2.inbound-header',
            type: 'httpHeaderAuth',
            data: {
                name: 'X-PWR-Webhook-Secret',
                value: config.nativeHeaderSecret,
            },
        },
        {
            id: config.ids.inboundHmac,
            name: 'pwr.v2.backend-to-n8n-hmac',
            type: 'pwrInboundHmac',
            data: config.backendToN8n,
        },
        {
            id: config.ids.outboundHmac,
            name: 'pwr.v2.n8n-to-backend-hmac',
            type: 'pwrOutboundHmac',
            data: config.n8nToBackend,
        },
    ];
}

function decodeBase64Secret(label, base64Value) {
    if (!base64Value) {
        return null;
    }
    const decoded = Buffer.from(base64Value, 'base64');
    if (decoded.length < 32) {
        throw new Error(
            `${label}: decoded HMAC secret must be at least 32 bytes, got ${decoded.length}`,
        );
    }
    return decoded;
}

/**
 * The three properties a secret file must have. Pure and exported so every
 * branch -- including the ownership one -- is testable without root: feed it
 * a synthetic stat-like object.
 *
 * `info` MUST come from fstat on an already-open descriptor, never from a
 * second lookup by path. See readSecretFile.
 */
export function assertSecretFileSafe(info, path) {
    if (!info.isFile()) {
        throw new Error(`credential file ${path} is not a regular file`);
    }
    if ((info.mode & 0o077) !== 0) {
        throw new Error(`credential file ${path} is group- or world-accessible`);
    }
    if (info.uid !== process.getuid()) {
        throw new Error(`credential file ${path} is not owned by the runtime user`);
    }
}

/**
 * Read one secret file, checking its permissions on the very descriptor it
 * then reads from.
 *
 * Der Host-Pfad-Check in provision-n8n-credentials.sh prueft eine andere
 * Datei als die, die hier gelesen wird -- gleicher Name, anderer Namespace.
 * Die einzige Pruefung, die zaehlt, sitzt hier, im Container, unmittelbar am
 * Lesevorgang.
 *
 * Zweimal ueber den PFAD aufzuloesen -- erst lstat, dann readFile -- laesst
 * genau die Tuer offen, die lstat schliessen sollte: zwischen Pruefung und
 * Lesen kann ein Angreifer mit Schreibrecht im Secret-Verzeichnis die
 * regulaere 0600-Datei durch einen Symlink ersetzen (TOCTOU). Deshalb wird
 * hier EINMAL mit O_NOFOLLOW geoeffnet -- ein Symlink schlaegt damit schon
 * beim open fehl (ELOOP), nicht erst bei einer Pruefung, die er ueberholen
 * koennte -- und danach ausschliesslich ueber diesen Deskriptor gearbeitet:
 * fstat und read sehen zwingend dasselbe Objekt.
 *
 * O_NONBLOCK verhindert, dass ein untergeschobener FIFO das open blockiert;
 * auf regulaere Dateien hat es keine Wirkung. Bekannte Restgrenze: O_NOFOLLOW
 * schuetzt nur die letzte Pfadkomponente, ein ausgetauschtes ELTERNVERZEICHNIS
 * bleibt moeglich -- dagegen hilft nur ein Verzeichnis, in das der Angreifer
 * gar nicht schreiben kann.
 *
 * A file that is simply absent is not an error: several of these secrets
 * are optional (the previous HMAC outside a rotation, the legacy callback
 * secret), and buildConfig decides which ones the current mode requires.
 */
export async function readSecretFile(path) {
    let handle;
    try {
        handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    } catch (error) {
        if (error.code === 'ENOENT') {
            return '';
        }
        if (error.code === 'ELOOP') {
            throw new Error(`credential file ${path} is not a regular file`);
        }
        throw error;
    }
    try {
        assertSecretFileSafe(await handle.stat(), path);
        const raw = await handle.readFile('utf8');
        return raw.trim();
    } finally {
        // A rejecting close() in a finally block replaces the original error
        // -- e.g. the "not a regular file" / permission finding above -- with
        // a close failure. Closing is best-effort; the finding is not.
        await handle.close().catch(() => {});
    }
}

async function readSecrets() {
    const entries = await Promise.all(
        Object.entries(SECRET_FILES).map(async ([name, path]) => [
            name,
            await readSecretFile(path),
        ]),
    );
    return Object.fromEntries(entries);
}

function readEnv(name, {required = false} = {}) {
    const value = process.env[name];
    if (required && !value) {
        throw new Error(`missing required environment variable: ${name}`);
    }
    return value || '';
}

async function buildConfig(mode) {
    const secrets = await readSecrets();

    const backendToN8nActiveKeyId = readEnv('PWR_BACKEND_TO_N8N_ACTIVE_KEY_ID', {required: true});
    const backendToN8nPreviousKeyId = readEnv('PWR_BACKEND_TO_N8N_PREVIOUS_KEY_ID');
    const n8nToBackendActiveKeyId = readEnv('PWR_N8N_TO_BACKEND_ACTIVE_KEY_ID', {required: true});
    const n8nToBackendBaseUrl = readEnv('PWR_N8N_TO_BACKEND_BASE_URL') || 'http://backend:8000';

    // Validate HMAC secrets decode to >= 32 bytes. The native header secret
    // and the legacy callback secret are plain shared strings, not HMAC
    // keys, so they are not subject to this check.
    decodeBase64Secret('backend-to-n8n active secret', secrets.backendToN8nActiveSecret);
    decodeBase64Secret('n8n-to-backend active secret', secrets.n8nToBackendActiveSecret);
    if (secrets.backendToN8nPreviousSecret) {
        decodeBase64Secret('backend-to-n8n previous secret', secrets.backendToN8nPreviousSecret);
    }

    if (!secrets.nativeHeaderSecret) {
        throw new Error(`missing secret file: ${SECRET_FILES.nativeHeaderSecret}`);
    }
    if (!secrets.backendToN8nActiveSecret) {
        throw new Error(`missing secret file: ${SECRET_FILES.backendToN8nActiveSecret}`);
    }
    if (!secrets.n8nToBackendActiveSecret) {
        throw new Error(`missing secret file: ${SECRET_FILES.n8nToBackendActiveSecret}`);
    }

    if (mode === 'rotate') {
        if (!backendToN8nPreviousKeyId || !secrets.backendToN8nPreviousSecret) {
            throw new Error(
                'rotate requires both PWR_BACKEND_TO_N8N_PREVIOUS_KEY_ID and the previous HMAC secret file',
            );
        }
    }

    return {
        nativeHeaderSecret: secrets.nativeHeaderSecret,
        backendToN8n: {
            activeKeyId: backendToN8nActiveKeyId,
            activeSecretBase64: secrets.backendToN8nActiveSecret,
            previousKeyId: backendToN8nPreviousKeyId,
            previousSecretBase64: secrets.backendToN8nPreviousSecret,
        },
        n8nToBackend: {
            baseUrl: n8nToBackendBaseUrl,
            activeKeyId: n8nToBackendActiveKeyId,
            activeSecretBase64: secrets.n8nToBackendActiveSecret,
            legacyCallbackSecret: secrets.n8nToBackendLegacyCallbackSecret,
        },
    };
}

async function writeSecretJson(path, value) {
    await writeFile(path, JSON.stringify(value), {mode: 0o600});
    await chmod(path, 0o600);
}

// Only the n8n subcommand name and exit status are ever included in a
// thrown error. n8n CLI stdout/stderr can echo back request bodies or other
// credential-shaped material on failure, so it must never be captured into
// an error message, a log line, or anything that could reach a report or a
// crash dump.
function n8nSubcommand(args) {
    return args[0] || 'n8n';
}

function runN8n(args) {
    const result = spawnSync('n8n', args, {encoding: 'utf8'});
    if (result.error) {
        throw new Error(`n8n ${n8nSubcommand(args)} could not be started: ${result.error.code || 'unknown error'}`);
    }
    if (result.status !== 0) {
        throw new Error(`n8n ${n8nSubcommand(args)} failed (exit ${result.status})`);
    }
    return result;
}

async function exportCredentials(exportPath) {
    process.env.CREDENTIAL_EXPORT_PATH = exportPath;
    runN8n(['export:credentials', '--all', `--output=${exportPath}`]);
    const raw = JSON.parse(await readFile(exportPath, 'utf8'));
    const list = Array.isArray(raw) ? raw : raw.data || [];
    // Only id/name/type are ever read from the export -- never any secret
    // payload -- because we intentionally do not pass --decrypted.
    return list.map((item) => ({id: item.id, name: item.name, type: item.type}));
}

async function verifyMetadata(existingIndex) {
    const inboundHeader = requireExistingCredentialId('pwr.v2.inbound-header', 'httpHeaderAuth', existingIndex);
    const inboundHmac = requireExistingCredentialId('pwr.v2.backend-to-n8n-hmac', 'pwrInboundHmac', existingIndex);
    const outboundHmac = requireExistingCredentialId('pwr.v2.n8n-to-backend-hmac', 'pwrOutboundHmac', existingIndex);
    return {
        credentials: [
            {id: inboundHeader, name: 'pwr.v2.inbound-header', type: 'httpHeaderAuth'},
            {id: inboundHmac, name: 'pwr.v2.backend-to-n8n-hmac', type: 'pwrInboundHmac'},
            {id: outboundHmac, name: 'pwr.v2.n8n-to-backend-hmac', type: 'pwrOutboundHmac'},
        ],
    };
}

async function runCli(mode) {
    if (!MODES.has(mode)) {
        throw new Error(`unsupported mode '${mode}': expected one of provision, verify, rotate`);
    }

    const tmpDir = await mkdtemp(join(tmpdir(), 'n8n-credentials-'));
    await chmod(tmpDir, 0o700);

    try {
        const exportPath = join(tmpDir, 'credentials-export.json');
        const existing = await exportCredentials(exportPath);
        const existingIndex = indexCredentials(existing);

        if (mode === 'verify') {
            return await verifyMetadata(existingIndex);
        }

        const config = await buildConfig(mode);
        const ids = {
            inboundHeader: resolveCredentialId('pwr.v2.inbound-header', 'httpHeaderAuth', existingIndex),
            inboundHmac: resolveCredentialId('pwr.v2.backend-to-n8n-hmac', 'pwrInboundHmac', existingIndex),
            outboundHmac: resolveCredentialId('pwr.v2.n8n-to-backend-hmac', 'pwrOutboundHmac', existingIndex),
        };
        const definitions = buildDefinitions({ids, ...config});

        const importPath = join(tmpDir, 'credentials-import.json');
        process.env.CREDENTIAL_IMPORT_PATH = importPath;
        await writeSecretJson(importPath, definitions);
        runN8n(['import:credentials', `--input=${importPath}`]);

        const reExportPath = join(tmpDir, 'credentials-export-after.json');
        const reExported = await exportCredentials(reExportPath);
        return await verifyMetadata(indexCredentials(reExported));
    } finally {
        await rm(tmpDir, {recursive: true, force: true});
    }
}

async function main() {
    const mode = process.argv[2];
    const metadata = await runCli(mode);
    process.stdout.write(`${JSON.stringify(metadata)}\n`);
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
    main().catch((error) => {
        process.stderr.write(`provision-credentials: ${error.message}\n`);
        process.exitCode = 1;
    });
}
