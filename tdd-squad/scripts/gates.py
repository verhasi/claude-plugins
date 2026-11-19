#!/usr/bin/env python3
"""SubagentStop hook: deterministic quality gates for the tdd-squad loop.

red-test     one new test per round, it must fail, every test carries a spec quote
green        whole suite passes
blue-intent  whole suite passes
blue-clean   whole suite passes

A failing gate keeps the agent working (decision "block") up to
max_gate_retries times; after that the agent may stop and the failure is
recorded for the orchestrator in .tdd-squad/state/last-gate.json.
"""
import glob
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tdd_common as tc  # noqa: E402

OUTPUT_TAIL_LINES = 60


# ---------------------------------------------------------------- helpers

def run_tests(cfg, cwd):
    """Run the gate test command. Returns (exit_code, output_tail, started_at)."""
    command = cfg.get("gate_command") or (cfg["test_commands"][0] if cfg["test_commands"] else None)
    if not command:
        return None, "no test command configured in .tdd-squad/config.json", time.time()
    started = time.time()
    try:
        proc = subprocess.run(
            shlex.split(command), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=cfg["test_timeout_seconds"], universal_newlines=True, errors="replace",
        )
    except FileNotFoundError:
        return None, "test command not found: %s" % command, started
    except subprocess.TimeoutExpired:
        return None, "test command timed out after %ss" % cfg["test_timeout_seconds"], started
    tail = "\n".join(proc.stdout.splitlines()[-OUTPUT_TAIL_LINES:])
    return proc.returncode, tail, started


def fresh_report_failures(cfg, cwd, since):
    """Count failing/erroring test cases in JUnit XML reports written after `since`.

    Returns None if no fresh reports were found (e.g. the build failed before tests ran).
    """
    import xml.etree.ElementTree as ET

    files = set()
    for pattern in cfg.get("junit_reports") or []:
        files.update(glob.glob(os.path.join(cwd, pattern), recursive=True))
    fresh = [f for f in files if os.path.getmtime(f) >= since - 1]
    if not fresh:
        return None
    failing = []
    for path in fresh:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for case in root.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failing.append("%s.%s" % (case.get("classname", "?"), case.get("name", "?")))
    return failing


def git(args, cwd):
    proc = subprocess.run(["git"] + args, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, universal_newlines=True, errors="replace")
    return proc.stdout if proc.returncode == 0 else ""


def changed_files(cwd):
    """Return [(status, path)] for files changed against HEAD, including untracked ones."""
    result = []
    for line in git(["status", "--porcelain", "--untracked-files=all"], cwd).splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        result.append((status, path.strip('"')))
    return result


def count_markers(lines, markers):
    return sum(1 for line in lines if any(m in line for m in markers))


def marker_delta(status, path, cwd, markers):
    """Net number of test markers added to a file compared with HEAD."""
    if status == "??":
        try:
            text = Path(cwd, path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0
        return count_markers(text.splitlines(), markers)
    diff = git(["diff", "HEAD", "--", path], cwd).splitlines()
    added = [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in diff if l.startswith("-") and not l.startswith("---")]
    return count_markers(added, markers) - count_markers(removed, markers)


def missing_traceability(paths, cwd, cfg):
    """Test files that have more test markers than spec-quote markers."""
    bad = []
    for path in paths:
        try:
            lines = Path(cwd, path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        tests = count_markers(lines, cfg["test_markers"])
        quotes = count_markers(lines, [cfg["trace_marker"]])
        if quotes < tests:
            bad.append("%s (%d tests, %d spec quotes)" % (path, tests, quotes))
    return bad


# ---------------------------------------------------------------- gates

def gate_red_test(payload, cfg, cwd):
    changes = [(s, p) for s, p in changed_files(cwd)
               if tc.categorize(p, cfg) == "tests" and "D" not in s]
    message = payload.get("last_assistant_message")

    if not changes:
        if message is not None and "COMPLETE" not in message:
            return "fail", ("You changed no test file and did not answer COMPLETE. Either write exactly ONE new "
                            "failing test for an untested spec-derivable behavior, or answer COMPLETE.")
        return "pass", "COMPLETE"

    bad = missing_traceability([p for _, p in changes], cwd, cfg)
    if bad:
        return "fail", ("Every test needs a traceability doc comment with Feature, Use Case and a %s line quoting "
                        "the spec. Missing in: %s" % (cfg["trace_marker"], "; ".join(bad)))

    new_tests = sum(marker_delta(s, p, cwd, cfg["test_markers"]) for s, p in changes)
    if new_tests > 1:
        return "fail", ("You added %d tests. Write exactly ONE new test per round; keep the most fundamental one "
                        "and remove the others (they will come in later rounds)." % new_tests)
    if new_tests < 1:
        return "pass", "existing tests edited, no new test"

    code, tail, started = run_tests(cfg, cwd)
    if code is None:
        return "fail", "Could not run the tests: %s" % tail
    if code == 0:
        return "fail", ("Your new test PASSES without any production change, so it does not drive new behavior. "
                        "Replace it with a test for a behavior that is not implemented yet, or answer COMPLETE.")
    failing = fresh_report_failures(cfg, cwd, started)
    if failing is None:
        return "pass", "red (build failed before tests ran, e.g. code not written yet)"
    if len(failing) != 1:
        return "fail", ("Expected exactly one failing test (yours), but %d fail: %s. Only your new test may fail; "
                        "fix or narrow it." % (len(failing), ", ".join(failing[:10])))
    return "pass", "red: %s" % failing[0]


def gate_suite_green(payload, cfg, cwd):
    code, tail, _ = run_tests(cfg, cwd)
    if code is None:
        return "fail", "Could not run the tests: %s" % tail
    if code != 0:
        return "fail", "The test suite does not pass. Make it pass before finishing.\n\nLast output:\n%s" % tail
    return "pass", "suite green"


GATES = {
    "red-test": gate_red_test,
    "green": gate_suite_green,
    "blue-intent": gate_suite_green,
    "blue-clean": gate_suite_green,
}


# ---------------------------------------------------------------- main

def evaluate(payload):
    """Return (decision, reason) where decision is None (allow stop) or 'block'."""
    cwd = payload.get("cwd") or "."
    role = tc.squad_role(payload.get("agent_type"), cwd)
    if role is None or role not in GATES:
        return None, None
    try:
        cfg = tc.load_config(cwd)
    except ValueError:
        cfg = None
    if cfg is None:
        return None, None

    state = tc.state_dir(cwd)
    agent_id = payload.get("agent_id") or role
    counter = state / ("retries-%s.json" % "".join(c for c in agent_id if c.isalnum() or c in "-_"))
    retries = json.loads(counter.read_text()) if counter.exists() else 0

    status, detail = GATES[role](payload, cfg, cwd)

    record = {"agent": role, "agent_id": agent_id, "status": status, "detail": detail,
              "retries": retries, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if status == "fail" and retries >= cfg["max_gate_retries"]:
        record["status"] = "gave-up"
    (state / "last-gate.json").write_text(json.dumps(record, indent=2))

    if status == "fail" and record["status"] != "gave-up":
        counter.write_text(json.dumps(retries + 1))
        return "block", "tdd-squad gate (%s, attempt %d of %d): %s" % (
            role, retries + 1, cfg["max_gate_retries"], detail)
    if counter.exists():
        counter.unlink()
    return None, None


def main():
    payload = tc.read_hook_input(sys.stdin)
    decision, reason = evaluate(payload)
    if decision:
        json.dump({"decision": decision, "reason": reason}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
