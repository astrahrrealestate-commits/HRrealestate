"""The compact form of a report for the owner feed card: verdict, coverage, counts and the gaps that matter."""

from typing import Any
from uuid import UUID

from app.contracts.diligence_report import ChecklistStatus, DDReport, DDSeverity, RequirementSeverity

_MUST_HAVE = (RequirementSeverity.critical, RequirementSeverity.important)
MAX_MISSING = 5


def feed_payload(review_id: UUID, title: str, report: DDReport) -> dict[str, Any]:
    missing = [
        i.label for i in report.checklist if i.status is not ChecklistStatus.present and i.severity in _MUST_HAVE
    ]
    return {
        "review_id": str(review_id),
        "title": title,
        "verdict": report.verdict.value,
        "coverage": {"present": report.coverage.present, "applicable": report.coverage.applicable},
        "counts": {
            "mismatches": len(report.mismatches),
            "high_risks": sum(1 for r in report.risks if r.severity is DDSeverity.high),
            "risks": len(report.risks),
        },
        "missing": missing[:MAX_MISSING],
    }
