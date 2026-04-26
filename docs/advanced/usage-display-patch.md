# Agent Client 使用量显示补丁记录

## 背景

Agent Client Obsidian 插件的 ChatInput 组件已内置上下文使用量指示器（左下角百分比显示），通过 ACP 协议的 `usage_update` 事件驱动。

- **Claude Code** (`claude-agent-acp`)：原生支持，每次回复后自动发送 `usage_update`（含 token 数 + USD 费用）
- **Gemini CLI** (`gemini --acp`)：有 token 数据但未通过 ACP 发出 → 已补丁修复

## 数据流

```
ACP usage_update 事件
  → acpAdapter.onSessionUpdate()  [useChatController.ts:835]
  → agentSession.updateUsage()    [useAgentSession.ts:1147]
  → session.usage                 [ChatSession.usage]
  → ChatInput usage={session.usage} [ChatView.tsx:594]
  → 渲染百分比指示器              [ChatInput.tsx:1253]
```

## SessionUsage 结构

```typescript
interface SessionUsage {
  used: number;  // 当前 prompt 占用的 token 数
  size: number;  // 模型总上下文窗口大小
  cost?: { amount: number; currency: string };  // 累计费用（Claude 有，Gemini 无）
}
```

## Gemini CLI 补丁位置

**文件**：`/opt/homebrew/lib/node_modules/@google/gemini-cli/dist/src/acp/acpClient.js`

### 改动 1：导入 tokenLimit

在 `@google/gemini-cli-core` 的 import 末尾加入 `tokenLimit`：
```js
import { ..., getDisplayString, tokenLimit } from '@google/gemini-cli-core';
```

### 改动 2：声明变量（prompt() 方法内，while 循环前）

```js
let nextMessage = { role: 'user', parts };
let lastUsageMetadata = null;  // ← 新增
while (nextMessage !== null) {
```

### 改动 3：捕获并发送 usage_update（for-await 循环内 + 循环后）

```js
// 循环内：捕获 usageMetadata
if (resp.type === StreamEventType.CHUNK && resp.value.usageMetadata) {
    lastUsageMetadata = resp.value.usageMetadata;
}

// for-await 循环结束后，发送 usage_update
if (lastUsageMetadata?.promptTokenCount !== undefined) {
    const contextWindowSize = tokenLimit(model);
    await this.sendUpdate({
        sessionUpdate: 'usage_update',
        used: lastUsageMetadata.promptTokenCount,
        size: contextWindowSize,
    });
}
```

## 说明

- Gemini API 在流式响应的每个 chunk 里都携带 `usageMetadata`，包含 `promptTokenCount`（当前 prompt 的 token 总数）
- 所有 Gemini 模型的上下文窗口均为 **1,048,576 tokens**（由 `tokenLimit()` 返回）
- 补丁使用 ESM 模块系统，直接修改 `.js` 文件即生效，无需编译

## 注意事项

> ⚠️ 补丁会在以下情况被覆盖，需重新打：
> - `npm update @google/gemini-cli`
> - `brew upgrade` 更新 Gemini CLI（版本号：0.33.1）

## 相关文件

| 文件 | 说明 |
|------|------|
| `src/components/chat/ChatInput.tsx:1253` | 使用量渲染逻辑 |
| `src/hooks/useAgentSession.ts:1147` | updateUsage() 实现 |
| `src/hooks/useChatController.ts:835` | usage_update 路由 |
| `src/domain/models/chat-session.ts:169` | SessionUsage 类型定义 |
| `/opt/homebrew/lib/node_modules/@google/gemini-cli/dist/src/acp/acpClient.js` | Gemini ACP 补丁文件 |
| `/opt/homebrew/lib/node_modules/@zed-industries/claude-agent-acp/dist/acp-agent.js` | Claude ACP 参考实现 |