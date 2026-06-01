#!/bin/bash
set -euo pipefail

# ── Media Contracts Analyzer — Interactive Deployment Menu ─────────────────
#
# Usage:
#   DEPLOYMENT_ID=dev ./deploy.sh      # Interactive menu
#   DEPLOYMENT_ID=dev ./deploy.sh 1    # Run option 1 directly (non-interactive)
#
# This script is fully resumable - re-run after failures to continue where you left off.
# All operations are idempotent (safe to run multiple times).
# ───────────────────────────────────────────────────────────────────────────

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

_ts() { date '+%Y-%m-%d %H:%M:%S'; }
log_info() { echo -e "${BLUE}[$(_ts)]${NC} $1"; }
log_success() { echo -e "${GREEN}[$(_ts) ✓]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[$(_ts) !]${NC} $1"; }
log_error() { echo -e "${RED}[$(_ts) ✗]${NC} $1"; }
log_step() { echo -e "${CYAN}${BOLD}── [$(_ts)]${NC} ${BOLD}$1${NC}"; }

# ── Defaults ──
AWS_REGION="${AWS_REGION:-us-west-2}"
MODEL_ID="${MODEL_ID:-us.anthropic.claude-sonnet-4-6}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
UI_CALLBACK_URL="${UI_CALLBACK_URL:-http://localhost:7870/callback}"
UI_LOGOUT_URL="${UI_LOGOUT_URL:-http://localhost:7870/}"
ECS_SERVICE_URL="${ECS_SERVICE_URL:-http://localhost:7870}"

# State file tracks completed steps
STATE_FILE=".deploy-state/${DEPLOYMENT_ID:-unknown}.json"

# ── Validate required vars ──
if [ -z "${DEPLOYMENT_ID:-}" ]; then
  log_error "DEPLOYMENT_ID is required (e.g. DEPLOYMENT_ID=dev ./deploy.sh)"
  exit 1
fi

# ── Stack suffix (3-char unique ID) ──
# Auto-generate once and persist in state file. Reuse on subsequent runs.
_generate_suffix() {
  python3 -c "import secrets; print(secrets.token_hex(2)[:3])"
}

_ensure_suffix() {
  init_state  # make sure state file exists
  local existing=$(get_state "stack_suffix")
  if [ -n "$existing" ] && [ "$existing" != "" ]; then
    STACK_SUFFIX="$existing"
  else
    STACK_SUFFIX=$(_generate_suffix)
    set_state "stack_suffix" "\"$STACK_SUFFIX\""
  fi
  export STACK_SUFFIX
}

# Helper to build stack names: MC-{Name}-{suffix}
_sn() { echo "MC-$1-${STACK_SUFFIX}"; }

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_BASE="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# ECR repo vars — set after _ensure_suffix populates STACK_SUFFIX
_set_ecr_vars() {
  ORCHESTRATOR_REPO="${ECR_BASE}/media-contracts-orchestrator-${DEPLOYMENT_ID}-${STACK_SUFFIX}"
  UI_REPO="${ECR_BASE}/media-contracts-ui-${DEPLOYMENT_ID}-${STACK_SUFFIX}"
}

# ── State Management ───────────────────────────────────────────────────────
init_state() {
  mkdir -p .deploy-state
  if [ ! -f "${STATE_FILE}" ]; then
    cat > "${STATE_FILE}" <<EOF
{
  "deployment_id": "${DEPLOYMENT_ID}",
  "started_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "infra_complete": false,
  "prompts_uploaded": false,
  "specialists_complete": false,
  "gateway_complete": false,
  "orchestrator_image_pushed": false,
  "orchestrator_runtime_deployed": false,
  "supporting_complete": false,
  "ui_image_pushed": false,
  "ecs_deployed": false,
  "gateway_url": ""
}
EOF
  fi
}

get_state() {
  local key=$1
  python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d.get('${key}', ''))"
}

set_state() {
  local key=$1
  local value=$2
  python3 -c "
import json
with open('${STATE_FILE}', 'r+') as f:
    data = json.load(f)
    data['${key}'] = ${value}
    f.seek(0)
    json.dump(data, f, indent=2)
    f.truncate()
"
}

