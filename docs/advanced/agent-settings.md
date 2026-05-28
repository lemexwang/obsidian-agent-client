# Agent Settings Reference (data.json)

Below is a reference for the `data.json` configuration used in Agent Client for various AI agents.

## Claude Code (ACP)
```json
"claude": {
  "id": "claude-code-acp",
  "displayName": "Claude Code",
  "apiKey": "",
  "command": "/opt/homebrew/bin/claude-agent-acp",
  "args": [],
  "env": []
}
```

For Claude subscription login, keep `apiKey` empty and log in with the
Claude Code CLI (`claude`) in a terminal. Do not set `ANTHROPIC_API_KEY` for
the built-in Claude agent unless you intentionally want API-key billing.

## Gemini CLI
```json
"gemini": {
  "id": "gemini-cli",
  "displayName": "Gemini CLI",
  "apiKey": "",
  "command": "/opt/homebrew/bin/gemini",
  "args": [
    "--experimental-acp",
    "--model",
    "gemini-2.5-pro"
  ],
  "env": []
}
```

## DeepSeek via Claude-ACP

Use this when you want Claude Code's normal agent behavior and permission flow,
but with DeepSeek as the Anthropic-compatible backend.

```json
{
  "id": "deepseek-v4",
  "displayName": "DeepSeek",
  "command": "/opt/homebrew/bin/claude-agent-acp",
  "args": [],
  "env": [
    { "key": "ANTHROPIC_BASE_URL", "value": "https://api.deepseek.com/anthropic" },
    { "key": "ANTHROPIC_MODEL", "value": "deepseek-v4-pro" },
    { "key": "ANTHROPIC_DEFAULT_OPUS_MODEL", "value": "deepseek-v4-pro" },
    { "key": "ANTHROPIC_DEFAULT_SONNET_MODEL", "value": "deepseek-v4-pro" },
    { "key": "ANTHROPIC_DEFAULT_HAIKU_MODEL", "value": "deepseek-v4-flash" },
    { "key": "ANTHROPIC_API_KEY", "value": "YOUR_API_KEY" }
  ]
}
```

`deepseek-v4-pro` is best for complex coding and long reasoning. Use
`deepseek-v4-flash` for cheaper, faster everyday tasks. Avoid new configs that
depend on `deepseek-chat` or `deepseek-reasoner`; DeepSeek marks those names as
legacy.

## DeepSeek Native ACP Agent

Use this when you want DeepSeek-specific model switching, including explicit
Thinking variants. This agent implements its own vault tools, so treat it as a
more direct file-access path than Claude Code's normal permission flow.
Image input is intentionally not advertised for this agent because DeepSeek V4
API vision support is not reliable enough for Obsidian attachments.

```json
{
  "id": "deepseek-acp",
  "displayName": "DeepSeek ACP",
  "command": "python3",
  "args": [
    "/path/to/deepseek-acp.py"
  ],
  "env": [
    { "key": "DEEPSEEK_API_KEY", "value": "YOUR_API_KEY" },
    { "key": "DEEPSEEK_MODEL", "value": "deepseek-v4-flash" },
    { "key": "DEEPSEEK_REASONING_EFFORT", "value": "high" }
  ]
}
```

## General Settings
```json
{
  "defaultAgentId": "gemini-cli",
  "autoAllowPermissions": false,
  "autoMentionActiveNote": false,
  "debugMode": false,
  "nodePath": "/opt/homebrew/bin/node",
  "windowsWslMode": false,
  "sendMessageShortcut": "enter",
  "chatViewLocation": "right-tab"
}
```
