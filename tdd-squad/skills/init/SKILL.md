---
name: init
description: Set up the tdd-squad plugin in the current project by writing .tdd-squad/config.json (test command, where tests, source and contracts live, JUnit report paths). Use before the first /tdd-squad:run, or when the user asks to configure the TDD squad.
---

# Set up tdd-squad for this project

The hooks that isolate the squad's agents and gate each step read `.tdd-squad/config.json`. Create it now.

## 1. Check prerequisites
- The project is a git repository with a clean working tree.
- `python3` is on the PATH (the hooks are Python 3.8+ scripts, standard library only). On Windows, check that `python3` resolves.
- A test framework is set up and the build compiles.

## 2. Detect the stack
Look at the build files and the existing layout, then propose values:

| Stack | test_commands | tests | source | junit_reports |
|---|---|---|---|---|
| Maven | `mvn -q test`, `./mvnw -q test` | `src/test/**` | `src/main/**` | `target/surefire-reports/TEST-*.xml` |
| Gradle | `./gradlew test` | `src/test/**` | `src/main/**` | `build/test-results/test/*.xml` |
| npm + Jest/Vitest | `npm test` | `**/*.test.ts`, `**/*.test.tsx`, `**/*.spec.ts`, `**/__tests__/**` | `src/**` | only if a JUnit reporter is configured (e.g. `reports/junit.xml`) |

- **contracts:** where red-contract puts the public API. For Java this is usually a dedicated package, e.g. `src/main/java/**/api/**`; for an HTTP service, e.g. `contracts/**` or `openapi/**`. Contract paths are checked before source paths, so contract types inside the source tree are read-only for green and blue-*.
- **test_markers:** strings that start a test, matched as plain substrings of a line. Java default: `@Test`, `@ParameterizedTest`, `@RepeatedTest`, `@Property`. Jest/Vitest: `it('`, `it("`, `test('`, `test("` (include the quote, or `it(` would also match `submit(`).
- **trace_marker:** the line every test's doc comment must contain. Default `Spec:`.

Show the proposed config to the user and confirm before writing. Use the test command they actually use.

## 3. Write the files
`.tdd-squad/config.json`, for example (Maven):

```json
{
  "test_commands": ["mvn -q test", "./mvnw -q test"],
  "paths": {
    "requirements": ["requirements.md"],
    "usecases": ["usecases.md"],
    "edge_reviews": ["edge-cases-review-*.md"],
    "contracts": ["src/main/java/**/api/**"],
    "tests": ["src/test/**"],
    "source": ["src/main/**"]
  },
  "junit_reports": ["target/surefire-reports/TEST-*.xml"],
  "test_markers": ["@Test", "@ParameterizedTest", "@RepeatedTest", "@Property"],
  "trace_marker": "Spec:",
  "max_gate_retries": 3,
  "test_timeout_seconds": 540
}
```

Fields:
- `test_commands`: the only shell commands the squad's agents may run (extra arguments allowed, no shell operators). The first one is what the gates run, unless `gate_command` is set.
- `junit_reports`: lets the red-test gate check that exactly one test fails. Without it the gate only checks that the suite fails.
- `max_gate_retries`: how many times a gate sends an agent back before letting it stop and flagging `gave-up`.

Then add `.tdd-squad/state/` to `.gitignore`, and commit the config and `.gitignore`.

## 4. Verify
Run the test command once. It must pass; the squad needs a green baseline. Then tell the user they can write `usecases.md` and start with `/tdd-squad:run 1`.
