"""
22 November: content is researched before it is made. Richard on a quote video built from four stills and a cliché:
"absolutely terrible for the cost and the time". The free research skills (social-media-skills, video-agent-skills)
are pinned, yt-dlp is in the sandbox, every content mission researches the niche's outliers first and saves them,
and Plexecute's playbook (organic, no call to action, natural voice or none, no music) is in the brief and in the
independent check. Pure: nothing runs, nothing is spent.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.core.knowledge import content_rules, skill_packs
from tests.repo_paths import repo_path

ROOT = "C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES"
EPISODE = ("Use OpenMontage to make episode 1 of Plexecute's black stick-figure series in "
           "C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES, about why plans collapse on day three.")
# Skills in the two packs that need a paid service or an account JAI does not have.
PAID = {"outliers", "vox", "codex-images", "insta-audit", "publish", "synthesia", "suno", "kling", "veo-3", "runway",
        "heygen", "luma", "opus-clip", "descript", "canva", "ideogram", "nano-banana", "flux", "ai-voiceover",
        "ai-video", "ai-music-and-sound", "ai-image-editing"}


def test_the_research_packs_are_mit_pinned_and_only_their_free_skills_are_listed():
    for name, publisher in (("social-media-skills", "Frank Heijdenrijk"), ("video-agent-skills", "Melvyn Malherbe")):
        pack = skill_packs.PACKS[name]
        assert len(pack["commit"]) == 40 and pack.get("licence", "MIT") == "MIT" and pack["publisher"] == publisher
    mine = {e["skill"] for e in skill_packs.SKILLS if e["pack"] in ("social-media-skills", "video-agent-skills")}
    assert {"studio-script", "steal", "competitor-analysis", "viral-reverse-engineering", "hook-writer",
            "short-form-video-script", "youtube-shorts"} <= mine
    assert not mine & PAID
    names = [e["skill"] for e in skill_packs.SKILLS]
    assert len(names) == len(set(names))  # the sandbox loads a skill by its name: one skill per name


def test_the_studio_and_content_specialists_are_offered_the_research_skills():
    for role in ("creation", "content", "marketing"):
        offered = {path.rsplit("/", 1)[-1] for path in skill_packs.sandbox_skills(role)}
        assert {"studio-script", "steal", "competitor-analysis", "viral-reverse-engineering"} <= offered, role
    assert "studio-script" not in {p.rsplit("/", 1)[-1] for p in skill_packs.sandbox_skills("coding_agent")}


def test_the_sandbox_has_yt_dlp_pinned_in_its_own_environment_with_node_for_youtube():
    dockerfile = repo_path("services", "openhands", "Dockerfile").read_text()
    assert "ARG YT_DLP_VERSION=2026.10.26" in dockerfile
    assert '"yt-dlp[default]==${YT_DLP_VERSION}"' in dockerfile and "python3 -m venv /opt/yt-dlp" in dockerfile
    # Deno, yt-dlp's default JavaScript runtime for YouTube, from Deno's official binary image; and yt-dlp with
    # youtube-transcript-api in OpenMontage's own environment, which its reference-video tools import.
    assert "ARG DENO_IMAGE=denoland/deno:bin-2.9.8" in dockerfile and "COPY --from=deno /deno /usr/local/bin/deno" in dockerfile
    assert '/opt/openmontage/.venv/bin/pip install --no-cache-dir "yt-dlp[default]==${YT_DLP_VERSION}"' in dockerfile
    assert "youtube-transcript-api==${YOUTUBE_TRANSCRIPT_API_VERSION}" in dockerfile
    # After OpenMontage, so adding it never makes Docker rebuild the studio or the toolchain.
    assert dockerfile.index("ARG OPENMONTAGE_COMMIT") < dockerfile.index("ARG YT_DLP_VERSION")
    assert "Social Media Skills and Video Agent Skills" in repo_path("scripts", "skill-packs.sh").read_text()


def test_only_a_brief_that_asks_for_an_ad_gets_one():
    assert content_rules.is_ad("Make a 30 second video ad for Plexecute")
    assert content_rules.is_ad("Make an advert for Plexecute")
    for organic in (EPISODE, "Make a reel about habits for Plexecute, not an ad", "Add the address to the brief"):
        assert not content_rules.is_ad(organic), organic


def test_the_playbook_applies_to_plexecute_by_its_name_or_its_folder():
    assert content_rules.product_of("Make a reel", ROOT) == "plexecute"
    assert content_rules.product_of("Make a reel for MYCO", "C:\\Projects\\MYCO") is None
    organic = content_rules.playbook_for(EPISODE, ROOT)
    assert "black stick-figure series" in organic and "No music." in organic
    assert "no call to action" in organic and "Never a robotic text-to-speech voice" in organic
    ad = content_rules.playbook_for("Make a 30 second video ad for Plexecute")
    assert "one clear call to action" in ad and "no call to action, no waiting list" not in ad
    assert content_rules.playbook_for("Make a reel for MYCO", "C:\\Projects\\MYCO") == ""


def test_research_comes_first_is_saved_and_reuses_the_watchlist(tmp_path):
    first = content_rules.research_rule(EPISODE, tmp_path)
    assert "RESEARCH BEFORE YOU CREATE" in first and "studio-script" in first and "ytsearch30" in first
    assert "Treg" in first and "paid service JAI does not use" in first
    assert ".jai/research/<today>-<topic>.md" in first and "No watchlist exists yet" in first
    assert "never invent an outlier" in first and "Never copy a line, a clip or a frame" in first
    (tmp_path / ".jai" / "research").mkdir(parents=True)
    (tmp_path / content_rules.WATCHLIST).write_text("@channel\n")
    assert "Start from .jai/research/watchlist.md" in content_rules.research_rule(EPISODE, tmp_path)


def _team(tmp_path, monkeypatch):
    from app.core.command import mission_org
    from app.core.workspaces import fs_inspector

    monkeypatch.setattr(fs_inspector, "host_to_container", lambda host: tmp_path)
    team = SimpleNamespace(workspace_root=ROOT)
    team._product_facts = lambda mission: mission_org.MissionTeam._product_facts(team, mission)
    team._content_rules = lambda mission, studio=False: mission_org.MissionTeam._content_rules(team, mission, studio)
    team._creative_check = mission_org.MissionTeam._creative_check
    return mission_org, team


def test_a_studio_video_researches_first_and_carries_the_playbook(tmp_path, monkeypatch):
    mission_org, team = _team(tmp_path, monkeypatch)
    package = mission_org.MissionTeam._skill_package(team, skill_packs.STUDIO_SKILL, ["R1"], EPISODE)
    assert "RESEARCH BEFORE YOU CREATE" in package.goal and "black stick-figure series" in package.goal
    # The outliers become OpenMontage's own references: its analyst and research director do the rest, with no
    # second scriptwriting method competing with its stages, and no music unless the brief asks.
    assert "skills/meta/video-reference-analyst.md" in package.goal and "VideoAnalysisBrief" in package.goal
    assert "no music unless the brief asks for music" in package.goal
    assert "competitor-analysis" not in package.goal and "steal skill" not in package.goal
    check = mission_org.MissionTeam._creative_verifier(team, skill_packs.STUDIO_SKILL, EPISODE)
    assert ".jai/research/" in check.goal and "call to action" in check.goal
    assert "worth watching for its own sake" in check.goal and "destination sold" not in check.goal
    assert "black stick-figure series" in check.goal  # the checker reads the playbook it judges by
    ad = mission_org.MissionTeam._creative_verifier(team, skill_packs.STUDIO_SKILL,
                                                    "Use OpenMontage to make a video ad for Plexecute")
    assert "destination sold" in ad.goal


def test_a_carousel_researches_first_and_software_does_not(tmp_path, monkeypatch):
    mission_org, team = _team(tmp_path, monkeypatch)
    social = next(e for e in skill_packs.SKILLS if (e["pack"], e["skill"]) == skill_packs.CAROUSEL_SKILL)
    carousel = mission_org.MissionTeam._skill_package(team, social, ["R1"], "Make a carousel for Plexecute")
    assert "RESEARCH BEFORE YOU CREATE" in carousel.goal and "competitor-analysis" in carousel.goal
    assert "video-reference-analyst" not in carousel.goal
    other = mission_org.MissionTeam._skill_package(team, {"skill": "frontend-design", "sandbox": ["coding_agent"]},
                                                   ["R1"], "Use your frontend-design skill")
    assert "RESEARCH BEFORE YOU CREATE" not in other.goal and "PLAYBOOK" not in other.goal


def test_a_content_specialist_mission_researches_first_and_a_sales_one_does_not(tmp_path, monkeypatch):
    from app.core.command.mission_org import MissionTeam
    from app.core.workspaces import fs_inspector

    monkeypatch.setattr(fs_inspector, "host_to_container", lambda host: tmp_path)
    team = MissionTeam.__new__(MissionTeam)
    team.workspace_root = ROOT
    content = team._builder_package(["R1"], kind={"specialist": "content", "skills": ()}, mission=EPISODE)
    assert "RESEARCH BEFORE YOU CREATE" in content.goal and "black stick-figure series" in content.goal
    sales = team._builder_package(["R1"], kind={"specialist": "sales", "skills": ()}, mission="Build a lead list")
    assert "RESEARCH BEFORE YOU CREATE" not in sales.goal
