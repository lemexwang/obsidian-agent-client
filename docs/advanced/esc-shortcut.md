---
tags: [obsidian, agent-client, 快捷键, 配置备忘]
date: 2026-03-20
---

# Agent Client — ESC 中止对话配置说明

## 配置位置

`.obsidian/hotkeys.json`

## 配置内容

```json
"agent-client:cancel-current-message": [
  {
    "modifiers": [],
    "key": "Escape"
  }
]
```

## 插件升级后如果失效

直接在 `hotkeys.json` 内添加上述内容即可，或通过 Obsidian 设置操作：

设置 → 快捷键 → 搜索 `cancel` → 找到 `Agent Client: Cancel current message` → 设置为 `Escape`
