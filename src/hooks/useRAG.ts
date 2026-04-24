import { useCallback } from "react";
import type { IVaultAccess } from "../domain/ports/vault-access.port";
import { getLogger } from "../shared/logger";

const logger = getLogger();

// Configuration for RAG
const TOP_N_RESULTS = 3; // Number of top search results to retrieve
const MAX_NOTE_LENGTH = 4000; // Max characters to take from each note
const MAX_TOTAL_CONTEXT_LENGTH = 8000; // Max total characters for the context

export interface UseRAGReturn {
	retrieveContext: (query: string) => Promise<string>;
}

/**
 * Hook for Retrieval-Augmented Generation (RAG).
 * Provides a function to search the vault and retrieve context for a given query.
 *
 * @param vaultAccess - The vault access adapter.
 */
export function useRAG(vaultAccess: IVaultAccess): UseRAGReturn {
	const retrieveContext = useCallback(
		async (query: string): Promise<string> => {
			if (!query) {
				return "";
			}

			logger.log(`Starting RAG retrieval for query: "${query}"`);

			try {
				const searchResults = await vaultAccess.searchNotes(query);
				if (!searchResults || searchResults.length === 0) {
					logger.log("No notes found for query.");
					return "";
				}

				const topResults = searchResults.slice(0, TOP_N_RESULTS);
				logger.log(
					`Found ${searchResults.length} notes, processing top ${topResults.length}.`
				);

				const contextPromises = topResults.map(async (note) => {
					try {
						const content = await vaultAccess.readNote(note.path);
						const truncatedContent = content.slice(
							0,
							MAX_NOTE_LENGTH
						);
						return `---
File: ${note.path}
Content:
${truncatedContent}
---`;
					} catch (error) {
						logger.error(`Failed to read note: ${note.path}`, error);
						return null; // Return null for failed reads
					}
				});

				const contexts = (await Promise.all(contextPromises)).filter(
					(c): c is string => c !== null
				);

				if (contexts.length === 0) {
					logger.log("No content could be retrieved from notes.");
					return "";
				}

				let combinedContext = contexts.join("\n\n");

				if (combinedContext.length > MAX_TOTAL_CONTEXT_LENGTH) {
					combinedContext = combinedContext.slice(
						0,
						MAX_TOTAL_CONTEXT_LENGTH,
					);
					logger.log(
						`Combined context truncated to ${MAX_TOTAL_CONTEXT_LENGTH} characters.`,
					);
				}

				const finalContext = `--- Retrieved Context from Obsidian Vault ---\n\n${combinedContext}\n\n--- End of Context ---`;

				logger.log(
					`Successfully retrieved ${finalContext.length} characters of context.`,
				);
				return finalContext;
			} catch (error) {
				logger.error("An error occurred during RAG retrieval:", error);
				return ""; // Return empty string on error
			}
		},
		[vaultAccess]
	);

	return {
		retrieveContext,
	};
}
