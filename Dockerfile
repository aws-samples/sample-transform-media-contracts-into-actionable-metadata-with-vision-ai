# ── Stage 1: Build the React frontend ──
FROM node:22-slim AS frontend
WORKDIR /app/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# ── Stage 2: Production UI server (Node only) ──
# The UI server is a thin Express proxy that calls the AgentCore Runtime
# via the AWS SDK. It does not run the pipeline locally, so it does not
# need Python, poppler, glossaries, or run_pipeline.py.
FROM node:22-slim

WORKDIR /app

# Node dependencies (server only — frontend is pre-built in stage 1)
COPY ui/package.json ui/package-lock.json ./ui/
RUN cd ui && npm ci --omit=dev

# Copy application code
COPY ui/server/ ./ui/server/
COPY ui/config/ ./ui/config/
# Remove local dev .env — production config comes from SSM
RUN rm -f ui/config/.env
COPY --from=frontend /app/ui/dist ./ui/dist

# Environment
ENV NODE_ENV=production
ENV PORT=8080
ENV AWS_REGION=us-west-2

EXPOSE 8080

# Run as non-root user
RUN useradd -r -u 1001 -g root appuser && chown -R appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://localhost:8080/api/env', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "ui/server/index.js"]
