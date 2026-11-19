import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import isolation  # noqa: E402

CONFIG = {
    "test_commands": ["mvn test", "./mvnw test"],
    "paths": {
        "contracts": ["src/main/java/**/api/**"],
        "tests": ["src/test/**"],
        "source": ["src/main/**"],
    },
}


class IsolationTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for rel in ["requirements.md", "usecases.md", "edge-cases-review-uc1.md", "pom.xml",
                    "src/main/java/com/x/api/Calculator.java", "src/main/java/com/x/CalculatorImpl.java",
                    "src/test/java/com/x/CalculatorTest.java"]:
            p = Path(self.root, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
        Path(self.root, ".tdd-squad").mkdir()
        Path(self.root, ".tdd-squad/config.json").write_text(json.dumps(CONFIG))

    def tearDown(self):
        shutil.rmtree(self.root)

    def call(self, agent, tool, **tool_input):
        return isolation.decide({"cwd": self.root, "agent_type": agent,
                                 "tool_name": tool, "tool_input": tool_input})

    def assertAllowed(self, *a, **kw):
        self.assertIsNone(self.call(*a, **kw))

    def assertDenied(self, *a, **kw):
        self.assertIsNotNone(self.call(*a, **kw))

    # --- who is affected

    def test_main_thread_is_never_restricted(self):
        self.assertAllowed(None, "Read", file_path="requirements.md")

    def test_unrelated_agent_is_not_restricted(self):
        self.assertAllowed("Explore", "Read", file_path="requirements.md")

    def test_prefixed_and_bare_names_are_both_recognised(self):
        self.assertDenied("tdd-squad:green", "Read", file_path="usecases.md")
        self.assertDenied("green", "Read", file_path="usecases.md")

    def test_bare_name_without_config_is_left_alone(self):
        os.remove(Path(self.root, ".tdd-squad/config.json"))
        self.assertAllowed("green", "Read", file_path="usecases.md")
        self.assertDenied("tdd-squad:green", "Read", file_path="src/main/java/com/x/CalculatorImpl.java")

    # --- read isolation table

    def test_green_reads(self):
        self.assertDenied("green", "Read", file_path="requirements.md")
        self.assertDenied("green", "Read", file_path=os.path.join(self.root, "usecases.md"))
        self.assertDenied("green", "Read", file_path="edge-cases-review-uc1.md")
        self.assertAllowed("green", "Read", file_path="src/test/java/com/x/CalculatorTest.java")
        self.assertAllowed("green", "Read", file_path="src/main/java/com/x/api/Calculator.java")

    def test_red_test_cannot_see_production_source_but_sees_contract(self):
        self.assertDenied("red-test", "Read", file_path="src/main/java/com/x/CalculatorImpl.java")
        self.assertAllowed("red-test", "Read", file_path="src/main/java/com/x/api/Calculator.java")
        self.assertAllowed("red-test", "Read", file_path="usecases.md")
        self.assertDenied("red-test", "Read", file_path="requirements.md")

    def test_red_contract_sees_usecase_and_existing_contracts_only(self):
        self.assertAllowed("red-contract", "Read", file_path="usecases.md")
        self.assertAllowed("red-contract", "Read", file_path="src/main/java/com/x/api/Calculator.java")
        self.assertDenied("red-contract", "Read", file_path="src/test/java/com/x/CalculatorTest.java")
        self.assertDenied("red-contract", "Read", file_path="src/main/java/com/x/CalculatorImpl.java")

    def test_path_traversal_is_normalised(self):
        self.assertDenied("green", "Read", file_path="src/../usecases.md")

    # --- writes

    def test_write_rules(self):
        self.assertAllowed("red-test", "Write", file_path="src/test/java/com/x/NewTest.java")
        self.assertAllowed("red-test", "Write", file_path="edge-cases-review-uc2.md")
        self.assertDenied("red-test", "Edit", file_path="src/main/java/com/x/CalculatorImpl.java")
        self.assertDenied("green", "Edit", file_path="src/test/java/com/x/CalculatorTest.java")
        self.assertAllowed("green", "Edit", file_path="src/main/java/com/x/CalculatorImpl.java")
        self.assertDenied("blue-clean", "Edit", file_path="src/main/java/com/x/api/Calculator.java")
        self.assertDenied("blue-intent", "Edit", file_path="usecases.md")
        self.assertDenied("green", "Edit", file_path="pom.xml")
        self.assertAllowed("red-contract", "Write", file_path="src/main/java/com/x/api/Parser.java")

    # --- search

    def test_grep_at_project_root_is_denied_for_isolated_agents(self):
        self.assertDenied("green", "Grep", pattern="add")
        self.assertDenied("green", "Grep", pattern="add", path=".")

    def test_grep_in_allowed_directory(self):
        self.assertAllowed("green", "Grep", pattern="add", path="src")
        self.assertDenied("red-test", "Grep", pattern="add", path="src")
        self.assertAllowed("red-test", "Grep", pattern="add", path="src/test")
        self.assertDenied("red-test", "Grep", pattern="add", path="src/main/java/com/x")

    def test_grep_on_single_file(self):
        self.assertDenied("green", "Grep", pattern="x", path="usecases.md")
        self.assertAllowed("blue-intent", "Grep", pattern="x", path="usecases.md")

    def test_glob_lists_names_only(self):
        self.assertAllowed("green", "Glob", pattern="**/*.md")

    # --- shell

    def test_shell_only_test_command(self):
        self.assertAllowed("green", "Bash", command="mvn test")
        self.assertAllowed("green", "Bash", command="mvn test -Dtest=CalculatorTest")
        self.assertDenied("green", "Bash", command="cat usecases.md")
        self.assertDenied("green", "Bash", command="mvn test; cat usecases.md")
        self.assertDenied("green", "Bash", command="mvn test && cat usecases.md")
        self.assertDenied("green", "Bash", command="mvn test $(cat usecases.md)")
        self.assertDenied("green", "Bash", command="mvn testx")
        self.assertDenied("red-contract", "Bash", command="mvn test")

    # --- wire format

    def test_script_emits_deny_json(self):
        payload = json.dumps({"cwd": self.root, "agent_type": "tdd-squad:green",
                              "tool_name": "Read", "tool_input": {"file_path": "usecases.md"}})
        out = subprocess.run([sys.executable, str(SCRIPTS / "isolation.py")], input=payload,
                             stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
        data = json.loads(out)
        self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_script_is_silent_when_allowed(self):
        payload = json.dumps({"cwd": self.root, "tool_name": "Read",
                              "tool_input": {"file_path": "usecases.md"}})
        out = subprocess.run([sys.executable, str(SCRIPTS / "isolation.py")], input=payload,
                             stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
