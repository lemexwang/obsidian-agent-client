---
tags: [obsidian, agent-client, css, 配置备忘]
date: 2026-03-26
updated: 2026-04-09
---

# Agent Client — main.js 补丁配置说明

## 配置位置

Logo 通过两部分协同实现：

1. **CSS Snippet**（不随插件升级丢失）：`.obsidian/snippets/agent-client-minimal.css`
2. **插件 main.js 补丁**（随插件升级需重新打）：`.obsidian/plugins/agent-client/main.js`

## 工作原理（当前版本）

插件标题栏 DOM 结构（2026-04-09 升级后）：

```
nav-header.agent-client-chat-view-header
  └── div.nav-buttons-container
        └── span.agent-client-chat-view-header-title[data-agent-label="Claude Code"]  ← main.js patch 注入
        └── span.agent-client-chat-view-header-title[data-agent-label="Gemini CLI"]
```

旧版 `Pd` 组件（`agent-client-agent-logo-claude/gemini` span）**已移除**，main.js 中不再有 "logo" 字样。

CSS Snippet 策略：**main.js patch 在 span 上注入 `data-agent-label`，CSS 通过属性选择器 `::before` 注入 Logo**：

```css
.agent-client-chat-view-header-title[data-agent-label="Claude Code"]::before { content: url("..."); }
.agent-client-chat-view-header-title[data-agent-label="Gemini CLI"]::before { content: url("..."); }
```

main.js patch 内容（需随插件升级重新打）：

```
old: (0,Ge.jsx)("span",{className:"agent-client-chat-view-header-title",children:e})
new: (0,Ge.jsx)("span",{className:"agent-client-chat-view-header-title","data-agent-label":e,children:e})
```

> ⚠️ **需要 main.js 补丁**，插件升级后需重新执行（见下方 patch 脚本）。

## 插件升级后如果 Logo 失效，排查顺序

### 检查点 1：DOM 结构是否变了

在 Obsidian 控制台（`Cmd+Option+I` → 控制台）运行：

```javascript
document.querySelector('.agent-client-chat-view-header-title')?.innerHTML
```

应看到含有 `agent-client-agent-logo-claude` 或 `agent-client-agent-logo-gemini` 的 span。

- 如果 class 名变了 → 更新 CSS Snippet 里的选择器
- 如果 span 消失了 → `Pd` 组件可能重写，需重新分析 main.js

### 检查点 2：agentId 是否包含 "claude"/"gemini"

`Pd` 组件判断逻辑：`agentId.toLowerCase().includes("claude/gemini")`。

确认 `data.json` 里的 id 字段：
- Claude → `"claude-code-acp"` ✓
- Gemini → `"gemini-cli"` ✓

如果 id 改了且不包含上述关键词，`Pd` 会返回 null（无 span），需更新 id 或改用其他 CSS 方案。

### 检查点 3：CSS Snippet 是否启用

Obsidian 设置 → 外观 → CSS 代码片段 → `agent-client-minimal` 开关是否打开。

## Agent 配置（来自 data.json）

| Agent  | displayName | 命令路径                             |
| ------ | ----------- | ------------------------------------ |
| Claude | Claude Code | `/opt/homebrew/bin/claude-agent-acp` |
| Gemini | Gemini CLI  | `/opt/homebrew/bin/gemini`           |

Gemini 参数：`--acp --model gemini-2.5-flash`

## 如何启用/禁用 Snippet

Obsidian 设置 → 外观 → CSS 代码片段 → 找到 `agent-client-minimal` → 开关切换。

## Logo patch 脚本（插件升级后重新执行）

```python
python3 << 'EOF'
old = '(0,Ge.jsx)("span",{className:"agent-client-chat-view-header-title",children:e})'
new = '(0,Ge.jsx)("span",{className:"agent-client-chat-view-header-title","data-agent-label":e,children:e})'

for vault in [
    '/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Lemex_Vault/.obsidian/plugins/agent-client/main.js',
    '/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Alice_Study_2026/.obsidian/plugins/agent-client/main.js',
]:
    try:
        with open(vault) as f:
            content = f.read()
        if old in content:
            with open(vault, 'w') as f:
                f.write(content.replace(old, new, 1))
            print(f'PATCHED: {vault}')
        elif new in content:
            print(f'ALREADY PATCHED: {vault}')
        else:
            print(f'NOT FOUND (DOM changed?): {vault}')
    except FileNotFoundError:
        print(f'FILE NOT FOUND: {vault}')
EOF
```

