# UI

[← Home](../../README.md) | [Architecture](ARCHITECTURE.md) | [Agents & Prompting](AGENTS.md) | [Deployment](DEPLOYMENT.md) | [Authentication](AUTHENTICATION.md) | [Local Dev](LOCAL_DEV.md)

---

## Overview

React frontend + Express API server, containerized and deployed on ECS Fargate. The Express server handles all AWS API calls — the browser never touches AWS directly.

```
ui/
├── server/
│   ├── index.js      # Express app, CORS, JWT auth middleware, SSM config loading
│   └── routes.js     # All API route handlers
└── src/
    ├── App.jsx        # Root component, OIDC provider, routing
    ├── main.jsx       # Entry point
    └── components/
        ├── Header.jsx          # Navigation, user info, logout
        ├── Login.jsx           # Cognito redirect trigger
        ├── Home.jsx            # Contract upload + analysis trigger
        ├── LegalTeam.jsx       # Specialist selection panel
        ├── JobStatus.jsx       # Job history panel (DynamoDB polling)
        ├── ResultsBrowser.jsx  # Browse and view analysis outputs from S3
        ├── Chat.jsx            # General Bedrock chat
        ├── KBChat.jsx          # Knowledge base retrieval chat
        └── CostCalculator.jsx  # Estimate analysis cost
```

---

## Auth Flow

Authentication uses [react-oidc-context](https://github.com/authts/react-oidc-context) with Cognito as the OIDC provider.

1. Unauthenticated user hits the app → redirected to Cognito hosted UI
2. User logs in (MFA required) → Cognito redirects back with auth code
3. react-oidc-context exchanges code for tokens (PKCE)
4. Access token stored in memory, sent as `Authorization: Bearer {token}` on every API request
5. Express verifies the token signature against Cognito's JWKS endpoint on every protected route

The JWKS client is lazy-initialized on first request and cached for the container lifetime.

### Protected Routes

All `/api/*` routes except `/api/env` require a valid JWT. `/api/env` is public — it returns branding config and the AWS region, needed before auth is established.

---

## API Routes

| Method   | Path                    | Description                                            |
| -------- | ----------------------- | ------------------------------------------------------ |
| `GET`    | `/api/env`              | Branding config, region (public)                       |
| `GET`    | `/api/specialists`      | Specialist registry from S3 config                     |
| `GET`    | `/api/glossaries`       | Glossary registry from S3 config                       |
| `GET`    | `/api/pipeline-config`  | User's session state (enabled specialists, agent mode) |
| `PUT`    | `/api/pipeline-config`  | Update user's session state                            |
| `POST`   | `/api/analyze`          | Submit contract for analysis (SSE response)            |
| `POST`   | `/api/chat`             | Bedrock Converse chat                                  |
| `POST`   | `/api/kb-query`         | Bedrock RetrieveAndGenerate                            |
| `GET`    | `/api/knowledge-bases`  | KB registry from local config                          |
| `GET`    | `/api/jobs`             | Job history list (DynamoDB status-index scan)          |
| `DELETE` | `/api/jobs/:job_id`     | Delete all records for a job                           |
| `GET`    | `/api/pricing`          | Pricing config from S3                                 |
| `POST`   | `/api/upload-url`       | Generate presigned S3 PUT URL for contract upload      |
| `GET`    | `/api/s3-browse`        | Browse source contract bucket                          |
| `GET`    | `/api/results`          | List analysis sessions from results bucket             |
| `GET`    | `/api/results/list`     | List files within a session prefix                     |
| `POST`   | `/api/results/fetch`    | Fetch a single result file's content                   |
| `POST`   | `/api/results/metadata` | Fetch KB metadata sidecar for a file                   |

---

## Analysis Flow (SSE)

`POST /api/analyze` returns a Server-Sent Events stream. The browser receives progress events as each specialist completes.

```
data: {"type":"progress","text":"{\"stage\":\"orchestrator\",\"status\":\"running\",\"job_id\":\"...\"}"}
data: {"type":"progress","text":"{\"stage\":\"financial\",\"status\":\"running\"}"}
data: {"type":"progress","text":"{\"stage\":\"financial\",\"status\":\"complete\"}"}
...
data: {"type":"done","text":"{\"code\":0,\"job_id\":\"...\"}"}
```

The server polls DynamoDB every 2 seconds. Max poll duration: 15 minutes (450 polls, matching AgentCore Runtime timeout). If the client disconnects, polling stops immediately.

**Idempotency:** If a `job_id` is supplied and the orchestrator record is already `COMPLETE` in DynamoDB, the server returns a cached result immediately without re-invoking the runtime.

---

## Session State

Per-user session state is stored in-memory on the Express server (keyed by Cognito `sub`). It resets on container restart.

```js
{
  enabledSpecialists: ['financial', 'rights_clearance', 'talent_guild_compliance', 'regulatory_compliance'],
  agentMode: false
}
```

`AGENT_MODE=true` in the environment locks agent mode on for all users regardless of session state.

---

## Configuration Loading

In production (`NODE_ENV=production`), the server loads config from SSM Parameter Store at startup. In local dev, it reads from `ui/config/.env`.

SSM parameters loaded (all prefixed with `/media-contracts/{deployment_id}-{suffix}/`):
- `orchestrator-runtime-arn`
- `jobs-table-name`
- `config-bucket-name`
- `results-bucket-name`
- `source-bucket-name`
- `chat-model`
- `agent-mode`
- `cognito-user-pool-id`
- `cognito-domain`
- `contract-kb-id`
- `terms-kb-id`

---

## CORS

CORS is restricted to the origin specified by `ALLOWED_ORIGIN` env var. In local dev, set `ALLOWED_ORIGIN=http://localhost:7870`. In production, set it to the ECS service URL or CloudFront distribution.

If `ALLOWED_ORIGIN` is not set, CORS falls back to permissive mode (development only).

---

## Vite Build

The React app is built with Vite. Build-time env vars (prefixed `VITE_`) are baked into the JS bundle:

| Variable                 | Description                                                              |
| ------------------------ | ------------------------------------------------------------------------ |
| `VITE_COGNITO_AUTHORITY` | OIDC issuer URL (`https://cognito-idp.{region}.amazonaws.com/{pool-id}`) |
| `VITE_COGNITO_CLIENT_ID` | Cognito UI app client ID                                                 |
| `VITE_COGNITO_DOMAIN`    | Cognito hosted UI domain                                                 |

These are generated by `deployment/scripts/generate_ui_env.sh` from CDK stack outputs.
