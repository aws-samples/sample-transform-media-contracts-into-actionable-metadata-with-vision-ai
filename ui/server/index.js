import express from 'express';
import cors from 'cors';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import { resolve, dirname } from 'path';
import { readFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { SSMClient, GetParametersCommand } from '@aws-sdk/client-ssm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const envPath = resolve(__dirname, '../config/.env');
if (existsSync(envPath)) {
    for (const line of readFileSync(envPath, 'utf-8').split('\n')) {
        const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
        if (m) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
    }
}

// ── Load config from SSM Parameter Store ──────────────────────────────────
// In production (NODE_ENV=production) all config lives in SSM.
// In local dev the .env file above provides the values instead.
const SSM_PARAM_MAP = {
    '/media-contracts/orchestrator-runtime-arn': 'ORCHESTRATOR_RUNTIME_ARN',
    '/media-contracts/jobs-table-name': 'JOBS_TABLE_NAME',
    '/media-contracts/config-bucket-name': 'CONFIG_BUCKET',
    '/media-contracts/results-bucket-name': 'RESULTS_BUCKET',
    '/media-contracts/source-bucket-name': 'SOURCE_BUCKET',
    '/media-contracts/chat-model': 'CHAT_MODEL',
    '/media-contracts/agent-mode': 'AGENT_MODE',
    '/media-contracts/cognito-user-pool-id': 'COGNITO_USER_POOL_ID',
    '/media-contracts/cognito-domain': 'COGNITO_DOMAIN',
    '/media-contracts/cognito-ui-client-id': 'COGNITO_UI_CLIENT_ID',
    '/media-contracts/contract-kb-id': 'CONTRACT_KB_ID',
    '/media-contracts/terms-kb-id': 'TERMS_KB_ID',
};

async function loadSSMConfig() {
    // Only pull from SSM if running in production and params aren't already set
    const missing = Object.entries(SSM_PARAM_MAP)
        .filter(([, envKey]) => !process.env[envKey])
        .map(([paramPath]) => paramPath);

    if (missing.length === 0) return;

    const region = process.env.AWS_REGION;
    const ssm = new SSMClient({ region });

    try {
        const resp = await ssm.send(new GetParametersCommand({
            Names: missing,
            WithDecryption: false,
        }));
        for (const param of resp.Parameters || []) {
            const envKey = SSM_PARAM_MAP[param.Name];
            if (envKey && param.Value) {
                process.env[envKey] = param.Value;
                console.log(`[config] ${envKey} loaded from SSM`);
            }
        }
        if (resp.InvalidParameters?.length) {
            console.warn('[config] SSM params not found:', resp.InvalidParameters);
        }
    } catch (e) {
        console.warn('[config] SSM load failed (continuing with env vars):', e.message);
    }
}

import { mountRoutes } from './routes.js';

const app = express();

// ── CORS — restrict to known frontend origin ───────────────────────────────
// ALLOWED_ORIGIN must be set explicitly. No open fallback — if it's missing in
// production the server still works (same-origin requests from the bundled React
// app don't need CORS), but cross-origin requests will be blocked by the browser.
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN;
app.use(cors(ALLOWED_ORIGIN ? { origin: ALLOWED_ORIGIN, credentials: true } : { origin: false }));

app.use(express.json({ limit: '10mb' }));

// ── Request logging ─────────────────────────────────────────────────────────
app.use((req, res, next) => {
    const start = Date.now();
    res.on('finish', () => {
        const duration = Date.now() - start;
        console.log(`${req.method} ${req.path} ${res.statusCode} ${duration}ms`);
    });
    next();
});

// ── JWT auth middleware — verify Cognito tokens on all /api/* except /api/env ──
const COGNITO_USER_POOL_ID = process.env.COGNITO_USER_POOL_ID;
const COGNITO_UI_CLIENT_ID = process.env.COGNITO_UI_CLIENT_ID;
const AWS_REGION_FOR_AUTH = process.env.AWS_REGION;

let _jwks = null;
function getJwks() {
    if (!_jwks && COGNITO_USER_POOL_ID) {
        const jwksUri = `https://cognito-idp.${AWS_REGION_FOR_AUTH}.amazonaws.com/${COGNITO_USER_POOL_ID}/.well-known/jwks.json`;
        _jwks = createRemoteJWKSet(new URL(jwksUri));
    }
    return _jwks;
}

async function requireAuth(req, res, next) {
    // Skip auth in local dev when no user pool is configured
    if (!COGNITO_USER_POOL_ID) return next();

    const auth = req.headers.authorization || '';
    const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
    if (!token) {
        console.log(`[auth] ${req.method} ${req.path} — no token provided`);
        return res.status(401).json({ error: 'Unauthorized' });
    }

    try {
        const verifyOptions = {
            issuer: `https://cognito-idp.${AWS_REGION_FOR_AUTH}.amazonaws.com/${COGNITO_USER_POOL_ID}`,
        };
        const { payload } = await jwtVerify(token, getJwks(), verifyOptions);

        // Validate client identity — access tokens use client_id, ID tokens use aud
        if (COGNITO_UI_CLIENT_ID) {
            const tokenClient = payload.client_id || payload.aud;
            if (tokenClient !== COGNITO_UI_CLIENT_ID) {
                console.log('[auth] %s %s — client mismatch: %s', req.method, req.path, tokenClient);
                return res.status(401).json({ error: 'Invalid token client' });
            }
        }

        req.user = payload;
        next();
    } catch (e) {
        console.log('[auth] %s %s — token verification failed:', req.method, req.path, e.message);
        return res.status(401).json({ error: 'Invalid or expired token' });
    }
}

const PORT = process.env.PORT || 7870;

async function start() {
    await loadSSMConfig();

    mountRoutes(app, resolve(__dirname, '..'), requireAuth);

    if (process.env.NODE_ENV === 'production') {
        const DIST = resolve(__dirname, '../dist');
        app.use(express.static(DIST));
        app.get('/*splat', (req, res, next) => {
            if (req.path.startsWith('/api')) return next();
            res.sendFile(resolve(DIST, 'index.html'));
        });
    }
    app.listen(PORT, () => console.log(`\n📄 Media Contracts UI on http://localhost:${PORT}\n`));
}

start();
