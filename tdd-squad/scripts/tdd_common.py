"""Shared helpers for the tdd-squad hooks.

Standard library only, Python 3.8+.
"""
import fnmatch
import json
import os
from pathlib import Path

PLUGIN_PREFIX = "tdd-squad:"
SQUAD = ("red-contract", "red-test", "green", "blue-intent", "blue-clean")
CONFIG_REL = os.path.join(".tdd-squad", "config.json")
STATE_REL = os.path.join(".tdd-squad", "state")

# Path categories, checked in this order; the first match wins.
# "contracts" is checked before "source" so that contract types living in the
# source tree are treated as the frozen API, not as ordinary source.
CATEGORIES = ("requirements", "usecases", "edge_reviews", "contracts", "tests", "source")

DEFAULT_PATHS = {
    "requirements": ["requirements.md"],
    "usecases": ["usecases.md"],
    "edge_reviews": ["edge-cases-review-*.md"],
    "contracts": ["contracts/**"],
    "tests": [],
    "source": [],
}

# What each agent may READ (categories not listed are readable).
READ_DENY = {
    "red-contract": {"requirements", "edge_reviews", "tests", "source"},
    "red-test": {"requirements", "source"},
    "green": {"requirements", "usecases", "edge_reviews"},
    "blue-intent": {"requirements"},
    "blue-clean": {"requirements", "usecases", "edge_reviews"},
}

# What each agent may WRITE (everything else is denied).
WRITE_ALLOW = {
    "red-contract": {"contracts"},
    "red-test": {"tests", "edge_reviews"},
    "green": {"source"},
    "blue-intent": {"source", "edge_reviews"},
    "blue-clean": {"source"},
}

# Agents that may run the configured test commands through Bash.
BASH_ALLOWED = {"red-test", "green", "blue-intent", "blue-clean"}


def squad_role(agent_type, cwd):
    """Return the squad role for a hook call, or None if the hook should ignore it.

    Plugin agents may be reported as "tdd-squad:green" or as "green". The bare
    form is only claimed when the project has a tdd-squad config, so an
    unrelated user agent called "green" elsewhere is left alone.
    """
    if not agent_type:
        return None
    if agent_type.startswith(PLUGIN_PREFIX):
        role = agent_type[len(PLUGIN_PREFIX):]
        return role if role in SQUAD else None
    if agent_type in SQUAD and Path(cwd, CONFIG_REL).is_file():
        return agent_type
    return None


def load_config(cwd):
    """Load .tdd-squad/config.json. Returns None if missing; raises ValueError if invalid."""
    path = Path(cwd, CONFIG_REL)
    if not path.is_file():
        return None
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read %s: %s" % (CONFIG_REL, exc))
    paths = dict(DEFAULT_PATHS)
    paths.update(cfg.get("paths") or {})
    cfg["paths"] = paths
    cfg.setdefault("test_commands", [])
    cfg.setdefault("test_markers", ["@Test", "@ParameterizedTest", "@RepeatedTest", "@Property"])
    cfg.setdefault("trace_marker", "Spec:")
    cfg.setdefault("junit_reports", [])
    cfg.setdefault("max_gate_retries", 3)
    cfg.setdefault("test_timeout_seconds", 540)
    return cfg


def relpath(path, cwd):
    """Project-relative POSIX path, or None if the path is outside the project."""
    if path is None or path == "":
        path = "."
    root = os.path.realpath(cwd)
    full = path if os.path.isabs(path) else os.path.join(root, path)
    full = os.path.realpath(full)
    if full == root:
        return ""
    if not full.startswith(root + os.sep):
        return None
    return Path(os.path.relpath(full, root)).as_posix()


def _match(rel, pattern):
    if fnmatch.fnmatchcase(rel, pattern):
        return True
    # Let "**/x" also match "x" at the project root.
    if pattern.startswith("**/") and fnmatch.fnmatchcase(rel, pattern[3:]):
        return True
    # Let "dir/**" also match "dir" itself.
    if pattern.endswith("/**") and rel == pattern[:-3]:
        return True
    return False


def categorize(rel, cfg):
    """Return the category of a project-relative path, or "other"."""
    if rel is None:
        return "outside"
    for cat in CATEGORIES:
        for pattern in cfg["paths"].get(cat, []):
            if _match(rel, pattern):
                return cat
    return "other"


def literal_prefix(pattern):
    """The text of a glob before its first wildcard, e.g. 'src/main/**' -> 'src/main/'."""
    for i, ch in enumerate(pattern):
        if ch in "*?[":
            return pattern[:i]
    return pattern


def scope_may_contain(scope_rel, pattern):
    """True if a directory search rooted at scope_rel could reach files matching pattern.

    Every path under the scope starts with "<scope>/" and every path matching the
    pattern starts with its literal prefix, so they can only overlap if one of
    those two strings is a prefix of the other.
    """
    if scope_rel == "":
        return True
    prefix = literal_prefix(pattern)
    scope = scope_rel + "/"
    return prefix.startswith(scope) or scope.startswith(prefix)


def state_dir(cwd):
    path = Path(cwd, STATE_REL)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_hook_input(stream):
    data = stream.read()
    return json.loads(data) if data.strip() else {}
