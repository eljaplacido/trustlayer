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

Do not invent architecture outside the plan. Prefer
[`docs/INTEGRATING.md`](../../docs/INTEGRATING.md) when documenting how
external stacks should attach to TrustLayer.
