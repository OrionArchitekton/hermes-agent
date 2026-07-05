"""Workflow contracts that keep branch protection satisfiable.

The live main-branch protection can still require child contexts produced by
reusable workflows. If the orchestrator skips the reusable workflow entirely,
GitHub never emits those contexts and a green aggregate gate cannot merge.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[2]


def _load_workflow(path: str) -> dict:
    yaml = YAML(typ="safe")
    with (ROOT / path).open(encoding="utf-8") as fh:
        return yaml.load(fh)


def test_typescript_contexts_are_emitted_when_frontend_is_unaffected():
    ci = _load_workflow(".github/workflows/ci.yml")
    typecheck_call = ci["jobs"]["typecheck"]

    assert "if" not in typecheck_call
    assert typecheck_call["with"]["run_checks"] == "${{ needs.detect.outputs.frontend == 'true' }}"

    typecheck = _load_workflow(".github/workflows/typecheck.yml")
    run_checks = typecheck["on"]["workflow_call"]["inputs"]["run_checks"]
    assert run_checks["type"] == "boolean"
    assert run_checks["default"] is True

    for job_name in ("typecheck", "desktop-build"):
        steps = typecheck["jobs"][job_name]["steps"]
        assert any(step.get("if") == "${{ !inputs.run_checks }}" for step in steps)
