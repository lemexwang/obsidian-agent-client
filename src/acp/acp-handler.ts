import * as acp from "@agentclientprotocol/sdk";

import type { SessionUpdate } from "../types/session";
import { AcpTypeConverter } from "./type-converter";
import type { PermissionManager } from "./permission-handler";
import type { TerminalManager } from "./terminal-handler";
import type { Logger } from "../utils/logger";

/**
 * Handles incoming ACP protocol events from the agent.
 *
 * Implements the acp.Client interface to receive session updates,
 * permission requests, and terminal operations from the SDK's
 * ClientSideConnection dispatch.
 *
 * This class does not initiate communication — that is AcpClient's role.
 * It only reacts to events from the agent side.
 */
export class AcpHandler {
	private sessionUpdateListeners = new Set<(update: SessionUpdate) => void>();

	/** Tracks session updates during a prompt. */
	private promptSessionUpdateCount = 0;

	/** State for parsing <think>...</think> tags across streaming chunks. */
	private isInThinkingMode = false;
	private pendingTagBuffer = "";

	constructor(
		private permissionManager: PermissionManager,
		private terminalManager: TerminalManager,
		private getWorkingDirectory: () => string,
		private getCurrentSessionId: () => string | null,
		private logger: Logger,
	) {}

	// ====================================================================
	// Callback Registration
	// ====================================================================

	/** Reset the update counter and think-tag parser state. Called by AcpClient before each sendPrompt. */
	resetUpdateCount(): void {
		this.promptSessionUpdateCount = 0;
		this.isInThinkingMode = false;
		this.pendingTagBuffer = "";
	}

	/** Whether any session update was received since the last reset. */
	hasReceivedUpdates(): boolean {
		return this.promptSessionUpdateCount > 0;
	}

	onSessionUpdate(callback: (update: SessionUpdate) => void): () => void {
		this.sessionUpdateListeners.add(callback);
		return () => this.sessionUpdateListeners.delete(callback);
	}

	/** Emit a session update to all listeners. Filters by current sessionId. */
	emitSessionUpdate(update: SessionUpdate): void {
		const currentId = this.getCurrentSessionId();
		if (currentId && update.sessionId !== currentId) {
			return;
		}
		for (const listener of this.sessionUpdateListeners) {
			listener(update);
		}
	}

	// ====================================================================
	// ACP Client Protocol Handlers (called by ClientSideConnection)
	// ====================================================================

	sessionUpdate(params: acp.SessionNotification): Promise<void> {
		const update = params.update;
		const sessionId = params.sessionId;
		this.promptSessionUpdateCount++;
		this.logger.log("[AcpHandler] sessionUpdate:", { sessionId, update });

		switch (update.sessionUpdate) {
			case "agent_message_chunk":
				if (update.content.type === "text") {
					this.parseAndEmitTextChunk(update.content.text, sessionId);
				}
				break;
			case "agent_thought_chunk":
			case "user_message_chunk":
				if (update.content.type === "text") {
					this.emitSessionUpdate({
						type: update.sessionUpdate,
						sessionId,
						text: update.content.text,
					});
				}
				break;

			case "tool_call":
			case "tool_call_update":
				this.emitSessionUpdate({
					type: update.sessionUpdate,
					sessionId,
					toolCallId: update.toolCallId,
					title: update.title ?? undefined,
					status: update.status || "pending",
					kind: update.kind ?? undefined,
					content: AcpTypeConverter.toToolCallContent(update.content),
					locations: update.locations ?? undefined,
					rawInput: update.rawInput as
						| { [k: string]: unknown }
						| undefined,
				});
				break;

			case "plan":
				this.emitSessionUpdate({
					type: "plan",
					sessionId,
					entries: update.entries,
				});
				break;

			case "available_commands_update":
				this.emitSessionUpdate({
					type: "available_commands_update",
					sessionId,
					commands: AcpTypeConverter.toSlashCommands(
						update.availableCommands,
					),
				});
				break;

			case "current_mode_update":
				this.emitSessionUpdate({
					type: "current_mode_update",
					sessionId,
					currentModeId: update.currentModeId,
				});
				break;

			case "session_info_update":
				this.emitSessionUpdate({
					type: "session_info_update",
					sessionId,
					title: update.title,
					updatedAt: update.updatedAt,
				});
				break;

			case "usage_update":
				this.emitSessionUpdate({
					type: "usage_update",
					sessionId,
					size: update.size,
					used: update.used,
					cost: update.cost ?? undefined,
				});
				break;

			case "config_option_update":
				this.emitSessionUpdate({
					type: "config_option_update",
					sessionId,
					configOptions: AcpTypeConverter.toSessionConfigOptions(
						update.configOptions,
					),
				});
				break;
		}
		return Promise.resolve();
	}

	requestPermission(
		params: acp.RequestPermissionRequest,
	): Promise<acp.RequestPermissionResponse> {
		return this.permissionManager.request(params);
	}

	// ====================================================================
	// ACP Extension Handlers
	// ====================================================================

