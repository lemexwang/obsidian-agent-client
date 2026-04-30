#!/usr/bin/env python3
"""
DeepSeek ACP Agent v1.3
ACP (Agent Client Protocol) wrapper for DeepSeek API.

Features:
  - Full DeepSeek V4 model selection in the UI (V4 Pro / V4 Flash, normal + thinking)
  - Legacy models kept for backward compatibility (deprecated Jul 2026)
  - Web search via DuckDuckGo (no API key required)
  - Vault file access: list, read, write, search Obsidian notes

Usage:
  python3 ~/bin/deepseek-acp.py

Environment variables (set in Obsidian Agent Client plugin settings):
  DEEPSEEK_API_KEY         Required. Your DeepSeek API key.
  DEEPSEEK_MODEL           Optional. Default model. Default: deepseek-v4-flash
  DEEPSEEK_BASE_URL        Optional. Default: https://api.deepseek.com
  DEEPSEEK_SYSTEM_PROMPT   Optional. Override the default system prompt.
  DEEPSEEK_WEB_SEARCH      Optional. Set to 'false' to disable web search. Default: true

Obsidian Agent Client configuration (Custom Agent):
  Command: python3
  Args:    /Users/alice/bin/deepseek-acp.py  (or the path in your plugin's scripts/)
  Env:     DEEPSEEK_API_KEY = sk-xxxx
"""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

PROTOCOL_VERSION  = 1
API_KEY           = os.environ.get("DEEPSEEK_API_KEY", "")
DEFAULT_MODEL     = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
BASE_URL          = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
SYSTEM_PROMPT     = os.environ.get(
    "DEEPSEEK_SYSTEM_PROMPT",
    "You are a helpful assistant with access to the Obsidian vault and the internet.\n"
    "Vault tools: list_vault_files, read_vault_file, write_vault_file, search_vault.\n"
    "Internet tool: web_search (use for current events, news, or up-to-date facts).\n"
    "Always use vault tools when the user refers to their notes or asks you to modify files.",
)
ENABLE_WEB_SEARCH = os.environ.get("DEEPSEEK_WEB_SEARCH", "true").lower() != "false"
MAX_TOOL_ROUNDS   = 10   # max consecutive tool-call rounds per prompt

# ── Model registry ─────────────────────────────────────────────────────────────

