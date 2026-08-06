# OpenCode skills for TrustLayer

Bounded workflows for AI and human contributors. Load the matching skill
before non-trivial work. The project contract is [`AGENTS.md`](../../AGENTS.md).

| Skill | When to use |
|---|---|
| **scout** | Inspect code and produce an evidence brief; no file edits |
| **plan** | Turn scout evidence into a bounded, approvable implementation plan |
| **build** | Implement an approved plan with tests and `./scripts/verify.sh` |
| **review** | Independent read-only review against plan, tests, security, release gate |
| **compliance** | EU AI Act / registry / readiness / Art. 50 / evidence tooling |

Order for feature work: **scout → plan → (human approve) → build → review**.

## One source of truth across harnesses

`.opencode/skills/<name>/` is canonical. `.claude/skills/<name>` is a
**symlink** to it, so Claude Code and OpenCode read the same file and cannot
drift (ADR-023 §4). Edit the `.opencode/` copy; never replace a symlink with a
real directory — two copies of a workflow means one of them is silently wrong,
and there is no way to tell which.

Every skill states its **refusal conditions**. Those are load-bearing: they are
what stops an agent from raising a compliance score by loosening a check
instead of closing the gap.

Do not invent architecture outside the plan. Prefer
[`docs/INTEGRATING.md`](../../docs/INTEGRATING.md) when documenting how
external stacks should attach to TrustLayer.
