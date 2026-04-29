import * as React from "react";
const { useState, useCallback } = React;
import { setIcon } from "obsidian";
import type { ChatMessage, MessageContent } from "../types/chat";
import type { AcpClient } from "../acp/acp-client";
import type AgentClientPlugin from "../plugin";
import { MarkdownRenderer } from "./shared/MarkdownRenderer";
import { TerminalBlock } from "./TerminalBlock";
import { ToolCallBlock } from "./ToolCallBlock";
import { LucideIcon } from "./shared/IconButton";

// ---------------------------------------------------------------------------
// TextWithMentions (internal helper)
// ---------------------------------------------------------------------------

interface TextWithMentionsProps {
	text: string;
	plugin: AgentClientPlugin;
	autoMentionContext?: {
		noteName: string;
		notePath: string;
		selection?: {
			fromLine: number;
			toLine: number;
		};
	};
}

// Function to render text with @mentions and optional auto-mention
function TextWithMentions({
	text,
	plugin,
	autoMentionContext,
}: TextWithMentionsProps): React.ReactElement {
	// Match @[[filename]] format only
	const mentionRegex = /@\[\[([^\]]+)\]\]/g;
	const parts: React.ReactNode[] = [];

	// Add auto-mention badge first if provided
	if (autoMentionContext) {
		const displayText = autoMentionContext.selection
			? `@${autoMentionContext.noteName}:${autoMentionContext.selection.fromLine}-${autoMentionContext.selection.toLine}`
			: `@${autoMentionContext.noteName}`;

		parts.push(
			<span
				key="auto-mention"
				className="agent-client-text-mention"
				onClick={() => {
					void plugin.app.workspace.openLinkText(
						autoMentionContext.notePath,
						"",
					);
				}}
			>
				{displayText}
			</span>,
		);
		parts.push("\n");
	}

	let lastIndex = 0;
	let match;

	while ((match = mentionRegex.exec(text)) !== null) {
		// Add text before the mention
		if (match.index > lastIndex) {
			parts.push(text.slice(lastIndex, match.index));
		}

		// Extract filename from [[brackets]]
		const noteName = match[1];

		// Check if file actually exists
		const file = plugin.app.vault
			.getMarkdownFiles()
			.find((f) => f.basename === noteName);

		if (file) {
			// File exists - render as clickable mention
			parts.push(
				<span
					key={match.index}
					className="agent-client-text-mention"
					onClick={() => {
						void plugin.app.workspace.openLinkText(file.path, "");
					}}
				>
					@{noteName}
				</span>,
			);
		} else {
			// File doesn't exist - render as plain text
			parts.push(`@${noteName}`);
		}

		lastIndex = match.index + match[0].length;
	}

	// Add any remaining text
	if (lastIndex < text.length) {
		parts.push(text.slice(lastIndex));
	}

	return <div className="agent-client-text-with-mentions">{parts}</div>;
}

// ---------------------------------------------------------------------------
// CollapsibleThought (internal helper)
// ---------------------------------------------------------------------------

interface CollapsibleThoughtProps {
	text: string;
	plugin: AgentClientPlugin;
}

function CollapsibleThought({ text, plugin }: CollapsibleThoughtProps) {
	const [isExpanded, setIsExpanded] = useState(false);
	const showEmojis = plugin.settings.displaySettings.showEmojis;

	return (
		<div
			className="agent-client-collapsible-thought"
			onClick={() => setIsExpanded(!isExpanded)}
		>
			<div className="agent-client-collapsible-thought-header">
				{showEmojis && (
					<LucideIcon
						name="lightbulb"
						className="agent-client-collapsible-thought-label-icon"
					/>
				)}
				Thinking
				<LucideIcon
					name={isExpanded ? "chevron-down" : "chevron-right"}
					className="agent-client-collapsible-thought-icon"
				/>
			</div>
			{isExpanded && (
				<div className="agent-client-collapsible-thought-content">
					<MarkdownRenderer text={text} plugin={plugin} />
				</div>
			)}
		</div>
	);
}

// ---------------------------------------------------------------------------
// ContentBlock (internal helper, formerly MessageContentRenderer)
// ---------------------------------------------------------------------------

interface ContentBlockProps {
	content: MessageContent;
	plugin: AgentClientPlugin;
	messageId?: string;
	messageRole?: "user" | "assistant";
	terminalClient?: AcpClient;
	/** Callback to approve a permission request */
	onApprovePermission?: (
		requestId: string,
		optionId: string,
	) => Promise<void>;
}

