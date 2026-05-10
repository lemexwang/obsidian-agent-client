#!/usr/bin/env python3
"""
Minimal Anthropic Messages API → Google AI Studio proxy.
Receives Anthropic /v1/messages requests, translates to OpenAI /chat/completions,
calls Google's OpenAI-compatible endpoint, translates responses back.

Web search: executes via DuckDuckGo, then makes a SECOND call to Google with
real search results so the model synthesizes a proper answer instead of
dumping raw links.

Usage:
  GOOGLE_API_KEY=... PROXY_PORT=14001 python3 gemma-anthr-proxy.py
"""

import json
import os
import sys
import uuid
import time
import urllib.request
import urllib.error
import socketserver
from http.server import BaseHTTPRequestHandler
from datetime import datetime

from ddgs import DDGS

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
MODEL = os.environ.get("GEMMA_MODEL", "gemma-4-31b-it")
PORT = int(os.environ.get("PROXY_PORT", "14001"))
DEBUG = os.environ.get("PROXY_DEBUG", "0") == "1"
MAX_SEARCH_ROUNDS = 3  # prevent infinite loops

LOG_PATH = "/tmp/gemma-proxy-req.log"


def log(msg: str) -> None:
    ts = datetime.now().isoformat()
    with open(LOG_PATH, "a") as f:
        f.write(f"[{ts}] {msg}\n")
    if DEBUG:
        print(f"[proxy] {msg}", file=sys.stderr, flush=True)


# ── Web-search system prompt augmentation ────────────────────────────────────
WEB_SEARCH_REMINDER = (
    "\n\nIMPORTANT: You have access to web_search and web_fetch tools. "
    "Do NOT guess or use training data for questions about current events, "
    "weather, recent news, or real-time facts. Use web_search first."
)


# ── Web search execution ─────────────────────────────────────────────────────

def execute_web_search(query: str, max_results: int = 5) -> str:
    try:
        results = list(DDGS().text(query, max_results=max_results))
    except Exception as e:
        log(f"WEB_SEARCH ERROR: {e}")
        return f"Web search for '{query}' failed: {e}"

    if not results:
        return f"No results found for: {query}"

    lines = [f'Web search results for query: "{query}"\n']
    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        url = r.get("href", "")
        body = r.get("body", "")
        lines.append(f"{i}. [{title}]({url})")
        lines.append(f"   {body}\n")

    # Fetch top result page content for richer data (short timeout, cleaned)
    top_url = results[0].get("href", "")
    if top_url:
        try:
            req = urllib.request.Request(top_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=6) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            import re
            # Aggressive cleaning: remove scripts, styles, HTML tags, extra whitespace
            text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            # Collapse whitespace, keep only printable chars
            text = re.sub(r'[^\x20-\x7E\xA0-\xFF一-鿿　-〿＀-￯\n]', '', text)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 2000:
                text = text[:2000] + "..."
            if len(text) > 100:  # only append if we got meaningful content
                lines.append(f"\n--- Content from {top_url} ---\n{text}")
                log(f"WEB_SEARCH enriched: {top_url} → {len(text)} chars")
        except Exception as e:
            log(f"WEB_SEARCH fetch top URL failed ({type(e).__name__}): {e}")

    return "\n".join(lines)


def execute_web_fetch(url: str, max_chars: int = 3000) -> str:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; GemmaProxy/1.0)"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log(f"WEB_FETCH ERROR for {url}: {e}")
        return f"Failed to fetch {url}: {e}"

    import re
    text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "..."

    log(f"WEB_FETCH: {url} → {len(text)} chars")
    return f"Web fetch results for: {url}\n\n{text}"


# ── Format converters ────────────────────────────────────────────────────────

def tools_anthr_to_openai(tools):
    result = []
    for t in tools:
        t_type = t.get("type", "custom")
        if t_type.startswith("web_search") or t_type.startswith("web_fetch"):
            name = t_type.split("_")[0] + "_" + t_type.split("_")[1]
            result.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": t.get("description", f"Web {'search' if 'search' in name else 'fetch'} tool"),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {
                        "query" if "search" in name else "url": {
                            "type": "string",
                            "description": "Search query" if "search" in name else "URL to fetch"
                        }
                    }}),
                },
            })
        else:
            result.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
    return result


