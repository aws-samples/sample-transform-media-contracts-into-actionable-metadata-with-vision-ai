import { readFileSync } from 'fs';
import { readFile } from 'fs/promises';
import { normalize, sep } from 'path';
import { randomUUID } from 'crypto';
import { BedrockAgentRuntimeClient, RetrieveAndGenerateCommand } from '@aws-sdk/client-bedrock-agent-runtime';
import { createRequire } from 'module';
const _require = createRequire(import.meta.url);
const { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } = _require('@aws-sdk/client-bedrock-agentcore');
import { BedrockRuntimeClient, ConverseCommand } from '@aws-sdk/client-bedrock-runtime';
import { DynamoDBClient, QueryCommand, ScanCommand, DeleteItemCommand } from '@aws-sdk/client-dynamodb';
import { S3Client, ListObjectsV2Command, GetObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { fromNodeProviderChain } from '@aws-sdk/credential-providers';

function safeJoin(base, filename) {
    // Normalize both paths and ensure the result stays within base
    const normalizedBase = normalize(base) + sep;
    const candidate = normalize(base + sep + filename);
    if (!candidate.startsWith(normalizedBase)) {
        throw new Error('Path traversal detected');
    }
    return candidate;
}

export function mountRoutes(app, UI_ROOT, requireAuth) {
    const CONFIG_DIR = normalize(UI_ROOT + '/config');
    const REGION = process.env.AWS_REGION;
    const AWS_PROFILE = process.env.AWS_PROFILE;

    const credentials = fromNodeProviderChain({ profile: AWS_PROFILE });
    const bedrockAgent = new BedrockAgentRuntimeClient({ region: REGION, credentials });
    const bedrockRuntime = new BedrockRuntimeClient({ region: REGION, credentials });
    const agentCoreRuntime = new BedrockAgentCoreClient({ region: REGION, credentials });
    const dynamodb = new DynamoDBClient({ region: REGION, credentials });

    const CONFIG_BUCKET = process.env.CONFIG_BUCKET;
    const CONFIG_BUCKET_PREFIX = process.env.CONFIG_BUCKET_PREFIX || 'ui-config/';
    const CHAT_MODEL = process.env.CHAT_MODEL;
    const AGENT_MODE_LOCKED = process.env.AGENT_MODE === 'true';
    const ORCHESTRATOR_RUNTIME_ARN = process.env.ORCHESTRATOR_RUNTIME_ARN;
    const JOBS_TABLE_NAME = process.env.JOBS_TABLE_NAME;

    // ── Per-user session state (in-memory, resets on restart) ──
    // Key: Cognito sub (user ID extracted from JWT)
    const userSessions = new Map();

    const DEFAULT_SPECIALISTS = ['financial', 'rights_clearance', 'talent_guild_compliance', 'regulatory_compliance'];

    function getSubFromRequest(req) {
        // req.user is set by the verified JWT payload from requireAuth middleware
        if (req.user?.sub) return req.user.sub;
        // Fallback for local dev (no COGNITO_USER_POOL_ID configured, auth skipped)
        const auth = req.headers.authorization || '';
        const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
        if (!token) return null;
        try {
            const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
            return payload.sub || null;
        } catch {
            return null;
        }
    }

    function getUsernameFromRequest(req) {
        // Cognito access tokens use 'username', ID tokens use 'cognito:username' or 'email'
        return req.user?.username
            || req.user?.['cognito:username']
            || req.user?.email
            || 'unknown';
    }

    function buildRuntimeSessionId(req, jobId) {
        // Build a human-readable session ID: "username--job_id"
        // AgentCore requires 33-256 chars. UUID alone is 36 chars, so this always meets the minimum.
        const username = getUsernameFromRequest(req);
        const sessionId = `${username}--${jobId}`;
        // Clamp to 256 chars max
        return sessionId.slice(0, 256);
    }

    function getSession(sub) {
        if (!userSessions.has(sub)) {
            userSessions.set(sub, { enabledSpecialists: [...DEFAULT_SPECIALISTS], agentMode: false });
        }
        return userSessions.get(sub);
    }

    // Lazy-loaded prompt cache
    const promptCache = {};
    async function loadPrompt(key) {
        if (promptCache[key]) return promptCache[key];
        const s3 = new S3Client({ region: REGION, credentials });
        const obj = await s3.send(new GetObjectCommand({ Bucket: CONFIG_BUCKET, Key: key })); const text = await obj.Body.transformToString();
        promptCache[key] = text;
        return text;
    }

    // Load a config JSON — S3 first, local fallback
    async function loadConfig(filename) {
        try {
            const s3 = new S3Client({ region: REGION, credentials });
            const obj = await s3.send(new GetObjectCommand({
                Bucket: CONFIG_BUCKET,
                Key: `${CONFIG_BUCKET_PREFIX}${filename}`,
            }));
            return JSON.parse(await obj.Body.transformToString());
        } catch {
            const localPath = safeJoin(CONFIG_DIR, filename);
            return JSON.parse(readFileSync(localPath, 'utf-8'));
        }
    }

    // ── Branding ──

    app.get('/api/env', async (_req, res) => {
        try {
            const branding = await loadConfig('branding.json');
            res.json({ region: REGION, branding });
        } catch {
            res.json({ region: REGION, branding: {} });
        }
    });

    // ── Glossaries registry ──

    app.get('/api/glossaries', requireAuth, async (_req, res) => {
        try {
            res.json(await loadConfig('glossaries.json'));
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Specialists registry ──

    app.get('/api/specialists', requireAuth, async (_req, res) => {
        try {
            res.set('Cache-Control', 'no-store');
            res.json(await loadConfig('specialists.json'));
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Pipeline config (per-user session state) ──

    app.get('/api/pipeline-config', requireAuth, (req, res) => {
        const sub = getSubFromRequest(req);
        const session = sub ? getSession(sub) : { enabledSpecialists: [...DEFAULT_SPECIALISTS], agentMode: false };
        res.set('Cache-Control', 'no-store');
        res.json({
            agent_mode: AGENT_MODE_LOCKED || session.agentMode,
            agent_mode_locked: AGENT_MODE_LOCKED,
            enabled_specialists: session.enabledSpecialists,
            available_specialists: DEFAULT_SPECIALISTS,
        });
    });

    app.put('/api/pipeline-config', requireAuth, (req, res) => {
        const sub = getSubFromRequest(req);
        if (!sub) return res.status(401).json({ error: 'Unauthorized' });
        const { enabled_specialists, agent_mode } = req.body;
        const session = getSession(sub);
        if (Array.isArray(enabled_specialists)) session.enabledSpecialists = enabled_specialists;
        // agent_mode can only be changed if not locked by env
        if (!AGENT_MODE_LOCKED && typeof agent_mode === 'boolean') session.agentMode = agent_mode;
        res.json({ ok: true });
    });

    // ── Chat (conversational + triggers analysis for PDFs) ──

    app.post('/api/chat', requireAuth, async (req, res) => {
        const { message, history } = req.body;
        if (!message) return res.status(400).json({ error: 'Missing message' });

        try {
            const systemPrompt = await loadPrompt('prompts/main-agent.xml');
            const messages = (history || []).map(m => ({
                role: m.role,
                content: [{ text: m.text }],
            }));
            messages.push({ role: 'user', content: [{ text: message }] });

            const command = new ConverseCommand({
                modelId: CHAT_MODEL,
                system: [{ text: systemPrompt }],
                messages,
                inferenceConfig: { maxTokens: 2048 },
            });

            const response = await bedrockRuntime.send(command);
            const text = response.output?.message?.content?.[0]?.text || 'No response.';
            res.json({ text });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Contract analysis (AgentCore Runtime, SSE progress via DynamoDB polling) ──
    // Task 21: invoke orchestrator runtime instead of spawning a subprocess
    // Task 22: stream progress by polling DynamoDB jobs table every 2s
    // Task 23: idempotency — if job already COMPLETE, return cached result immediately

    app.post('/api/analyze', requireAuth, async (req, res) => {
        const { contract_path, job_id: client_job_id } = req.body;
        if (!contract_path) return res.status(400).json({ error: 'Missing contract_path' });

        const sub = getSubFromRequest(req);
        const session = sub ? getSession(sub) : { enabledSpecialists: [...DEFAULT_SPECIALISTS], agentMode: false };
        const agentMode = AGENT_MODE_LOCKED || session.agentMode;
        const specialists = agentMode ? [] : session.enabledSpecialists;

        // Use client-supplied job_id for idempotency, or generate a new one
        const job_id = client_job_id || randomUUID();

        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        res.flushHeaders();

        const send = (type, text) => {
            res.write(`data: ${JSON.stringify({ type, text })}\n\n`);
        };

        // ── Task 23: idempotency check ──────────────────────────────
        if (JOBS_TABLE_NAME) {
            try {
                const existing = await dynamodb.send(new QueryCommand({
                    TableName: JOBS_TABLE_NAME,
                    KeyConditionExpression: 'job_id = :jid AND specialist = :s',
                    ExpressionAttributeValues: {
                        ':jid': { S: job_id },
                        ':s': { S: 'orchestrator' },
                    },
                }));
                const record = existing.Items?.[0];
                if (record?.status?.S === 'COMPLETE') {
                    send('progress', JSON.stringify({ stage: 'complete', status: 'done', cached: true }));
                    send('done', JSON.stringify({ code: 0, job_id, cached: true }));
                    res.end();
                    return;
                }
            } catch (e) {
                console.error('[analyze] idempotency check failed:', e.message);
                // Non-fatal — proceed with invocation
            }
        }

        // ── Task 21: invoke orchestrator runtime ────────────────────
        console.log('[analyze] job_id:', job_id, 'contract_path:', contract_path,
            'agent_mode:', agentMode, 'specialists:', specialists);

        if (!ORCHESTRATOR_RUNTIME_ARN) {
            send('stderr', 'ORCHESTRATOR_RUNTIME_ARN not configured');
            send('done', JSON.stringify({ code: 1 }));
            res.end();
            return;
        }

        // Build a human-readable runtime session ID for AgentCore tracing
        const runtimeSessionId = buildRuntimeSessionId(req, job_id);
        console.log('[analyze] runtimeSessionId:', runtimeSessionId);

        send('session', JSON.stringify({ job_id, runtimeSessionId }));

        const payload = Buffer.from(JSON.stringify({
            job_id,
            contract_path,
            specialists: agentMode ? null : specialists,
            agent_mode: agentMode,
        }));

        // Fire-and-forget invocation — progress tracked via DynamoDB
        agentCoreRuntime.send(new InvokeAgentRuntimeCommand({
            agentRuntimeArn: ORCHESTRATOR_RUNTIME_ARN,
            qualifier: 'DEFAULT',
            runtimeSessionId,
            payload,
        })).catch(e => {
            console.error('[analyze] runtime invocation error:', e.message);
            if (!res.writableEnded) {
                send('stderr', `Orchestrator invocation failed: ${e.message}`);
                send('done', JSON.stringify({ code: 1, job_id, error: e.message }));
                res.end();
            }
        });

        send('progress', JSON.stringify({ stage: 'orchestrator', status: 'running', job_id }));

        // ── Task 22: poll DynamoDB for progress ─────────────────────
        if (!JOBS_TABLE_NAME) {
            // No table configured — just signal done immediately (dev mode)
            send('done', JSON.stringify({ code: 0, job_id }));
            res.end();
            return;
        }

        const POLL_INTERVAL_MS = 2000;
        const MAX_POLLS = 450; // 15 minutes max (matches AgentCore Runtime timeout)
        const TERMINAL_STATUSES = new Set(['COMPLETE', 'FAILED']);
        const seenStatuses = {};
        let polls = 0;

        // SSE comment heartbeat — keeps ALB/proxy connections alive
        const heartbeatTimer = setInterval(() => {
            if (!res.writableEnded) res.write(': keepalive\n\n');
        }, 15_000);

        const pollTimer = setInterval(async () => {
            if (res.writableEnded) {
                clearInterval(pollTimer);
                return;
            }

            polls++;
            if (polls > MAX_POLLS) {
                clearInterval(pollTimer);
                send('stderr', 'Polling timeout — check job status manually');
                send('done', JSON.stringify({ code: 1, job_id }));
                res.end();
                return;
            }

            try {
                const result = await dynamodb.send(new QueryCommand({
                    TableName: JOBS_TABLE_NAME,
                    KeyConditionExpression: 'job_id = :jid',
                    ExpressionAttributeValues: { ':jid': { S: job_id } },
                }));

                const items = result.Items || [];

                // Stream any status changes as progress events
                for (const item of items) {
                    const specialist = item.specialist?.S;
                    const status = item.status?.S;
                    const key = `${specialist}:${status}`;
                    if (specialist && status && !seenStatuses[key]) {
                        seenStatuses[key] = true;
                        send('progress', JSON.stringify({
                            stage: specialist,
                            status: status.toLowerCase(),
                            elapsed: item.completed_at?.S
                                ? undefined
                                : undefined,
                            s3_key: item.result_s3_key?.S,
                            error: item.error?.S,
                        }));
                    }
                }

                // Check if orchestrator is done
                const orchRecord = items.find(i => i.specialist?.S === 'orchestrator');
                if (orchRecord && TERMINAL_STATUSES.has(orchRecord.status?.S)) {
                    clearInterval(pollTimer);
                    const code = orchRecord.status.S === 'COMPLETE' ? 0 : 1;
                    send('done', JSON.stringify({ code, job_id }));
                    res.end();
                }
            } catch (e) {
                console.error('[analyze] poll error:', e.message);
                // Non-fatal — keep polling
            }
        }, POLL_INTERVAL_MS);

        res.on('close', () => {
            clearInterval(pollTimer);
            clearInterval(heartbeatTimer);
        });
    });

    // ── Knowledge Base chat ──

    const TERMS_KB_ID = process.env.TERMS_KB_ID;
    const CONTRACT_KB_ID = process.env.CONTRACT_KB_ID;

    const KB_PROMPTS = {};
    if (TERMS_KB_ID) KB_PROMPTS[TERMS_KB_ID] = { key: 'prompts/terms-kb.xml' };

    app.post('/api/kb-query', requireAuth, async (req, res) => {
        const { knowledgeBaseId, query } = req.body;
        if (!knowledgeBaseId || !query) {
            return res.status(400).json({ error: 'Missing knowledgeBaseId or query' });
        }

        try {
            // Load prompt template from S3 if one is configured for this KB
            let generationConfiguration;
            const promptConfig = KB_PROMPTS[knowledgeBaseId];
            if (promptConfig) {
                const promptTemplate = await loadPrompt(promptConfig.key);
                generationConfiguration = {
                    promptTemplate: { textPromptTemplate: promptTemplate },
                };
            }

            const command = new RetrieveAndGenerateCommand({
                input: { text: query },
                retrieveAndGenerateConfiguration: {
                    type: 'KNOWLEDGE_BASE',
                    knowledgeBaseConfiguration: {
                        knowledgeBaseId,
                        modelArn: 'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
                        ...(generationConfiguration && { generationConfiguration }),
                    },
                },
            });

            const response = await bedrockAgent.send(command);
            const text = response.output?.text || 'No response generated.';
            const citations = (response.citations || []).map(c => ({
                text: c.generatedResponsePart?.textResponsePart?.text || '',
                references: (c.retrievedReferences || []).map(r => ({
                    content: r.content?.text || '',
                    location: r.location?.s3Location?.uri || '',
                })),
            }));

            res.json({ text, citations });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Job status (DynamoDB status-index GSI scan) ──

    app.get('/api/jobs', requireAuth, async (req, res) => {
        if (!JOBS_TABLE_NAME) return res.json({ jobs: [] });
        const limit = Math.min(parseInt(req.query.limit) || 50, 200);
        const jobIdSearch = (req.query.job_id || '').trim().toLowerCase();
        const statusFilter = req.query.status || 'ALL'; // ALL | RUNNING | COMPLETE | FAILED | PENDING

        try {
            let allItems = [];

            if (jobIdSearch) {
                // Direct table query by job_id (exact or prefix match)
                const result = await dynamodb.send(new QueryCommand({
                    TableName: JOBS_TABLE_NAME,
                    KeyConditionExpression: 'job_id = :jid',
                    ExpressionAttributeValues: { ':jid': { S: jobIdSearch } },
                }));
                allItems = result.Items || [];
            } else if (statusFilter === 'ALL') {
                // Fetch all active statuses in parallel
                const statuses = ['RUNNING', 'COMPLETE', 'FAILED', 'PENDING'];
                const results = await Promise.all(statuses.map(s =>
                    dynamodb.send(new QueryCommand({
                        TableName: JOBS_TABLE_NAME,
                        IndexName: 'status-index',
                        KeyConditionExpression: '#s = :s',
                        ExpressionAttributeNames: { '#s': 'status' },
                        ExpressionAttributeValues: { ':s': { S: s } },
                        ScanIndexForward: false,
                        Limit: s === 'COMPLETE' ? limit : 50,
                    }))
                ));
                allItems = results.flatMap(r => r.Items || []);
            } else {
                // Single status filter
                const result = await dynamodb.send(new QueryCommand({
                    TableName: JOBS_TABLE_NAME,
                    IndexName: 'status-index',
                    KeyConditionExpression: '#s = :s',
                    ExpressionAttributeNames: { '#s': 'status' },
                    ExpressionAttributeValues: { ':s': { S: statusFilter } },
                    ScanIndexForward: false,
                    Limit: limit,
                }));
                allItems = result.Items || [];
            }

            // Group by job_id
            const jobMap = {};
            for (const item of allItems) {
                const jobId = item.job_id?.S;
                const specialist = item.specialist?.S;
                if (!jobId) continue;
                if (!jobMap[jobId]) jobMap[jobId] = { job_id: jobId, specialists: [] };
                const entry = {
                    specialist,
                    status: item.status?.S,
                    started_at: item.started_at?.S,
                    completed_at: item.completed_at?.S,
                    result_s3_key: item.result_s3_key?.S,
                    error: item.error?.S,
                };
                if (specialist === 'orchestrator') {
                    jobMap[jobId].orchestrator = entry;
                } else {
                    jobMap[jobId].specialists.push(entry);
                }
            }

            const jobs = Object.values(jobMap).sort((a, b) => {
                const ta = a.orchestrator?.started_at || '';
                const tb = b.orchestrator?.started_at || '';
                return tb.localeCompare(ta);
            });

            res.json({ jobs });
        } catch (e) {
            console.error('[jobs] error:', e.message);
            res.status(500).json({ error: e.message });
        }
    });

    // ── Delete a job (all specialist records) ──

    app.delete('/api/jobs/:job_id', requireAuth, async (req, res) => {
        if (!JOBS_TABLE_NAME) return res.status(404).json({ error: 'Jobs table not configured' });
        const jobId = req.params.job_id;
        if (!jobId) return res.status(400).json({ error: 'Missing job_id' });

        try {
            // Query all records for this job_id (orchestrator + specialists)
            const result = await dynamodb.send(new QueryCommand({
                TableName: JOBS_TABLE_NAME,
                KeyConditionExpression: 'job_id = :jid',
                ExpressionAttributeValues: { ':jid': { S: jobId } },
                ProjectionExpression: 'job_id, specialist',
            }));

            const items = result.Items || [];
            if (items.length === 0) return res.status(404).json({ error: 'Job not found' });

            // Delete each record
            await Promise.all(items.map(item =>
                dynamodb.send(new DeleteItemCommand({
                    TableName: JOBS_TABLE_NAME,
                    Key: {
                        job_id: item.job_id,
                        specialist: item.specialist,
                    },
                }))
            ));

            console.log('[jobs] deleted job_id=%s records=%d', jobId, items.length);
            res.json({ deleted: jobId, records: items.length });
        } catch (e) {
            console.error('[jobs] delete error:', e.message);
            res.status(500).json({ error: e.message });
        }
    });

    app.get('/api/knowledge-bases', requireAuth, async (_req, res) => {
        const knowledgeBases = [];
        if (CONTRACT_KB_ID) {
            knowledgeBases.push({
                id: CONTRACT_KB_ID,
                name: 'Contract Analysis KB',
                description: 'Analyzed contract outputs and specialist findings',
            });
        }
        if (TERMS_KB_ID) {
            knowledgeBases.push({
                id: TERMS_KB_ID,
                name: 'Terms KB',
                description: 'Reference materials, glossaries.',
                showGlossaries: true,
            });
        }
        res.json({ knowledgeBases });
    });

    app.get('/api/pricing', requireAuth, async (_req, res) => {
        try {
            res.json(await loadConfig('pricing.json'));
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── S3 clients (shared by browse + results) ──

    const s3 = new S3Client({ region: REGION, credentials });

    // ── S3 source contract browser ──

    const SOURCE_BUCKET = process.env.SOURCE_BUCKET;
    const SOURCE_PREFIX = process.env.SOURCE_PREFIX || 'xml-versions/';

    // Presigned upload URL — scoped to testing/{sub}/
    app.post('/api/upload-url', requireAuth, async (req, res) => {
        const { filename } = req.body;
        if (!filename) return res.status(400).json({ error: 'Missing filename' });
        if (!SOURCE_BUCKET) return res.status(500).json({ error: 'SOURCE_BUCKET not configured' });

        const sub = req.user?.sub || 'unknown';
        const ext = filename.split('.').pop().toLowerCase();
        if (ext !== 'pdf') return res.status(400).json({ error: 'Only PDF files are supported' });

        const safeFilename = filename.replace(/[^a-zA-Z0-9._-]/g, '_');
        const key = `testing/${sub}/${randomUUID()}-${safeFilename}`;

        try {
            const command = new PutObjectCommand({
                Bucket: SOURCE_BUCKET,
                Key: key,
                ContentType: 'application/pdf',
            });
            const uploadUrl = await getSignedUrl(s3, command, { expiresIn: 900 }); // 15 min
            res.json({ uploadUrl, s3Uri: `s3://${SOURCE_BUCKET}/${key}`, key });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    app.get('/api/s3-browse', requireAuth, async (req, res) => {
        const sub = req.user?.sub || 'unknown';
        const bucket = req.query.bucket || SOURCE_BUCKET;
        // Default to user's testing folder; allow explicit prefix override for admins
        const prefix = req.query.prefix !== undefined
            ? req.query.prefix
            : `testing/${sub}/`;
        try {
            const command = new ListObjectsV2Command({
                Bucket: bucket,
                Prefix: prefix,
                Delimiter: '/',
            });
            const response = await s3.send(command);

            const folders = (response.CommonPrefixes || []).map(p => ({
                type: 'folder',
                key: p.Prefix,
                name: p.Prefix.replace(prefix, '').replace(/\/$/, ''),
            }));

            const files = (response.Contents || [])
                .filter(obj => obj.Key !== prefix && obj.Key.toLowerCase().endsWith('.pdf'))
                .map(obj => ({
                    type: 'file',
                    key: obj.Key,
                    name: obj.Key.replace(prefix, ''),
                    size: obj.Size,
                    lastModified: obj.LastModified,
                }));

            res.json({ bucket, prefix, folders, files });
        } catch (e) {
            console.error('[s3-browse] error:', e.name, e.message);
            res.status(500).json({ error: `${e.name}: ${e.message}` });
        }
    });

    // ── Results browser (S3 knowledge base bucket) ──

    const RESULTS_BUCKET = process.env.RESULTS_BUCKET;

    // List analysis sessions (jobs under the canonical prefix)
    app.get('/api/results', requireAuth, async (_req, res) => {
        try {
            const CANONICAL_PREFIX = 'jobs-canonical-versions/';
            const command = new ListObjectsV2Command({
                Bucket: RESULTS_BUCKET,
                Prefix: CANONICAL_PREFIX,
                Delimiter: '/',
            });
            const response = await s3.send(command);
            const sessions = (response.CommonPrefixes || []).map(p => {
                // p.Prefix is e.g. "jobs-canonical-versions/CONTRACT_NAME_YYYYMMDDTHHMMSSz/"  // pragma: allowlist secret
                const job = p.Prefix.slice(CANONICAL_PREFIX.length).replace(/\/$/, '');
                const lastUnderscore = job.lastIndexOf('_');
                const name = lastUnderscore > 0 ? job.substring(0, lastUnderscore) : job;
                const ts = lastUnderscore > 0 ? job.substring(lastUnderscore + 1) : '';
                return { prefix: p.Prefix, name, timestamp: ts };
            });
            // Sort newest first
            sessions.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
            res.json({ bucket: RESULTS_BUCKET, sessions });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // List files within a session prefix
    app.get('/api/results/list', requireAuth, async (req, res) => {
        try {
            let prefix = req.query.prefix || '';
            if (prefix && !prefix.endsWith('/')) prefix += '/';
            const command = new ListObjectsV2Command({
                Bucket: RESULTS_BUCKET,
                Prefix: prefix,
            });
            const response = await s3.send(command);
            const files = (response.Contents || [])
                .filter(obj => !obj.Key.endsWith('.metadata.json') && obj.Key !== prefix)
                .map(obj => ({
                    key: obj.Key,
                    name: obj.Key.replace(prefix, ''),
                    size: obj.Size,
                    lastModified: obj.LastModified,
                }));
            res.json({ prefix, files });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // Fetch a single file's content
    app.post('/api/results/fetch', requireAuth, async (req, res) => {
        const { key } = req.body;
        if (!key) return res.status(400).json({ error: 'Missing key' });
        try {
            const command = new GetObjectCommand({ Bucket: RESULTS_BUCKET, Key: key });
            const response = await s3.send(command);
            const body = await response.Body.transformToString();
            res.json({ key, content: body, contentType: response.ContentType });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // Fetch metadata sidecar for a file
    app.post('/api/results/metadata', requireAuth, async (req, res) => {
        const { key } = req.body;
        if (!key) return res.status(400).json({ error: 'Missing key' });
        try {
            const metaKey = key + '.metadata.json';
            const command = new GetObjectCommand({ Bucket: RESULTS_BUCKET, Key: metaKey });
            const response = await s3.send(command);
            const body = await response.Body.transformToString();
            res.json(JSON.parse(body));
        } catch {
            res.json(null);
        }
    });
}
