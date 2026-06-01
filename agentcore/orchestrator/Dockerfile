# MediaContracts Orchestrator — AgentCore Runtime container
# Must be ARM64 (AgentCore requirement)
FROM --platform=linux/arm64 python:3.12-slim

WORKDIR /app

# System deps for pdf2image (poppler) and Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY agentcore/orchestrator/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared utilities and agent prompts
COPY utils/ utils/
COPY media_contracts_agents/ media_contracts_agents/
COPY agentcore/shared/ agentcore/shared/
COPY agentcore/orchestrator/main.py agentcore/orchestrator/main.py

# AgentCore requires the app to listen on 0.0.0.0:8080
ENV PORT=8080
ENV PYTHONPATH=/app
EXPOSE 8080

# Run as non-root user
RUN useradd -r -u 1001 -g root appuser && chown -R appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "agentcore/orchestrator/main.py"]