mark_complete() {
  set_state "$1" "True"
  set_state "${1}_at" "\"$(date -u +"%Y-%m-%dT%H:%M:%SZ")\""
  log_success "Step complete: $1"
}

check_completed() {
  local step=$1
  local completed=$(get_state "$step")
  [ "$completed" = "True" ]
}

# ── Export CDK env vars ────────────────────────────────────────────────────
export_cdk_env() {
  export DEPLOYMENT_ID
  export STACK_SUFFIX
  export MODEL_ID
  export IMAGE_TAG
  export UI_CALLBACK_URL
  export UI_LOGOUT_URL
  export CDK_DEFAULT_ACCOUNT="${ACCOUNT_ID}"
  export CDK_DEFAULT_REGION="${AWS_REGION}"

  local gateway_url=$(get_state "gateway_url")
  if [ -n "$gateway_url" ] && [ "$gateway_url" != "" ]; then
    export GATEWAY_URL="$gateway_url"
  fi

  local cors_origin=$(get_state "cors_origin")
  if [ -n "$cors_origin" ] && [ "$cors_origin" != "" ]; then
    export CORS_ORIGIN="$cors_origin"
  fi
}

# ── Ensure Python deps ─────────────────────────────────────────────────────
ensure_cdk_deps() {
  if ! command -v uv &> /dev/null; then
    log_error "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
  fi

  log_info "Syncing Python dependencies..."
  unset VIRTUAL_ENV
  uv sync --quiet
  export VIRTUAL_ENV="${PWD}/.venv"
  export PATH="${PWD}/.venv/bin:${PATH}"
}

# ── ECR login ──────────────────────────────────────────────────────────────
ecr_login() {
  log_info "Logging into ECR..."
  aws ecr get-login-password --region "${AWS_REGION}" | \
    docker login --username AWS --password-stdin "${ECR_BASE}" 2>/dev/null
}

