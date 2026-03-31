#!/bin/bash
# ============================================================
#  remote_deploy.sh — runs ON the remote server via SSH pipe
#  Usage: ssh user@host "bash -s -- <APP_DIR> <SERVICE> <PORT>" < remote_deploy.sh
#
#  Positional args (passed from GitHub Actions SSH step):
#    $1  APP_DIR  — absolute path to the app on the server
#    $2  SERVICE  — systemd service name (e.g. skyai-cctv)
#    $3  PORT     — port the app listens on (default 8000)
# ============================================================

set -euo pipefail

# ── Arguments ───────────────────────────────────────────────
APP_DIR="${1:?APP_DIR not set}"
SERVICE="${2:?SERVICE not set}"
PORT="${3:-8000}"

HEALTH_URL="http://localhost:${PORT}/health"
HEALTH_RETRIES=5
HEALTH_DELAY=6
ROLLBACK_REF_FILE="${APP_DIR}/.rollback_commit"
LOG_FILE="${APP_DIR}/logs/deploy.log"

# ── Helpers ──────────────────────────────────────────────────
log() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[${ts}] $*" | tee -a "$LOG_FILE"
}

die() {
  log "ERROR: $*"
  exit 1
}

health_check() {
  local attempt=0
  log "Running health check → ${HEALTH_URL}"
  while [ "$attempt" -lt "$HEALTH_RETRIES" ]; do
    attempt=$(( attempt + 1 ))
    log "  Attempt ${attempt}/${HEALTH_RETRIES}..."
    if curl -sf --max-time 5 "${HEALTH_URL}" > /dev/null; then
      log "  Health check PASSED"
      return 0
    fi
    log "  Not ready yet — waiting ${HEALTH_DELAY}s"
    sleep "$HEALTH_DELAY"
  done
  log "  Health check FAILED after ${HEALTH_RETRIES} attempts"
  return 1
}

rollback() {
  log "=========================================="
  log "  ROLLBACK TRIGGERED"
  log "=========================================="

  if [ ! -f "$ROLLBACK_REF_FILE" ]; then
    die "No rollback reference found at ${ROLLBACK_REF_FILE} — cannot rollback."
  fi

  local prev_commit
  prev_commit="$(cat "$ROLLBACK_REF_FILE")"
  log "Rolling back to commit: ${prev_commit}"

  cd "$APP_DIR"
  git reset --hard "$prev_commit" || die "git reset --hard to ${prev_commit} failed"

  log "Reinstalling dependencies for rollback commit..."
  .venv/bin/pip install -q -r requirements.txt || die "pip install during rollback failed"

  log "Restarting service after rollback..."
  sudo systemctl restart "$SERVICE" || die "systemctl restart during rollback failed"

  log "Waiting for rollback service to stabilise..."
  sleep 5

  if health_check; then
    log "Rollback SUCCESSFUL — service is running on previous commit (${prev_commit})"
    exit 1   # Still exit 1 so GitHub Actions marks the job as failed
  else
    die "Rollback health check also FAILED — manual intervention required!"
  fi
}

# ── Main Deployment ──────────────────────────────────────────
mkdir -p "$(dirname "$LOG_FILE")"
log "=========================================="
log "  DEPLOYMENT STARTED"
log "  App dir : ${APP_DIR}"
log "  Service : ${SERVICE}"
log "  Port    : ${PORT}"
log "=========================================="

cd "$APP_DIR" || die "Cannot cd to ${APP_DIR}"

# ── 1. Save current commit for rollback ──────────────────────
CURRENT_COMMIT="$(git rev-parse HEAD)"
echo "$CURRENT_COMMIT" > "$ROLLBACK_REF_FILE"
log "Saved rollback point: ${CURRENT_COMMIT}"

# ── 2. Pull latest code ──────────────────────────────────────
log "Pulling latest code from origin/main..."
git fetch origin main || die "git fetch failed"
git reset --hard origin/main || die "git reset failed"

NEW_COMMIT="$(git rev-parse HEAD)"
log "Updated to commit: ${NEW_COMMIT}"

if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
  log "No new commits — skipping reinstall (service unchanged)"
  # Still do health check to confirm current state
  health_check || die "Health check failed on unchanged deployment"
  log "Deployment complete (no changes)"
  exit 0
fi

# ── 3. Install / update dependencies ─────────────────────────
log "Installing Python dependencies..."
if [ ! -d ".venv" ]; then
  log "Creating virtual environment..."
  python3 -m venv .venv
fi

.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt || die "pip install failed"
log "Dependencies installed"

# ── 4. Run DB migrations if alembic is present ───────────────
if [ -f "alembic.ini" ]; then
  log "Running database migrations..."
  .venv/bin/alembic upgrade head || die "DB migration failed"
  log "Migrations complete"
fi

# ── 5. Graceful service restart ───────────────────────────────
log "Restarting systemd service: ${SERVICE}..."

# Reload systemd in case the unit file changed
sudo systemctl daemon-reload

# Restart — systemd sends SIGTERM; uvicorn drains in-flight requests
# KillMode=mixed + TimeoutStopSec in the unit file ensures graceful drain
sudo systemctl restart "$SERVICE" || die "systemctl restart failed"
log "Service restart issued"

# Give systemd a moment to actually start the process
sleep 3

# Confirm systemd reports the service as active
if ! sudo systemctl is-active --quiet "$SERVICE"; then
  log "Service failed to start — checking journal..."
  sudo journalctl -u "$SERVICE" -n 30 --no-pager | tee -a "$LOG_FILE"
  rollback
fi

# ── 6. Health check ───────────────────────────────────────────
if ! health_check; then
  log "Health check failed after deploy — triggering rollback..."
  rollback
fi

# ── 7. Done ───────────────────────────────────────────────────
log "=========================================="
log "  DEPLOYMENT SUCCESSFUL"
log "  Commit : ${NEW_COMMIT}"
log "  Service: ${SERVICE} is active and healthy"
log "=========================================="