def messages_anthr_to_openai(messages):
    result = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")

        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue

        if role == "user":
            tool_results = [b for b in content if b.get("type") == "tool_result"]
            text_blocks  = [b for b in content if b.get("type") == "text"]
            if tool_results:
                for tr in tool_results:
                    tc = tr.get("content", "")
                    if isinstance(tc, list):
                        tc = " ".join(b.get("text", "") for b in tc if b.get("type") == "text")
                    result.append({"role": "tool", "tool_call_id": tr["tool_use_id"], "content": tc})
                if text_blocks:
                    text = " ".join(b.get("text", "") for b in text_blocks)
                    if text:
                        result.append({"role": "user", "content": text})
            else:
                parts = []
                for b in content:
                    btype = b.get("type")
                    if btype == "text":
                        t = b.get("text", "")
                        if t:
                            parts.append({"type": "text", "text": t})
                    elif btype == "image":
                        source = b.get("source", {})
                        src_type = source.get("type", "")
                        if src_type == "base64":
                            data = source.get("data", "")
                            media_type = source.get("media_type", "image/png")
                            parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{media_type};base64,{data}"},
                            })
                        elif src_type == "url":
                            url = source.get("url", "")
                            if url:
                                parts.append({"type": "image_url", "image_url": {"url": url}})
                if len(parts) == 1 and parts[0].get("type") == "text":
                    result.append({"role": "user", "content": parts[0]["text"]})
                elif parts:
                    result.append({"role": "user", "content": parts})

        elif role == "assistant":
            text_blocks     = [b for b in content if b.get("type") == "text"]
            tool_use_blocks = [b for b in content if b.get("type") == "tool_use"]
            text = " ".join(b.get("text", "") for b in text_blocks)
            if tool_use_blocks:
                tool_calls = [
                    {
                        "id": tu["id"],
                        "type": "function",
                        "function": {
                            "name": tu["name"],
                            "arguments": json.dumps(tu.get("input", {})),
                        },
                    }
                    for tu in tool_use_blocks
                ]
                result.append({"role": "assistant", "content": text or None, "tool_calls": tool_calls})
            else:
                result.append({"role": "assistant", "content": text})

    return result


# ── SSE event helpers ────────────────────────────────────────────────────────

def _sse_send(wfile, event, data):
    try:
        wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
        wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        raise


def _sse_stream_message(wfile, msg_id, model, text, tool_use_blocks):
    """Send a complete Anthropic SSE message to wfile."""
    _sse_send(wfile, "message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id, "type": "message", "role": "assistant",
            "content": [], "model": model,
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })
    _sse_send(wfile, "content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""},
    })
    _sse_send(wfile, "ping", {"type": "ping"})

    if text:
        _sse_send(wfile, "content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": text},
        })
    _sse_send(wfile, "content_block_stop", {"type": "content_block_stop", "index": 0})

    for blk_idx, (tc_id, tc_name, tc_args) in enumerate(tool_use_blocks, 1):
        _sse_send(wfile, "content_block_start", {
            "type": "content_block_start", "index": blk_idx,
            "content_block": {"type": "tool_use", "id": tc_id, "name": tc_name, "input": {}},
        })
        _sse_send(wfile, "content_block_delta", {
            "type": "content_block_delta", "index": blk_idx,
            "delta": {"type": "input_json_delta", "partial_json": tc_args},
        })
        _sse_send(wfile, "content_block_stop", {"type": "content_block_stop", "index": blk_idx})

    stop_reason = "tool_use" if tool_use_blocks else "end_turn"
    _sse_send(wfile, "message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": 0},
    })
    _sse_send(wfile, "message_stop", {"type": "message_stop"})