MODEL_OPTIONS = [
    {
        "group": "DeepSeek V4",
        "name":  "DeepSeek V4",
        "options": [
            {
                "value":       "deepseek-v4-flash",
                "name":        "V4 Flash",
                "description": "快速 · 经济 · 1M 上下文",
            },
            {
                "value":       "deepseek-v4-flash:thinking",
                "name":        "V4 Flash (Thinking)",
                "description": "推理模式 · 适合数学、代码、逻辑",
            },
            {
                "value":       "deepseek-v4-pro",
                "name":        "V4 Pro",
                "description": "旗舰模型 · 1M 上下文",
            },
            {
                "value":       "deepseek-v4-pro:thinking",
                "name":        "V4 Pro (Thinking)",
                "description": "旗舰推理模式",
            },
        ],
    },
    {
        "group": "Legacy（将于 2026.7.24 弃用）",
        "name":  "Legacy",
        "options": [
            {
                "value":       "deepseek-chat",
                "name":        "deepseek-chat",
                "description": "→ V4 Flash（非推理）",
            },
            {
                "value":       "deepseek-reasoner",
                "name":        "deepseek-reasoner",
                "description": "→ V4 Flash（推理）",
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


def resolve_model(value: str) -> tuple[str, dict]:
    """Returns (api_model_id, extra_api_kwargs).
    Thinking variants pass enable_thinking=True in extra_body.
    """
    if value.endswith(":thinking"):
        base = value[:-9]
        return base, {"extra_body": {"enable_thinking": True}}
    return value, {}


def model_supports_tools(value: str) -> bool:
    """Thinking mode and deepseek-reasoner do not support function calling."""
    return not (value.endswith(":thinking") or value == "deepseek-reasoner")


def model_supports_vision(value: str) -> bool:
    """Thinking mode and deepseek-reasoner do not support image input."""
    return not (value.endswith(":thinking") or value == "deepseek-reasoner")


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
                "Use when you need up-to-date data not available in your training. "
                "Returns titles, URLs, and short snippets. Use fetch_webpage to read full content."
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
    },
    {
        "type": "function",
        "function": {
            "name":        "fetch_webpage",
            "description": (
                "Fetch the full text content of a web page by URL. "
                "Use after web_search to read the complete article or page."
            ),
            "parameters": {
                "type":       "object",
                "properties": {
                    "url": {
                        "type":        "string",
                        "description": "The full URL of the web page to fetch.",
                    }
                },
                "required": ["url"],
            },
        },
    },
]

# ── State ─────────────────────────────────────────────────────────────────────

sessions:      dict[str, list[dict]] = {}   # sessionId -> message history
session_models: dict[str, str]       = {}   # sessionId -> selected model value
session_cwds:   dict[str, str]       = {}   # sessionId -> vault path (cwd)
cancel_events:  dict[str, asyncio.Event] = {}

# ── Wire I/O ──────────────────────────────────────────────────────────────────

def _write(obj: dict) -> None:
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
    sys.stdout.buffer.flush()

async def get_balance() -> dict:
    """Fetch account balance from DeepSeek API."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}

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

def send_thought_chunk(session_id: str, text: str) -> None:
    send_notification("session/update", {
        "sessionId": session_id,
        "update": {
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": text},
        },
    })

# ── Vault helpers ─────────────────────────────────────────────────────────────

_SKIP = {".obsidian", ".git", "node_modules", "__pycache__", ".trash", ".DS_Store"}


def _safe_path(cwd: str, rel: str) -> Path | None:
    """Resolve rel inside the vault; returns None if it escapes the vault root."""
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
                return list(ddgs.text(query, max_results=10))
        results = await loop.run_in_executor(None, _search)
        if not results:
            return "No results found."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. {r.get('title', '')}\n"
                f"   URL: {r.get('href', '')}\n"
                f"   {r.get('body', '')}"
            )
        return "\n\n".join(lines)
    except Exception as exc:
        return f"Search error: {exc}"


async def do_fetch_webpage(url: str) -> str:
    try:
        import urllib.request
        import html.parser

        class _TextExtractor(html.parser.HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts: list[str] = []
                self._skip = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style", "nav", "footer", "head"):
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in ("script", "style", "nav", "footer", "head"):
                    self._skip = False
                if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"):
                    self.parts.append("\n")

            def handle_data(self, data):
                if not self._skip:
                    self.parts.append(data)

        loop = asyncio.get_event_loop()
        def _fetch():
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; DeepSeek-Agent/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                charset = "utf-8"
                ct = resp.headers.get_content_charset()
                if ct:
                    charset = ct
                return resp.read().decode(charset, errors="replace")

        html_text = await loop.run_in_executor(None, _fetch)
        parser = _TextExtractor()
        parser.feed(html_text)
        text = "".join(parser.parts)
        # Collapse whitespace
        import re
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = text.strip()
        # Limit to ~8000 chars to avoid context overflow
        if len(text) > 8000:
            text = text[:8000] + "\n\n… (truncated)"
        return text if text else "No readable text found on page."
    except Exception as exc:
        return f"Fetch error: {exc}"


# ── Tool dispatcher ────────────────────────────────────────────────────────────

async def execute_tool(name: str, args: dict, session_id: str) -> str:
    cwd = session_cwds.get(session_id, str(Path.home()))

    if name == "web_search":
        q = args.get("query", "")
        send_chunk(session_id, f"\n\n🔍 **Searching:** {q}\n\n")
        return await do_web_search(q)

    if name == "fetch_webpage":
        url = args.get("url", "")
        send_chunk(session_id, f"\n\n🌐 **Fetching:** {url}\n\n")
        return await do_fetch_webpage(url)

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

def build_user_content(prompt: list, allow_images: bool = True):
    """Convert ACP prompt blocks to OpenAI message content.

    Returns a plain str when there are no images (text-only models),
    or a list of content blocks when images are present.
    """
    text_parts: list[str] = []
    image_blocks: list[dict] = []

    for block in prompt:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = block.get("text", "")
            if t:
                text_parts.append(t)
        elif btype == "resource":
            res  = block.get("resource", {})
            uri  = res.get("uri", "")
            text = res.get("text", "")
            if text:
                text_parts.append(f"[File: {uri}]\n{text}")
        elif btype == "image" and allow_images:
            data      = block.get("data", "")
            mime_type = block.get("mimeType", "image/png")
            if data:
                image_blocks.append({
                    "type":      "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{data}"},
                })

    combined_text = "\n".join(text_parts)

    if not image_blocks:
        return combined_text

    # Build multimodal content list
    content: list[dict] = []
    if combined_text:
        content.append({"type": "text", "text": combined_text})
    content.extend(image_blocks)
    return content


# ── Prompt handler ────────────────────────────────────────────────────────────

async def handle_prompt(req_id, session_id: str, prompt: list) -> None:
    if not API_KEY:
        send_chunk(session_id, "Error: DEEPSEEK_API_KEY is not set.")
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

    model_value          = session_models.get(session_id, DEFAULT_MODEL)
    api_model, extra_kw  = resolve_model(model_value)
    use_tools            = model_supports_tools(model_value)
    use_vision           = model_supports_vision(model_value)

    messages = sessions[session_id]
    user_content = build_user_content(prompt, allow_images=use_vision)
    if user_content:
        messages.append({"role": "user", "content": user_content})

    cancel_event = asyncio.Event()
    cancel_events[session_id] = cancel_event

    # Build active tool list
    tools: list[dict] = list(VAULT_TOOLS)
    if ENABLE_WEB_SEARCH:
        tools.extend(WEB_SEARCH_TOOLS)

    final_content  = ""
    final_reasoning = ""
    cancelled      = False
    client        = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            if cancel_event.is_set():
                cancelled = True
                break

            create_kwargs: dict = {
                "model":    api_model,
                "messages": messages,
                "stream":   True,
                **extra_kw,
            }
            if use_tools and tools:
                create_kwargs["tools"]       = tools
                create_kwargs["tool_choice"] = "auto"

            stream = await client.chat.completions.create(**create_kwargs)

            round_content    = ""
            round_reasoning  = ""
            tool_calls_buf: dict[int, dict] = {}

            async for chunk in stream:
                if cancel_event.is_set():
                    cancelled = True
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                rc = getattr(delta, "reasoning_content", None)
                if rc is None:
                    rc = (getattr(delta, "model_extra", None) or {}).get("reasoning_content")
                if rc:
                    round_reasoning += rc
                    send_thought_chunk(session_id, rc)

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

            # No tool calls → final response
            if not tool_calls_buf:
                final_content   = round_content
                final_reasoning = round_reasoning
                break

            # Append assistant turn with tool_calls
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
            if round_reasoning:
                assistant_turn["reasoning_content"] = round_reasoning
            messages.append(assistant_turn)

            # Execute tools and append results
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

    if not cancelled and (final_content or final_reasoning):
        assistant_msg: dict = {"role": "assistant", "content": final_content or ""}
        # Thinking-mode turns MUST always include reasoning_content (even empty string),
        # otherwise DeepSeek rejects the next multi-turn request with a 400 error.
        if not model_supports_tools(model_value):
            assistant_msg["reasoning_content"] = final_reasoning
        elif final_reasoning:
            assistant_msg["reasoning_content"] = final_reasoning
        messages.append(assistant_msg)

    send_response(req_id, {"stopReason": "cancelled" if cancelled else "end_turn"})


# ── Main dispatch loop ────────────────────────────────────────────────────────

async def main() -> None:
    loop = asyncio.get_event_loop()
    debug_log = Path("/tmp/deepseek-acp-debug.log")
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
                "agentCapabilities": {
                    "loadSession":        False,
                    "promptCapabilities": {
                        "image": model_supports_vision(DEFAULT_MODEL),
                    },
                },
                "agentInfo": {
                    "name":    "deepseek-acp",
                    "title":   f"DeepSeek ({DEFAULT_MODEL})",
                    "version": "1.4.0",
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

        elif method == "session/get_balance":
            balance_info = await get_balance()
            send_response(req_id, balance_info)

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
