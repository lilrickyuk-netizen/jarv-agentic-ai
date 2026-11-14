"""
JAI Backend - A specialist's mission is done by that specialist's agent, the way that role works

Richard's design: 31 agents, each with its own role, tools and way of working. From 8 November every mission went
through one software-builder process: research, sales, marketing and writing missions were the software builder
"acting as" the specialist, in the coding sandbox, with a requirements ledger, a step-by-step build method and a
separate checker (commits 921183c, a06769a, ae0099a). On 10 November Richard asked: "why would a marketing agent
start a mission like a software engineer? It makes no sense." Every list mission that day came back partial, while
Plexecute itself (one capable model with a search tool) researches without trouble.

Now a mission whose work belongs to a specialist (work_type.classify: marketing, sales, partnerships, research,
content, business, finance, legal, customer support) is run by that role's agent, in JAI itself, not in the coding
sandbox:
- it acts as its own role (the agent registry's name, authority and the role's standard), not as the orchestrator;
- its tools are its trade's: web search (Exa and Tavily), page reading, the browser, documents, spreadsheets and
  files in the product's folder, JAI's memory, knowledge and Richard's standing rules, and the role's own business
  tools (the Sales agent's prospecting, the Partnerships agent's shortlist and pipeline, the Marketing agent's
  campaign and content drafting); nothing that sends, posts or publishes;
- it works from the job as a senior specialist set it out, with its playbooks and field knowledge
  (command/expertise), and the numbered requirements;
- it runs on a capable model that researches well and costs little (ROLE_AGENT_MODEL, GPT-6 Luna by default, as
  Plexecute does), stepping up when a round completed nothing;
- the mission engine's own independent check, evidence-based report (Upgrade 4) and knowledge graph (Upgrade 3) run
  as for any mission, and it carries on round after round until the work is verified;
- each such mission has a hard spending allowance (ROLE_MISSION_MAX_COST_USD, about £2): when it is used, the
  mission stops, keeps what it wrote and says so.
Software, a named skill (BRAG) and work Richard asks to split "in parallel" keep the builder and its sandbox.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app.core.command.agent_executor import _FINISH, AgentExecutor, _tool_schemas
from app.core.config import settings

logger = logging.getLogger(__name__)

# What every specialist works with: files and spreadsheets in the product's folder, the web, documents, memory and
# knowledge. No shell, builds, installs, deletes or pushes: those are the software builder's.
TRADE_TOOLS = (
    "list_files", "read_file", "search_files", "get_file_metadata", "write_file", "edit_file", "write_spreadsheet",
    "create_folder", "move_file", "copy_file", "read_document", "web_search", "research_web", "fetch_url",
    "use_browser", "memory_search", "memory_add", "knowledge_graph_search", "knowledge_graph_add", "recall_richard",
    "read_mission_report", "consult_specialist_knowledge", "read_skill", "git_status", "git_log",
)
# Making images, voiceovers, videos and social drafts (drafts only: JAI never publishes).
CREATIVE_TOOLS = ("generate_image", "make_voiceover", "make_video", "social_channels", "social_draft")
CREATIVE_ROLES = ("marketing", "content", "growth", "community")
# The business tool groups of roles that have no business mode of their own.
EXTRA_GROUPS = {"customer_support": ("support",), "research": (), "legal": ()}
SAVE_EVERY = 12  # steps between reminders to save what has been found
UNMARKED_STEPS = 18  # steps with no requirement marked before the agent is sent back to its checklist
# Tools that act on the world from Richard's name (send, post, publish, moderate): never in a specialist's mission.
_ACTS = ("send", "publish", "moderate", "post_")


def role_tools(role: str) -> List[str]:
    """The tools a role's agent works with in its missions."""
    tools = list(TRADE_TOOLS)
    if role in CREATIVE_ROLES:
        tools += list(CREATIVE_TOOLS)
    try:
        from app.core.agents.specialists.business_mode import MODES, tools_for

        if role in MODES:
            tools += tools_for(role)
        else:
            from app.tools.business import TOOLS_BY_GROUP

            for group in EXTRA_GROUPS.get(role, ()):
                tools += list(TOOLS_BY_GROUP.get(group, []))
    except Exception as exc:  # noqa: BLE001 - the trade tools still serve
        logger.info(f"business tools for {role} unavailable: {exc}")
    return [t for t in dict.fromkeys(tools) if not any(word in t for word in _ACTS)]


