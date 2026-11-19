# tdd-squad

A Claude Code plugin in which five specialized subagents implement use cases autonomously, in a strict Red-Green-Blue TDD loop.

Scope: only the TDD step where AI works alone. It takes approved use cases as input and produces tested, committed code. Where the use cases come from (BDD, specs, planning) and what happens to the result (review, acceptance testing) are outside this plugin.

Ported from the Kiro power [verhasi/kiro-powers/tdd-squad](https://github.com/verhasi/kiro-powers/tree/main/tdd-squad). The main difference: context isolation and the TDD rules are **enforced by hooks**, not only requested in prompts.

## The squad

| Agent | Role | Sees | May write |
|---|---|---|---|
| `red-contract` | API Architect: designs the contract for one use case | current use case, existing contracts | contracts |
| `red-test` | QA Pessimist: one failing test per round, or COMPLETE; ambiguities go to a human | use case, contract, tests | tests, edge-case review |
| `green` | Pragmatic Hacker: simplest code that passes | tests, contract types, source | source |
| `blue-intent` | Intent Bridge: catches specification gaming | use case, contract, tests, source | source, edge-case review |
| `blue-clean` | Code Artisan: refactors without knowing the business | tests, contract types, source | source |

No agent reads `requirements.md`. The orchestrator (the `run` skill, in your main conversation) runs the loop:

```
for each use case:
  red-contract
  loop until red-test says COMPLETE:
    red-test -> green -> blue-intent -> commit -> blue-clean -> amend
  edge-case review by a human (ACCEPT / REJECT / DEFER / ESCALATE)
  one more TDD loop per ACCEPT decision
```

## What the hooks enforce

**Isolation (PreToolUse).** For calls coming from a squad agent:
- Read and Grep are blocked on files outside the agent's column above. A Grep whose scope could include a forbidden file is blocked too, with a hint to narrow `path`.
- Write and Edit are allowed only in the agent's own areas. The contract is read-only for green and the blue agents, so it is effectively a frozen API.
- Bash is limited to the configured test command(s), with arguments but without shell operators, so `cat usecases.md` can't get around the Read rule. red-contract has no shell.

Calls from the main conversation and from other agents are never touched.

**Gates (SubagentStop).** When an agent finishes:
- `red-test`: exactly one new test; it fails and it is the only failing test (using JUnit XML reports when configured); every test carries a `Spec:` quote. A test that passes straight away is rejected. If nothing changed, the agent must have answered COMPLETE.
- `green`, `blue-intent`, `blue-clean`: the whole suite passes.

A failing gate sends the agent back with the reason, up to `max_gate_retries` times. After that it may stop, and the orchestrator finds `"status": "gave-up"` in `.tdd-squad/state/last-gate.json` and escalates.

## Install

```
/plugin marketplace add verhasi/claude-plugins
/plugin install tdd-squad@verhasi
```

Requirements: Claude Code with `agent_type` in tool hook input (a recent 2.1.x), `python3` on the PATH, git.

## Use

1. `/tdd-squad:init`: detects the stack and writes `.tdd-squad/config.json` (test command; where tests, source and contracts live; JUnit report paths).
2. Write `usecases.md`: an ordered, human-approved list of use cases.
3. `/tdd-squad:run 1` for one use case, or `/tdd-squad:run all`.

For a fully unattended run, start Claude Code in a permission mode that doesn't prompt for edits and for the test command. Plugin agents can't set their own permission mode. The hooks still limit what each agent can touch.

## Design notes and open questions

- **Contract types are visible to green and blue-clean.** The Kiro version hid the contract from them, but in Java and TypeScript the code can't compile without the types. Only the configured contract paths are visible, and they are read-only. If your contract is an OpenAPI file with business prose in it, keep it out of `paths.contracts` and expose only the generated types.
- **A compile failure counts as red.** When red-test calls code that doesn't exist yet, the build fails before any test runs. The gate accepts that, so a typo in a test also looks red. Green can't edit tests, so it escalates after its retries.
- **blue-intent vs. "fake it till you make it".** blue-intent may generalize a hard-coded implementation before red-test has written the test that would force it. red-test's next test may then already pass, and the gate rejects it and asks for a different behavior. Whether blue-intent should only report instead of fixing is still open.
- **Grep is coarse.** Agents must point Grep at a directory they may read; a search from the project root is blocked when requirements.md or usecases.md live there.
- Test markers and the `Spec:` check are substring matches, so treat them as a guard rail, not a parser.

## Development

The hook scripts are tested (stdlib `unittest`, no dependencies):

```
cd tdd-squad && python3 -m unittest discover -s tests -v
```
