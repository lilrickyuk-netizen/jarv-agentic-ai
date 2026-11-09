"""
JAI Backend - A finished mission whose last step is Richard's becomes one approval on his Approvals page

Richard is the boundary operator, not the technical reviewer: JAI does the technical work and the Independent
Verifier checks it. When everything JAI can do is done and verified and what is left only Richard can give (his
sign-off on a phase, an approval, the go-ahead for the acceptance tag), the mission does not go round again and does
not end as failed. It stops as a blocked mission with a plain-English summary, which the Approvals page lists with
Approve and Reject. Approving it re-queues the same mission, which then does the steps that waited on him (locally:
pushing, publishing and deploying stay refused unless he names them) and nothing else.

On 9 November the MYCO Phase 0 tidy-up was finished and verified, but its last item waited on Richard's review and
there was no way for him to give it: JAI kept re-running the team, which made six commits re-proving finished work.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

BOUNDARY = "richard_sign_off"
APPROVED = "RICHARD HAS APPROVED THE SIGN-OFF"


def waiting(result: Dict[str, Any]) -> List[str]:
    """What a verified mission is waiting on Richard for; empty unless everything else is done and verified."""
    if not result.get("success") or result.get("needs_continuation"):
        return []
    verification = result.get("verification") or {}
    if not verification.get("verified"):
        return []
    return [str(item) for item in verification.get("waiting_on_richard") or [] if str(item).strip()]


def reason(items: List[str]) -> str:
    """The plain-English line Richard reads on his Approvals page."""
    lines = "; ".join(item.split(": ", 1)[-1][:200] for item in items[:5])
    return ("Everything JAI can do is done, and the Independent Verifier checked it. Your sign-off is the last step: "
            f"{lines}. Approve to let JAI finish it (locally; nothing is pushed, published or deployed), or reject "
            "to close the mission as it is.")[:1500]


def mark(task, items: List[str]) -> None:
    """Record on the mission what it waits for, so the Approvals page shows it and approving resumes it."""
    meta = dict(task.meta_data or {})
    meta.update({"blocked_reason": reason(items), "boundary_type": BOUNDARY, "waiting_on_richard": items[:20],
                 "sign_off_requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    meta.pop("sign_off_used_at", None)
    task.meta_data = meta


def on_approve(meta: Dict[str, Any]) -> Dict[str, Any]:
    """An approved sign-off continues the same mission (its requirements and progress) rather than starting over."""
    if meta.get("boundary_type") == BOUNDARY:
        meta["resume_mode"] = "continuation"
    return meta


def granted(meta: Dict[str, Any]) -> bool:
    """Whether Richard approved this mission's sign-off and the round that uses it has not run yet."""
    return (meta.get("boundary_type") == BOUNDARY and bool(meta.get("approval_grant"))
            and not meta.get("sign_off_used_at"))


def reopen(requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """After Richard's approval, what waited on him is open (and approved) work; everything else is unchanged."""
    out = []
    for r in requirements:
        r = dict(r)
        if r.get("status") == "waiting":
            r["status"], r["evidence"] = "open", "Richard approved this step"
        out.append(r)
    return out


def resume(requirements: Optional[List[Dict[str, Any]]], meta: Dict[str, Any]) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
    """The note and requirements for the round after Richard's approval: what waited on him is open again (and
    approved), everything done stays done."""
    items = [str(i) for i in meta.get("waiting_on_richard") or []]
    out = reopen(requirements) if requirements else None
    note = (f"{APPROVED} this mission was waiting for"
            + (f" ({meta.get('approval_note')})" if meta.get("approval_note") else "") + ". Do now the steps that "
            "waited on him, and nothing else: everything else is done and verified, so do not redo or re-record it. "
            "These steps are local (a commit, a tag); pushing, publishing and deploying stay refused unless his note "
            "names them. What waited on him:\n" + "\n".join(f"- {i[:300]}" for i in items[:20]))
    return note, out
