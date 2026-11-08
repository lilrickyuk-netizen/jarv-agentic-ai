"""
JAI Backend - Source documentation catalogue for all 31 agents (Upgrades 1a and 1b)

Official documentation pages an expert in each field looks things up in. ``licence`` and ``licence_evidence``
were read from the publisher's own page on 2 November 2026; a source's text is stored only when that licence allows
it (``store``). Where the licence could not be confirmed, or does not allow storing (no-derivatives or
non-commercial terms), the source is ``link_only``: it is listed and found by its title, and agents read it live
with fetch_url. A page that has moved shows as an error in ``python -m app.cli.knowledge status`` rather than being
silently skipped. Sources dropped from this catalogue are retired on the next ingest (their passages go inactive).

Upgrade 1a covered the eight engineering agents; Upgrade 1b covers the other 23, with UK sources (GOV.UK, the ICO)
for business, finance, legal, sales and support, since Richard's companies operate in the UK.
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
    # Upgrade 1b
    "owasp-cheatsheets": ("CC-BY-SA-4.0", "https://github.com/OWASP/CheatSheetSeries (license: cc-by-sa-4.0)"),
    "prometheus": ("Apache-2.0", "https://github.com/prometheus/docs (Apache License 2.0; the repository holds the "
                                 "prometheus.io documentation content)"),
    "ogl-govuk": ("OGL-UK-3.0", "GOV.UK footer: All content is available under the Open Government Licence v3.0, "
                                "except where otherwise stated (https://www.nationalarchives.gov.uk/doc/"
                                "open-government-licence/version/3/)"),
    "ogl-ico": ("OGL-UK-3.0", "https://ico.org.uk/global/copyright-and-re-use-of-materials/ (All text content on this "
                              "website is available under the Open Government Licence v3.0, except where otherwise "
                              "stated; credit: Information Commissioner's Office)"),
    "google-developers": ("CC-BY-4.0", "https://developers.google.com/site-policies (Except as otherwise noted, the "
                                       "content of this page is licensed under the Creative Commons Attribution 4.0 "
                                       "License)"),
    "mdn": ("CC-BY-SA-2.5", "https://developer.mozilla.org/en-US/docs/MDN/Writing_guidelines/Attrib_copyright_license "
                            "(prose CC-BY-SA v2.5 or later; credit Mozilla Contributors)"),
    "nist": ("US-Government-public", "https://www.nist.gov/copyrights-disclaimers (With the exception of material "
                                     "marked as copyrighted, information presented on NIST sites are considered public "
                                     "information and may be distributed or copied)"),
    "wikipedia": ("CC-BY-SA-4.0", "Wikipedia footer: Text is available under the Creative Commons "
                                  "Attribution-ShareAlike 4.0 License"),
    "creativecommons": ("CC-BY-4.0", "creativecommons.org footer: Except where otherwise noted, content on this site "
                                     "is licensed under a Creative Commons Attribution 4.0 International license"),
    "pgvector": ("PostgreSQL", "https://github.com/pgvector/pgvector (LICENSE: PostgreSQL License; the README is in "
                               "the repository)"),
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
ORCH, SWARM, MONITOR, HEAL, ROLLBACK = "orchestrator", "swarm_manager", "monitoring", "self_healing", "rollback"
COMPANY, WORKSPACE, BUSINESS, FINANCE = "company_operator", "workspace_manager", "business", "finance"
RESEARCH, MEMORY, EVOLVE = "research", "memory", "self_evolution"
MARKETING, GROWTH, SUPPORT, SALES = "marketing", "growth", "customer_support", "sales"
ONBOARD, COMMUNITY, PARTNER, CONTENT = "onboarding", "community", "partnerships", "content"
CREATION, LEGAL, ANALYTICS = "creation", "legal", "analytics"

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
    _src("https://cloudnative-pg.io/docs/1.30/backup", "Backup", "CloudNativePG", [INFRA, VERIFY, ROLLBACK],
         "cloudnative-pg"),
    _src("https://cloudnative-pg.io/docs/1.30/recovery", "Recovery", "CloudNativePG", [INFRA, ROLLBACK],
         "cloudnative-pg"),
    _src("https://cloudnative-pg.io/docs/1.30/wal_archiving", "WAL archiving", "CloudNativePG", [INFRA, VERIFY],
         "cloudnative-pg"),
    _src("https://cloudnative-pg.io/docs/1.30/connection_pooling", "Connection pooling", "CloudNativePG", [INFRA],
         "cloudnative-pg"),
    # ----- Security and versioning -----------------------------------------------------------------------
    _src("https://owasp.org/www-project-ASVS/", "OWASP Application Security Verification Standard", "OWASP",
         [SEC, VERIFY, QA], "owasp-asvs"),
    _src("https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html",
         "Secrets Management Cheat Sheet", "OWASP", [SEC, DEVOPS, INFRA], "owasp-cheatsheets"),
    _src("https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html",
         "Authentication Cheat Sheet", "OWASP", [SEC, CODING], "owasp-cheatsheets"),
    _src("https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html",
         "Input Validation Cheat Sheet", "OWASP", [SEC, CODING, QA], "owasp-cheatsheets"),
    _src("https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html", "Logging Cheat Sheet", "OWASP",
         [SEC, MONITOR, CODING], "owasp-cheatsheets"),
    _src("https://semver.org/", "Semantic Versioning 2.0.0", "semver.org", [VERIFY, DOCS, CODING, CONTENT]),

    # ===== Upgrade 1b: the other 23 agents ===============================================================
    # ----- Operations: monitoring, self-healing, rollback -------------------------------------------------
    _src("https://prometheus.io/docs/practices/alerting/", "Alerting", "Prometheus", [MONITOR, HEAL], "prometheus"),
    _src("https://prometheus.io/docs/practices/naming/", "Metric and label naming", "Prometheus",
         [MONITOR, ANALYTICS], "prometheus"),
    _src("https://prometheus.io/docs/practices/instrumentation/", "Instrumentation", "Prometheus",
         [MONITOR, CODING], "prometheus"),
    _src("https://prometheus.io/docs/concepts/metric_types/", "Metric types", "Prometheus", [MONITOR, ANALYTICS],
         "prometheus"),
    _src("https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/", "Alerting rules",
         "Prometheus", [MONITOR, HEAL], "prometheus"),
    _src("https://prometheus.io/docs/alerting/latest/overview/", "Alerting overview", "Prometheus",
         [MONITOR, HEAL], "prometheus"),
    _src("https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/",
         "Configure Liveness, Readiness and Startup Probes", "Kubernetes", [HEAL, MONITOR, INFRA], "kubernetes"),
    _src("https://kubernetes.io/docs/concepts/workloads/controllers/job/", "Jobs", "Kubernetes",
         [SWARM, INFRA], "kubernetes"),
    _src("https://helm.sh/docs/helm/helm_rollback", "helm rollback", "Helm", [ROLLBACK, DEVOPS], "helm"),
    _src("https://developer.mozilla.org/en-US/docs/Web/HTTP/Status", "HTTP response status codes", "MDN",
         [MONITOR, HEAL, DEBUG, SUPPORT], "mdn"),
    _src("https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching", "HTTP caching", "MDN", [HEAL, INFRA], "mdn"),
    _src("https://sre.google/sre-book/monitoring-distributed-systems/", "Monitoring Distributed Systems",
         "Google SRE book", [MONITOR, HEAL]),  # CC BY-NC-ND: read live, never stored
    _src("https://sre.google/sre-book/postmortem-culture/", "Postmortem Culture", "Google SRE book",
         [HEAL, ROLLBACK, EVOLVE]),

    # ----- Orchestration, swarm, memory, self-evolution, research -----------------------------------------
    _src("https://airc.nist.gov/airmf-resources/airmf/5-sec-core/", "AI RMF Core", "NIST",
         [ORCH, EVOLVE, SWARM, LEGAL], "nist"),
    _src("https://airc.nist.gov/airmf-resources/playbook/", "AI RMF Playbook", "NIST", [EVOLVE, ORCH], "nist"),
    _src("https://www.anthropic.com/engineering/building-effective-agents", "Building effective agents",
         "Anthropic", [ORCH, SWARM, EVOLVE]),
    _src("https://docs.celeryq.dev/en/stable/userguide/canvas.html", "Canvas: Designing Work-flows", "Celery",
         [SWARM, ORCH]),
    _src("https://github.com/pgvector/pgvector", "pgvector", "pgvector", [MEMORY, CODING], "pgvector"),
    _src("https://www.postgresql.org/docs/current/textsearch-intro.html", "Full Text Search: Introduction",
         "PostgreSQL", [MEMORY, RESEARCH], "postgresql"),
    _src("https://en.wikipedia.org/wiki/Wikipedia:Reliable_sources", "Reliable sources", "Wikipedia",
         [RESEARCH, CONTENT, MEMORY], "wikipedia"),
    _src("https://www.gov.uk/service-manual/user-research/start-by-learning-user-needs",
         "Learning about users and their needs", "GOV.UK Service Manual", [RESEARCH, ONBOARD, BUSINESS],
         "ogl-govuk"),

    # ----- Company operations, workspace management, business, finance (UK) ------------------------------
    _src("https://www.gov.uk/service-manual/service-standard", "The Service Standard", "GOV.UK Service Manual",
         [COMPANY, WORKSPACE, BUSINESS, QA], "ogl-govuk"),
    _src("https://www.gov.uk/service-manual/agile-delivery/agile-government-services-introduction",
         "Agile delivery: an introduction", "GOV.UK Service Manual", [COMPANY, WORKSPACE, ORCH], "ogl-govuk"),
    _src("https://www.gov.uk/running-a-limited-company", "Running a limited company", "GOV.UK",
         [COMPANY, BUSINESS, LEGAL, FINANCE], "ogl-govuk"),
    _src("https://www.gov.uk/prepare-file-annual-accounts-for-limited-company",
         "Prepare annual accounts for a private limited company", "GOV.UK", [FINANCE, COMPANY], "ogl-govuk"),
    _src("https://www.gov.uk/corporation-tax", "Corporation Tax", "GOV.UK", [FINANCE, BUSINESS], "ogl-govuk"),
    _src("https://www.gov.uk/vat-registration", "VAT registration", "GOV.UK", [FINANCE, BUSINESS, SALES],
         "ogl-govuk"),
    _src("https://www.gov.uk/register-for-vat/how-register-for-vat", "How to register for VAT", "GOV.UK",
         [FINANCE], "ogl-govuk"),
    _src("https://www.gov.uk/paye-for-employers", "PAYE for employers", "GOV.UK", [FINANCE, COMPANY], "ogl-govuk"),
    _src("https://www.gov.uk/service-manual/measuring-success/how-to-set-performance-metrics-for-your-service",
         "How to set performance metrics for your service", "GOV.UK Service Manual",
         [ANALYTICS, BUSINESS, GROWTH, FINANCE], "ogl-govuk"),
    _src("https://www.gov.uk/service-manual/measuring-success/measuring-the-success-of-your-service",
         "Measuring the success of your service", "GOV.UK Service Manual", [ANALYTICS, GROWTH, COMPANY],
         "ogl-govuk"),

    # ----- Marketing, growth, content, creation ----------------------------------------------------------
    _src("https://developers.google.com/search/docs/fundamentals/seo-starter-guide", "SEO Starter Guide",
         "Google Search Central", [MARKETING, GROWTH, CONTENT], "google-developers"),
    _src("https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
         "Creating helpful, reliable, people-first content", "Google Search Central", [CONTENT, MARKETING, DOCS],
         "google-developers"),
    _src("https://developers.google.com/search/docs/essentials", "Google Search Essentials",
         "Google Search Central", [MARKETING, GROWTH, CONTENT], "google-developers"),
    _src("https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/"
         "guidance-on-direct-marketing-using-electronic-mail/", "Guidance on direct marketing using electronic mail",
         "Information Commissioner's Office", [MARKETING, SALES, GROWTH, LEGAL], "ogl-ico"),
    _src("https://www.asa.org.uk/codes-and-rulings/advertising-codes/non-broadcast-code.html",
         "The CAP Code (non-broadcast advertising)", "ASA / CAP", [MARKETING, CONTENT, LEGAL]),
    _src("https://web.dev/articles/vitals", "Web Vitals", "web.dev", [GROWTH, MARKETING, CODING]),
    _src("https://www.gov.uk/copyright", "How copyright protects your work", "GOV.UK",
         [CREATION, CONTENT, LEGAL], "ogl-govuk"),
    _src("https://creativecommons.org/share-your-work/cclicenses/", "About CC Licenses", "Creative Commons",
         [CREATION, CONTENT, LEGAL], "creativecommons"),

    # ----- Customer support, sales, onboarding, community, partnerships ----------------------------------
    _src("https://www.gov.uk/accepting-returns-and-giving-refunds", "Accepting returns and giving refunds: the law",
         "GOV.UK", [SUPPORT, SALES, LEGAL], "ogl-govuk"),
    _src("https://www.gov.uk/online-and-distance-selling-for-businesses", "Online and distance selling",
         "GOV.UK", [SALES, SUPPORT, LEGAL], "ogl-govuk"),
    _src("https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/right-of-access/",
         "Right of access", "Information Commissioner's Office", [SUPPORT, LEGAL], "ogl-ico"),
    _src("https://www.gov.uk/service-manual/design/writing-for-user-interfaces", "Writing for user interfaces",
         "GOV.UK Service Manual", [ONBOARD, CONTENT, SUPPORT, DOCS], "ogl-govuk"),
    _src("https://www.gov.uk/service-manual/helping-people-to-use-your-service/"
         "making-your-service-accessible-an-introduction", "Making your service accessible: an introduction",
         "GOV.UK Service Manual", [ONBOARD, QA, CONTENT], "ogl-govuk"),
    _src("https://design-system.service.gov.uk/patterns/question-pages/", "Question pages",
         "GOV.UK Design System", [ONBOARD], "ogl-govuk"),
    _src("https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/"
         "adding-a-code-of-conduct-to-your-project", "Adding a code of conduct to your project", "GitHub",
         [COMMUNITY], "github-docs"),
    _src("https://docs.github.com/en/communities/moderating-comments-and-conversations/managing-disruptive-comments",
         "Managing disruptive comments", "GitHub", [COMMUNITY], "github-docs"),
    _src("https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-sharing/"
         "data-sharing-a-code-of-practice/", "Data sharing: a code of practice", "Information Commissioner's Office",
         [PARTNER, LEGAL], "ogl-ico"),
    _src("https://www.gov.uk/intellectual-property-an-overview", "Intellectual property: an overview", "GOV.UK",
         [PARTNER, LEGAL, CREATION], "ogl-govuk"),

    # ----- Legal and compliance (UK) ---------------------------------------------------------------------
    _src("https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/a-guide-to-lawful-basis/",
         "A guide to lawful basis", "Information Commissioner's Office", [LEGAL, MARKETING, ANALYTICS], "ogl-ico"),
    _src("https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/"
         "the-right-to-be-informed/", "The right to be informed", "Information Commissioner's Office",
         [LEGAL, ONBOARD], "ogl-ico"),
    _src("https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/"
         "guidance-on-the-use-of-storage-and-access-technologies/what-are-storage-and-access-technologies/",
         "What are storage and access technologies (cookies)", "Information Commissioner's Office",
         [LEGAL, ANALYTICS, GROWTH], "ogl-ico"),
]

ENGINEERING_AGENTS = (CODING, DEBUG, DEVOPS, QA, VERIFY, INFRA, SEC, DOCS)
ALL_AGENTS = ENGINEERING_AGENTS + (ORCH, SWARM, MONITOR, HEAL, ROLLBACK, COMPANY, WORKSPACE, BUSINESS, FINANCE,
                                   RESEARCH, MEMORY, EVOLVE, MARKETING, GROWTH, SUPPORT, SALES, ONBOARD, COMMUNITY,
                                   PARTNER, CONTENT, CREATION, LEGAL, ANALYTICS)


def catalogue() -> List[Dict]:
    """The official documentation, then the skill packs' skills (Upgrades 1-5) when they are switched on."""
    from app.core.config import settings
    from app.core.knowledge.skill_packs import catalogue_entries

    entries = [dict(entry) for entry in CATALOGUE]
    if getattr(settings, "SKILL_PACKS_ENABLED", True):
        entries += catalogue_entries()
    return entries