# ── CDK deploy helper ─────────────────────────────────────────────────────
cdk_deploy() {
  (unset VIRTUAL_ENV; cd deployment && uv run cdk deploy --app "python app.py" --require-approval never "$@")
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 1: Foundational Infrastructure
# ══════════════════════════════════════════════════════════════════════════
step_infra() {
  log_step "Step 1: Foundational Infrastructure"

  if check_completed "infra_complete"; then
    log_warn "Already complete. Re-running will update stacks if changes detected."
    read -p "Continue? (y/n): " confirm
    [ "$confirm" != "y" ] && return
  fi

  ensure_cdk_deps
  export_cdk_env

  log_info "Deploying VPC, S3, Cognito, DynamoDB, ECR, IAM, KBs, InferenceProfiles, XRay..."
  cdk_deploy \
    "$(_sn Vpc)" \
    "$(_sn Cognito)" \
    "$(_sn InferenceProfiles)" \
    "$(_sn S3)" \
    "$(_sn DynamoDB)" \
    "$(_sn ECR)" \
    "$(_sn IAM)" \
    "$(_sn AnalysisKB)" \
    "$(_sn TermsKB)" \
    "$(_sn XRay)"

  mark_complete "infra_complete"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 2: Upload Prompts, Schemas & Glossaries
# ══════════════════════════════════════════════════════════════════════════
step_upload() {
  log_step "Step 2: Upload Prompts, Schemas & Glossaries"

  if check_completed "prompts_uploaded"; then
    log_info "Already uploaded. Re-uploading to sync any changes..."
  fi

  local config_bucket=$(aws cloudformation describe-stacks \
    --stack-name "$(_sn S3)" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='ConfigBucketName'].OutputValue" \
    --output text 2>/dev/null || echo "")

  if [ -z "$config_bucket" ] || [ "$config_bucket" = "None" ]; then
    log_error "$(_sn S3) stack not found. Run Step 1 first."
    exit 1
  fi

  log_info "Syncing prompts to s3://${config_bucket}/prompts/agents/..."
  aws s3 sync media_contracts_agents/ "s3://${config_bucket}/prompts/agents/" --quiet

  log_info "Syncing foundation prompts to s3://${config_bucket}/prompts/foundation/..."
  aws s3 sync media_contracts_agents/foundation/ "s3://${config_bucket}/prompts/foundation/" --quiet

  log_info "Syncing UI prompts to s3://${config_bucket}/prompts/..."
  aws s3 sync prompts/ "s3://${config_bucket}/prompts/" --quiet

  if [ -d "schemas/" ]; then
    log_info "Syncing schemas to s3://${config_bucket}/schemas/..."
    aws s3 sync schemas/ "s3://${config_bucket}/schemas/" --quiet
  fi

  # Upload glossary definitions to Terms KB bucket
  local terms_bucket=$(aws cloudformation describe-stacks \
    --stack-name "$(_sn S3)" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='TermsBucketName'].OutputValue" \
    --output text 2>/dev/null || echo "")

  if [ -n "$terms_bucket" ] && [ "$terms_bucket" != "None" ] && [ -d "deployment/glossaries/" ]; then
    log_info "Syncing glossaries to s3://${terms_bucket}/..."
    aws s3 sync deployment/glossaries/ "s3://${terms_bucket}/" \
      --exclude "*.DS_Store" --exclude ".git/*" --exclude "*.pyc" --quiet
    log_success "Glossary data uploaded to ${terms_bucket}"

    # Kick off KB ingestion in the background (non-blocking)
    local terms_kb_id=$(aws cloudformation describe-stacks \
      --stack-name "$(_sn TermsKB)" \
      --region "${AWS_REGION}" \
      --query "Stacks[0].Outputs[?OutputKey=='TermsKBId'].OutputValue" \
      --output text 2>/dev/null || echo "")
    local terms_ds_id=$(aws cloudformation describe-stacks \
      --stack-name "$(_sn TermsKB)" \
      --region "${AWS_REGION}" \
      --query "Stacks[0].Outputs[?OutputKey=='TermsDataSourceId'].OutputValue" \
      --output text 2>/dev/null || echo "")

    if [ -n "$terms_kb_id" ] && [ "$terms_kb_id" != "None" ] && \
       [ -n "$terms_ds_id" ] && [ "$terms_ds_id" != "None" ]; then
      log_info "Starting Terms KB ingestion (background)..."
      aws bedrock-agent start-ingestion-job \
        --knowledge-base-id "$terms_kb_id" \
        --data-source-id "$terms_ds_id" \
        --region "${AWS_REGION}" \
        --no-cli-pager > /dev/null 2>&1 &
      log_success "Terms KB ingestion started"
    fi
  fi

  mark_complete "prompts_uploaded"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 3: Specialist Lambdas
# ══════════════════════════════════════════════════════════════════════════
step_specialists() {
  log_step "Step 3: Specialist Lambdas"

  if check_completed "specialists_complete"; then
    log_warn "Already complete. Re-running will update if changes are detected."
    read -p "Continue? (y/n): " confirm
    [ "$confirm" != "y" ] && return
  fi

  ensure_cdk_deps
  export_cdk_env

  log_info "Deploying $(_sn Specialists)..."
  cdk_deploy "$(_sn Specialists)"

  mark_complete "specialists_complete"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 4: Gateway
# ══════════════════════════════════════════════════════════════════════════
step_gateway() {
  log_step "Step 4: Gateway"

  if check_completed "gateway_complete"; then
    log_warn "Already complete. Re-running will update if changes are detected."
    read -p "Continue? (y/n): " confirm
    [ "$confirm" != "y" ] && return
  fi

  ensure_cdk_deps
  export_cdk_env

  log_info "Deploying $(_sn Gateway)..."
  cdk_deploy "$(_sn Gateway)"

  # Auto-detect Gateway URL
  local gateway_url=$(aws cloudformation describe-stacks \
    --stack-name "$(_sn Gateway)" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue" \
    --output text 2>/dev/null || echo "")

  if [ -n "$gateway_url" ] && [ "$gateway_url" != "None" ]; then
    set_state "gateway_url" "\"$gateway_url\""
    log_success "Gateway URL: $gateway_url"
    export GATEWAY_URL="$gateway_url"
  else
    log_error "Could not auto-detect Gateway URL from stack outputs"
    exit 1
  fi

  mark_complete "gateway_complete"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 5: Orchestrator — Build, Push & Deploy
# ══════════════════════════════════════════════════════════════════════════
step_orchestrator() {
  log_step "Step 5: Orchestrator — Build, Push & Deploy"

  local gateway_url=$(get_state "gateway_url")
  if [ -z "$gateway_url" ] || [ "$gateway_url" = "" ]; then
    log_error "Gateway URL not found. Run Step 4 (Gateway) first."
    exit 1
  fi

  ecr_login

  log_info "Building orchestrator image (linux/arm64 — AgentCore requirement)..."
  docker buildx build \
    --platform linux/arm64 \
    --file agentcore/orchestrator/Dockerfile \
    --tag "${ORCHESTRATOR_REPO}:${IMAGE_TAG}" \
    --push \
    .

  log_success "Orchestrator image pushed: ${ORCHESTRATOR_REPO}:${IMAGE_TAG}"

  # Verify the image actually landed in ECR before deploying
  log_info "Verifying image exists in ECR..."
  if ! aws ecr describe-images \
    --repository-name "media-contracts-orchestrator-${DEPLOYMENT_ID}-${STACK_SUFFIX}" \
    --image-ids imageTag="${IMAGE_TAG}" \
    --region "${AWS_REGION}" \
    --no-cli-pager > /dev/null 2>&1; then
    log_error "Image ${ORCHESTRATOR_REPO}:${IMAGE_TAG} not found in ECR after push!"
    log_error "The buildx push may have failed silently. Try: docker push ${ORCHESTRATOR_REPO}:${IMAGE_TAG}"
    exit 1
  fi
  log_success "Image verified in ECR: ${IMAGE_TAG}"

  mark_complete "orchestrator_image_pushed"

  ensure_cdk_deps
  export_cdk_env

  log_info "Deploying $(_sn Runtimes)..."
  cdk_deploy "$(_sn Runtimes)"

  log_success "Orchestrator runtime updated with image tag ${IMAGE_TAG}"
  mark_complete "orchestrator_runtime_deployed"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 6: Supporting Stacks
# ══════════════════════════════════════════════════════════════════════════
step_supporting() {
  log_step "Step 6: Supporting Stacks (AutoTrigger, KBSync, Dashboard)"

  ensure_cdk_deps
  export_cdk_env

  log_info "Deploying AutoTrigger, KBSync, Dashboard..."
  cdk_deploy \
    "$(_sn AutoTrigger)" \
    "$(_sn AnalysisKBSync)" \
    "$(_sn Dashboard)"

  mark_complete "supporting_complete"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 7: UI — Build & Push Image
# ══════════════════════════════════════════════════════════════════════════
step_ui_build() {
  log_step "Step 7: UI — Build & Push Image"

  ecr_login

  log_info "Generating ui/.env from Cognito stack outputs..."
  DEPLOYMENT_ID="${DEPLOYMENT_ID}" \
  AWS_REGION="${AWS_REGION}" \
  ECS_SERVICE_URL="${ECS_SERVICE_URL}" \
    bash deployment/scripts/generate_ui_env.sh

  log_info "Building React app..."
  (cd ui && npm install --silent && npm run build)

  log_info "Building UI container image (linux/amd64)..."
  docker build \
    --platform linux/amd64 \
    --file Dockerfile \
    --tag "${UI_REPO}:${IMAGE_TAG}" \
    --quiet \
    .

  log_info "Pushing UI image to ECR..."
  docker push "${UI_REPO}:${IMAGE_TAG}" --quiet

  log_success "UI image pushed: ${UI_REPO}:${IMAGE_TAG}"
  mark_complete "ui_image_pushed"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 8: UI — Deploy ECS
# ══════════════════════════════════════════════════════════════════════════
step_ui_deploy() {
  log_step "Step 8: UI — Deploy ECS"

  ensure_cdk_deps
  export_cdk_env

  local service_name="media-contracts-${DEPLOYMENT_ID}-${STACK_SUFFIX}"

  log_info "Deploying $(_sn ECS) stack..."
  cdk_deploy "$(_sn ECS)"

  log_info "Forcing image rollout for ${service_name}..."
  local service_arn="arn:aws:ecs:${AWS_REGION}:${ACCOUNT_ID}:service/default/${service_name}"
  aws ecs update-express-gateway-service \
    --service-arn "${service_arn}" \
    --primary-container "{\"image\":\"${UI_REPO}:${IMAGE_TAG}\",\"containerPort\":8080}" \
    --region "${AWS_REGION}" \
    --no-cli-pager > /dev/null

  log_info "Polling rollout state..."
  while true; do
    local state=$(aws ecs describe-services \
      --cluster default \
      --services "${service_name}" \
      --region "${AWS_REGION}" \
      --query "services[0].deployments[0].rolloutState" \
      --output text 2>/dev/null || echo "UNKNOWN")
    echo "  $(_ts) — ${state}"
    [ "${state}" = "COMPLETED" ] && break
    [ "${state}" = "FAILED" ] && log_error "Deployment failed" && exit 1
    sleep 5
  done

  log_success "ECS Express service deployed and rolled out."
  mark_complete "ecs_deployed"

  # ── Update S3 CORS with the actual ECS endpoint ──────────────
  local ecs_endpoint=$(aws cloudformation describe-stacks \
    --stack-name "$(_sn ECS)" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='ServiceEndpoint'].OutputValue" \
    --output text 2>/dev/null || echo "")

  if [ -n "$ecs_endpoint" ] && [ "$ecs_endpoint" != "None" ]; then
    log_info "Setting S3 source bucket CORS origin to https://${ecs_endpoint}..."
    export CORS_ORIGIN="https://${ecs_endpoint}"
    set_state "cors_origin" "\"https://${ecs_endpoint}\""
    cdk_deploy "$(_sn S3)"
    log_success "S3 CORS updated for ${ecs_endpoint}"
  else
    log_warn "Could not read ECS endpoint — S3 CORS not configured. Uploads will fail."
  fi
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 9: Full Deploy (All Steps)
# ══════════════════════════════════════════════════════════════════════════
step_full() {
  log_step "Full Deployment (All Steps)"
  echo ""
  log_warn "This will run all deployment steps in sequence."
  read -p "Continue? (y/n): " confirm
  [ "$confirm" != "y" ] && return

  step_infra
  step_upload
  step_specialists
  step_gateway
  step_orchestrator
  step_supporting
  step_ui_build
  step_ui_deploy

  echo ""
  log_success "Full deployment complete!"
  show_status
}

# ══════════════════════════════════════════════════════════════════════════
# Show Deployment Status
# ══════════════════════════════════════════════════════════════════════════
show_status() {
  echo ""
  echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
  echo -e "${BOLD}  Deployment Status: ${DEPLOYMENT_ID}  (suffix: ${STACK_SUFFIX}, tag: ${IMAGE_TAG})${NC}"
  echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
  echo ""

  _step_line() {
    local key=$1 label=$2
    local done=$(check_completed "$key" && echo "✓" || echo "○")
    local ts=$(get_state "${key}_at")
    if [ -n "$ts" ] && [ "$ts" != "" ]; then
      echo -e "  ${done}  ${label}  ${YELLOW}${ts}${NC}"
    else
      echo "  ${done}  ${label}"
    fi
  }

  _step_line "infra_complete"                "1. Foundational Infrastructure"
  _step_line "prompts_uploaded"              "2. Prompts, Schemas & Glossaries"
  _step_line "specialists_complete"          "3. Specialist Lambdas"
  _step_line "gateway_complete"              "4. Gateway"

  # Step 5 is two sub-steps
  local s5a=$(check_completed "orchestrator_image_pushed" && echo "✓" || echo "○")
  local s5b=$(check_completed "orchestrator_runtime_deployed" && echo "✓" || echo "○")
  local s5="○"; [ "$s5a" = "✓" ] && [ "$s5b" = "✓" ] && s5="✓"
  local s5_ts=$(get_state "orchestrator_runtime_deployed_at")
  if [ -n "$s5_ts" ] && [ "$s5_ts" != "" ]; then
    echo -e "  ${s5}  5. Orchestrator — Build & Deploy  ${YELLOW}${s5_ts}${NC}"
  else
    echo "  ${s5}  5. Orchestrator — Build & Deploy"
  fi

  _step_line "supporting_complete"           "6. Supporting Stacks"
  _step_line "ui_image_pushed"               "7. UI — Build Image"
  _step_line "ecs_deployed"                  "8. UI — Deploy ECS"
  echo ""

  local gateway_url=$(get_state "gateway_url")
  if [ -n "$gateway_url" ] && [ "$gateway_url" != "" ]; then
    echo "  Gateway URL: ${gateway_url}"
  fi
  echo ""
}

# ══════════════════════════════════════════════════════════════════════════
# Interactive Menu
# ══════════════════════════════════════════════════════════════════════════
show_menu() {
  clear
  echo -e "${CYAN}${BOLD}"
  cat << "EOF"
╔════════════════════════════════════════════════════════════╗
║     Media Contracts Analyzer — Deployment Menu            ║
╚════════════════════════════════════════════════════════════╝
EOF
  echo -e "${NC}"

  echo -e "  ${BOLD}Deployment ID:${NC} ${DEPLOYMENT_ID}"
  echo -e "  ${BOLD}Stack Suffix:${NC}  ${STACK_SUFFIX}"
  echo -e "  ${BOLD}AWS Region:${NC}    ${AWS_REGION}"
  echo -e "  ${BOLD}AWS Account:${NC}   ${ACCOUNT_ID}"
  echo -e "  ${BOLD}Image Tag:${NC}     ${IMAGE_TAG}"
  echo ""

  show_status

  echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
  echo ""
  echo -e "  ${BOLD} 1${NC}) Foundational Infra (VPC, S3, Cognito, DynamoDB, ECR, IAM, KBs)"
  echo -e "  ${BOLD} 2${NC}) Upload Prompts, Schemas & Glossaries"
  echo -e "  ${BOLD} 3${NC}) Specialist Lambdas"
  echo -e "  ${BOLD} 4${NC}) Gateway"
  echo -e "  ${BOLD} 5${NC}) Orchestrator — Build & Deploy"
  echo -e "  ${BOLD} 6${NC}) Supporting Stacks (AutoTrigger, KBSync, Dashboard)"
  echo -e "  ${BOLD} 7${NC}) UI — Build & Push Image"
  echo -e "  ${BOLD} 8${NC}) UI — Deploy ECS"
  echo ""
  echo -e "  ${BOLD} 9${NC}) ${GREEN}Full Deployment (Run All Steps)${NC}"
  echo ""
  echo -e "  ${BOLD}10${NC}) Show Deployment Status"
  echo -e "  ${BOLD}11${NC}) Reset Deployment State (start fresh)"
  echo -e "  ${BOLD} 0${NC}) Exit"
  echo ""
  echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
  echo ""
}

reset_state() {
  log_warn "This will reset deployment state and mark all steps as incomplete."
  read -p "Continue? (y/n): " confirm
  [ "$confirm" != "y" ] && return

  rm -f "${STATE_FILE}"
  init_state
  log_success "Deployment state reset."
}

# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════
init_state
_ensure_suffix
_set_ecr_vars

# Non-interactive mode: run specific step
if [ $# -gt 0 ]; then
  case "$1" in
    1)  step_infra ;;
    2)  step_upload ;;
    3)  step_specialists ;;
    4)  step_gateway ;;
    5)  step_orchestrator ;;
    6)  step_supporting ;;
    7)  step_ui_build ;;
    8)  step_ui_deploy ;;
    9)  step_full ;;
    10) show_status ;;
    11) reset_state ;;
    *)  log_error "Invalid option: $1" && exit 1 ;;
  esac
  exit 0
fi

# Interactive mode
while true; do
  show_menu
  read -p "Select option (0-11): " choice
  echo ""

  case "$choice" in
    1)  step_infra ;;
    2)  step_upload ;;
    3)  step_specialists ;;
    4)  step_gateway ;;
    5)  step_orchestrator ;;
    6)  step_supporting ;;
    7)  step_ui_build ;;
    8)  step_ui_deploy ;;
    9)  step_full ;;
    10) show_status ;;
    11) reset_state ;;
    0)  log_info "Exiting..."; exit 0 ;;
    *)  log_error "Invalid option. Press Enter to continue..."; read ;;
  esac

  echo ""
  read -p "Press Enter to continue..."
done
