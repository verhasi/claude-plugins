---
name: run
description: Orchestrate the tdd-squad Red-Green-Blue TDD loop that implements the use cases in usecases.md with five isolated subagents. Use when the user asks to implement a feature or use case with the TDD squad, or runs /tdd-squad:run.
argument-hint: "[use case number or name | all]"
---

# TDD Squad orchestration

You are the orchestrator. You run the loop, pass each subagent exactly the context it is allowed to have, commit after each round, and bring ambiguities to the human. You do not write tests or production code yourself.

Arguments: `$ARGUMENTS` (a use case number or name, or `all`; default: the first use case without a commit marked complete).

## Before starting
1. `.tdd-squad/config.json` must exist. If it doesn't, run the `init` skill of this plugin first (/tdd-squad:init).
2. `usecases.md` must exist with an ordered list of human-approved use cases. If `requirements.md` exists, that's fine, but no subagent reads it; the use cases are the spec.
3. The working tree must be clean (`git status`), and the test command from the config must pass. Don't start on a red or dirty baseline; tell the user.

## Subagents
Start them with the Agent tool using these types: `tdd-squad:red-contract`, `tdd-squad:red-test`, `tdd-squad:green`, `tdd-squad:blue-intent`, `tdd-squad:blue-clean`.

Hooks enforce what each one may read, write and run, and they check each agent's result when it finishes. You still must not paste forbidden context into a prompt: the hooks can't see what you write in the prompt.

| Agent | usecases.md (current UC) | contract | tests | production source | edge-case reviews |
|-------|:-:|:-:|:-:|:-:|:-:|
| red-contract | read | read, write | - | - | - |
| red-test | read | read | read, write | - | write |
| green | - | read | read | read, write | - |
| blue-intent | read | read | read | read, write | write |
| blue-clean | - | read | read | read, write | - |

No subagent reads requirements.md.

After every subagent, read `.tdd-squad/state/last-gate.json`. A `gave-up` status means the agent finished without passing its gate; handle it as described under Error handling.

## For each use case

### Step 1: red-contract (once per use case)
- Prompt: the current use case text, verbatim. Task: "Design the contract for this use case, consistent with the existing contracts."

### Step 2: TDD loop, repeating until red-test answers COMPLETE

**red-test**
- Prompt: the current use case text (including its Edge Case Decisions) and where the contract and tests live. Task: "Apply your systematic boundary analysis. Write ONE new failing test, or answer COMPLETE if every spec-derivable behavior is tested."
- Do NOT tell red-test which test to write next. Do NOT hint at remaining behaviors, list already-tested behaviors, or decide completeness for it. It owns that decision.
- The gate checks: one new test, failing, spec quote on every test. When red-test answers `COMPLETE`, go to the Edge Cases Review.

**green**
- Prompt: "Make the failing test pass with the simplest possible implementation." Name the failing test. Do NOT include the use case text, requirements or contract prose.

**blue-intent**
- Prompt: the current use case text. Task: "Verify the implementation matches the use case intent. Fix specification gaming if you detect it."

**Commit (checkpoint)**
- When blue-intent passes its gate, stage the tests, production source and contract files (not `.tdd-squad/state/`) and commit:
  `TDD [UC name] Round N: [one-line summary of what was tested and implemented]`
- This commit is the safe point blue-clean's changes can be rolled back to.

**blue-clean**
- Prompt: "Refactor the production code for clean code and architecture. Tests must keep passing." No use case text.
- If it changed anything and passed its gate, fold the refactoring into the round's commit (`git add` the changed source, then `git commit --amend --no-edit`).
- Then loop back to red-test.

## Edge Cases Review (after red-test answers COMPLETE)

1. Look for `edge-cases-review-[uc-slug].md`. If there is none, go to the next use case.
2. If there is one, rewrite it in the format from `references/edge-cases-review-format.md` and present ALL edge cases to the human at once. Then stop and wait.
3. The human may decide all at once ("ACCEPT 1 (throw), REJECT 2, DEFER 3, ESCALATE 4 to team lead"), go one by one, ask questions first, or mix these. Interpret whatever format they use; don't force a one-by-one interview.
4. When all decisions are in:
   - write them into `usecases.md` under the use case, in the format below;
   - delete the review file;
   - commit `usecases.md` with `TDD [UC name]: edge case decisions`.
5. For each ACCEPT: run the TDD loop again (red-test, green, blue-intent, blue-clean, commit). red-test can now quote the decision text.
   REJECT: no action, documented as out of scope. DEFER: no action now, kept for later.
   ESCALATE: STOP. Don't move to the next use case until the human comes back with ACCEPT or REJECT.

Only when no ESCALATE is pending, go to the next use case.

Decision format in usecases.md:

```markdown
### Use Case 1: Basic Addition

(original spec text...)

#### Edge Case Decisions

##### Trailing delimiter (ACCEPT)
> **From the edge-case review:** "Spec does not define behavior for inputs ending with a delimiter (e.g., '1,2,')"
> **Possible behaviors:** A) throw exception B) ignore trailing C) treat as zero
> **Decision:** ACCEPT - throw IllegalArgumentException
> **Rationale:** Consistent with strict parsing philosophy

##### Whitespace around numbers (REJECT)
> **From the edge-case review:** "Spec does not define whether ' 1 , 2 ' is valid"
> **Decision:** REJECT - out of scope, inputs are always well-formed
> **Rationale:** Spec explicitly shows clean examples

##### Very large numbers (DEFER)
> **Decision:** DEFER - track for v2

##### Unicode delimiters (ESCALATE)
> **Decision:** ESCALATE to Tech Lead
> **Rationale:** Internationalization decision beyond developer scope
```

## Completion
A use case is done when red-test has answered COMPLETE, every edge case is decided (no ESCALATE pending), and every ACCEPT decision has gone through its own TDD loop. When all requested use cases are done, report: use cases implemented, number of rounds, edge-case decisions, and anything escalated or deferred.

## Error handling
- **red-test `gave-up`:** its test is not a clean single red. Show the human the gate detail; don't run green on it.
- **green `gave-up`** (the gate already gave it several attempts): stop and escalate to the human with the failing test and the gate output.
- **blue-intent reports gaming it cannot fix, or `gave-up`:** flag to the human with its explanation.
- **blue-clean `gave-up`:** discard its changes back to the round's checkpoint commit (`git checkout -- .` and remove the untracked source files it created), confirm the suite is green again, and continue.
- Never commit while the suite is red.