def _sse_stream_from_response(wfile, msg_id, resp):
    """Stream an OpenAI SSE response as Anthropic SSE. Handles one turn only."""
    send = lambda e, d: _sse_send(wfile, e, d)

    send("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id, "type": "message", "role": "assistant",
            "content": [], "model": MODEL,
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })
    send("content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""},
    })
    send("ping", {"type": "ping"})

    text_buf = []
    all_tc = []
    tc_to_blk = {}
    text_open = True
    next_blk = 1

    for raw in resp:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data: "):
            continue
        ds = line[6:]
        if ds == "[DONE]":
            break
        try:
            chunk = json.loads(ds)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices", [])
        if not choices:
            continue
        delta = choices[0].get("delta", {})
        finish = choices[0].get("finish_reason")

        txt = delta.get("content", "")
        if txt:
            txt = txt.replace("<thought>", "<think>").replace("</thought>", "</think>")
            text_buf.append(txt)

        for tc in delta.get("tool_calls", []):
            tc_idx = tc.get("index", 0)
            tc_func = tc.get("function") or {}
            tc_name = tc_func.get("name", "")
            tc_args = tc_func.get("arguments", "")
            if tc_idx not in tc_to_blk:
                tc_id = tc.get("id", f"toolu_{uuid.uuid4().hex[:8]}")
                tc_to_blk[tc_idx] = len(all_tc)
                all_tc.append((tc_idx, tc_id, tc_name, tc_args))
            else:
                idx = tc_to_blk[tc_idx]
                _, tid, tname, old_args = all_tc[idx]
                all_tc[idx] = (tc_idx, tid, tname, old_args + tc_args)

        if finish:
            buffered = "".join(text_buf)
            if buffered:
                send("content_block_delta", {
                    "type": "content_block_delta", "index": 0,
                    "delta": {"type": "text_delta", "text": buffered},
                })
            if text_open:
                send("content_block_stop", {"type": "content_block_stop", "index": 0})
                text_open = False

            for tc_idx, tc_id, tc_name, tc_args in all_tc:
                try:
                    json.loads(tc_args)
                except Exception:
                    pass
                blk = next_blk
                next_blk += 1
                send("content_block_start", {
                    "type": "content_block_start", "index": blk,
                    "content_block": {"type": "tool_use", "id": tc_id, "name": tc_name, "input": {}},
                })
                send("content_block_delta", {
                    "type": "content_block_delta", "index": blk,
                    "delta": {"type": "input_json_delta", "partial_json": tc_args},
                })
                send("content_block_stop", {"type": "content_block_stop", "index": blk})

            has_tools = len(all_tc) > 0
            send("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use" if has_tools else "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 0},
            })
            send("message_stop", {"type": "message_stop"})
            return [tc for tc in all_tc]  # return tool calls for potential multi-turn

    # fallback: no finish_reason
    buffered = "".join(text_buf)
    if buffered:
        send("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": buffered},
        })
    if text_open:
        send("content_block_stop", {"type": "content_block_stop", "index": 0})
    for tc_idx, tc_id, tc_name, tc_args in all_tc:
        blk = next_blk
        next_blk += 1
        send("content_block_start", {
            "type": "content_block_start", "index": blk,
            "content_block": {"type": "tool_use", "id": tc_id, "name": tc_name, "input": {}},
        })
        send("content_block_delta", {
            "type": "content_block_delta", "index": blk,
            "delta": {"type": "input_json_delta", "partial_json": tc_args},
        })
        send("content_block_stop", {"type": "content_block_stop", "index": blk})
    has_tools = len(all_tc) > 0
    send("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use" if has_tools else "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 0},
    })
    send("message_stop", {"type": "message_stop"})
    return [tc for tc in all_tc]


# ── Multi-turn web search ────────────────────────────────────────────────────

def _is_web_call(tc_name):
    return tc_name in ("web_search", "web_fetch", "WebSearch", "WebFetch")


def _run_web_search(tc_name, tc_args):
    try:
        args = json.loads(tc_args)
    except Exception:
        args = {}
    if tc_name in ("web_search", "WebSearch"):
        q = args.get("query", "").strip()
        if not q:
            log("WEB_SEARCH SKIPPED: empty query")
            return "Error: web_search requires a non-empty 'query' parameter."
        return execute_web_search(q)
    else:
        url = args.get("url", "").strip()
        if not url:
            return "Error: web_fetch requires a non-empty 'url' parameter."
        return execute_web_fetch(url)


def _parse_tool_calls(chunks):
    """Parse streaming OpenAI chunks into resolved tool calls list."""
    tc_to_blk = {}
    all_tc = []
    for chunk in chunks:
        choices = chunk.get("choices", [])
        if not choices:
            continue
        delta = choices[0].get("delta", {})
        for tc in delta.get("tool_calls", []):
            tc_idx = tc.get("index", 0)
            tc_func = tc.get("function") or {}
            tc_name = tc_func.get("name", "")
            tc_args = tc_func.get("arguments", "")
            if tc_idx not in tc_to_blk:
                tc_id = tc.get("id", f"toolu_{uuid.uuid4().hex[:8]}")
                tc_to_blk[tc_idx] = len(all_tc)
                all_tc.append((tc_idx, tc_id, tc_name, tc_args))
            else:
                idx = tc_to_blk[tc_idx]
                _, tid, tname, old_args = all_tc[idx]
                all_tc[idx] = (tc_idx, tid, tname, old_args + tc_args)
    return all_tc