function ContentBlock({
	content,
	plugin,
	messageId,
	messageRole,
	terminalClient,
	onApprovePermission,
}: ContentBlockProps) {
	switch (content.type) {
		case "text":
			// User messages: render with mention support
			// Assistant messages: render as markdown
			if (messageRole === "user") {
				return <TextWithMentions text={content.text} plugin={plugin} />;
			}
			return <MarkdownRenderer text={content.text} plugin={plugin} />;

		case "text_with_context":
			// User messages with auto-mention context
			return (
				<TextWithMentions
					text={content.text}
					autoMentionContext={content.autoMentionContext}
					plugin={plugin}
				/>
			);

		case "agent_thought":
			return <CollapsibleThought text={content.text} plugin={plugin} />;

		case "tool_call":
			return (
				<ToolCallBlock
					content={content}
					plugin={plugin}
					terminalClient={terminalClient}
					onApprovePermission={onApprovePermission}
				/>
			);

		case "plan": {
			const showEmojis = plugin.settings.displaySettings.showEmojis;
			return (
				<div className="agent-client-message-plan">
					<div className="agent-client-message-plan-title">
						{showEmojis && (
							<LucideIcon
								name="list-checks"
								className="agent-client-message-plan-label-icon"
							/>
						)}
						Plan
					</div>
					{content.entries.map((entry, idx) => (
						<div
							key={idx}
							className={`agent-client-message-plan-entry agent-client-plan-status-${entry.status}`}
						>
							{showEmojis && (
								<span
									className={`agent-client-message-plan-entry-icon agent-client-status-${entry.status}`}
								>
									<LucideIcon
										name={
											entry.status === "completed"
												? "check"
												: entry.status === "in_progress"
													? "loader"
													: "circle"
										}
									/>
								</span>
							)}{" "}
							{entry.content}
						</div>
					))}
				</div>
			);
		}

		case "terminal":
			return (
				<TerminalBlock
					terminalId={content.terminalId}
					terminalClient={terminalClient || null}
					plugin={plugin}
				/>
			);

		case "image":
			return (
				<div className="agent-client-message-image">
					<img
						src={`data:${content.mimeType};base64,${content.data}`}
						alt="Attached image"
						className="agent-client-message-image-thumbnail"
					/>
				</div>
			);

		case "resource_link":
			return (
				<div className="agent-client-message-resource-link">
					<span
						className="agent-client-message-resource-link-icon"
						ref={(el) => {
							if (el) setIcon(el, "file");
						}}
					/>
					<span className="agent-client-message-resource-link-name">
						{content.name}
					</span>
				</div>
			);

		default:
			return <span>Unsupported content type</span>;
	}
}

// ---------------------------------------------------------------------------
// MessageBubble (exported, formerly MessageRenderer)
// ---------------------------------------------------------------------------

export interface MessageBubbleProps {
	message: ChatMessage;
	plugin: AgentClientPlugin;
	terminalClient?: AcpClient;
	/** Callback to approve a permission request */
	onApprovePermission?: (
		requestId: string,
		optionId: string,
	) => Promise<void>;
}

/**
 * Extract plain text from message contents for clipboard copy.
 */
function extractTextContent(contents: MessageContent[]): string {
	return contents
		.filter((c) => c.type === "text" || c.type === "text_with_context")
		.map((c) => ("text" in c ? c.text : ""))
		.join("\n");
}

/**
 * Simple markdown to HTML converter for rich text clipboard.
 * Optimized for Outlook/Word/Teams.
 */
