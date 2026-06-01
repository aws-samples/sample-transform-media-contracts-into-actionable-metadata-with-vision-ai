# Upload & Pipeline Flow

[← Home](../../README.md) | [Architecture](ARCHITECTURE.md) | [Agents & Prompting](AGENTS.md) | [Deployment](DEPLOYMENT.md) | [UI](UI.md) | [Local Dev](LOCAL_DEV.md)

---

## Bucket Prefix Layout

```
s3://media-contracts-source-{id}/
├── testing/
│   └── {cognito-sub}/          # per-user uploads from the UI
│       └── contract.pdf
└── pipeline/
    └── contract.pdf             # PDFs dropped here auto-trigger the pipeline
```

---

## Flow 1 — User Upload (manual trigger)

User uploads a PDF through the UI and clicks Analyze.

```
1. User picks a PDF file in the UI (file input)

2. Browser → POST /api/upload-url
   Body: { filename: "contract.pdf" }
   Server generates a presigned S3 PUT URL for:
     s3://source-bucket/testing/{cognito-sub}/{uuid}-contract.pdf
   Returns: { uploadUrl, s3Uri }

3. Browser → PUT {uploadUrl}  (direct to S3, no server proxy)
   File lands at: s3://source-bucket/testing/{sub}/{uuid}-contract.pdf

4. Browser → POST /api/analyze
   Body: { contract_path: "s3://source-bucket/testing/{sub}/{uuid}-contract.pdf", job_id }
   Pipeline starts normally (AgentCore Runtime invocation)

5. SSE progress stream → browser (same as existing flow)
```

**Key points:**
- Presigned URL keeps credentials server-side
- File is scoped to the user's Cognito sub — users can only see their own uploads
- `testing/` prefix is browseable in the UI (filtered to `testing/{sub}/`)
- No auto-trigger — user explicitly clicks Analyze

---

## Flow 2 — Pipeline Prefix (auto-trigger)

A PDF is dropped into `pipeline/` by any means (CLI, SDK, another system, or a future admin UI). The pipeline starts automatically with no user interaction.

```
1. Any actor uploads a PDF to:
     s3://source-bucket/pipeline/contract.pdf

2. S3 Event Notification fires on s3:ObjectCreated:*
   Filter: prefix=pipeline/, suffix=.pdf

3. EventBridge rule (or direct Lambda trigger) invokes
   AutoTriggerLambda with the S3 event

4. AutoTriggerLambda:
   - Reads ORCHESTRATOR_RUNTIME_ARN from SSM
   - Generates a job_id (UUID)
   - Calls InvokeAgentRuntime with:
       { job_id, contract_path: "s3://source-bucket/pipeline/contract.pdf", agent_mode: true }
   - Writes a PENDING record to DynamoDB for job tracking

5. Pipeline runs normally
   Results appear in the Jobs tab as they complete
```

**Key points:**
- `agent_mode: true` — no user to select specialists, agent decides
- Job appears in the Jobs tab automatically (DynamoDB polling)
- No UI involvement required

---

## Flow 3 — Browse Previously Uploaded PDFs

User wants to re-analyze a PDF they uploaded earlier, or pick from the `testing/` folder.

```
1. User opens the file picker in the Chat tab

2. Picker calls GET /api/s3-browse?prefix=testing/{cognito-sub}/
   Returns only that user's uploads

3. User selects a file → s3 URI populated in the input

4. User clicks Analyze → same as Flow 1 step 4 onwards
```

**Key points:**
- Picker is scoped to `testing/{sub}/` — users cannot browse other users' files
- `pipeline/` prefix is not browseable from the UI (admin/system use only)

---

## Components to Build

### Backend

| Component                   | What it does                                                          |
| --------------------------- | --------------------------------------------------------------------- |
| `POST /api/upload-url`      | Generates presigned S3 PUT URL for `testing/{sub}/{uuid}-{filename}`  |
| `AutoTriggerLambda`         | Invoked by S3 event on `pipeline/` prefix; calls `InvokeAgentRuntime` |
| `GET /api/s3-browse` update | Scope default browse to `testing/{sub}/` when no prefix supplied      |

### Infrastructure (CDK)

| Component                              | What it does                                                                 |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| S3 event notification on source bucket | `s3:ObjectCreated:*` on `pipeline/*.pdf` → Lambda                            |
| `AutoTriggerLambda` CDK construct      | Lambda + IAM role (SSM read, `InvokeAgentRuntime`, DynamoDB write)           |
| ECS task role update                   | Add `s3:PutObject` on `source-bucket/testing/*` for presigned URL generation |

### Frontend

| Component          | What it does                                                     |
| ------------------ | ---------------------------------------------------------------- |
| File input in Chat | Pick local PDF → upload via presigned URL → auto-populate S3 URI |
| S3 Picker update   | Default to `testing/{sub}/` prefix; show upload option inline    |

---

## IAM Notes

- Presigned URL is generated server-side using the ECS task role — the task role needs `s3:PutObject` on `source-bucket/testing/*`
- `AutoTriggerLambda` needs: `ssm:GetParameter` on `/media-contracts/*`, `bedrock-agentcore:InvokeAgentRuntime` on the runtime ARN, `dynamodb:PutItem` on the jobs table
- The ECS task role already has `s3:GetObject` + `s3:ListBucket` on the source bucket — no change needed for browsing

---

## Security Notes

- `testing/{sub}/` scoping is enforced server-side using the verified JWT `sub` claim — the client cannot override it
- Presigned URLs expire after 15 minutes
- `pipeline/` is not accessible from the UI — no presigned URLs are generated for that prefix
