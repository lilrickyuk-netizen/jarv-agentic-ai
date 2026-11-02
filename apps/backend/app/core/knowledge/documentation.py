"""
JARV Backend - Source documentation catalogue for the engineering agents (Upgrade 1a)

Official documentation pages an expert in each field looks things up in. ``licence`` and ``licence_evidence``
were read from the project's own page on 2 November 2026; a source's text is stored only when that licence allows
it (``store``). Where the licence could not be confirmed, the source is ``link_only``: it is listed and found by
its title, and agents read it live with fetch_url. A page that has moved shows as an error in
``python -m app.cli.knowledge status`` rather than being silently skipped.

The other 23 agents' sources follow in Upgrade 1b with the same rules.
"""
from __future__ import annotations

from typing import Dict, List

from app.models.knowledge_library import LICENCE_LINK_ONLY as LINK, LICENCE_STORE as STORE

# Licence facts, each read on the page given as evidence.
_LICENCES = {
    "pnpm": ("MIT", "https://awesome.ecosyste.ms/projects/github.com%2Fpnpm%2Fpnpm.io (pnpm/pnpm.io: MIT)"),
    "uv": ("MIT OR Apache-2.0", "https://docs.astral.sh/uv/reference/policies/license/"),
    "pytest": ("MIT", "https://docs.pytest.org/en/9.0.x/license.html"),
    "kubernetes": ("CC-BY-4.0", "kubernetes.io footer: Documentation Distributed under CC BY 4.0 "
                                "(https://git.k8s.io/website/LICENSE)"),
    "docker": ("Apache-2.0", "https://github.com/docker/docs (content released under the Apache 2.0 license)"),
    "postgresql": ("PostgreSQL", "https://www.postgresql.org/docs/18/legalnotice.html (use, copy, modify, "
                                 "distribute the software and its documentation)"),
    "cloudnative-pg": ("Apache-2.0", "https://github.com/cloudnative-pg/docs (licensed under Apache License 2.0)"),
    "github-docs": ("CC-BY-4.0", "github/docs README, License: content in assets, content and data is CC-BY "
                                 "(as mirrored at https://github.com/Simek/docs)"),
    "vitest": ("MIT", "https://awesome.ecosyste.ms/projects/github.com%2Fvitest-dev%2Fvitest (MIT)"),
    "biome": ("MIT", "https://www.github.com/biomejs/website (MIT license)"),
    "helm": ("MIT", "https://github.com/helm/helm-www (repository licence MIT; the docs live in the repository)"),
    "owasp-asvs": ("CC-BY-SA-4.0", "https://owasp.org/www-project-ASVS/ (Creative Commons Attribution Share "
                                   "Alike 4.0 International)"),
}


def _src(url: str, title: str, publisher: str, agents: List[str], licence_key: str = "") -> Dict:
    if licence_key:
        licence, evidence = _LICENCES[licence_key]
        return {"url": url, "title": title, "publisher": publisher, "agents": agents, "licence": licence,
                "licence_evidence": evidence, "licence_class": STORE}
    return {"url": url, "title": title, "publisher": publisher, "agents": agents, "licence": None,
            "licence_evidence": None, "licence_class": LINK}


CODING, DEBUG, DEVOPS, QA = "coding_agent", "debugging_agent", "devops", "qa"
VERIFY, INFRA, SEC, DOCS = "verifier", "infrastructure", "security", "documentation"

