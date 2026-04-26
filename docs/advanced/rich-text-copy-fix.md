---
category: 技术笔记
project: Agent Client 增强
priority: High
tags: [Obsidian, Plugin, Patch, React, HTML]
created: 2026-04-21
status: 归档
---

# 📄 Agent Client 富文本复制功能恢复指南

## 🎯 功能概述
为 `agent-client` 插件新增“复制为富文本 (Copy as Rich Text)”按钮。点击后会将 Markdown 转换为经过优化的 HTML 格式，方便直接粘贴到 Outlook、Word 或 Teams 中，保持排版（如代码块背景、粗体、列表等）。

---

## 🛠️ 恢复步骤

如果插件发生升级，导致该功能失效，请按照以下步骤手动恢复。

### 1. 定位文件
打开插件源码目录下的 UI 组件文件：
`src/ui/MessageBubble.tsx`

### 2. 插入代码块 A：转换器与组件
在文件中的 `extractTextContent` 函数之后，`MessageBubble` 组件定义之前，插入以下两个部分：

#### A.1 `markdownToHtml` 转换器
```typescript
/**
 * Simple markdown to HTML converter for rich text clipboard.
 * Optimized for Outlook/Word/Teams.
 */
function markdownToHtml(markdown: string): string {
	let html = markdown;

	// Code blocks: ```lang\ncode\n```
	html = html.replace(/```(?:\w+)?\n([\s\S]+?)\n```/g, (_, code) => {
		const escapedCode = code
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;");
		return `<pre style="background-color: #f6f8fa; padding: 16px; border-radius: 6px; font-family: ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace; font-size: 85%; line-height: 1.45; overflow: auto;"><code>${escapedCode}</code></pre>`;
	});

	// Inline code: `code`
	html = html.replace(/`([^`]+)`/g, (_, code) => {
		return `<code style="background-color: rgba(175,184,193,0.2); padding: 0.2em 0.4em; border-radius: 6px; font-family: ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace; font-size: 85%;">$1</code>`;
	});

	// Bold: **text**
	html = html.replace(/\*\*([^\*]+)\*\*/g, "<b>$1</b>");

	// Italic: *text*
	html = html.replace(/\*([^\*]+)\*/g, "<i>$1</i>");

	// Headers
	html = html.replace(/^### (.*$)/gm, "<h3>$1</h3>");
	html = html.replace(/^## (.*$)/gm, "<h2>$1</h2>");
	html = html.replace(/^# (.*$)/gm, "<h1>$1</h1>");

	// Lists
	html = html.replace(/^[*-] (.*$)/gm, "<li>$1</li>");
	html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");

	// Links
	html = html.replace(/\[([^\]]+)\]\(([^\)]+)\)/g, '<a href="$2">$1</a>');

	// Paragraphs
	html = html
		.split("\n\n")
		.map((p) => {
			if (p.trim().startsWith("<h") || p.trim().startsWith("<ul") || p.trim().startsWith("<pre")) {
				return p;
			}
			return `<p>${p.replace(/\n/g, "<br>")}</p>`;
		})
		.join("\n");

	return html;
}
```

#### A.2 `CopyRichButton` 组件
```typescript
/**
 * Copy button for rich text (HTML).
 */
function CopyRichButton({ contents }: { contents: MessageContent[] }) {
	const [copied, setCopied] = useState(false);

	const handleCopyRichText = useCallback(() => {
		const text = extractTextContent(contents);
		if (!text) return;

		const html = markdownToHtml(text);

		const blobPlain = new Blob([text], { type: "text/plain" });
		const blobHtml = new Blob([html], { type: "text/html" });

		const data = [
			new ClipboardItem({
				"text/plain": blobPlain,
				"text/html": blobHtml,
			}),
		];

		void navigator.clipboard
			.write(data)
			.then(() => {
				setCopied(true);
				setTimeout(() => setCopied(false), 2000);
			})
			.catch((err) => {
				console.error("Failed to copy rich text:", err);
			});
	}, [contents]);

	const iconRef = useCallback(
		(el: HTMLButtonElement | null) => {
			if (el) setIcon(el, copied ? "check" : "file-text");
		},
		[copied],
	);

	return (
		<button
			className="clickable-icon agent-client-message-action-button"
			onClick={handleCopyRichText}
			aria-label="Copy as rich text"
			ref={iconRef}
		/>
	);
}
```

### 3. 修改 MessageBubble 渲染逻辑
找到 `MessageBubble` 组件中渲染 `agent-client-message-actions` 的部分，添加新按钮：

**修改前：**
```tsx
<div className="agent-client-message-actions">
    <CopyButton contents={message.content} />
</div>
```

**修改后：**
```tsx
<div className="agent-client-message-actions">
    <CopyButton contents={message.content} />
    <CopyRichButton contents={message.content} />
</div>
```

---

## 🔨 重新编译
修改完成后，在插件根目录下执行以下命令以生效：

```bash
npm run build
```

然后重新加载 Obsidian 即可。
