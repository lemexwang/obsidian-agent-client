#!/bin/bash
# DeepSeek Claude CLI — Lemex Vault launcher
# Starts the Anthropic→DeepSeek proxy and launches claude with DeepSeek.
#
# API key is auto-loaded from .claude/.deepseek_env if present.
# Override with DEEPSEEK_API_KEY env var.
#
# Usage:
#   .claude/scripts/deepseek4.sh                  # auto-load key from .deepseek_env
#   .claude/scripts/deepseek4.sh -c               # resume last session
#   .claude/scripts/deepseek4.sh -p "prompt"      # non-interactive

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROXY_PORT="${DEEPSEEK_PROXY_PORT:-14002}"
PROXY_SCRIPT="/Users/alice/bin/deepseek-anthr-proxy.py"
DS_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro}"
DS_HAIKU="${DEEPSEEK_HAIKU:-deepseek-v4-flash}"

# ── Load API key ─────────────────────────────────────────────────────────────

if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -f "$VAULT_ROOT/.claude/.deepseek_env" ]; then
  source "$VAULT_ROOT/.claude/.deepseek_env"
fi

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "ERROR: DEEPSEEK_API_KEY is not set." >&2
  echo "Set it via: export DEEPSEEK_API_KEY=your-key" >&2
  echo "Or create:  .claude/.deepseek_env with DEEPSEEK_API_KEY=your-key" >&2
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
  echo "→ Starting DeepSeek proxy on port ${PROXY_PORT}..."
  DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  PROXY_PORT="$PROXY_PORT" \
  python3 "$PROXY_SCRIPT" > /tmp/deepseek-proxy.log 2>&1 &
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
    echo "ERROR: Proxy failed to start. Check /tmp/deepseek-proxy.log" >&2
    cat /tmp/deepseek-proxy.log >&2
    exit 1
  fi
fi

# ── Launch Claude CLI with DeepSeek ─────────────────────────────────────────────
# NOTE: proxy is NOT killed on exit — it is a shared daemon across vaults.

cd "$VAULT_ROOT"

export ANTHROPIC_BASE_URL="http://localhost:${PROXY_PORT}"
export ANTHROPIC_API_KEY="dummy-key"
export ANTHROPIC_MODEL="$DS_MODEL"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$DS_MODEL"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$DS_MODEL"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$DS_HAIKU"
export CLAUDE_CODE_SUBAGENT_MODEL="$DS_MODEL"
export CLAUDE_CODE_ENABLE_WEB_SEARCH="true"
export CLAUDE_CODE_ENABLE_WEB_FETCH="true"

echo "→ Launching Claude CLI with DeepSeek (${DS_MODEL})..."
echo ""

claude "$@"