def _collect_chunks(resp):
    """Read all streaming chunks from a response. Returns list of parsed JSON chunks."""
    chunks = []
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data: "):
            continue
        ds = line[6:]
        if ds == "[DONE]":
            break
        try:
            chunks.append(json.loads(ds))
        except json.JSONDecodeError:
            continue
    return chunks


def _execute_searches(tool_calls):
    """Execute web searches/fetches, return (results, tool_call_info)."""
    results = []
    for tc_idx, tc_id, tc_name, tc_args in tool_calls:
        result_text = _run_web_search(tc_name, tc_args)
        try:
            q = json.loads(tc_args).get("query", json.loads(tc_args).get("url", ""))
        except Exception:
            q = ""
        log(f"WEB_SEARCH: {tc_name}({q[:100]}) → {len(result_text)} chars")
        results.append((tc_id, tc_name, result_text))
    return results


def _make_google_request(messages, tools=None, stream=True):
    """Make a request to Google's OpenAI-compatible endpoint."""
    oai_req = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 4096,
        "stream": stream,
    }
    if tools:
        oai_req["tools"] = tools
        oai_req["tool_choice"] = "auto"
    return urllib.request.Request(
        f"{GOOGLE_BASE}/chat/completions",
        data=json.dumps(oai_req).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GOOGLE_API_KEY}",
        },
        method="POST",
    )


# ── Streaming handler with multi-turn ────────────────────────────────────────

def _extract_text(chunks):
    """Extract and concatenate text from streaming chunks."""
    text_buf = []
    for chunk in chunks:
        choices = chunk.get("choices", [])
        if not choices:
            continue
        delta = choices[0].get("delta", {})
        txt = delta.get("content", "")
        if txt:
            txt = txt.replace("<thought>", "<think>").replace("</thought>", "</think>")
            text_buf.append(txt)
    return "".join(text_buf)


def stream_openai_to_anthr(resp, msg_id, wfile, oai_messages, oai_tools=None):
    """Handle streaming response with recursive multi-turn web search.

    If the model calls web_search, we execute the search and make another
    call to Google with real results. Loops up to MAX_SEARCH_ROUNDS times.
    The intermediate responses are never sent to the client.
    """
    current_messages = list(oai_messages)

    for round_num in range(MAX_SEARCH_ROUNDS):
        chunks = _collect_chunks(resp)
        all_tc = _parse_tool_calls(chunks)

        web_calls = [(i, tid, tn, ta) for i, tid, tn, ta in all_tc if _is_web_call(tn)]
        other_calls = [(i, tid, tn, ta) for i, tid, tn, ta in all_tc if not _is_web_call(tn)]

        if not web_calls:
            # No web_search — stream this response to client
            buffered_text = _extract_text(chunks)
            tool_use_blocks = [(tid, tn, ta) for _, tid, tn, ta in other_calls]
            try:
                _sse_stream_message(wfile, msg_id, MODEL, buffered_text, tool_use_blocks)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        # Execute web searches
        search_results = _execute_searches(web_calls)

        # Build continuation messages
        cont_messages = list(current_messages)
        assistant_tc = [
            {"id": tid, "type": "function", "function": {"name": tn, "arguments": ta}}
            for _, tid, tn, ta in all_tc
        ]
        cont_messages.append({"role": "assistant", "content": None, "tool_calls": assistant_tc})
        for tc_id, tc_name, result_text in search_results:
            cont_messages.append({"role": "tool", "tool_call_id": tc_id, "content": result_text})

        current_messages = cont_messages  # carry forward for next round

        log(f"MULTI-TURN round {round_num + 1}: {len(cont_messages)} msgs → calling Google...")

        try:
            req2 = _make_google_request(cont_messages, tools=oai_tools, stream=True)
            resp = urllib.request.urlopen(req2, timeout=120)
            # Loop continues with new resp
        except Exception as e:
            log(f"MULTI-TURN stream ERROR round {round_num + 1}: {e}")
            # Fallback: send search results as text
            fallback_text = "\n\n".join(rt for _, _, rt in search_results)
            try:
                _sse_stream_message(wfile, msg_id, MODEL, fallback_text, [])
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

    # Exhausted all rounds — stream final response with whatever tool calls remain
    chunks = _collect_chunks(resp)
    all_tc = _parse_tool_calls(chunks)
    buffered_text = _extract_text(chunks)
    tool_use_blocks = [(tid, tn, ta) for _, tid, tn, ta in all_tc]
    try:
        _sse_stream_message(wfile, msg_id, MODEL, buffered_text, tool_use_blocks)
    except (BrokenPipeError, ConnectionResetError):
        pass


