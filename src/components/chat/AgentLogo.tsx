import * as React from "react";

/**
 * Official SVG logo for Anthropic Claude.
 * Anthropic brand mark (simplified).
 */
const ClaudeSvg = () => (
	<svg
		viewBox="0 0 24 24"
		fill="currentColor"
		xmlns="http://www.w3.org/2000/svg"
		aria-hidden="true"
	>
		<path d="M13.827 3.52h3.603L24 20.48h-3.603l-1.422-4.321H12.19l1.637-3.073h5.209L16.43 7.147ZM8.307 3.52 2.173 20.48H5.76l1.422-4.321h6.563l-1.422-4.321H7.214l2.258-5.027L8.657 3.52z" />
	</svg>
);

/**
 * Official SVG logo for Google Gemini.
 * Gemini 4-pointed star mark.
 */
const GeminiSvg = () => (
	<svg
		viewBox="0 0 24 24"
		fill="currentColor"
		xmlns="http://www.w3.org/2000/svg"
		aria-hidden="true"
	>
		<path d="M12 2C12 8.627 8.627 12 2 12C8.627 12 12 15.373 12 22C12 15.373 15.373 12 22 12C15.373 12 12 8.627 12 2Z" />
	</svg>
);

/**
 * Renders the official AI brand logo based on agent ID.
 * Matches agent IDs containing "claude" or "gemini".
 */
export function AgentLogo({ agentId }: { agentId: string }) {
	const lowerAgentId = agentId.toLowerCase();

	if (lowerAgentId.includes("claude")) {
		return (
			<span className="agent-client-agent-logo agent-client-agent-logo-claude">
				<ClaudeSvg />
			</span>
		);
	}

	if (lowerAgentId.includes("gemini")) {
		return (
			<span className="agent-client-agent-logo agent-client-agent-logo-gemini">
				<GeminiSvg />
			</span>
		);
	}

	return null;
}