class RoleAgent:
    """The identity a role's mission acts as: the agent registry's name for the role, at the mission's authority."""

    def __init__(self, runtime, role: str):
        from app.core.agents.base import AuthorityLevel

        self.name = role
        level = max(0, min(int(getattr(runtime, "authority_level", 3) or 3), 10))
        self.config = SimpleNamespace(agent_id=getattr(runtime, "agent_id", None), authority_level=AuthorityLevel(level))
        self._tools = role_tools(role)

    def get_allowed_tools(self) -> List[str]:
        return list(self._tools)


async def role_model(stuck: bool = False) -> str:
    """GPT-6 Luna (ROLE_AGENT_MODEL), Sonnet 5.5 when a round completed nothing (ROLE_AGENT_STUCK_MODEL), and the
    other provider when one has no key or has run out of credit."""
    from app.core.providers.router import has_no_credit

    wanted = str((settings.ROLE_AGENT_STUCK_MODEL if stuck else settings.ROLE_AGENT_MODEL) or "")
    claude_ok = bool(settings.CLAUDE_API_KEY or settings.ANTHROPIC_API_KEY) and not await has_no_credit("claude")
    openai_ok = bool(settings.OPENAI_API_KEY) and not await has_no_credit("openai")
    if wanted.startswith("claude") and not claude_ok and openai_ok:
        return str(settings.ROLE_AGENT_MODEL if not str(settings.ROLE_AGENT_MODEL).startswith("claude")
                   else settings.OPENHANDS_FALLBACK_MODEL)
    if wanted.startswith("gpt") and not openai_ok and claude_ok:
        return str(settings.ROLE_AGENT_STUCK_MODEL if str(settings.ROLE_AGENT_STUCK_MODEL).startswith("claude")
                   else settings.OPENHANDS_MODEL)
    return wanted


