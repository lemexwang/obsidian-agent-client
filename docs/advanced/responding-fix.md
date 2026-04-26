# Agent Client 对话结束后持续显示 Responding 修复记录

## 问题现象

Claude Code 完成回复后，对话界面仍一直显示"Responding"加载状态，无法发送下一条消息。文本内容已正常渲染，但 UI 卡死在发送中。

## 根本原因

### 调用链

```
useChat.sendMessage()
  → sendPreparedPrompt()
    → AcpAdapter.sendPrompt()
      → connection.prompt()  ← 永远不 resolve
```

`connection.prompt()` 是 ACP SDK 的 JSON-RPC 请求，会等待 `claude-agent-acp` 发回响应。只要它挂起，`isSending` 就永远是 `true`。

### 为什么挂起

`claude-agent-acp` v0.30.0 的 `acp-agent.js` 处理 `session/prompt` 请求的 while 循环结构：

```
while (true) {
    message = await session.query.next()

    switch (message.type) {
        case "result":
            // 发送 usage_update 通知
            // 处理成功/失败
            break  // ← 继续循环，等待下一条消息

        case "session_state_changed":
            if (state === "idle")
                return { stopReason, usage }  // ← 才会发送 JSON-RPC 响应
    }
}
```

收到 `result` 消息后，循环不退出，而是继续等待 `session_state_changed { state: "idle" }` 事件。这个事件需要 Claude Code 支持 `CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS=1` 环境变量。

**Claude Code v2.1.78 不支持该环境变量**（binary 中完全没有该字符串），所以 `session_state_changed` 永远不来，循环永远挂起，JSON-RPC 响应永远不发送。

## 修复方案

修改全局安装的 `acp-agent.js`，在 `result` 消息处理完成后直接 `return`，不再等待 `session_state_changed`。

### 修改文件

```
/opt/homebrew/lib/node_modules/@agentclientprotocol/claude-agent-acp/dist/acp-agent.js
```

### 修改位置（约第 517 行）

**修改前：**
```javascript
                        }
                        break;  // 继续 while 循环等待 session_state_changed
                    }
                    case "stream_event": {
```

**修改后：**
```javascript
                        }
                        // Return immediately on result — don't wait for session_state_changed
                        // (Claude Code <2.2 doesn't emit CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS)
                        return { stopReason, usage: sessionUsage(session) };
                    }
                    case "stream_event": {
```

### 覆盖的所有退出路径

| `stopReason` | 触发条件 | 修复后行为 |
|---|---|---|
| `end_turn` | 正常完成 | 立即返回 ✓ |
| `max_tokens` | 上下文超限 | 立即返回 ✓ |
| `max_turn_requests` | 超过轮次限制 | 立即返回 ✓ |
| `cancelled` | 用户取消 | 立即返回 ✓ |
| （throw） | 认证错误/内部错误 | 已有异常路径，不受影响 ✓ |

## 生效方式

修改的是全局 npm 包，**插件无需重新构建**。在 Obsidian 中关闭当前 Agent Client 对话并重新打开（或重启 Obsidian）以创建新 session 即可生效。

## 版本信息

| 组件 | 版本 |
|---|---|
| Claude Code | v2.1.78 |
| `claude-agent-acp` | v0.30.0 |
| `@agentclientprotocol/sdk`（插件端） | v0.14.1 |
| `@agentclientprotocol/sdk`（agent 端） | v0.19.0 |

## 注意事项

- `acp-agent.js` 修改为本地补丁，更新 `claude-agent-acp` 后会被覆盖，需重新修改
- 若未来 Claude Code 更新后开始正常发送 `session_state_changed`，可考虑恢复原逻辑（但提前 return 不影响正确性）

## 关联修复

本次 session 还同步修复了另外两个问题：

### 1. Session 创建时报错 `[object Object]`

**原因**：`useAgentSession.ts` 的 catch 块使用了 `String(error)`，而 ACP SDK 抛出的是普通对象（非 `Error` 实例），导致显示 `[object Object]`。

**修改文件**：`src/hooks/useAgentSession.ts`

新增 import：
```typescript
import { extractErrorMessage } from "../utils/error-utils";
```

修改 catch 块（约第 281 行）：
```typescript
// 修改前
message: `Failed to create new session: ${error instanceof Error ? error.message : String(error)}`,

// 修改后
message: `Failed to create new session: ${extractErrorMessage(error)}`,
```

`extractErrorMessage()` 会优先读取 ACP 错误对象的 `data.details` 字段，再回退到 `message` 字段，正确处理非 `Error` 实例的 ACP 错误。修改后重新构建了 `main.js` 并同步到两个 vault。

### 2. Native CLI binary for darwin-arm64 not found

在两个 vault 的 `data.json` 的 `claude.env` 中添加：
```json
{ "key": "CLAUDE_CODE_EXECUTABLE", "value": "/Users/alice/.local/bin/claude" }
```
指向本地安装的 Claude Code 原生二进制（v2.1.78）。

## v0.31.0 新增 Bug（2026-04-26）

### `session.cancelled → break` 导致 while 循环继续挂起

**背景**：包从 v0.30.0 升级到 v0.31.0 后，引入了新的 `session.cancelled` 早期退出逻辑。

**问题**：在 `case "result":` 内部，新增代码：
```javascript
if (session.cancelled) {
    stopReason = "cancelled";
    break;  // ← 仅退出 switch，while(true) 继续运行，等下一条消息 → 永远挂起
}
```
这个 `break` 绕过了原有补丁（line 606 的 `return`），在 while 循环里继续调用 `session.query.next()`，而 Claude Code 已发完最后一条消息，没有更多消息，导致永久挂起。

**触发时机**：插件调用 `cancelOperation()` 与 `result` 消息处理发生竞态（例如：新建 session 时、连接重置时）。

**修复**：将 `break` 改为 `return { stopReason: "cancelled", usage: sessionUsage(session) }`（2026-04-26 应用）。

---

## 修复验证状态

| 修复项 | 适用版本 | 状态 |
|---|---|---|
| `acp-agent.js` result case return 替换 break | v0.30.0 | ✅ |
| `useAgentSession.ts` extractErrorMessage | — | ✅ |
| `CLAUDE_CODE_EXECUTABLE` in data.json | — | ✅ |
| `acp-agent.js` cancelled 早退 return 替换 break | v0.31.0 | ✅ 2026-04-26 |
