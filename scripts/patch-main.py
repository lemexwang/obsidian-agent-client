#!/usr/bin/env python3
"""
Agent Client main.js patch script.

Applies two patches after every plugin upgrade:
  1. Logo patch  — injects data-agent-label on the header title span so
                   CSS ::before selectors can show per-agent logos.
  2. Codex removal — removes the hard-coded Codex entry from the Switch
                     agent list (bh() function in the bundle).

Usage:
    python3 scripts/patch-main.py

Re-run after each plugin upgrade; the upgrade overwrites main.js and
resets both patches.

Last verified against bundle version: 2026-06-10
  - bundle helper: je.jsx  (was Ge.jsx before 2026-06-10)
  - agent list uses e.codex  (was this.settings.codex before 2026-06-10)
"""

import sys

VAULTS = [
    "/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Alice_Study_2026/.obsidian/plugins/agent-client/main.js",
    "/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Lemex_Vault/.obsidian/plugins/agent-client/main.js",
]

# Patch 1: inject data-agent-label on header title span
LOGO_OLD = '(0,je.jsx)("span",{className:"agent-client-chat-view-header-title",children:e})'
LOGO_NEW = '(0,je.jsx)("span",{className:"agent-client-chat-view-header-title","data-agent-label":e,children:e})'

# Patch 2: remove Codex from agent list function bh(e)
CODEX_OLD = ",{id:e.codex.id,displayName:e.codex.displayName||e.codex.id}"
CODEX_NEW = ""


def patch_file(path: str) -> None:
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        print(f"FILE NOT FOUND: {path}")
        return

    results = []
    changed = False

    # Logo patch
    count = content.count(LOGO_OLD)
    if count > 0:
        content = content.replace(LOGO_OLD, LOGO_NEW, 1)
        results.append(f"logo PATCHED")
        changed = True
    elif LOGO_NEW in content:
        results.append("logo already patched")
    else:
        results.append("logo: target NOT FOUND — bundle variable may have changed")

    # Codex removal
    count = content.count(CODEX_OLD)
    if count > 0:
        content = content.replace(CODEX_OLD, CODEX_NEW)
        results.append(f"codex REMOVED ({count} occurrence)")
        changed = True
    elif "{id:e.codex.id" not in content:
        results.append("codex: already removed")
    else:
        results.append("codex: target NOT FOUND — pattern may have changed")

    if changed:
        with open(path, "w") as f:
            f.write(content)

    vault_name = path.split("/")[-5]
    print(f"{vault_name}: {', '.join(results)}")


if __name__ == "__main__":
    for vault in VAULTS:
        patch_file(vault)
    print("\nDone. Restart Obsidian (or reload the plugin) for changes to take effect.")
