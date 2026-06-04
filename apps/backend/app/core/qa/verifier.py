"""
JARV Backend - QA / Verifier Validation Loop

An independent verifier (separate from the agent that produced the work) checks
a task's output and produces a persistent VerificationResult artifact: expected
vs actual, pass/fail, confidence, errors, findings. Used so JARV never trusts
its own output blindly.

For a workspace scan, the verifier independently re-checks that every file the
scan report referenced actually exists on disk.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workspaces import fs_inspector
from app.models.company_operations import LiveOperationsFeedItem
from app.models.self_evolution import VerificationResult

logger = logging.getLogger(__name__)


class QAVerifier:
    """Independent QA verification producing a VerificationResult artifact."""

    VERIFIER = "qa-verifier"

    async def verify_scan(
        self,
        db: AsyncSession,
        task_id: UUID,
        workspace_id: UUID,
        host_path: str,
        scan_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Re-check every referenced file exists. Returns a verification summary."""
        # Collect the relative paths the scan claimed to find.
        referenced: List[str] = []
        for key in ("top_level_files", "package_files", "doc_files",
                    "entry_points", "env_files"):
            for rel in scan_data.get(key, []) or []:
                if rel not in referenced:
                    referenced.append(rel)

        tests: List[Dict[str, Any]] = []
        issues: List[str] = []
        sep = "\\" if "\\" in host_path else "/"
        base = host_path.rstrip("\\/")
        for rel in referenced:
            rel_native = rel.replace("/", sep)
            full = f"{base}{sep}{rel_native}"
            chk = fs_inspector.path_exists(full)
            exists = bool(chk.accessible and chk.exists)
            tests.append({"file": rel, "expected": "exists", "actual": "exists" if exists else "missing",
                          "passed": exists})
            if not exists:
                issues.append(f"Referenced file not found on disk: {rel}")

        total = len(tests)
        passed_n = sum(1 for t in tests if t["passed"])
        failed_n = total - passed_n
        passed = failed_n == 0 and total > 0
        # If the scan referenced nothing, that's a soft pass with low confidence.
        if total == 0:
            passed = True
            confidence = 0.5
            reasoning = "Scan referenced no files; nothing to cross-check."
            recommendation = "accept"
        else:
            confidence = round(passed_n / total, 3)
            reasoning = (
                f"Independently re-checked {total} referenced file(s): "
                f"{passed_n} exist, {failed_n} missing."
            )
            recommendation = "accept" if passed else "reject"

        overall = "passed" if passed else "failed"
        try:
            db.add(VerificationResult(
                id=uuid4(),
                evolution_record_id=None,
                verification_type="output_validation",
                verifier=self.VERIFIER,
                tests_run=tests,
                tests_passed=passed_n,
                tests_failed=failed_n,
                overall_status=overall,
                passed=passed,
                confidence_score=confidence,
                findings=[{"referenced_files": total, "verified": passed_n}],
                issues=issues,
                warnings=[],
                recommendation=recommendation,
                reasoning=reasoning,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                meta_data={"task_id": str(task_id), "workspace_id": str(workspace_id),
                           "host_path": host_path},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ))
            await db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"VerificationResult write failed: {exc}")

        try:
            db.add(LiveOperationsFeedItem(
                id=uuid4(), workspace_id=workspace_id, item_type="verification",
                severity="success" if passed else "error",
                title=f"QA verification {overall}",
                message=reasoning, related_task_id=task_id, requires_action=not passed,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            ))
            await db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"verification feed write failed: {exc}")

        return {
            "verifier": self.VERIFIER,
            "verification_type": "output_validation",
            "passed": passed,
            "overall_status": overall,
            "confidence_score": confidence,
            "tests_passed": passed_n,
            "tests_failed": failed_n,
            "tests_run": tests,
            "issues": issues,
            "recommendation": recommendation,
            "reasoning": reasoning,
        }


qa_verifier = QAVerifier()