# ── HTTP Handler ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _health(self):
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self._health()

    def do_GET(self):
        self._health()

    def do_POST(self):
        if not self.path.startswith("/v1/messages"):
            self.send_error(404)
            return

        t0 = time.time()
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length) or b"{}")

        # ── Build system prompt ──────────────────────────────────────────────
        sys_prompt = body.get("system", "")
        if isinstance(sys_prompt, list):
            sys_prompt = " ".join(b.get("text", "") for b in sys_prompt if b.get("type") == "text")

        if sys_prompt:
            sys_prompt = sys_prompt + WEB_SEARCH_REMINDER

        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.extend(messages_anthr_to_openai(body.get("messages", [])))

        # ── Build OpenAI request ─────────────────────────────────────────────
        oai_req = {
            "model":      MODEL,
            "messages":   messages,
            "max_tokens": body.get("max_tokens", 4096),
            "stream":     body.get("stream", False),
        }
        oai_tools = None
        if body.get("tools"):
            oai_tools              = tools_anthr_to_openai(body["tools"])
            oai_req["tools"]       = oai_tools
            oai_req["tool_choice"] = "auto"
            tool_names = [t.get("name", t.get("type", "?")) for t in body["tools"]]
            log(f"Tools [{len(body['tools'])}]: {tool_names}")
        if body.get("temperature") is not None:
            oai_req["temperature"] = body["temperature"]

        is_stream = oai_req["stream"]
        log(f"REQ stream={is_stream} msgs={len(body.get('messages',[]))} "
            f"tools={len(body.get('tools',[]))} chars={len(json.dumps(messages))}")

        # Log translated messages for debugging
        for i, m in enumerate(messages):
            role = m.get("role", "?")
            if role == "tool":
                tc = m.get("content", "")
                log(f"  → oai_msg[{i}] role=tool call_id={m.get('tool_call_id','?')} content_len={len(tc)} content={tc[:800]}")
            elif role == "assistant" and m.get("tool_calls"):
                tc_names = [tc.get("function", {}).get("name", "?") for tc in m.get("tool_calls", [])]
                log(f"  → oai_msg[{i}] role=assistant tool_calls={tc_names}")

        for msg in body.get("messages", []):
            if isinstance(msg.get("content"), list):
                for blk in msg["content"]:
                    if blk.get("type") == "tool_result":
                        tc = blk.get("content", "")
                        if isinstance(tc, list):
                            tc_full = " ".join(b.get("text", "") for b in tc if b.get("type") == "text")
                            log(f"  tool_result[{blk.get('tool_use_id','?')}] list len={len(tc)} text={tc_full[:1000]}")
                        elif isinstance(tc, str):
                            log(f"  tool_result[{blk.get('tool_use_id','?')}] str len={len(tc)} content={tc[:1500]}")

        req = urllib.request.Request(
            f"{GOOGLE_BASE}/chat/completions",
            data=json.dumps(oai_req).encode(),
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {GOOGLE_API_KEY}",
            },
            method="POST",
        )

        msg_id = f"msg_{uuid.uuid4().hex}"
        try:
            if is_stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                with urllib.request.urlopen(req, timeout=120) as resp:
                    stream_openai_to_anthr(resp, msg_id, self.wfile, messages, oai_tools=oai_tools)
                log(f"DONE stream {time.time() - t0:.2f}s")
            else:
                # Non-streaming with recursive multi-turn web search
                current_messages = list(messages)
                content = []
                stop_reason = "end_turn"

                for round_num in range(MAX_SEARCH_ROUNDS):
                    oai_req_r = {
                        "model": MODEL,
                        "messages": current_messages,
                        "max_tokens": 4096,
                        "stream": False,
                    }
                    # Include tools only on first round (tools not needed for continuation)
                    if round_num == 0 and body.get("tools"):
                        oai_req_r["tools"] = tools_anthr_to_openai(body["tools"])
                        oai_req_r["tool_choice"] = "auto"
                    if body.get("temperature") is not None:
                        oai_req_r["temperature"] = body["temperature"]

                    req_r = urllib.request.Request(
                        f"{GOOGLE_BASE}/chat/completions",
                        data=json.dumps(oai_req_r).encode(),
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {GOOGLE_API_KEY}",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req_r, timeout=120) as resp_r:
                        oai_resp = json.loads(resp_r.read())
                    msg = oai_resp["choices"][0]["message"]

                    # Separate web_search from other tool calls
                    web_searches = []
                    other_calls = []
                    for tc in msg.get("tool_calls", []):
                        tc_name = tc["function"]["name"]
                        if _is_web_call(tc_name):
                            web_searches.append(tc)
                        else:
                            other_calls.append(tc)

                    if not web_searches:
                        # No web_search — use this response
                        if msg.get("content"):
                            raw_text = msg["content"].replace("<thought>", "<think>").replace("</thought>", "</think>")
                            content.append({"type": "text", "text": raw_text})
                        for tc in other_calls:
                            try:
                                inp = json.loads(tc["function"]["arguments"])
                            except Exception:
                                inp = {}
                            content.append({
                                "type": "tool_use",
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "input": inp,
                            })
                        stop_reason = "tool_use" if other_calls else "end_turn"
                        break

                    # Execute searches
                    search_results = []
                    for tc in web_searches:
                        tc_name = tc["function"]["name"]
                        result_text = _run_web_search(tc_name, tc["function"]["arguments"])
                        search_results.append((tc["id"], tc_name, result_text))

                    # Build continuation messages
                    cont_messages = list(current_messages)
                    all_tc_for_msg = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}
                        for tc in web_searches + other_calls
                    ]
                    cont_messages.append({"role": "assistant", "content": None, "tool_calls": all_tc_for_msg})
                    for tc_id, tc_name, result_text in search_results:
                        cont_messages.append({"role": "tool", "tool_call_id": tc_id, "content": result_text})

                    log(f"MULTI-TURN non-stream round {round_num + 1}: {len(cont_messages)} msgs → calling Google...")
                    current_messages = cont_messages

                else:
                    # Exhausted all rounds — use last response as-is
                    if msg.get("content"):
                        raw_text = msg["content"].replace("<thought>", "<think>").replace("</thought>", "</think>")
                        content.append({"type": "text", "text": raw_text})
                    for tc in msg.get("tool_calls", []):
                        try:
                            inp = json.loads(tc["function"]["arguments"])
                        except Exception:
                            inp = {}
                        content.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": inp,
                        })
                    stop_reason = "tool_use" if msg.get("tool_calls") else "end_turn"
                    log(f"MULTI-TURN non-stream exhausted after {MAX_SEARCH_ROUNDS} rounds")

                anthr_resp = {
                    "id": msg_id, "type": "message", "role": "assistant",
                    "model": MODEL, "content": content,
                    "stop_reason": stop_reason, "stop_sequence": None,
                    "usage": {
                        "input_tokens":  oai_resp.get("usage", {}).get("prompt_tokens", 0),
                        "output_tokens": oai_resp.get("usage", {}).get("completion_tokens", 0),
                    },
                }
                body_bytes = json.dumps(anthr_resp).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)
                log(f"DONE non-stream {time.time() - t0:.2f}s content={len(content)} blocks")

        except (BrokenPipeError, ConnectionResetError):
            pass
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            log(f"HTTP ERROR {e.code}: {err[:500]}")
            try:
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"error": {"message": err, "type": "api_error", "code": str(e.code)}}).encode()
                )
            except (BrokenPipeError, ConnectionResetError):
                pass
        except Exception as e:
            log(f"ERROR: {e}")
            try:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"error": {"message": str(e), "type": "internal_error"}}).encode()
                )
            except (BrokenPipeError, ConnectionResetError):
                pass


class ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    server = ThreadingServer(("", PORT), Handler)
    print(f"Anthropic→Google proxy on port {PORT}", file=sys.stderr, flush=True)
    log(f"START port={PORT} model={MODEL}")
    server.serve_forever()