> ⚠️ 插件升级后需重新执行。若 NOT FOUND，说明 DOM 结构再次变更，需重新分析 main.js。

## 移除不需要的 Agent（如 Codex）

Codex 是插件**硬编码**的内置 agent，仅删除 `data.json` 里的条目**不够**，Switch agent 列表里仍会出现。需要同时 patch `main.js`。

两个库都需要执行：

```python
python3 << 'EOF'
old = ',{id:this.settings.codex.id,displayName:this.settings.codex.displayName||this.settings.codex.id}'
new = ''

for vault in [
    '/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Lemex_Vault/.obsidian/plugins/agent-client/main.js',
    '/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Alice_Study_2026/.obsidian/plugins/agent-client/main.js',
]:
    try:
        with open(vault) as f:
            content = f.read()
        count = content.count(old)
        if count == 0:
            print(f'NOT FOUND in {vault}')
        else:
            patched = content.replace(old, new)
            with open(vault, 'w') as f:
                f.write(patched)
            print(f'PATCHED ({count} occurrence): {vault}')
    except FileNotFoundError:
        print(f'FILE NOT FOUND: {vault}')
EOF
```

重启 Obsidian 后生效。

> ⚠️ 插件升级后此 patch 会被覆盖，需重新执行。

## Auto Mention 切换笔记不更新修复

**Bug**：切换笔记时 Auto Mention 不自动更新 @的笔记。

**根因**：`VaultAdapter.attachToView()` 里有多余守卫条件 `this.lastSelectionKey &&`，导致 `lastSelectionKey` 为空时（初始状态）切换笔记不触发 `handleSelectionChange`，监听链断掉，`updateActiveNote` 不被调用。

两个库都需要执行：

```python
python3 << 'EOF'
old = 'this.lastSelectionKey&&!this.lastSelectionKey.startsWith(`${i}:`)&&this.handleSelectionChange(i,null)'
new = '!this.lastSelectionKey.startsWith(`${i}:`)&&this.handleSelectionChange(i,null)'

for vault in [
    '/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Lemex_Vault/.obsidian/plugins/agent-client/main.js',
    '/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Alice_Study_2026/.obsidian/plugins/agent-client/main.js',
]:
    try:
        with open(vault) as f:
            content = f.read()
        if old not in content:
            if new in content:
                print(f'ALREADY PATCHED: {vault}')
            else:
                print(f'NOT FOUND in {vault}')
        else:
            patched = content.replace(old, new, 1)
            with open(vault, 'w') as f:
                f.write(patched)
            print(f'PATCHED: {vault}')
    except FileNotFoundError:
        print(f'FILE NOT FOUND: {vault}')
EOF
```

重启 Obsidian 后生效。

> ⚠️ 插件升级后此 patch 会被覆盖，需重新执行。

## 历史变更记录

| 版本区间 | DOM 结构 | patch 方式 | CSS 选择器 |
| -------- | -------- | ---------- | ---------- |
| < v0.9.3 | `div.agent-client-inline-header` > `span.agent-client-agent-label` | main.js：在 inline-header 上加 `data-agent-id` | `[data-agent-id="claude-code-acp"] .agent-client-agent-label::before` |
| v0.9.3 ~ 2026-03-28 | `h3.agent-client-chat-view-header-title` | main.js：在 h3 上加 `data-agent-label` | `.agent-client-chat-view-header-title[data-agent-label="Claude Code"]::before` |
| 2026-03-28 ~ 2026-04-09 | `h3` > `span.agent-client-agent-logo-claude` (Pd 内建) | **无需 patch** | `.agent-client-agent-logo-claude::before`（隐藏内建 SVG，注入自定义图标） |
| ≥ 2026-04-09（当前） | `span.agent-client-chat-view-header-title` 无 logo span | main.js：在 span 上加 `"data-agent-label":e` | `.agent-client-chat-view-header-title[data-agent-label="Claude Code"]::before` |
