#!/usr/bin/env python3
"""PreToolUse hook: enforces what each tdd-squad agent may read, write and run.

Calls from the main conversation (the orchestrator) and from agents that are
not part of the squad are always allowed.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tdd_common as tc  # noqa: E402

READ_TOOLS = {"Read"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SEARCH_TOOLS = {"Grep"}
LISTING_TOOLS = {"Glob"}
SHELL_TOOLS = {"Bash"}

SHELL_META = re.compile(r"[;&|`$<>\n\r\\]")

CATEGORY_LABEL = {
    "requirements": "the requirements",
    "usecases": "the use case specs",
    "edge_reviews": "the edge-case review files",
    "contracts": "the API contract",
    "tests": "the tests",
    "source": "the production source",
    "other": "files outside the squad's areas (build files, configs, docs)",
    "outside": "files outside the project",
}


def decide(payload):
    """Return None to allow, or a reason string to deny."""
    cwd = payload.get("cwd") or "."
    role = tc.squad_role(payload.get("agent_type"), cwd)
    if role is None:
        return None
    try:
        cfg = tc.load_config(cwd)
    except ValueError as exc:
        return "tdd-squad: %s. Ask the user to fix it or run /tdd-squad:init." % exc
    if cfg is None:
        return "tdd-squad: no .tdd-squad/config.json in this project. Run /tdd-squad:init first."

    tool = payload.get("tool_name", "")
    args = payload.get("tool_input") or {}

    if tool in READ_TOOLS:
        return _check_read(role, args.get("file_path"), cwd, cfg)
    if tool in WRITE_TOOLS:
        return _check_write(role, args.get("file_path") or args.get("notebook_path"), cwd, cfg)
    if tool in SEARCH_TOOLS:
        return _check_search(role, args.get("path"), cwd, cfg)
    if tool in LISTING_TOOLS:
        return None  # file names only, no content
    if tool in SHELL_TOOLS:
        return _check_shell(role, args.get("command", ""), cfg)
    return None


def _check_read(role, path, cwd, cfg):
    cat = tc.categorize(tc.relpath(path, cwd), cfg)
    if cat in tc.READ_DENY[role]:
        return "tdd-squad: %s may not read %s (%s). This is deliberate context isolation; work from what you are allowed to see." % (
            role, CATEGORY_LABEL[cat], path)
    return None


def _check_write(role, path, cwd, cfg):
    cat = tc.categorize(tc.relpath(path, cwd), cfg)
    if cat not in tc.WRITE_ALLOW[role]:
        allowed = ", ".join(CATEGORY_LABEL[c] for c in sorted(tc.WRITE_ALLOW[role]))
        return "tdd-squad: %s may not modify %s (%s). It may only write %s. If the change is really needed, stop and report it." % (
            role, CATEGORY_LABEL[cat], path, allowed)
    return None


def _check_search(role, path, cwd, cfg):
    rel = tc.relpath(path, cwd)
    if rel is None:
        return None
    full = Path(cwd, rel)
    if full.is_file():
        return _check_read(role, path, cwd, cfg)
    if tc.categorize(rel, cfg) in tc.READ_DENY[role]:
        return _check_read(role, path, cwd, cfg)
    for cat in tc.READ_DENY[role]:
        for pattern in cfg["paths"].get(cat, []):
            if tc.scope_may_contain(rel, pattern):
                return "tdd-squad: this Grep scope ('%s') could include %s, which %s may not read. Pass `path` set to a directory you are allowed to read." % (
                    rel or ".", CATEGORY_LABEL[cat], role)
    return None


def _check_shell(role, command, cfg):
    if role not in tc.BASH_ALLOWED:
        return "tdd-squad: %s has no shell access." % role
    cmd = command.strip()
    allowed = cfg.get("test_commands") or []
    if not SHELL_META.search(cmd):
        for prefix in allowed:
            if cmd == prefix or cmd.startswith(prefix + " "):
                return None
    return "tdd-squad: %s may only run the project's test command (one of: %s), with extra arguments but no shell operators. Use the Read/Grep/Glob tools to inspect files." % (
        role, ", ".join(allowed) or "none configured")


def main():
    payload = tc.read_hook_input(sys.stdin)
    reason = decide(payload)
    if reason:
        json.dump({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
