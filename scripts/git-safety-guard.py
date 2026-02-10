#!/usr/bin/env python3
"""PreToolUse safety guard for Claude Code hooks.

Blocks destructive git and filesystem commands mechanically.
Reads JSON from stdin (Claude Code hook format), checks the command
against regex patterns, and outputs JSON allow/deny.

Install:
  1) Copy to ~/.local/bin/git-safety-guard.py
  2) chmod +x ~/.local/bin/git-safety-guard.py
  3) Wire in .claude/settings.json (see repo AGENTS.md for the recommended format)

The hook receives the tool input as JSON on stdin and must output
JSON with {"allow": true/false, "reason": "...", "hint": "..."}.
Exit code 0 = allow, exit code 2 = deny.
"""

from __future__ import annotations

import json
import re
import sys


def _normalize_absolute_paths(cmd: str) -> str:
    """Normalize absolute tool paths at the start of the command.

    Without this, agents can bypass regex matching by invoking /bin/git or /usr/bin/rm.
    """

    if not cmd:
        return cmd
    result = cmd.lstrip()
    result = re.sub(r"^/(?:\\S*/)*s?bin/rm(?=\\s|$)", "rm", result)
    result = re.sub(r"^/(?:\\S*/)*s?bin/git(?=\\s|$)", "git", result)
    return result


BLOCK_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"\bgit\s+reset\s+--hard\b",
        "git reset --hard destroys uncommitted work irreversibly",
        "Use 'git stash' to save changes, or 'git diff' to review first",
    ),
    (
        r"\bgit\s+clean\s+-[^\s]*f\b",
        "git clean -f deletes untracked files without recovery",
        "Use 'git status' to review untracked files first",
    ),
    (
        r"\bgit\s+checkout\s+--\s",
        "git checkout -- discards working tree changes",
        "Use 'git stash' or 'git diff <path>' to review first",
    ),
    (
        r"\bgit\s+checkout\s+\.\s*$",
        "git checkout . discards working tree changes",
        "Use 'git diff' to review changes and 'git stash' to save them",
    ),
    (
        r"\bgit\s+restore\s+(?!.*--staged)",
        "git restore (without --staged) discards working tree changes",
        "Use 'git restore --staged <path>' to unstage, or 'git diff' to review",
    ),
    (
        r"\bgit\s+push\b.*\s--force-with-lease\b",
        "git push --force-with-lease rewrites remote history",
        "Use 'git push' (non-force) or coordinate a safe rebase/merge first",
    ),
    (
        r"\bgit\s+push\b.*\s--force\b",
        "git push --force rewrites remote history",
        "Use 'git push' (non-force) or coordinate a safe rebase/merge first",
    ),
    (
        r"\bgit\s+push\b.*\s-f\b",
        "git push -f rewrites remote history",
        "Use 'git push' (non-force) or coordinate a safe rebase/merge first",
    ),
    (
        r"\bgit\s+branch\s+-D\b",
        "git branch -D force-deletes a branch even if unmerged",
        "Use 'git branch -d' (lowercase) which refuses to delete unmerged branches",
    ),
    (
        r"\bgit\s+rebase\s+-i\b",
        "Interactive rebase requires TTY input and blocks agent sessions",
        "Use non-interactive rebase or individual git commands",
    ),
    (
        r"\bgit\s+add\s+-i\b",
        "Interactive add requires TTY input and blocks agent sessions",
        "Use 'git add <specific-files>' instead",
    ),
    (
        r"\bgit\s+add\s+-A\b",
        "git add -A is too broad for multi-agent work and makes reviews harder",
        "Use 'git add <specific-files>' instead",
    ),
    (
        r"\bgit\s+add\s+\.\s*$",
        "git add . is too broad for multi-agent work and makes reviews harder",
        "Use 'git add <specific-files>' instead",
    ),
    (
        r"\bgit\s+stash\s+drop\b",
        "git stash drop destroys a stash entry",
        "Use 'git stash list' and 'git stash show' to review first",
    ),
    (
        r"\bgit\s+stash\s+clear\b",
        "git stash clear destroys all stash entries",
        "Use 'git stash list' to review what would be lost",
    ),
    (
        r"\brm\s+-[^\s]*r[^\s]*\b",
        "rm -r / rm -rf is a destructive filesystem operation",
        "Use 'ls' to verify paths, or use 'trash <path>' only with explicit human approval",
    ),
    (
        r"\btrash\s+.*AGENTS\.md\b",
        "Deleting AGENTS.md is explicitly disallowed",
        "Edit AGENTS.md instead, do not delete it",
    ),
    (
        r"\btrash\s+.*NOTES\.md\b",
        "Deleting NOTES.md is explicitly disallowed",
        "Edit NOTES.md instead, do not delete it",
    ),
    (
        r"\btruncate\b",
        "truncate can destroy file contents without an easy recovery path",
        "Use an editor patch, or write to a new file and review diff first",
    ),
    (
        r">\s*/dev/null\s*2>&1.*\brm\b",
        "Obfuscated deletion detected (rm combined with output redirection)",
        "Run the command without obfuscation and review target paths first",
    ),
]


def extract_command(payload: str) -> str:
    """Extract the command string from the hook payload."""

    try:
        obj = json.JSONDecoder().decode(payload)
        if isinstance(obj, dict):
            tool_input = obj.get("tool_input", {})
            if isinstance(tool_input, dict) and "command" in tool_input:
                return str(tool_input["command"])
            if "command" in obj:
                return str(obj["command"])
            if "input" in obj:
                return str(obj["input"])
    except Exception:
        return payload
    return payload


def check_command(cmd: str) -> tuple[str, str] | None:
    """Return (reason, hint) if blocked, else None."""

    for pattern, reason, hint in BLOCK_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return reason, hint
    return None


def main() -> int:
    payload = sys.stdin.read().strip()
    if not payload:
        sys.stdout.write(json.dumps({"allow": True}))
        return 0

    cmd = _normalize_absolute_paths(extract_command(payload)).strip()
    result = check_command(cmd)
    if result is not None:
        reason, hint = result
        sys.stdout.write(json.dumps({"allow": False, "reason": f"BLOCKED by safety guard: {reason}", "hint": hint}))
        return 2

    sys.stdout.write(json.dumps({"allow": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
