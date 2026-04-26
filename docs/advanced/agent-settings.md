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

## DeepSeek (Custom Agent via Claude-ACP)
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
    { "key": "CLAUDE_CODE_SUBAGENT_MODEL", "value": "deepseek-v4-pro" },
    { "key": "ANTHROPIC_API_KEY", "value": "YOUR_API_KEY" }
  ]
}
```

## General Settings
```json
{
  "defaultAgentId": "gemini-cli",
  "autoAllowPermissions": true,
  "autoMentionActiveNote": false,
  "debugMode": false,
  "nodePath": "/opt/homebrew/bin/node",
  "windowsWslMode": false,
  "sendMessageShortcut": "enter",
  "chatViewLocation": "right-tab"
}
```
