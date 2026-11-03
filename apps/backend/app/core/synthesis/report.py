"""
JAI Backend - The Synthesizer (Upgrade 4)

Every mission report is assembled from numbered evidence, and anything that claims a result without evidence is
removed before Richard sees it.

1. The evidence ledger: every tool result of the mission and of its independent check gets an id (E1, E2, ...):
   who ran it, the tool, what it acted on (file path or command), whether it succeeded and the exit code.
2. The draft: one model call, through a fixed-shape tool, gives per requirement a status, one plain statement and
   the evidence ids behind it, plus one overall line.
3. The check, in code, whatever the draft says:
   * an evidence id that does not exist is dropped;
   * "done" needs at least one cited entry that succeeded (a failed command or a refused write proves nothing);
     otherwise the requirement shows as "not shown", with the reason;
   * a statement with no evidence left is removed, its requirement "not shown";
   * a requirement the independent check found unmet cannot be "done";
   * every hard-check failure is listed;
   * a requirement the draft left out is listed as "not shown".
4. Confidence (High, Medium, Low) and risks, worked out in code from the evidence: requirements shown done, whether
   the independent check passed, hard checks failing, steps waiting for approval, steps that failed.
5. The render: the overall line and the confidence, a table (requirement, status, what was found, evidence), each
   cited id spelled out, the hard-check failures, what is waiting on Richard, then the risks. The structured report is stored with the mission, so it is shown again
   later without another model call, identically.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

MAX_LEDGER = 400
STATUSES = ("done", "open", "waiting", "failed")
NOT_SHOWN = "not shown"

REPORT_TOOL = {
    "name": "write_report",
    "description": "Write the mission report: per requirement, its status, one plain statement and the evidence ids.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall": {"type": "string", "description": "One sentence: where the mission stands."},
            "items": {"type": "array", "items": {"type": "object", "properties": {
                "requirement": {"type": "string", "description": "The requirement id, for example R3"},
                "status": {"type": "string", "enum": list(STATUSES)},
                "statement": {"type": "string", "description": "What was found or done, in one sentence"},
                "evidence": {"type": "array", "items": {"type": "string"},
                             "description": "Ledger ids (E4, E9) that show it"}},
                "required": ["requirement", "status", "statement", "evidence"]}},
        },
        "required": ["overall", "items"],
    },
}

_SYSTEM = (
    "You are JAI's report writer. Write the mission report for Richard from the evidence ledger only. For each "
    "requirement give its status, one plain sentence, and the ledger ids that show it. Cite only entries that "
    "really show the statement: a failed command or refused action does not show that something is done. If "
    "nothing in the ledger shows a requirement, say so and leave the evidence empty. Do not claim anything the "
    "ledger does not show. Call write_report once.")


def _target(entry: Dict[str, Any]) -> str:
    inputs = entry.get("inputs") if isinstance(entry.get("inputs"), dict) else {}
    for key in ("command", "path", "destination", "source", "query", "url", "name"):
        if inputs.get(key):
            return str(inputs[key])[:300]
    return ""


def build_ledger(mission_calls: Sequence[Dict[str, Any]],
                 check_calls: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """Number every recorded tool result: the mission's first, then the independent check's."""
    ledger: List[Dict[str, Any]] = []
    for who, calls in (("mission", mission_calls), ("check", check_calls)):
        for call in calls:
            if not isinstance(call, dict) or len(ledger) >= MAX_LEDGER:
                continue
            output = call.get("output") if isinstance(call.get("output"), dict) else {}
            exit_code = output.get("exit_code")
            ledger.append({
                "id": f"E{len(ledger) + 1}", "by": who, "tool": str(call.get("tool") or ""),
                "target": _target(call), "success": bool(call.get("success")),
                "exit_code": exit_code if isinstance(exit_code, int) else None,
                "summary": str(call.get("summary") or "")[:200],
            })
    return ledger


def _supports(entry: Dict[str, Any]) -> bool:
    """An entry can show that something is done only if it succeeded (and, for a command, exited 0)."""
    if not entry["success"]:
        return False
    if str(entry.get("summary", "")).startswith("paused for approval"):
        return False
    return entry["exit_code"] in (None, 0)


def _spell(entry: Dict[str, Any]) -> str:
    what = f"{entry['tool']} {entry['target']}".strip()
    if entry["exit_code"] is not None:
        what += f" → exit {entry['exit_code']}"
    elif not entry["success"]:
        what += " → did not succeed"
    return f"{entry['id']} ({entry['by']}): {what}"


def _fallback_items(requirements: Sequence[Dict[str, Any]], ledger: Sequence[Dict[str, Any]],
                    verification: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Without a usable draft: each requirement's own status and evidence, and the independent check's evidence for
    it, matched to the ledger entries they name (a file path or a command)."""
    checks = (verification or {}).get("checks") or []
    items = []
    for r in requirements:
        pattern = re.compile(rf"\b{re.escape(r['id'])}\b", re.IGNORECASE)
        said = [str(c.get("evidence") or "") for c in checks if isinstance(c, dict) and c.get("met") is True
                and pattern.search(str(c.get("requirement") or ""))]
        text = " ".join([str(r.get("evidence") or "")] + said)
        evidence = [e["id"] for e in ledger if e["target"] and e["target"] in text]
        items.append({"requirement": r["id"], "status": r.get("status") or "open",
                      "statement": (said[0] if said else str(r.get("evidence") or ""))[:400], "evidence": evidence})
    return items


