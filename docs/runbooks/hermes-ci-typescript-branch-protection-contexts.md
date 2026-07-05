---
title: Hermes CI - TypeScript branch-protection contexts
verified: 2026-07-05
review_after: 2026-10-05
topics: [hermes-agent, ci, github-actions, branch-protection, runbooks]
references:
  - .github/workflows/ci.yml
  - .github/workflows/typecheck.yml
  - tests/ci/test_workflow_branch_protection_contract.py
---

# Hermes CI TypeScript Branch-Protection Contexts

Hermes CI uses a top-level orchestrator workflow plus reusable child workflows.
The aggregate `All required checks pass` job is the preferred branch-protection
gate, but live branch protection can still require child TypeScript contexts
directly.

## Symptom

A PR shows green Python, lint, supply-chain, OSV, and aggregate CI checks, but
GitHub refuses a non-admin merge with:

`the base branch policy prohibits the merge`

The live branch protection API shows required contexts such as
`TypeScript / Check TypeScript (apps/desktop)`, while the PR only emitted the
skipped parent `TypeScript` workflow context.

## Root Cause

The CI orchestrator skipped the reusable TypeScript workflow when the frontend
lane was unaffected. Skipping the reusable workflow prevents GitHub from
creating its child job contexts, so required legacy TypeScript contexts remain
missing even when the aggregate gate succeeds.

## Rollout

1. Merge the workflow change through normal branch protection.
2. For non-frontend PRs, confirm the reusable TypeScript workflow is called and
   its child jobs complete quickly through the no-op path.
3. For frontend PRs, confirm the full TypeScript matrix and desktop build still
   run.

## Validation

1. Run the source contract test:
   `scripts/run_tests.sh tests/ci/test_workflow_branch_protection_contract.py -q`
2. Run the classifier tests:
   `scripts/run_tests.sh tests/ci/test_classify_changes.py -q`
3. On GitHub, confirm the PR emits the six TypeScript child contexts required by
   branch protection.
4. Confirm `gh pr merge <number> --merge` is no longer blocked by missing
   TypeScript contexts.

## Monitoring

Watch PR checks for missing required contexts after workflow edits, especially
changes under `.github/`, `package.json`, `package-lock.json`, `ui-tui/`, `web/`,
and `apps/`.

## Rollback

Revert the workflow change only after live branch protection no longer requires
the TypeScript child contexts. Rolling back while those contexts remain required
will reintroduce green-but-unmergeable PRs for non-frontend changes.