CATALOGUE: List[Dict] = [
    # ----- JavaScript and TypeScript toolchain --------------------------------------------------------
    _src("https://pnpm.io/settings", "Settings (pnpm-workspace.yaml)", "pnpm", [CODING, DEVOPS, VERIFY], "pnpm"),
    _src("https://pnpm.io/package_json", "package.json", "pnpm", [CODING, DEVOPS, VERIFY], "pnpm"),
    _src("https://pnpm.io/workspaces", "Workspace", "pnpm", [CODING, DEVOPS], "pnpm"),
    _src("https://vitest.dev/config/", "Configuring Vitest", "Vitest", [CODING, QA], "vitest"),
    _src("https://vitest.dev/guide/", "Getting Started", "Vitest", [CODING, QA, DEBUG], "vitest"),
    _src("https://biomejs.dev/reference/configuration/", "Configuration", "Biome", [CODING, QA], "biome"),
    _src("https://www.typescriptlang.org/tsconfig/", "TSConfig Reference", "TypeScript", [CODING, DEBUG]),
    _src("https://turborepo.com/docs/reference/configuration", "Configuring turbo.json", "Turborepo",
         [CODING, DEVOPS]),
    _src("https://nodejs.org/en/about/previous-releases", "Node.js Releases", "Node.js", [CODING, DEVOPS, VERIFY]),
    _src("https://docs.npmjs.com/cli/configuring-npm/package-json", "package.json", "npm", [CODING, VERIFY]),
    # ----- Python toolchain -----------------------------------------------------------------------------
    _src("https://docs.astral.sh/uv/concepts/python-versions/", "Python versions", "Astral (uv)",
         [CODING, DEVOPS, VERIFY], "uv"),
    _src("https://docs.astral.sh/uv/concepts/projects/sync/", "Locking and syncing", "Astral (uv)",
         [CODING, DEVOPS, VERIFY], "uv"),
    _src("https://docs.astral.sh/uv/concepts/projects/config/", "Configuring projects", "Astral (uv)",
         [CODING, DEVOPS], "uv"),
    _src("https://docs.pytest.org/en/stable/how-to/fixtures.html", "How to use fixtures", "pytest",
         [CODING, QA, DEBUG], "pytest"),
    _src("https://docs.pytest.org/en/stable/reference/customize.html", "Configuration", "pytest", [QA, DEVOPS],
         "pytest"),
    _src("https://docs.python.org/3/library/asyncio.html", "asyncio", "Python Software Foundation",
         [CODING, DEBUG]),
    # ----- Containers, CI and orchestration --------------------------------------------------------------
    _src("https://docs.docker.com/build/building/best-practices/", "Building best practices", "Docker",
         [DEVOPS, INFRA, SEC], "docker"),
    _src("https://docs.docker.com/reference/compose-file/services/", "Services top-level elements", "Docker",
         [DEVOPS, INFRA, DEBUG], "docker"),
    _src("https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions",
         "Workflow syntax for GitHub Actions", "GitHub", [DEVOPS, QA, VERIFY], "github-docs"),
    _src("https://docs.github.com/en/actions/security-for-github-actions/security-guides/"
         "security-hardening-for-github-actions", "Security hardening for GitHub Actions", "GitHub",
         [SEC, DEVOPS], "github-docs"),
    _src("https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-"
         "github/basic-writing-and-formatting-syntax", "Basic writing and formatting syntax", "GitHub", [DOCS],
         "github-docs"),
    _src("https://kubernetes.io/docs/concepts/workloads/controllers/deployment/", "Deployments", "Kubernetes",
         [INFRA, DEVOPS], "kubernetes"),
    _src("https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",
         "Resource Management for Pods and Containers", "Kubernetes", [INFRA, DEBUG], "kubernetes"),
    _src("https://helm.sh/docs/topics/charts/", "Charts", "Helm", [INFRA, DEVOPS, VERIFY], "helm"),
    _src("https://helm.sh/docs/chart_best_practices/values/", "Values", "Helm", [INFRA, DEVOPS], "helm"),
    # ----- Infrastructure as code ------------------------------------------------------------------------
    _src("https://developer.hashicorp.com/terraform/language/tests", "Tests", "HashiCorp",
         [INFRA, VERIFY, QA]),
    _src("https://developer.hashicorp.com/terraform/language/tests/mocking", "Tests - mocks", "HashiCorp",
         [INFRA, VERIFY, QA]),
    _src("https://developer.hashicorp.com/terraform/language/terraform", "terraform block reference",
         "HashiCorp", [INFRA, VERIFY]),
    # ----- Databases --------------------------------------------------------------------------------------
    _src("https://www.postgresql.org/docs/current/ddl-generated-columns.html", "Generated Columns", "PostgreSQL",
         [CODING, INFRA], "postgresql"),
    _src("https://www.postgresql.org/docs/current/textsearch-controls.html", "Controlling Text Search",
         "PostgreSQL", [CODING, DEBUG], "postgresql"),
    _src("https://www.postgresql.org/docs/current/continuous-archiving.html",
         "Continuous Archiving and Point-in-Time Recovery", "PostgreSQL", [INFRA], "postgresql"),
    _src("https://cloudnative-pg.io/documentation/current/backup/", "Backup", "CloudNativePG",
         [INFRA, VERIFY], "cloudnative-pg"),
    _src("https://cloudnative-pg.io/documentation/current/wal_archiving/", "WAL archiving", "CloudNativePG",
         [INFRA, VERIFY], "cloudnative-pg"),
    _src("https://cloudnative-pg.io/documentation/current/connection_pooling/", "Connection pooling",
         "CloudNativePG", [INFRA], "cloudnative-pg"),
    # ----- Security and versioning -----------------------------------------------------------------------
    _src("https://owasp.org/www-project-ASVS/", "OWASP Application Security Verification Standard", "OWASP",
         [SEC, VERIFY, QA], "owasp-asvs"),
    _src("https://semver.org/", "Semantic Versioning 2.0.0", "semver.org", [VERIFY, DOCS, CODING]),
]

ENGINEERING_AGENTS = (CODING, DEBUG, DEVOPS, QA, VERIFY, INFRA, SEC, DOCS)


def catalogue() -> List[Dict]:
    return [dict(entry) for entry in CATALOGUE]
