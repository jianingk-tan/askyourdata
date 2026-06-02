"""
test_audit_isolation.py — Verifies that audit passes are isolated.

The audit tool's whole job is to surface data problems, so it must not fall
over when it hits one. This test deliberately breaks one pass and asserts
that:
  1. the remaining passes still run
  2. the failure is recorded as a HIGH-severity finding
  3. the failure is counted (for the non-zero exit code)

Run: python test_audit_isolation.py
"""

import importlib.util
import sqlite3
import sys


def load_audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_data", "scripts/audit_data.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_failing_pass_does_not_abort_the_rest():
    audit = load_audit_module()

    def broken_pass(cur, report):
        raise ValueError("simulated failure in NULL profiling")

    report = audit.AuditReport()
    conn = sqlite3.connect(audit.DB_PATH)
    cur = conn.cursor()

    passes = [
        (audit.audit_structure, "Structural audit"),
        (audit.audit_blobs,     "BLOB scan"),
        (broken_pass,           "NULL profile"),       # sabotaged
        (audit.audit_types,     "Type quirks"),
        (audit.audit_integrity, "Referential integrity"),
        (audit.audit_business,  "Business rules"),
    ]
    for fn, name in passes:
        audit.run_pass(fn, name, cur, report)
    conn.close()

    # 1. All six were attempted, exactly one failed
    assert report.passes_run == 6, f"expected 6 attempts, got {report.passes_run}"
    assert report.passes_failed == 1, f"expected 1 failure, got {report.passes_failed}"

    # 2. The failure is recorded as a HIGH finding
    failures = [f for f in report.findings if f["category"] == "Audit pass failure"]
    assert len(failures) == 1, "failure not recorded as a finding"
    assert failures[0]["severity"] == "HIGH"

    # 3. Passes AFTER the broken one still produced output
    joined = "\n".join(report.lines)
    assert "Discontinued" in joined, "Type quirks (pass 4) did not run"
    assert "orphan" in joined.lower() or "Referential" in joined, "pass 5 did not run"
    assert "Quantity" in joined or "business" in joined.lower(), "pass 6 did not run"

    print("✓ One failing pass does not abort the others")
    print(f"  - {report.passes_run} passes attempted, {report.passes_failed} failed")
    print(f"  - failure recorded: {failures[0]['message']}")
    print("  - passes 4, 5, 6 all produced output after the failure")


def test_all_passes_clean_means_zero_failures():
    audit = load_audit_module()

    report = audit.AuditReport()
    conn = sqlite3.connect(audit.DB_PATH)
    cur = conn.cursor()
    for fn, name in [
        (audit.audit_structure, "Structural audit"),
        (audit.audit_blobs,     "BLOB scan"),
        (audit.audit_nulls,     "NULL profile"),
        (audit.audit_types,     "Type quirks"),
        (audit.audit_integrity, "Referential integrity"),
        (audit.audit_business,  "Business rules"),
    ]:
        audit.run_pass(fn, name, cur, report)
    conn.close()

    assert report.passes_run == 6
    assert report.passes_failed == 0, "a clean run should have zero failures"
    print("✓ Clean run reports zero pass failures")


if __name__ == "__main__":
    print("Testing audit pass isolation...\n")
    test_one_failing_pass_does_not_abort_the_rest()
    test_all_passes_clean_means_zero_failures()
    print("\n✅ All isolation tests passed.")
