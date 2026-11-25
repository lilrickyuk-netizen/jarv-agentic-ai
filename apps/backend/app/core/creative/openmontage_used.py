"""
JAI Backend - What OpenMontage actually did in a mission, for the mission's report

25 November (mission 00d44272): a studio mission skipped OpenMontage's pipeline and hand-wrote its composition, and
nothing on the card showed it. OpenMontage records its own work in each project folder: every tool's execute() is
wrapped to append start and finish lines (tool, success, nesting depth) to the project's events.jsonl
(tools/base_tool.py _instrument_execute, lib/events.py at the pinned 2e003e65), project.json names the pipeline, a
checkpoint per stage records the stages done, and the edit stage's edit_decisions is what VideoCompose renders:
its renderer_family picks the composer's composition (VideoCompose.RENDERER_FAMILY_MAP), its cut and overlay types
pick the components (remotion-composer/SCENE_TYPES.md), and composition_mode "atelier" means a hand-written one.
This reads those files from the mission's folder; it never guesses from what an agent said.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECTS = "openmontage-projects"

# OpenMontage 2e003e65: VideoCompose.RENDERER_FAMILY_MAP and remotion-composer/SCENE_TYPES.md.
COMPOSITION = {"explainer-data": "Explainer", "explainer-teacher": "Explainer", "cinematic-trailer":
               "CinematicRenderer", "documentary-montage": "CinematicRenderer", "product-reveal": "Explainer",
               "screen-demo": "Explainer", "presenter": "TalkingHead", "animation-first": "Explainer"}
CUT_COMPONENT = {None: "OffthreadVideo", "text_card": "TextCard", "hero_title": "HeroTitle", "stat_card": "StatCard",
                 "callout": "CalloutBox", "comparison": "ComparisonCard", "bar_chart": "BarChart",
                 "line_chart": "LineChart", "pie_chart": "PieChart", "kpi_grid": "KPIGrid",
                 "progress_bar": "ProgressBar", "anime_scene": "AnimeScene", "terminal_scene": "TerminalScene",
                 "screenshot_scene": "ScreenshotScene"}
OVERLAY_COMPONENT = {"section_title": "SectionTitle", "stat_reveal": "StatReveal", "hero_title": "HeroTitle",
                     "provider_chip": "ProviderChip"}


def _when(value: Any) -> Optional[datetime]:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _components(edit: Dict[str, Any]) -> List[str]:
    if str(edit.get("composition_mode") or "").lower() == "atelier":
        bespoke = edit.get("bespoke") or {}
        return [f"hand-written composition {bespoke.get('composition_id') or ''}".rstrip() + " (atelier)"]
    found: List[str] = []
    family = edit.get("renderer_family")
    if family in COMPOSITION:
        found.append(COMPOSITION[family])
    for cut in edit.get("cuts") or []:
        if isinstance(cut, dict):
            found.append(CUT_COMPONENT.get(cut.get("type"), str(cut.get("type"))))
    for overlay in edit.get("overlays") or []:
        if isinstance(overlay, dict) and overlay.get("type"):
            found.append(OVERLAY_COMPONENT.get(overlay["type"], str(overlay["type"])))
    subtitles = edit.get("subtitles")
    if subtitles and (not isinstance(subtitles, dict) or subtitles.get("enabled", True)):
        found.append("CaptionOverlay")
    if edit.get("end_tag"):
        found.append("EndTag")
    return list(dict.fromkeys(found))


def used(root: Optional[Path], since: Optional[datetime]) -> Dict[str, Any]:
    """{"pipelines", "stages", "tools", "failed", "components"} from the OpenMontage projects in a mission's folder
    that this mission worked on (touched since it started; every project when since is None)."""
    out: Dict[str, Any] = {"pipelines": [], "stages": [], "tools": {}, "failed": {}, "components": []}
    folder = Path(root) / PROJECTS if root is not None else None
    if folder is None or not folder.is_dir():
        return out
    for project in sorted(p for p in folder.iterdir() if p.is_dir()):
        try:
            touched = datetime.fromtimestamp(max(f.stat().st_mtime for f in [project, *project.iterdir()]),
                                             timezone.utc)
        except (OSError, ValueError):
            continue
        if since is not None and touched < since:
            continue
        pipeline = _json(project / "project.json").get("pipeline_type")
        if pipeline and pipeline not in out["pipelines"]:
            out["pipelines"].append(str(pipeline))
        for checkpoint in sorted(project.glob("checkpoint_*.json")):
            data = _json(checkpoint)
            if data.get("status") == "completed" and data.get("stage") not in out["stages"]:
                out["stages"].append(str(data.get("stage")))
            edit = (data.get("artifacts") or {}).get("edit_decisions") if data.get("stage") == "edit" else None
            if isinstance(edit, dict):
                out["components"] = list(dict.fromkeys([*out["components"], *_components(edit)]))
        try:
            lines = (project / "events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("event") != "finish" or event.get("depth"):
                continue  # a selector's provider call (depth 1+) is the same run, counted once
            stamp = _when(event.get("ts"))
            if since is not None and (stamp is None or stamp < since):
                continue
            key = "tools" if event.get("success") else "failed"
            tool = str(event.get("tool") or "")
            if tool:
                out[key][tool] = out[key].get(tool, 0) + 1
    return out


def summary(found: Dict[str, Any]) -> str:
    """One line for Richard's report: the pipeline, its stages done, the tools that ran (and failed), the
    composer's components the render used."""
    if not found.get("pipelines") and not found.get("tools") and not found.get("failed"):
        return ("**OpenMontage used:** none of its tools ran and no OpenMontage project was made in this "
                "mission's folder.")
    parts = []
    for pipeline in found.get("pipelines") or []:
        stages = found.get("stages") or []
        parts.append(f"pipeline {pipeline}" + (f" (stages done: {', '.join(stages)})" if stages else
                                              " (no stage completed)"))
    tools = found.get("tools") or {}
    parts.append(("tools: " + ", ".join(f"{t} ×{n}" for t, n in tools.items())) if tools
                 else "none of its tools ran")
    if found.get("failed"):
        parts.append("failed: " + ", ".join(f"{t} ×{n}" for t, n in found["failed"].items()))
    if found.get("components"):
        parts.append("components: " + ", ".join(found["components"]))
    return "**OpenMontage used:** " + "; ".join(parts) + "."
