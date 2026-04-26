#!/usr/bin/env python3
"""
DeepSeek ACP Agent v1.0
Minimal ACP (Agent Client Protocol) wrapper for DeepSeek API.

Usage:
  python3 ~/bin/deepseek-acp.py

Environment variables (set in Obsidian Agent Client plugin settings):
  DEEPSEEK_API_KEY         Required. Your DeepSeek API key.
  DEEPSEEK_MODEL           Optional. Default: deepseek-chat
  DEEPSEEK_BASE_URL        Optional. Default: https://api.deepseek.com
  DEEPSEEK_SYSTEM_PROMPT   Optional. System prompt for the assistant.

Obsidian Agent Client configuration (Custom Agent):
  Command: python3
  Args:    /Users/alice/bin/deepseek-acp.py
  Env:     DEEPSEEK_API_KEY = sk-xxxx
"""

import asyncio
import json
import os
import sys
import uuid

# ── Configuration ─────────────────────────────────────────────────────────────

PROTOCOL_VERSION = 1
API_KEY      = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL        = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
BASE_URL     = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
SYSTEM_PROMPT = os.environ.get("DEEPSEEK_SYSTEM_PROMPT", "You are a helpful assistant.")

# ── State ─────────────────────────────────────────────────────────────────────

# sessionId -> [{"role": "system"|"user"|"assistant", "content": str}]
sessions: dict[str, list[dict]] = {}

# sessionId -> asyncio.Event  (set to abort in-flight streaming)
cancel_events: dict[str, asyncio.Event] = {}

# ── Wire I/O ──────────────────────────────────────────────────────────────────

def _write(obj: dict) -> None:
    """Write one JSON-RPC line to stdout (ndjson frame)."""
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
    sys.stdout.buffer.flush()

def send_response(req_id, result: dict) -> None:
    _write({"jsonrpc": "2.0", "id": req_id, "result": result})

def send_error(req_id, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

def send_notification(method: str, params: dict) -> None:
    _write({"jsonrpc": "2.0", "method": method, "params": params})

def send_chunk(session_id: str, text: str) -> None:
    send_notification("session/update", {
        "sessionId": session_id,
        "update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": text},
        },
    })

# ── Prompt content extraction ─────────────────────────────────────────────────

def extract_text(prompt: list) -> str:
    """Flatten ACP prompt content blocks into a single string."""
    parts: list[str] = []
    for block in prompt:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = block.get("text", "")
            if t:
                parts.append(t)
        elif btype == "resource":
            res  = block.get("resource", {})
            uri  = res.get("uri", "")
            text = res.get("text", "")
            if text:
                parts.append(f"[File: {uri}]\n{text}")
    return "\n".join(parts)

# ── Prompt handler ────────────────────────────────────────────────────────────

async def handle_prompt(req_id, session_id: str, prompt: list) -> None:
    """Stream a DeepSeek response and relay chunks as ACP session updates."""

    # ── Pre-flight checks ──────────────────────────────────────────────────
    if not API_KEY:
        send_chunk(session_id, "Error: DEEPSEEK_API_KEY is not set.")
        send_response(req_id, {"stopReason": "end_turn"})
        return

    try:
        from openai import AsyncOpenAI
    except ImportError:
        send_chunk(session_id, "Error: `openai` package not installed. Run: pip3 install openai")
        send_response(req_id, {"stopReason": "end_turn"})
        return

    # ── Build message history ──────────────────────────────────────────────
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    messages = sessions[session_id]
    user_text = extract_text(prompt)
    if user_text:
        messages.append({"role": "user", "content": user_text})

    # ── Register cancellation handle ───────────────────────────────────────
    cancel_event = asyncio.Event()
    cancel_events[session_id] = cancel_event

    full_response = ""
    cancelled = False

    try:
        client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
        stream = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            if cancel_event.is_set():
                cancelled = True
                break
            if chunk.choices:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full_response += delta
                    send_chunk(session_id, delta)

    except asyncio.CancelledError:
        cancelled = True
    except Exception as exc:
        send_chunk(session_id, f"\n\nError: {exc}")
    finally:
        cancel_events.pop(session_id, None)

    if cancelled:
        send_response(req_id, {"stopReason": "cancelled"})
    else:
        if full_response:
            messages.append({"role": "assistant", "content": full_response})
        send_response(req_id, {"stopReason": "end_turn"})

# ── Main dispatch loop ────────────────────────────────────────────────────────

async def main() -> None:
    loop = asyncio.get_event_loop()

    while True:
        # Blocking stdin read — yields to event loop so prompt tasks can run
        raw = await loop.run_in_executor(None, sys.stdin.readline)
        if not raw:
            break

        line = raw.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method: str  = msg.get("method", "")
        params: dict = msg.get("params") or {}
        req_id       = msg.get("id")  # None for notifications

        if method == "initialize":
            send_response(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "agentCapabilities": {"loadSession": False},
                "agentInfo": {
                    "name":    "deepseek-acp",
                    "title":   f"DeepSeek ({MODEL})",
                    "version": "1.0.0",
                },
            })

        elif method == "session/new":
            sid = uuid.uuid4().hex
            sessions[sid] = [{"role": "system", "content": SYSTEM_PROMPT}]
            send_response(req_id, {"sessionId": sid})

        elif method == "authenticate":
            send_response(req_id, {})

        elif method == "session/prompt":
            sid    = params.get("sessionId", "")
            prompt = params.get("prompt", [])
            # Abort any previous in-flight stream for this session
            if sid in cancel_events:
                cancel_events[sid].set()
            asyncio.ensure_future(handle_prompt(req_id, sid, prompt))

        elif method == "session/cancel":
            # Notification — no response expected
            sid = params.get("sessionId", "")
            if sid in cancel_events:
                cancel_events[sid].set()

        elif req_id is not None:
            send_error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    asyncio.run(main())