def check(draft: Dict[str, Any], requirements: Sequence[Dict[str, Any]], ledger: Sequence[Dict[str, Any]],
          verification: Optional[Dict[str, Any]], hard: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply the rules to a draft (or to nothing) and return the structured report."""
    by_id = {e["id"]: e for e in ledger}
    unmet_text = " ".join(str(u) for u in ((verification or {}).get("unmet") or []))
    if not (draft or {}).get("items"):
        draft = {"overall": "", "items": _fallback_items(requirements, ledger, verification)}
    drafted = {}
    for item in (draft or {}).get("items") or []:
        if isinstance(item, dict):
            drafted.setdefault(str(item.get("requirement") or "").strip().upper(), item)
    items: List[Dict[str, Any]] = []
    for r in requirements:
        item = drafted.get(r["id"].upper()) or {}
        status = str(item.get("status") or "").lower()
        statement = " ".join(str(item.get("statement") or "").split())[:400]
        cited = [str(e).strip().upper() for e in (item.get("evidence") or []) if str(e).strip()]
        known = [e for e in cited if e in by_id]
        note = ""
        if not item:
            status, statement, note = NOT_SHOWN, "", "The report draft did not cover it."
        elif not known:
            status, statement, note = NOT_SHOWN, "", "No evidence was cited for it."
        elif status == "done":
            supporting = [e for e in known if _supports(by_id[e])]
            if not supporting:
                status, note = NOT_SHOWN, "The cited evidence did not succeed: " + "; ".join(
                    _spell(by_id[e]) for e in known)[:300]
                statement = ""
            else:
                known = supporting
        if status == "done" and re.search(rf"\b{re.escape(r['id'])}\b", unmet_text):
            status, note = "open", "The independent check found it unmet."
        if status not in STATUSES + (NOT_SHOWN,):
            status = "open"
        if r.get("status") == "waiting" and status != "done":
            status = "waiting"
        items.append({"id": r["id"], "text": r["text"], "source": r.get("source", ""), "status": status,
                      "statement": statement, "evidence": known if status != NOT_SHOWN else [], "note": note})
    failures = [dict(f) for f in ((hard or {}).get("findings") or [])]
    waiting = [e for e in ledger if str(e.get("summary", "")).startswith("paused for approval")]
    overall = " ".join(str((draft or {}).get("overall") or "").split())[:300]
    done = sum(1 for i in items if i["status"] == "done")
    if not overall or (done < len(items) and re.search(r"\b(all|every|complete|completed|done)\b", overall, re.I)):
        overall = f"{done} of {len(items)} requirements shown done with evidence."
    confidence, reason, risks = _confidence(items, failures, waiting, ledger, verification)
    return {"overall": overall, "items": items, "hard_failures": failures,
            "waiting": [_spell(e) for e in waiting], "ledger": list(ledger),
            "confidence": confidence, "confidence_reason": reason, "risks": risks}


def _confidence(items, failures, waiting, ledger, verification) -> tuple:
    """How sure JAI is, worked out from the evidence (never from the draft's tone), and what is risky."""
    total = len(items)
    done = sum(1 for i in items if i["status"] == "done")
    verified = bool((verification or {}).get("verified"))
    failed_steps = [e for e in ledger if e["by"] == "mission" and not e["success"]
                    and not str(e.get("summary", "")).startswith("paused for approval")]
    if total and done == total and verified and not failures:
        level = "High"
    elif not total or done * 2 < total or (failures and not verified):
        level = "Low"
    else:
        level = "Medium"
    reason = (f"{done} of {total} requirements shown done with evidence; independent check "
              f"{'passed' if verified else 'not passed'}; {len(failures)} hard check(s) failing.")
    risks: List[str] = []
    for i in items:
        if i["status"] != "done":
            note = f" ({i['note'][:120]})" if i["note"] else ""
            risks.append(f"{i['id']} is {i['status']}: {i['text'][:120]}{note}")
    if failures:
        risks.append(f"{len(failures)} hard check(s) still failing against the specification.")
    if waiting:
        risks.append(f"{len(waiting)} step(s) waiting for Richard's approval.")
    if failed_steps:
        risks.append(f"{len(failed_steps)} step(s) failed along the way, the last: {_spell(failed_steps[-1])}")
    return level, reason, risks[:12]


def render(report: Dict[str, Any]) -> str:
    """The report as Markdown. Pure: the same stored report always renders the same text."""
    by_id = {e["id"]: e for e in report.get("ledger") or []}
    lines = [f"**{report.get('overall', '')}**"]
    if report.get("confidence"):
        lines.append(f"**Confidence: {report['confidence']}.** {report.get('confidence_reason', '')}")
    lines += ["", "| Requirement | Status | Found | Evidence |", "|---|---|---|---|"]
    cited: List[str] = []
    for item in report.get("items") or []:
        found = item["statement"] or item.get("note") or ""
        evidence = ", ".join(item["evidence"]) or "none"
        cited += [e for e in item["evidence"] if e not in cited]
        text = item["text"].replace("|", "/")
        lines.append(f"| {item['id']} {text[:140]} | {item['status']} | {found.replace('|', '/')[:240]} | {evidence} |")
    if cited:
        lines += ["", "**Evidence**"] + [f"- {_spell(by_id[e])}" for e in cited if e in by_id]
    if report.get("hard_failures"):
        lines += ["", "**Hard checks still failing**"] + [
            f"- [{f.get('check')}] {f.get('file')}: {f.get('detail')}" for f in report["hard_failures"][:30]]
    if report.get("waiting"):
        lines += ["", "**Waiting on Richard**"] + [f"- {w}" for w in report["waiting"][:20]]
    if report.get("risks"):
        lines += ["", "**Risks**"] + [f"- {r}" for r in report["risks"]]
    return "\n".join(lines)


async def synthesize(router, model: str, mission: str, requirements: Sequence[Dict[str, Any]],
                     ledger: Sequence[Dict[str, Any]], verification: Optional[Dict[str, Any]],
                     hard: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{"report": structured report, "tokens": n}. Without a usable draft the rules still produce a report."""
    from app.core.config import settings
    from app.core.providers import CompletionRequest, Message

    draft: Dict[str, Any] = {}
    tokens = 0
    prompt = (f"MISSION:\n{mission[:3000]}\n\nREQUIREMENTS:\n"
              + "\n".join(f"- {r['id']} [{r.get('status', 'open')}] {r['text']}"
                          + (f" (agent's evidence: {r['evidence'][:200]})" if r.get("evidence") else "")
                          for r in requirements)
              + "\n\nEVIDENCE LEDGER:\n" + "\n".join(_spell(e) + (f" — {e['summary']}" if e["summary"] else "")
                                                   for e in ledger)
              + "\n\nINDEPENDENT CHECK:\n" + json.dumps({
                  "verified": (verification or {}).get("verified"),
                  "checks": ((verification or {}).get("checks") or [])[:40],
                  "unmet": ((verification or {}).get("unmet") or [])[:30]}, default=str)[:12000]
              + "\n\nWrite the report now.")
    try:
        resp = await router.complete(CompletionRequest(
            model=model, messages=[Message(role="user", content=prompt)], system=_SYSTEM, tools=[REPORT_TOOL],
            max_tokens=settings.AGENT_MAX_OUTPUT_TOKENS, temperature=0.0,
            reasoning_effort=getattr(settings, "OPENAI_VERIFIER_REASONING_EFFORT", "high")))
        tokens = int((resp.usage or {}).get("total_tokens", 0) or 0)
        for call in resp.tool_calls or []:
            if call["function"]["name"] == REPORT_TOOL["name"]:
                parsed = json.loads(call["function"]["arguments"] or "{}")
                draft = parsed if isinstance(parsed, dict) else {}
                break
    except Exception as exc:  # noqa: BLE001 - the rules still produce a report from the evidence
        logger.warning(f"report draft failed: {exc}")
    return {"report": check(draft, requirements, ledger, verification, hard), "tokens": tokens}
