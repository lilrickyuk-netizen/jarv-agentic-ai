"""
JARV Backend - Partner and sales pipelines (persisted)

Partners are PartnershipRecord rows moving through shortlisted -> contacted ->
in_discussion -> proposal -> negotiating -> active (or paused / declined).
Becoming "active" means an agreement is in force, which is a binding
commercial commitment: it needs Richard's approval. Deals are the CRM deals
(CRMDeal) the CRM tools already use. A shortlist scores real candidates
against stated criteria; candidates suggested by a model are marked
unverified until researched.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business import PartnershipRecord
from app.models.company_crm import CRMContact, CRMDeal

PARTNER_STAGES = ("shortlisted", "contacted", "in_discussion", "proposal", "negotiating", "active", "paused", "declined")
BINDING_STAGES = ("active",)
DEAL_STAGES = ("prospecting", "qualified", "proposal", "negotiation", "closed_won", "closed_lost")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def partner_view(p: PartnershipRecord) -> Dict[str, Any]:
    meta = p.meta_data or {}
    return {"id": str(p.id), "name": p.partner_name, "type": p.partner_type, "status": p.status,
            "contact": p.contact_name, "email": p.contact_email, "description": p.description,
            "estimated_value": float(p.estimated_value) if p.estimated_value is not None else None,
            "score": meta.get("score"), "reasons": meta.get("reasons"), "verified": meta.get("verified", True),
            "history": meta.get("history", [])}


def deal_view(d: CRMDeal) -> Dict[str, Any]:
    return {"id": str(d.id), "title": d.title, "stage": d.stage, "value": d.value, "notes": d.notes,
            "contact_id": str(d.contact_id) if d.contact_id else None,
            "expected_close_date": d.expected_close_date.isoformat() if d.expected_close_date else None}


def score_candidate(candidate: Dict[str, Any], criteria: Dict[str, float], stack: List[str]) -> tuple[float, List[str]]:
    text = " ".join(str(candidate.get(k) or "") for k in ("name", "type", "notes", "url", "audience")).lower()
    reasons, score = [], 0.0
    for term, weight in criteria.items():
        if term.lower() in text:
            score += float(weight)
            reasons.append(f"matches '{term}' (+{weight:g})")
    overlap = [s for s in stack if s.lower() in text]
    if overlap:
        score += 0.5 * len(overlap)
        reasons.append(f"shares stack: {', '.join(overlap)}")
    return round(score, 2), reasons


class PipelineService:
    async def partner(self, db: AsyncSession, workspace_id: UUID, partner_id: Any) -> PartnershipRecord:
        try:
            key = partner_id if isinstance(partner_id, UUID) else UUID(str(partner_id))
        except (TypeError, ValueError):
            raise ValueError(f"'{partner_id}' is not a valid id") from None
        row = (await db.execute(select(PartnershipRecord).where(PartnershipRecord.id == key,
                                                                PartnershipRecord.workspace_id == workspace_id))
               ).scalar_one_or_none()
        if row is None:
            raise LookupError("Partner not found in this workspace")
        return row

    async def shortlist(self, db: AsyncSession, workspace_id: UUID, *, candidates: List[Dict[str, Any]],
                        criteria: Dict[str, float], partner_type: str, owner: Optional[UUID],
                        model: Optional[str] = None) -> List[PartnershipRecord]:
        from app.core.agents.specialists import _helpers as helpers
        from app.core.business.facts import gather

        facts = await gather(db, workspace_id)
        verified = True
        if not candidates:
            if not helpers.provider_configured():
                raise ValueError("Give the candidates to compare (name, type, notes, url); with a model provider "
                                 "JARV can also suggest some for research")
            reply = await helpers.llm_complete(
                model or "claude-sonnet-4-6",
                f"Suggest up to 8 {partner_type} partner candidates for this product. Reply with JSON only: "
                f'[{{"name": "...", "type": "{partner_type}", "notes": "why they fit", "url": "..."}}]\n\n{facts.summary(3000)}',
                system="Suggest real, well-known organisations only.", temperature=0.2, max_tokens=1200)
            text = (reply or {}).get("text", "")
            start, end = text.find("["), text.rfind("]")
            try:
                candidates = json.loads(text[start:end + 1]) if start != -1 else []
            except ValueError:
                candidates = []
            if not candidates:
                raise ValueError("No candidates were suggested; give the candidates to compare")
            verified = False
        rows = []
        now = _now()
        for candidate in candidates[:30]:
            name = str(candidate.get("name") or "").strip()
            if not name:
                continue
            score, reasons = score_candidate(candidate, criteria, facts.stack)
            existing = (await db.execute(select(PartnershipRecord).where(
                PartnershipRecord.workspace_id == workspace_id, PartnershipRecord.partner_name == name))).scalar_one_or_none()
            if existing is not None:
                existing.meta_data = {**(existing.meta_data or {}), "score": score, "reasons": reasons}
                rows.append(existing)
                continue
            row = PartnershipRecord(
                id=uuid4(), workspace_id=workspace_id, partner_name=name[:255],
                partner_type=str(candidate.get("type") or partner_type)[:50], description=candidate.get("notes"),
                contact_name=candidate.get("contact"), contact_email=candidate.get("email"), start_date=now.date(),
                status="shortlisted", is_active=False, actual_value=Decimal("0"), currency="USD", managed_by=owner,
                tags=["shortlist"], meta_data={"score": score, "reasons": reasons, "url": candidate.get("url"),
                                               "verified": verified,
                                               "history": [{"status": "shortlisted", "at": now.isoformat()}]},
                created_at=now, updated_at=now)
            db.add(row)
            rows.append(row)
        await db.flush()
        return sorted(rows, key=lambda r: -float((r.meta_data or {}).get("score") or 0))

    async def update_partner(self, db: AsyncSession, workspace_id: UUID, partner_id: Any, *, status: Optional[str],
                             notes: Optional[str], estimated_value: Optional[float], contact_name: Optional[str],
                             contact_email: Optional[str], approved: bool) -> PartnershipRecord:
        row = await self.partner(db, workspace_id, partner_id)
        now = _now()
        meta = dict(row.meta_data or {})
        if status:
            if status not in PARTNER_STAGES:
                raise ValueError(f"status is one of {', '.join(PARTNER_STAGES)}")
            if status in BINDING_STAGES and not approved:
                raise PermissionError("Making a partnership active means an agreement is in force (a binding "
                                      "commitment); Richard must approve it")
            row.status = status
            row.is_active = status == "active"
            meta["history"] = list(meta.get("history", [])) + [{"status": status, "at": now.isoformat(), "notes": notes}]
        elif notes:
            meta["history"] = list(meta.get("history", [])) + [{"note": notes, "at": now.isoformat()}]
        if estimated_value is not None:
            row.estimated_value = Decimal(str(estimated_value))
        if contact_name:
            row.contact_name = contact_name
        if contact_email:
            row.contact_email = contact_email
        row.meta_data = meta
        row.updated_at = now
        await db.flush()
        return row

    async def update_deal(self, db: AsyncSession, workspace_id: UUID, owner: UUID, *, deal_id: Optional[str],
                          title: Optional[str], stage: Optional[str], value: Optional[float], notes: Optional[str],
                          expected_close_date: Optional[str], contact_name: Optional[str],
                          contact_email: Optional[str], company: Optional[str]) -> CRMDeal:
        from app.core.jarv_memory import memory_service

        if stage and stage not in DEAL_STAGES:
            raise ValueError(f"stage is one of {', '.join(DEAL_STAGES)}")
        now = _now()
        agent_id = await memory_service._agent_id(db, workspace_id)
        if deal_id:
            deal = (await db.execute(select(CRMDeal).where(CRMDeal.id == UUID(str(deal_id)),
                                                           CRMDeal.workspace_id == workspace_id))).scalar_one_or_none()
            if deal is None:
                raise LookupError("Deal not found in this workspace")
        else:
            if not title:
                raise ValueError("A new deal needs a title")
            contact_id = None
            if contact_name or contact_email:
                contact = CRMContact(id=uuid4(), owner_id=owner, workspace_id=workspace_id, agent_id=agent_id,
                                     name=(contact_name or contact_email)[:200], email=contact_email, company=company,
                                     is_active=True, created_at=now, updated_at=now)
                db.add(contact)
                await db.flush()
                contact_id = contact.id
            deal = CRMDeal(id=uuid4(), owner_id=owner, workspace_id=workspace_id, agent_id=agent_id, contact_id=contact_id,
                           title=title[:200], stage=stage or "prospecting", is_active=True, created_at=now, updated_at=now)
            db.add(deal)
        if stage:
            deal.stage = stage
            deal.is_active = stage not in ("closed_won", "closed_lost")
        if value is not None:
            deal.value = float(value)
        if notes:
            deal.notes = ((deal.notes + "\n") if deal.notes else "") + f"[{now.date().isoformat()}] {notes}"
        if expected_close_date:
            deal.expected_close_date = date.fromisoformat(expected_close_date[:10])
        deal.updated_at = now
        await db.flush()
        return deal

    async def pipeline(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        partners = (await db.execute(select(PartnershipRecord).where(PartnershipRecord.workspace_id == workspace_id))
                    ).scalars().all()
        deals = (await db.execute(select(CRMDeal).where(CRMDeal.workspace_id == workspace_id))).scalars().all()
        by_stage: Dict[str, Dict[str, float]] = {}
        for d in deals:
            entry = by_stage.setdefault(d.stage, {"count": 0, "value": 0.0})
            entry["count"] += 1
            entry["value"] = round(entry["value"] + float(d.value or 0), 2)
        partner_stages: Dict[str, int] = {}
        for p in partners:
            partner_stages[p.status] = partner_stages.get(p.status, 0) + 1
        open_value = sum(float(d.value or 0) for d in deals if d.stage not in ("closed_won", "closed_lost"))
        won = sum(float(d.value or 0) for d in deals if d.stage == "closed_won")
        closed = [d for d in deals if d.stage in ("closed_won", "closed_lost")]
        return {"deals_by_stage": by_stage, "open_pipeline_value": round(open_value, 2), "won_value": round(won, 2),
                "win_rate": round(sum(d.stage == "closed_won" for d in closed) / len(closed), 3) if closed else None,
                "partners_by_status": partner_stages, "partners": [partner_view(p) for p in partners],
                "deals": [deal_view(d) for d in deals]}


pipeline_service = PipelineService()
