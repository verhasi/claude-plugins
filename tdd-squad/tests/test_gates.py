import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import gates  # noqa: E402

# A fake test runner: each "@Test name" in src/test/*.txt is a test; it fails
# when the matching "impl name" line is missing from src/main/impl.txt.
# Writes a JUnit report unless src/main/broken exists (simulates a compile error).
RUNNER = r'''
import pathlib, sys
root = pathlib.Path(".")
if (root / "src/main/broken").exists():
    print("COMPILATION ERROR"); sys.exit(1)
impl = (root / "src/main/impl.txt").read_text().split() if (root / "src/main/impl.txt").exists() else []
cases, failed = [], 0
for f in sorted((root / "src/test").glob("*.txt")):
    for line in f.read_text().splitlines():
        if line.startswith("@Test"):
            name = line.split()[1]
            ok = name in impl
            failed += not ok
            cases.append('<testcase classname="T" name="%s">%s</testcase>' % (name, "" if ok else "<failure/>"))
(root / "reports").mkdir(exist_ok=True)
(root / "reports/TEST-T.xml").write_text("<testsuite>%s</testsuite>" % "".join(cases))
print("%d tests, %d failed" % (len(cases), failed))
sys.exit(1 if failed else 0)
'''


def test_block(name, quote=True):
    doc = "/** Feature: F\n * Use Case: UC1\n * Spec: \"%s\"\n */\n" % name if quote else ""
    return doc + "@Test %s\n" % name


class GateTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        r = Path(self.root)
        (r / "src/test").mkdir(parents=True)
        (r / "src/main").mkdir(parents=True)
        (r / "run.py").write_text(RUNNER)
        (r / ".tdd-squad").mkdir()
        (r / ".tdd-squad/config.json").write_text(json.dumps({
            "test_commands": ["%s run.py" % sys.executable],
            "paths": {"tests": ["src/test/**"], "source": ["src/main/**"]},
            "junit_reports": ["reports/*.xml"],
            "max_gate_retries": 2,
        }))
        (r / ".gitignore").write_text(".tdd-squad/state/\nreports/\n")
        (r / "src/test/CalcTest.txt").write_text(test_block("empty"))
        (r / "src/main/impl.txt").write_text("empty\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")

    def tearDown(self):
        shutil.rmtree(self.root)

    def git(self, *args):
        subprocess.run(["git"] + list(args), cwd=self.root, check=True)

    def write(self, rel, text):
        Path(self.root, rel).write_text(text)

    def append_test(self, name, quote=True):
        p = Path(self.root, "src/test/CalcTest.txt")
        p.write_text(p.read_text() + test_block(name, quote))

    def stop(self, agent, message=None, agent_id="a1"):
        payload = {"cwd": self.root, "agent_type": "tdd-squad:" + agent, "agent_id": agent_id}
        if message is not None:
            payload["last_assistant_message"] = message
        return gates.evaluate(payload)

    def last_gate(self):
        return json.loads(Path(self.root, ".tdd-squad/state/last-gate.json").read_text())

    # --- red-test

    def test_one_new_failing_traced_test_passes(self):
        self.append_test("single")
        self.assertEqual(self.stop("red-test"), (None, None))
        self.assertEqual(self.last_gate()["status"], "pass")
        self.assertIn("T.single", self.last_gate()["detail"])

    def test_new_test_that_already_passes_is_rejected(self):
        self.write("src/main/impl.txt", "empty single\n")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "impl")
        self.append_test("single")
        decision, reason = self.stop("red-test")
        self.assertEqual(decision, "block")
        self.assertIn("PASSES", reason)

    def test_two_new_tests_are_rejected(self):
        self.append_test("single")
        self.append_test("many")
        decision, reason = self.stop("red-test")
        self.assertEqual(decision, "block")
        self.assertIn("ONE new test", reason)

    def test_missing_spec_quote_is_rejected(self):
        self.append_test("single", quote=False)
        decision, reason = self.stop("red-test")
        self.assertEqual(decision, "block")
        self.assertIn("Spec:", reason)

    def test_new_test_file_counts(self):
        self.write("src/test/OtherTest.txt", test_block("other"))
        self.assertEqual(self.stop("red-test"), (None, None))

    def test_compile_failure_counts_as_red(self):
        self.append_test("single")
        self.write("src/main/broken", "")
        self.assertEqual(self.stop("red-test"), (None, None))
        self.assertIn("build failed", self.last_gate()["detail"])

    def test_complete_without_changes(self):
        self.assertEqual(self.stop("red-test", message="COMPLETE"), (None, None))

    def test_no_changes_and_no_complete_is_rejected(self):
        decision, _ = self.stop("red-test", message="I think we are done")
        self.assertEqual(decision, "block")

    def test_another_test_breaking_is_rejected(self):
        self.write("src/main/impl.txt", "nothing\n")  # breaks "empty" (not allowed for red-test anyway)
        self.append_test("single")
        decision, reason = self.stop("red-test")
        self.assertEqual(decision, "block")
        self.assertIn("2 fail", reason)

    # --- green / blue

    def test_green_must_leave_suite_passing(self):
        self.append_test("single")
        decision, reason = self.stop("green")
        self.assertEqual(decision, "block")
        self.assertIn("does not pass", reason)
        self.write("src/main/impl.txt", "empty single\n")
        self.assertEqual(self.stop("green"), (None, None))

    def test_gives_up_after_max_retries(self):
        self.append_test("single")
        self.assertEqual(self.stop("blue-clean")[0], "block")
        self.assertEqual(self.stop("blue-clean")[0], "block")
        self.assertEqual(self.stop("blue-clean"), (None, None))
        self.assertEqual(self.last_gate()["status"], "gave-up")

    def test_red_contract_and_other_agents_are_not_gated(self):
        self.assertEqual(self.stop("red-contract"), (None, None))
        self.assertEqual(gates.evaluate({"cwd": self.root, "agent_type": "Explore"}), (None, None))

    def test_script_emits_block_json(self):
        self.append_test("single")
        payload = json.dumps({"cwd": self.root, "agent_type": "tdd-squad:green", "agent_id": "z"})
        out = subprocess.run([sys.executable, str(SCRIPTS / "gates.py")], input=payload,
                             stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
        self.assertEqual(json.loads(out)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
