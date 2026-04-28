#!/usr/bin/env python3
"""
Gemma ACP Agent v1.1
ACP (Agent Client Protocol) wrapper for Gemma models via Google AI Studio.

Features:
  - Gemma 4 model selection in the UI
  - Web search via DuckDuckGo (no API key required)
  - Vault file access: list, read, write, search Obsidian notes

Usage:
  python3 ~/bin/gemma-acp.py

Environment variables (set in Obsidian Agent Client plugin settings):
  GOOGLE_API_KEY         Required. Your Google AI Studio API key.
  GEMMA_MODEL            Optional. Default model. Default: gemma-4-31b-it
  GEMMA_SYSTEM_PROMPT    Optional. Override the default system prompt.
  GEMMA_WEB_SEARCH       Optional. Set to 'false' to disable web search. Default: true

Obsidian Agent Client configuration (Custom Agent):
  Command: python3
  Args:    /Users/alice/bin/gemma-acp.py  (or the path in your plugin's scripts/)
  Env:     GOOGLE_API_KEY = AIza-xxxx
"""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

PROTOCOL_VERSION  = 1
API_KEY           = os.environ.get("GOOGLE_API_KEY", "")
DEFAULT_MODEL     = os.environ.get("GEMMA_MODEL", "gemma-4-31b-it")
BASE_URL          = "https://generativelanguage.googleapis.com/v1beta/openai/"
SYSTEM_PROMPT     = os.environ.get(
    "GEMMA_SYSTEM_PROMPT",
    "You are a helpful assistant with access to the Obsidian vault and the internet.\n"
    "Vault tools: list_vault_files, read_vault_file, write_vault_file, search_vault.\n"
    "Internet tool: web_search (use for current events, news, or up-to-date facts).\n"
    "Always use vault tools when the user refers to their notes or asks you to modify files.",
)
ENABLE_WEB_SEARCH = os.environ.get("GEMMA_WEB_SEARCH", "true").lower() != "false"
MAX_TOOL_ROUNDS   = 10

# ── Model registry ─────────────────────────────────────────────────────────────

MODEL_OPTIONS = [
    {
        "group": "Gemma 4",
        "name":  "Gemma 4",
        "options": [
            {
                "value":       "gemma-4-31b-it",
                "name":        "Gemma 4 31B",
                "description": "31B 参数 · Google AI Studio",
            },
        ],
    },
]


def build_config_options(current_model: str) -> list:
    return [
        {
            "id":           "model",
            "name":         "Model",
            "category":     "model",
            "type":         "select",
            "currentValue": current_model,
            "options":      MODEL_OPTIONS,
        }
    ]


# ── Tool definitions ───────────────────────────────────────────────────────────

