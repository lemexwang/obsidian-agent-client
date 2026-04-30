#!/bin/bash
# Gemma 4 Claude CLI — Lemex Vault launcher
# Starts the Anthropic→Google proxy and launches claude with Gemma 4.
#
# API key is auto-loaded from .claude/.gemma_env if present.
# Override with GOOGLE_API_KEY env var.
#
# Usage:
#   .claude/scripts/gemma4.sh                  # auto-load key from .gemma_env
#   .claude/scripts/gemma4.sh -c               # resume last session
#   .claude/scripts/gemma4.sh -p "prompt"      # non-interactive

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROXY_PORT="${GEMMA_PROXY_PORT:-14001}"
PROXY_SCRIPT="/Users/alice/bin/gemma-anthr-proxy.py"
GEMMA_MODEL="${GEMMA_MODEL:-gemma-4-31b-it}"

# ── Load API key ─────────────────────────────────────────────────────────────

if [ -z "${GOOGLE_API_KEY:-}" ] && [ -f "$VAULT_ROOT/.claude/.gemma_env" ]; then
  source "$VAULT_ROOT/.claude/.gemma_env"
fi

if [ -z "${GOOGLE_API_KEY:-}" ]; then
  echo "ERROR: GOOGLE_API_KEY is not set." >&2
  echo "Set it via: export GOOGLE_API_KEY=your-key" >&2
  echo "Or create:  .claude/.gemma_env with GOOGLE_API_KEY=your-key" >&2
  exit 1
fi

if [ ! -f "$PROXY_SCRIPT" ]; then
  echo "ERROR: Proxy script not found: $PROXY_SCRIPT" >&2
  exit 1
fi

# ── Start proxy (if not already running) ──────────────────────────────────────

STALE_PID=$(lsof -ti ":${PROXY_PORT}" 2>/dev/null || true)
PROXY_PID=""

if [ -n "$STALE_PID" ]; then
  echo "→ Proxy already running on port ${PROXY_PORT} (PID $STALE_PID), reusing..."
  PROXY_PID="$STALE_PID"
else
  echo "→ Starting Gemma proxy on port ${PROXY_PORT}..."
  GOOGLE_API_KEY="$GOOGLE_API_KEY" \
  PROXY_PORT="$PROXY_PORT" \
  GEMMA_MODEL="$GEMMA_MODEL" \
  python3 "$PROXY_SCRIPT" > /tmp/gemma-proxy.log 2>&1 &
  PROXY_PID=$!

  # Wait for proxy to be ready
  for i in $(seq 1 20); do
    if curl -sf "http://localhost:${PROXY_PORT}/health" > /dev/null 2>&1; then
      echo "→ Proxy ready (PID $PROXY_PID)"
      break
    fi
    sleep 0.5
  done

  if ! curl -sf "http://localhost:${PROXY_PORT}/health" > /dev/null 2>&1; then
    echo "ERROR: Proxy failed to start. Check /tmp/gemma-proxy.log" >&2
    cat /tmp/gemma-proxy.log >&2
    exit 1
  fi
fi

# ── Launch Claude CLI with Gemma 4 ─────────────────────────────────────────────
# NOTE: proxy is NOT killed on exit — it is a shared daemon across vaults.

cd "$VAULT_ROOT"

export ANTHROPIC_BASE_URL="http://localhost:${PROXY_PORT}"
export ANTHROPIC_API_KEY="dummy-key"
export ANTHROPIC_MODEL="$GEMMA_MODEL"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$GEMMA_MODEL"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$GEMMA_MODEL"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$GEMMA_MODEL"
export CLAUDE_CODE_SUBAGENT_MODEL="$GEMMA_MODEL"
export CLAUDE_CODE_ENABLE_WEB_SEARCH="true"
export CLAUDE_CODE_ENABLE_WEB_FETCH="true"

echo "→ Launching Claude CLI with Gemma 4 (${GEMMA_MODEL})..."
echo ""

claude --dangerously-skip-permissions "$@"
