<!--
Thanks for contributing to TrustLayer.

Everything below mirrors the checklist in CONTRIBUTING.md. It lives here too
because a checklist nobody sees at the moment of the pull request is a
checklist that does not run.
-->

## What this changes

<!-- One or two sentences. What behaviour is different after this merges? -->

## Why

<!-- The problem, not the patch. Link the issue or ADR if there is one. -->

## Verification

<!--
Paste the command and its outcome, not a summary of it. "verify.sh test
passed" and a green transcript are different claims, and reviewers can only
check the second. If a check did not run, say which and why — that is a
normal answer, not a failing one.
-->

```
$ ./scripts/verify.sh test
```

## Checklist

- [ ] `./scripts/verify.sh test` is green, or the exact failures are reported above
- [ ] New behaviour has a test; refactors keep the existing tests green
- [ ] Schema changes touch **all five** implementations in this change set —
      `spec/v0.1/`, `docs/SCHEMA.md`, Python, TypeScript, Go, Rust — with a
      cross-language fixture
- [ ] Architectural changes have an ADR in `obsidian_vault/01_Architecture/`
      and a row in `docs/DECISIONS.md`
- [ ] `CHANGELOG.md` records anything a user or integrator would notice
- [ ] `docs/CURRENT_STATUS.md` / `docs/CURRENT_STATE.md` updated if a milestone moved
- [ ] No secrets, signing keys, real traces, personal data, or third-party
      system registries are committed
- [ ] Any new documented invariant is enforced by a test, not only stated

## Anything you are unsure about

<!--
Optional, and genuinely useful. Naming the part you are least confident in
tells a reviewer where to spend their attention.
-->