VAULT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name":        "list_vault_files",
            "description": (
                "List files inside the Obsidian vault. "
                "Use to explore the vault structure before reading notes."
            ),
            "parameters": {
                "type":       "object",
                "properties": {
                    "directory": {
                        "type":        "string",
                        "description": "Subdirectory relative to vault root. Omit to list the entire vault.",
                    },
                    "extension": {
                        "type":        "string",
                        "description": "Filter by file extension, e.g. '.md', '.py'. Omit for all files.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "read_vault_file",
            "description": "Read the full text content of a file in the Obsidian vault.",
            "parameters": {
                "type":       "object",
                "properties": {
                    "path": {
                        "type":        "string",
                        "description": "File path relative to vault root, e.g. '档案/数学档案/note.md'.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "write_vault_file",
            "description": (
                "Create or completely overwrite a file in the Obsidian vault. "
                "Creates parent directories automatically."
            ),
            "parameters": {
                "type":       "object",
                "properties": {
                    "path": {
                        "type":        "string",
                        "description": "File path relative to vault root.",
                    },
                    "content": {
                        "type":        "string",
                        "description": "Complete file content to write (replaces existing content).",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "search_vault",
            "description": (
                "Search for text content inside vault Markdown files. "
                "Returns matching lines with file path and line number."
            ),
            "parameters": {
                "type":       "object",
                "properties": {
                    "query": {
                        "type":        "string",
                        "description": "Text or keyword to search for (case-insensitive).",
                    },
                    "directory": {
                        "type":        "string",
                        "description": "Subdirectory to limit the search. Omit to search entire vault.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

WEB_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name":        "web_search",
            "description": (
                "Search the internet for current information, news, or facts. "
                "Use when you need up-to-date data not available in your training."
            ),
            "parameters": {
                "type":       "object",
                "properties": {
                    "query": {
                        "type":        "string",
                        "description": "Search query string.",
                    }
                },
                "required": ["query"],
            },
        },
    }
]

# ── State ─────────────────────────────────────────────────────────────────────

sessions:       dict[str, list[dict]] = {}
session_models: dict[str, str]        = {}
session_cwds:   dict[str, str]        = {}
cancel_events:  dict[str, asyncio.Event] = {}

# ── Wire I/O ──────────────────────────────────────────────────────────────────

def _write(obj: dict) -> None:
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

# ── Vault helpers ─────────────────────────────────────────────────────────────

_SKIP = {".obsidian", ".git", "node_modules", "__pycache__", ".trash", ".DS_Store"}


def _safe_path(cwd: str, rel: str) -> Path | None:
    vault = Path(cwd).resolve()
    p = (vault / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    try:
        p.relative_to(vault)
        return p
    except ValueError:
        return None


def do_list_vault_files(cwd: str, directory: str = "", extension: str = "") -> str:
    root = _safe_path(cwd, directory) if directory else Path(cwd).resolve()
    if root is None:
        return f"Error: '{directory}' is outside the vault."
    if not root.is_dir():
        return f"Error: '{directory}' is not a directory."

    ext_filter = ("." + extension.lstrip(".")).lower() if extension else ""
    files: list[str] = []
    for p in sorted(root.rglob("*")):
        if any(skip in p.parts for skip in _SKIP):
            continue
        if not p.is_file():
            continue
        if ext_filter and p.suffix.lower() != ext_filter:
            continue
        files.append(str(p.relative_to(cwd)))
        if len(files) >= 300:
            files.append("… (output truncated at 300 entries)")
            break

    return "\n".join(files) if files else "No files found."


def do_read_vault_file(cwd: str, path: str) -> str:
    p = _safe_path(cwd, path)
    if p is None:
        return "Error: path is outside the vault."
    if not p.exists():
        return f"Error: file not found — {path}"
    try:
        return p.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error reading file: {exc}"


def do_write_vault_file(cwd: str, path: str, content: str) -> str:
    p = _safe_path(cwd, path)
    if p is None:
        return "Error: path is outside the vault."
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: wrote {path}"
    except Exception as exc:
        return f"Error writing file: {exc}"


def do_search_vault(cwd: str, query: str, directory: str = "") -> str:
    root = _safe_path(cwd, directory) if directory else Path(cwd).resolve()
    if root is None:
        return f"Error: '{directory}' is outside the vault."

    hits: list[str] = []
    q = query.lower()
    for p in sorted(root.rglob("*.md")):
        if any(skip in p.parts for skip in _SKIP):
            continue
        try:
            for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if q in line.lower():
                    hits.append(f"{p.relative_to(cwd)}:{i}: {line.strip()}")
                    if len(hits) >= 100:
                        break
        except Exception:
            pass
        if len(hits) >= 100:
            break

    return "\n".join(hits) if hits else f"No matches found for '{query}'."


# ── Web search ─────────────────────────────────────────────────────────────────

async def do_web_search(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "Error: `duckduckgo_search` not installed. Run: pip3 install duckduckgo_search"
    try:
        loop = asyncio.get_event_loop()
        def _search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=5))
        results = await loop.run_in_executor(None, _search)
        if not results:
            return "No results found."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. {r.get('title', '')}\n"
                f"   {r.get('href', '')}\n"
                f"   {r.get('body', '')}"
            )
        return "\n\n".join(lines)
    except Exception as exc:
        return f"Search error: {exc}"


# ── Tool dispatcher ────────────────────────────────────────────────────────────

async def execute_tool(name: str, args: dict, session_id: str) -> str:
    cwd = session_cwds.get(session_id, str(Path.home()))

    if name == "web_search":
        q = args.get("query", "")
        send_chunk(session_id, f"\n\n🔍 **Searching:** {q}\n\n")
        return await do_web_search(q)

    if name == "list_vault_files":
        directory = args.get("directory", "")
        extension = args.get("extension", "")
        label = f" in {directory}" if directory else ""
        send_chunk(session_id, f"\n\n📁 **Listing vault files{label}...**\n\n")
        return do_list_vault_files(cwd, directory, extension)

    if name == "read_vault_file":
        path = args.get("path", "")
        send_chunk(session_id, f"\n\n📄 **Reading:** {path}\n\n")
        return do_read_vault_file(cwd, path)

    if name == "write_vault_file":
        path = args.get("path", "")
        content = args.get("content", "")
        send_chunk(session_id, f"\n\n✏️ **Writing:** {path}\n\n")
        return do_write_vault_file(cwd, path, content)

    if name == "search_vault":
        q = args.get("query", "")
        directory = args.get("directory", "")
        label = f" in {directory}" if directory else ""
        send_chunk(session_id, f"\n\n🔎 **Searching vault{label}:** {q}\n\n")
        return do_search_vault(cwd, q, directory)

    return f"Unknown tool: {name}"


# ── Prompt content extraction ─────────────────────────────────────────────────

def extract_text(prompt: list) -> str:
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
    if not API_KEY:
        send_chunk(session_id, "Error: GOOGLE_API_KEY is not set.")
        send_response(req_id, {"stopReason": "end_turn"})
        return

    try:
        from openai import AsyncOpenAI
    except ImportError:
        send_chunk(session_id, "Error: `openai` not installed. Run: pip3 install openai")
        send_response(req_id, {"stopReason": "end_turn"})
        return

    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    model_value = session_models.get(session_id, DEFAULT_MODEL)
    messages    = sessions[session_id]
    user_text   = extract_text(prompt)
    if user_text:
        messages.append({"role": "user", "content": user_text})

    cancel_event = asyncio.Event()
    cancel_events[session_id] = cancel_event

    tools: list[dict] = list(VAULT_TOOLS)
    if ENABLE_WEB_SEARCH:
        tools.extend(WEB_SEARCH_TOOLS)

    final_content = ""
    cancelled     = False
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            if cancel_event.is_set():
                cancelled = True
                break

            create_kwargs: dict = {
                "model":    model_value,
                "messages": messages,
                "stream":   True,
                "tools":    tools,
                "tool_choice": "auto",
            }

            stream = await client.chat.completions.create(**create_kwargs)

            round_content    = ""
            tool_calls_buf: dict[int, dict] = {}

            async for chunk in stream:
                if cancel_event.is_set():
                    cancelled = True
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    round_content += delta.content
                    send_chunk(session_id, delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_buf:
                            tool_calls_buf[idx] = {"id": "", "name": "", "arguments": ""}
                        buf = tool_calls_buf[idx]
                        if tc.id:
                            buf["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                buf["name"] += tc.function.name
                            if tc.function.arguments:
                                buf["arguments"] += tc.function.arguments

            if cancelled:
                break

            if not tool_calls_buf:
                final_content = round_content
                break

            assistant_turn = {
                "role":       "assistant",
                "content":    round_content or None,
                "tool_calls": [
                    {
                        "id":       tool_calls_buf[idx]["id"],
                        "type":     "function",
                        "function": {
                            "name":      tool_calls_buf[idx]["name"],
                            "arguments": tool_calls_buf[idx]["arguments"],
                        },
                    }
                    for idx in sorted(tool_calls_buf)
                ],
            }
            messages.append(assistant_turn)

            for idx in sorted(tool_calls_buf):
                buf = tool_calls_buf[idx]
                try:
                    args = json.loads(buf["arguments"])
                except (json.JSONDecodeError, ValueError):
                    args = {}
                result = await execute_tool(buf["name"], args, session_id)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": buf["id"],
                    "content":      result,
                })

    except asyncio.CancelledError:
        cancelled = True
    except Exception as exc:
        send_chunk(session_id, f"\n\nError: {exc}")
    finally:
        cancel_events.pop(session_id, None)

    if not cancelled and final_content:
        messages.append({"role": "assistant", "content": final_content})

    send_response(req_id, {"stopReason": "cancelled" if cancelled else "end_turn"})


# ── Main dispatch loop ────────────────────────────────────────────────────────

async def main() -> None:
    loop = asyncio.get_event_loop()
    debug_log = Path("/tmp/gemma-acp-debug.log")
    with debug_log.open("a", encoding="utf-8") as f:
        f.write(f"\n--- Starting session {uuid.uuid4().hex} ---\n")
        f.flush()

    while True:
        raw_bytes = await loop.run_in_executor(None, sys.stdin.buffer.readline)
        if not raw_bytes:
            break

        line = raw_bytes.decode("utf-8")
        with debug_log.open("a", encoding="utf-8") as f:
            f.write(f"RECV: {line.strip()}\n")
            f.flush()

        if not line.strip():
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method: str  = msg.get("method", "")
        params: dict = msg.get("params") or {}
        req_id       = msg.get("id")

        if method == "initialize":
            send_response(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "agentCapabilities": {"loadSession": False},
                "agentInfo": {
                    "name":    "gemma-acp",
                    "title":   f"Gemma ({DEFAULT_MODEL})",
                    "version": "1.0.0",
                },
            })

        elif method == "session/new":
            sid = uuid.uuid4().hex
            cwd = params.get("cwd", str(Path.home()))
            sessions[sid]       = [{"role": "system", "content": SYSTEM_PROMPT}]
            session_models[sid] = DEFAULT_MODEL
            session_cwds[sid]   = cwd
            send_response(req_id, {
                "sessionId":     sid,
                "configOptions": build_config_options(DEFAULT_MODEL),
            })

        elif method == "authenticate":
            send_response(req_id, {})

        elif method == "session/set_config_option":
            sid       = params.get("sessionId", "")
            config_id = params.get("configId", "")
            value     = params.get("value", "")
            if config_id == "model" and sid:
                session_models[sid] = value
            send_response(req_id, {
                "configOptions": build_config_options(
                    session_models.get(sid, DEFAULT_MODEL)
                )
            })

        elif method == "session/prompt":
            sid    = params.get("sessionId", "")
            prompt = params.get("prompt", [])
            if sid in cancel_events:
                cancel_events[sid].set()
            asyncio.ensure_future(handle_prompt(req_id, sid, prompt))

        elif method == "session/cancel":
            sid = params.get("sessionId", "")
            if sid in cancel_events:
                cancel_events[sid].set()

        elif req_id is not None:
            send_error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    asyncio.run(main())
