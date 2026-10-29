"""
JARV Backend - Company operating layer (persisted)

Operating plans with versions, daily operating loops, weekly execution plans,
AI standups, KPIs, the risk register, the decision log and the live
operations feed, all stored in the database and computed from the
workspace's real tasks, approvals, incidents and records.
"""
from app.core.company_ops.service import CompanyOpsService, company_ops

__all__ = ["CompanyOpsService", "company_ops"]