	async extNotification(
		method: string,
		params: Record<string, unknown>,
	): Promise<void> {
		this.logger.log(
			`[AcpHandler] Extension notification received: ${method}`,
			params,
		);
	}

	// ====================================================================
	// File System Stubs
	// ====================================================================

	readTextFile(params: acp.ReadTextFileRequest) {
		return Promise.resolve({ content: "" });
	}

	writeTextFile(params: acp.WriteTextFileRequest) {
		return Promise.resolve({});
	}

	// ====================================================================
	// Terminal Operations (called by ClientSideConnection)
	// ====================================================================

	createTerminal(
		params: acp.CreateTerminalRequest,
	): Promise<acp.CreateTerminalResponse> {
		this.logger.log(
			"[AcpHandler] createTerminal called with params:",
			params,
		);

		const terminalId = this.terminalManager.createTerminal({
			command: params.command,
			args: params.args,
			cwd: params.cwd || this.getWorkingDirectory(),
			env: params.env ?? undefined,
			outputByteLimit: params.outputByteLimit ?? undefined,
		});
		return Promise.resolve({ terminalId });
	}

	terminalOutput(
		params: acp.TerminalOutputRequest,
	): Promise<acp.TerminalOutputResponse> {
		const result = this.terminalManager.getOutput(params.terminalId);
		if (!result) {
			throw new Error(`Terminal ${params.terminalId} not found`);
		}
		return Promise.resolve(result);
	}

	async waitForTerminalExit(
		params: acp.WaitForTerminalExitRequest,
	): Promise<acp.WaitForTerminalExitResponse> {
		return await this.terminalManager.waitForExit(params.terminalId);
	}

	killTerminal(
		params: acp.KillTerminalCommandRequest,
	): Promise<acp.KillTerminalCommandResponse> {
		const success = this.terminalManager.killTerminal(params.terminalId);
		if (!success) {
			throw new Error(`Terminal ${params.terminalId} not found`);
		}
		return Promise.resolve({});
	}

	releaseTerminal(
		params: acp.ReleaseTerminalRequest,
	): Promise<acp.ReleaseTerminalResponse> {
		const success = this.terminalManager.releaseTerminal(params.terminalId);
		if (!success) {
			this.logger.log(
				`[AcpHandler] releaseTerminal: Terminal ${params.terminalId} not found (may have been already cleaned up)`,
			);
		}
		return Promise.resolve({});
	}

	// ====================================================================
	// <think> Tag Parser (for models that inline reasoning in output)
	// ====================================================================

	/**
	 * Parse a streaming text chunk, splitting on <think>...</think> tags.
	 * Content inside the tags is emitted as agent_thought_chunk; content outside
	 * is emitted as agent_message_chunk. Handles tags split across chunk boundaries
	 * by buffering the incomplete tag suffix until the next chunk arrives.
	 */
	private parseAndEmitTextChunk(rawText: string, sessionId: string): void {
		let text = this.pendingTagBuffer + rawText;
		this.pendingTagBuffer = "";

		while (text.length > 0) {
			if (this.isInThinkingMode) {
				const closeIdx = text.indexOf("</think>");
				if (closeIdx === -1) {
					const partial = this.findPartialTagSuffix(text, "</think>");
					if (partial > 0) {
						const emit = text.slice(0, text.length - partial);
						if (emit) this.emitSessionUpdate({ type: "agent_thought_chunk", sessionId, text: emit });
						this.pendingTagBuffer = text.slice(text.length - partial);
					} else {
						this.emitSessionUpdate({ type: "agent_thought_chunk", sessionId, text });
					}
					return;
				}
				const thinkContent = text.slice(0, closeIdx);
				if (thinkContent) this.emitSessionUpdate({ type: "agent_thought_chunk", sessionId, text: thinkContent });
				this.isInThinkingMode = false;
				text = text.slice(closeIdx + "</think>".length);
			} else {
				const openIdx = text.indexOf("<think>");
				if (openIdx === -1) {
					const partial = this.findPartialTagSuffix(text, "<think>");
					if (partial > 0) {
						const emit = text.slice(0, text.length - partial);
						if (emit) this.emitSessionUpdate({ type: "agent_message_chunk", sessionId, text: emit });
						this.pendingTagBuffer = text.slice(text.length - partial);
					} else {
						this.emitSessionUpdate({ type: "agent_message_chunk", sessionId, text });
					}
					return;
				}
				const normalContent = text.slice(0, openIdx);
				if (normalContent) this.emitSessionUpdate({ type: "agent_message_chunk", sessionId, text: normalContent });
				this.isInThinkingMode = true;
				text = text.slice(openIdx + "<think>".length);
			}
		}
	}

	/**
	 * Return the length of the longest prefix of `tag` that `text` ends with.
	 * Used to detect a tag split across chunk boundaries.
	 */
	private findPartialTagSuffix(text: string, tag: string): number {
		const maxLen = Math.min(tag.length - 1, text.length);
		for (let len = maxLen; len >= 1; len--) {
			if (text.endsWith(tag.slice(0, len))) return len;
		}
		return 0;
	}
}