class RoleExecutor(AgentExecutor):
    """The mission engine (its rounds, independent check, report and graph) run by a role's own agent."""

    def __init__(self, runtime, model: str, workspace_root: Optional[str], *, role: str, job=None, team=None):
        super().__init__(runtime, model, workspace_root)
        self.role = role
        self.job = job
        self.team = team
        self.capped = False
        self._spent_before = 0.0
        from app.core.command.mission_org import SPECIALISTS

        self.title = SPECIALISTS.get(role, {}).get("title", role.replace("_", " ").title())
        self.standard = SPECIALISTS.get(role, {}).get("standard", "")

    async def _prepare_tools(self) -> List[Dict[str, Any]]:
        from app.core.agents.toolbox import AgentToolbox

        rt = self.runtime
        context = SimpleNamespace(db_session=rt.db, workspace_id=rt.workspace_id, task_id=rt.task_id,
                                  user_id=rt.user_id, session_id=rt.session_id, approval_granted=False,
                                  approved_tools=[])
        try:
            toolbox = AgentToolbox(RoleAgent(rt, self.role), context, runtime=rt, root_host=self.workspace_root)
            await toolbox.prepare()
        except Exception as exc:  # noqa: BLE001 - no workspace record: the core tools still enforce every rule
            logger.info(f"{self.role} toolbox unavailable, using the core tools: {exc}")
            return _tool_schemas()
        self.toolbox = toolbox
        if toolbox.root_host and not self.workspace_root:
            self.workspace_root = toolbox.root_host
        return toolbox.model_tools() + [_FINISH]

    def _system_prompt(self, full: bool) -> str:
        own = sorted(set(role_tools(self.role)) - set(TRADE_TOOLS) - set(CREATIVE_TOOLS))
        return (
            f"You are JAI's {self.title}, one of the 31 specialists in Richard's AI company. {self.standard} "
            "You work the way a senior professional in your field works, with a browser, a search engine and a "
            "spreadsheet; you are not a software engineer and this is not a software build: no scripts, tests, "
            "builds or check files. "
            "You work ONLY inside the product's folder"
            + (f" (`{self.workspace_root}`); paths may be relative to it. " if self.workspace_root else ". ")
            + "YOUR TOOLS: web_search (run several searches, each a different angle; search a name to find its "
              "page), fetch_url to read a page, research_web for a cited answer to a question, use_browser for a "
              "page that needs clicking through, read_document for PDFs, Word, PowerPoint and Excel files, "
              "write_spreadsheet for any list (one sheet per kind of entry, headings in the first row; add new "
              "entries with mode \"append\", and sheets you do not name are kept), read_file to see a workbook's "
              "rows, write_file "
              "and edit_file for documents, memory_search, recall_richard and knowledge_graph_search for what JAI "
              "and Richard already know, consult_specialist_knowledge for your field's reference material, "
              "read_skill to open any of your skills in full (its whole playbook, or one of its templates, "
              "checklists and examples)"
            + (", generate_image, make_voiceover, make_video and social_draft for drafts (never published)"
               if self.role in CREATIVE_ROLES else "")
            + (f", and your own role's tools: {', '.join(own)}" if own else "") + ". "
            "HOW YOU WORK: your playbooks for this job are in your brief: they are your trade's method, so work "
            "the way they say, and when part of the job is what another of your skills is for, open that skill "
            "with read_skill before doing that part. Read the product's own description in the folder first. To build a list, find "
            "round-up, directory and 'best of' pages first, take the names from them, then look each one up for "
            "its own page and published contact. Open only web addresses that a search result or a page you read "
            "gave you; never type an address from memory (made-up addresses fail and waste the mission). Keep an "
            "entry you could not fully confirm, marked with what is "
            "still to check, rather than dropping it; never pad a list and never guess a detail or an email. "
            "Save the deliverable after every ten or so entries, and mark each requirement with requirement_status "
            "as soon as it is met, so a stopped round keeps its progress. Work until every requirement and target "
            "is met: do not stop early to report a short list. "
            "Contact, send, post, publish and spend nothing: drafts and lists are for Richard to use. Never claim "
            "something was done unless a tool result in this conversation shows it. Mark each requirement with "
            "requirement_status as you meet it, and call finish when the whole job is done.")

    def _reminder(self) -> Optional[str]:
        """Every SAVE_EVERY steps: save what has been found and mark what is met (10 November: a list mission found
        a dozen creators and saved once in about 200 steps)."""
        done = sum(1 for r in (self.requirements or []) if r.get("status") == "done")
        if done != getattr(self, "_done_seen", None):
            self._done_seen, self._done_step = done, self.iterations
        quiet = self.iterations - getattr(self, "_done_step", self.iterations)
        still_open = [r["id"] for r in (self.requirements or []) if r.get("status") != "done"]
        if still_open and quiet and quiet % UNMARKED_STEPS == 0:
            # 14 November: a database mission passed its row targets and went on adding rows for ten rounds with
            # 20 of its 30 requirements still marked open; nothing made it go back to its list.
            return (f"[YOUR CHECKLIST] You have worked {quiet} steps without marking a requirement, and "
                    f"{len(still_open)} are still open: {', '.join(still_open[:40])}. Stop adding to the work and "
                    "go through them now, one by one, against what is saved (read_file shows a workbook's facts: "
                    "its sheets, row counts per country and type, rows without a source, duplicates). Mark every "
                    "one that is already met with requirement_status and its evidence. Then do only what is still "
                    "unmet: usually fixing what is there (sheet names, columns, duplicates, blank cells), not "
                    "finding more. When none is open, call finish.")
        if self.iterations <= 1 or self.iterations % SAVE_EVERY:
            return None
        return ("[SAVE NOW] Before searching further, save every entry you have found since your last save "
                "(write_spreadsheet with mode \"append\" for a list, write_file or edit_file for a document), "
                "then mark each requirement that is now met with requirement_status. Compare the WORKBOOK FACTS "
                "that each save reports with the requirements' targets: once the targets are met, stop searching. "
                "Finish the job instead: fix what the facts show (sheet names, duplicates, blank cells, rows "
                "without a source), mark every requirement, and call finish. Otherwise carry on.")

    def _not_finished(self, remaining: int) -> str:
        still_open = [r["id"] for r in (self.requirements or []) if r.get("status") != "done"]
        return (f"Not accepted yet: nothing is blocked or waiting for approval, and you have {remaining} steps "
                "left" + (f"; still open: {', '.join(still_open[:40])}" if still_open else "") + ". Go through "
                "what is open against what is saved in the folder: mark what is already met with its evidence, "
                "and do the rest (find what is missing, or fix what is there). If something truly stops you (a "
                "hard boundary, or a sign-in, payment or decision only Richard can give), call finish again and "
                "name it; then the rest is reported as waiting on him.")

    async def _notes(self) -> Optional[str]:
        """Richard's words about this mission, left while it works (command/steer): given to the agent once, at
        its next step."""
        from app.core.command import steer

        notes = await steer.take(self.runtime.task_id)
        if not notes:
            return None
        self.told = getattr(self, "told", []) + notes
        return steer.as_message(notes)

    async def _over_allowance(self) -> Optional[str]:
        cap = float(getattr(settings, "ROLE_MISSION_MAX_COST_USD", 0) or 0)
        if cap <= 0:
            return None
        used = self._spent_before + float(self.usage.cost_usd or 0)
        if used < cap:
            return None
        self.capped = True
        return (f"The {self.title} stopped at this mission's spending allowance (${used:.2f} of ${cap:.2f}, about "
                f"£{used * 0.78:.2f}). Everything written so far is saved in the folder.")

    def _progress_extra(self) -> Dict[str, Any]:
        from app.core.command.mission_org import Package

        card = Package(id="A1", title=f"The {self.title} does the mission", specialist=self.role, goal="",
                       owns=[], depends_on=[], requirements=[], done_when="", status="working",
                       step=self.iterations, steps=self._round[1] if self._round else 0,
                       model=self.model).card()
        card["doing_now"] = getattr(self, "_agent_said", None)
        approach = getattr(self.team, "approach", "") if self.team is not None else ""
        return {"team": {"approach": approach, "parallel": 1, "phase": "working", "packages": [card]}}

    async def run(self, mission: str, *args, **kwargs) -> Dict[str, Any]:
        from app.core.command import mission_budget

        self._spent_before = await mission_budget.spent(self.runtime.task_id)
        if self.job is not None:
            extra = "\n\n".join(part for part in (self.job.brief_for_team(), self.job.brief_for_specialist())
                                if part)
            if extra:
                known = kwargs.get("known")
                kwargs["known"] = (f"{known}\n\n" if known else "") + extra
        result = await super().run(mission, *args, **kwargs)
        await mission_budget.add(self.runtime.task_id, float(self.usage.cost_usd or 0))
        if self.capped:
            note = (f"The {self.title} stopped at this mission's spending allowance; what it found is saved. Say "
                    "\"carry on\" to give it a new allowance.")
            verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
            verification = {**verification, "verified": False,
                            "unmet": [note] + list(verification.get("unmet") or [])}
            result.update({"verification": verification, "needs_continuation": False, "success": False})
        result["role"] = {"specialist": self.role, "title": self.title, "model": self.model}
        return result