function markdownToHtml(markdown: string): string {
	let html = markdown.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

	// Code blocks: ```lang\ncode\n```
	html = html.replace(/```(?:\w+)?\n([\s\S]+?)\n```/g, (_, code) => {
		const escapedCode = code
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;");
		return `<pre style="background-color: #f6f8fa; color: #000000; padding: 16px; border-radius: 6px; font-family: ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace; font-size: 85%; line-height: 1.45; overflow: auto;"><code style="color: #000000;">${escapedCode}</code></pre>`;
	});

	// Inline code: `code`
	html = html.replace(/`([^`]+)`/g, (_, code) => {
		return `<code style="background-color: rgba(175,184,193,0.2); color: #000000; padding: 0.2em 0.4em; border-radius: 6px; font-family: ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace; font-size: 85%;">${code}</code>`;
	});

	// Bold: **text**
	html = html.replace(/\*\*(.*?)\*\*/g, "<b>$1</b>");

	// Italic: *text*
	html = html.replace(/\*(.*?)\*/g, "<i>$1</i>");

	// Headers (must match longer patterns first)
	html = html.replace(/^######\s+(.*)/gm, '<h6 style="color:#000000;">$1</h6>');
	html = html.replace(/^#####\s+(.*)/gm, '<h5 style="color:#000000;">$1</h5>');
	html = html.replace(/^####\s+(.*)/gm, '<h4 style="color:#000000;">$1</h4>');
	html = html.replace(/^###\s+(.*)/gm, '<h3 style="color:#000000;">$1</h3>');
	html = html.replace(/^##\s+(.*)/gm, '<h2 style="color:#000000;">$1</h2>');
	html = html.replace(/^#\s+(.*)/gm, '<h1 style="color:#000000;">$1</h1>');

	// Lists (simplified)
	html = html.replace(/^[*-]\s+(.*)/gm, '<li style="color:#000000;">$1</li>');
	// Wrap lists in <ul> (very basic logic)
	html = html.replace(/((?:<li[^>]*>.*<\/li>\n?)+)/g, "<ul>$1</ul>");

	// Links: [text](url)
	html = html.replace(/\[([^\]]+)\]\(([^\)]+)\)/g, '<a href="$2" style="color:#0563C1;">$1</a>');

	// Tables: convert markdown pipe tables to HTML
	// Matches contiguous lines that all contain pipe characters,
	// with at least one separator row (e.g. |---|---|)
	html = html.replace(/(?:^\|.+\|\s*$\n?)+/gm, (tableBlock) => {
		const lines = tableBlock.trim().split("\n");
		if (lines.length < 2) return tableBlock;

		// Second line must be a separator row
		if (!/^\|[\s\-\|:]+$/.test(lines[1])) return tableBlock;

		// Parse column alignments from separator row
		const sepCells = lines[1].split("|").filter((c) => c.trim() !== "");
		const alignments = sepCells.map((c) => {
			const trimmed = c.trim();
			if (trimmed.startsWith(":") && trimmed.endsWith(":")) return "center";
			if (trimmed.endsWith(":")) return "right";
			return "left";
		});

		const headerCells = lines[0]
			.split("|")
			.filter((c) => c.trim() !== "")
			.map((c) => c.trim());

		const tableStyle =
			"border-collapse:collapse;width:100%;margin:8px 0;font-size:14px;color:#000000;";
		const thStyle =
			"border:1px solid #d0d7de;padding:6px 13px;background-color:#f6f8fa;color:#000000;font-weight:600;white-space:nowrap;";
		const tdStyle = "border:1px solid #d0d7de;padding:6px 13px;color:#000000;";

		let tableHtml = `<table style="${tableStyle}">`;

		// Header
		tableHtml += "<thead><tr>";
		headerCells.forEach((cell, i) => {
			tableHtml += `<th style="${thStyle}text-align:${alignments[i] || "left"};">${cell}</th>`;
		});
		tableHtml += "</tr></thead>";

		// Body rows
		tableHtml += "<tbody>";
		for (let i = 2; i < lines.length; i++) {
			const cells = lines[i]
				.split("|")
				.map((c) => c.trim())
				.filter((c, idx, arr) => {
					// Drop empty first (leading |) and empty last (trailing |)
					if (idx === 0 && c === "") return false;
					if (idx === arr.length - 1 && c === "") return false;
					return true;
				});
			tableHtml += "<tr>";
			cells.forEach((cell, j) => {
				tableHtml += `<td style="${tdStyle}text-align:${alignments[j] || "left"};">${cell}</td>`;
			});
			tableHtml += "</tr>";
		}
		tableHtml += "</tbody></table>";

		return tableHtml;
	});

	// Paragraphs
	html = html
		.split("\n\n")
		.map((p) => {
			if (
				p.trim().startsWith("<h") ||
				p.trim().startsWith("<ul") ||
				p.trim().startsWith("<pre") ||
				p.trim().startsWith("<table")
			) {
				return p;
			}
			return `<p style="color:#000000;">${p.replace(/\n/g, "<br>")}</p>`;
		})
		.join("\n");

	return `<html><head><style>body,p,li,ul,ol,h1,h2,h3,h4,h5,h6,td,th,tr,table,span,div,b,i,strong,em{color:#000000!important;background-color:transparent!important;}a{color:#0563C1!important;}pre,code{color:#000000!important;}body{background-color:white!important;}</style></head><body style="background-color:white;color:black;margin:0;padding:0;">${html}</body></html>`;
}

/**
 * Copy button that shows a check icon briefly after copying.
 * Uses callback ref for Obsidian's setIcon DOM manipulation.
 */
function CopyButton({ contents }: { contents: MessageContent[] }) {
	const [copied, setCopied] = useState(false);

	const handleCopy = useCallback(() => {
		const text = extractTextContent(contents);
		if (!text) return;
		void navigator.clipboard
			.writeText(text)
			.then(() => {
				setCopied(true);
				setTimeout(() => setCopied(false), 2000);
			})
			.catch(() => {});
	}, [contents]);

	const iconRef = useCallback(
		(el: HTMLButtonElement | null) => {
			if (el) setIcon(el, copied ? "check" : "copy");
		},
		[copied],
	);

	return (
		<button
			className="clickable-icon agent-client-message-action-button"
			onClick={handleCopy}
			aria-label="Copy message"
			ref={iconRef}
		/>
	);
}

