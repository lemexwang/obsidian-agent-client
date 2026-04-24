import * as React from "react";
import { setIcon } from "obsidian";
import type {
	ChatMessage,
	MessageContent,
} from "../../domain/models/chat-message";
import type { IAcpClient } from "../../adapters/acp/acp.adapter";
import type AgentClientPlugin from "../../plugin";
import { MessageContentRenderer } from "./MessageContentRenderer";

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
		return `<code style="background-color: rgba(175,184,193,0.2); padding: 0.2em 0.4em; border-radius: 6px; font-family: ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace; font-size: 85%;">${code}</code>`;
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

/**
 * Copy button for rich text (HTML).
 */
function CopyRichButton({ contents }: { contents: MessageContent[] }) {
	const [copied, setCopied] = React.useState(false);

	const handleCopyRichText = React.useCallback(() => {
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

	const iconRef = React.useCallback(
		(el: HTMLButtonElement | null) => {
			if (el) setIcon(el, copied ? "check" : "file-text");
		},
		[copied],
	);

	return (
		<button
			className="agent-client-message-action-button"
			onClick={handleCopyRichText}
			aria-label="Copy as rich text"
			ref={iconRef}
		/>
	);
}
interface MessageRendererProps {
	message: ChatMessage;
	plugin: AgentClientPlugin;
	acpClient?: IAcpClient;
	/** Callback to approve a permission request */
	onApprovePermission?: (
		requestId: string,
		optionId: string,
	) => Promise<void>;
}

/**
 * Group consecutive image/resource_link contents together for horizontal display.
 * Non-attachment contents are wrapped individually.
 */
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

export const MessageRenderer = React.memo(function MessageRenderer({
	message,
	plugin,
	acpClient,
	onApprovePermission,
}: MessageRendererProps) {
	const groups = groupContent(message.content);
	const [copied, setCopied] = React.useState(false);
	const [hovered, setHovered] = React.useState(false);

	const handleCopy = React.useCallback(() => {
		const text = extractTextContent(message.content);
		if (!text) return;
		void navigator.clipboard.writeText(text).then(() => {
			setCopied(true);
			setTimeout(() => setCopied(false), 2000);
		}).catch(() => {});
	}, [message.content]);

	const copyButtonRef = React.useCallback(
		(el: HTMLButtonElement | null) => {
			if (el) setIcon(el, copied ? "check" : "copy");
		},
		[copied],
	);

	const hasText = message.content.some(
		(c) => (c.type === "text" || c.type === "text_with_context") && c.text,
	);

	return (
		<div
			className={`agent-client-message-renderer ${message.role === "user" ? "agent-client-message-user" : "agent-client-message-assistant"}`}
			onMouseEnter={hasText ? () => setHovered(true) : undefined}
			onMouseLeave={hasText ? () => setHovered(false) : undefined}
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
								<MessageContentRenderer
									key={imgIdx}
									content={content}
									plugin={plugin}
									messageId={message.id}
									messageRole={message.role}
									acpClient={acpClient}
									onApprovePermission={onApprovePermission}
								/>
							))}
						</div>
					);
				} else {
					// Render single non-image content
					return (
						<div key={idx}>
							<MessageContentRenderer
								content={group.item}
								plugin={plugin}
								messageId={message.id}
								messageRole={message.role}
								acpClient={acpClient}
								onApprovePermission={onApprovePermission}
							/>
						</div>
					);
				}
			})}
			{hasText && hovered && (
				<div className="agent-client-message-actions">
					<button
						className="agent-client-message-action-button"
						onClick={handleCopy}
						aria-label="Copy message"
						ref={copyButtonRef}
					/>
				</div>
			)}
		</div>
	);
});
