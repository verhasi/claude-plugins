# claude-plugins

Claude Code plugins by Istvan Verhas, published as a plugin marketplace.

| Plugin | What it does |
|---|---|
| [tdd-squad](./tdd-squad/) | Five isolated subagents implement use cases with a strict Red-Green-Blue TDD loop; isolation and TDD rules enforced by hooks |

## Install

```
/plugin marketplace add verhasi/claude-plugins
/plugin install tdd-squad@verhasi
```

## Layout

```
.claude-plugin/marketplace.json   marketplace catalog
<plugin>/
  .claude-plugin/plugin.json      plugin manifest
  agents/                         subagents
  skills/                         skills (invoked as /<plugin>:<skill>)
  hooks/hooks.json                hooks
  scripts/                        hook scripts
  tests/                          tests for the hook scripts
```