/**
 * Copy button for rich text (HTML).
 */
function CopyRichButton({ contents }: { contents: MessageContent[] }) {
	const [copied, setCopied] = useState(false);

	const handleCopyRichText = useCallback(() => {
		const text = extractTextContent(contents);
		if (!text) return;

		const html = markdownToHtml(text);

		// Use a hidden contenteditable element + execCommand('copy').
		// This is the reliable path in Electron: it writes proper native
		// CF_HTML / NSPasteboard HTML that Teams, Outlook, WeChat, etc. read.
		// navigator.clipboard.write(ClipboardItem) in Electron does not
		// reliably populate the native HTML clipboard format for other apps.
		const el = document.createElement("div");
		el.setAttribute("contenteditable", "true");
		el.style.cssText =
			"position:fixed;left:-9999px;top:-9999px;opacity:0;pointer-events:none;white-space:pre-wrap;background-color:white;color:black;";
		el.innerHTML = html;
		document.body.appendChild(el);

		const selection = window.getSelection();
		const range = document.createRange();
		range.selectNodeContents(el);
		selection?.removeAllRanges();
		selection?.addRange(range);

		const success = document.execCommand("copy");

		selection?.removeAllRanges();
		document.body.removeChild(el);

		if (success) {
			setCopied(true);
			setTimeout(() => setCopied(false), 2000);
		} else {
			// Fallback: ClipboardItem API (works in standard browser contexts)
			const blobPlain = new Blob([text], { type: "text/plain" });
			const blobHtml = new Blob([html], { type: "text/html" });
			void navigator.clipboard
				.write([new ClipboardItem({ "text/plain": blobPlain, "text/html": blobHtml })])
				.then(() => {
					setCopied(true);
					setTimeout(() => setCopied(false), 2000);
				})
				.catch((err) => {
					console.error("Failed to copy rich text:", err);
				});
		}
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

function groupContent(
	contents: MessageContent[],
): Array<
	| { type: "attachments"; items: MessageContent[] }
	| { type: "single"; item: MessageContent }
> {
	const groups: Array<
		| { type: "attachments"; items: MessageContent[] }
		| { type: "single"; item: MessageContent }
	> = [];

	let currentAttachmentGroup: MessageContent[] = [];

	for (const content of contents) {
		if (content.type === "image" || content.type === "resource_link") {
			currentAttachmentGroup.push(content);
		} else {
			// Flush any pending attachment group
			if (currentAttachmentGroup.length > 0) {
				groups.push({
					type: "attachments",
					items: currentAttachmentGroup,
				});
				currentAttachmentGroup = [];
			}
			groups.push({ type: "single", item: content });
		}
	}

	// Flush remaining attachments
	if (currentAttachmentGroup.length > 0) {
		groups.push({ type: "attachments", items: currentAttachmentGroup });
	}

	return groups;
}

export const MessageBubble = React.memo(function MessageBubble({
	message,
	plugin,
	terminalClient,
	onApprovePermission,
}: MessageBubbleProps) {
	const groups = groupContent(message.content);

	return (
		<div
			className={`agent-client-message-renderer ${message.role === "user" ? "agent-client-message-user" : "agent-client-message-assistant"}`}
		>
			{groups.map((group, idx) => {
				if (group.type === "attachments") {
					// Render attachments (images + resource_links) in horizontal strip
					return (
						<div
							key={idx}
							className="agent-client-message-images-strip"
						>
							{group.items.map((content, imgIdx) => (
								<ContentBlock
									key={imgIdx}
									content={content}
									plugin={plugin}
									messageId={message.id}
									messageRole={message.role}
									terminalClient={terminalClient}
									onApprovePermission={onApprovePermission}
								/>
							))}
						</div>
					);
				} else {
					// Render single non-image content
					return (
						<div key={idx}>
							<ContentBlock
								content={group.item}
								plugin={plugin}
								messageId={message.id}
								messageRole={message.role}
								terminalClient={terminalClient}
								onApprovePermission={onApprovePermission}
							/>
						</div>
					);
				}
			})}
			{message.content.some(
				(c) =>
					(c.type === "text" || c.type === "text_with_context") &&
					c.text,
			) && (
				<div className="agent-client-message-actions">
					<CopyButton contents={message.content} />
					<CopyRichButton contents={message.content} />
				</div>
			)}
		</div>
	);
});
