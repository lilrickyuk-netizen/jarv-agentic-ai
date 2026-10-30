"""Curated, source-attributed specialist knowledge for the design roster."""
from typing import Dict, List


_SOURCES = {
    "langchain_multi_agent": {
        "url": "https://docs.langchain.com/oss/python/langchain/multi-agent",
        "title": "Multi-agent",
        "publisher": "LangChain",
    },
    "langgraph_stores": {
        "url": "https://docs.langchain.com/oss/python/langgraph/stores",
        "title": "Stores",
        "publisher": "LangChain",
    },
    "python_style": {
        "url": "https://peps.python.org/pep-0008/",
        "title": "PEP 8 - Style Guide for Python Code",
        "publisher": "Python Software Foundation",
    },
    "python_errors": {
        "url": "https://docs.python.org/3/tutorial/errors.html",
        "title": "Errors and Exceptions",
        "publisher": "Python Software Foundation",
    },
    "pytest_fixtures": {
        "url": "https://docs.pytest.org/en/stable/how-to/fixtures.html",
        "title": "How to use fixtures",
        "publisher": "pytest",
    },
    "sre_troubleshooting": {
        "url": "https://sre.google/sre-book/effective-troubleshooting/",
        "title": "Effective Troubleshooting",
        "publisher": "Google SRE",
    },
    "sre_alerting": {
        "url": "https://sre.google/workbook/alerting-on-slos/",
        "title": "Alerting on SLOs",
        "publisher": "Google SRE Workbook",
    },
    "compose": {
        "url": "https://docs.docker.com/compose/",
        "title": "Docker Compose",
        "publisher": "Docker",
    },
    "prometheus_instrumentation": {
        "url": "https://prometheus.io/docs/practices/instrumentation/",
        "title": "Instrumentation",
        "publisher": "Prometheus Authors",
    },
    "owasp_api": {
        "url": "https://api-security.owasp.org/editions/2023/en/0x11-t10",
        "title": "OWASP Top 10 API Security Risks - 2023",
        "publisher": "OWASP API Security Project",
    },
    "sba_business": {
        "url": "https://www.sba.gov/business-guide/plan-your-business/write-your-business-plan",
        "title": "Plan your business",
        "publisher": "U.S. Small Business Administration",
    },
    "diataxis": {
        "url": "https://diataxis.fr/",
        "title": "Diataxis",
        "publisher": "Diataxis",
    },
    "google_content": {
        "url": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
        "title": "Creating helpful, reliable, people-first content",
        "publisher": "Google Search Central",
    },
    "nist_ai_rmf": {
        "url": "https://www.nist.gov/itl/ai-risk-management-framework",
        "title": "AI Risk Management Framework",
        "publisher": "National Institute of Standards and Technology",
    },
    "ftc_endorsements": {
        "url": "https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking",
        "title": "FTC's Endorsement Guides: What People Are Asking",
        "publisher": "U.S. Federal Trade Commission",
    },
    "ga4_data_api": {
        "url": "https://developers.google.com/analytics/devguides/reporting/data/v1",
        "title": "Google Analytics Data API overview",
        "publisher": "Google Analytics",
    },
    "plain_language": {
        "url": "https://digital.gov/guides/plain-language",
        "title": "Plain language guide series",
        "publisher": "U.S. General Services Administration",
    },
    "contributor_covenant": {
        "url": "https://www.contributor-covenant.org/version/2/1/code_of_conduct/",
        "title": "Contributor Covenant Code of Conduct, version 2.1",
        "publisher": "Contributor Covenant",
    },
    "compose_production": {
        "url": "https://docs.docker.com/compose/how-tos/production/",
        "title": "Use Compose in production",
        "publisher": "Docker",
    },
    "release_rollbacks": {
        "url": "https://cloud.google.com/blog/products/gcp/reliable-releases-and-rollbacks-cre-life-lessons/",
        "title": "Reliable releases and rollbacks - CRE life lessons",
        "publisher": "Google Cloud Blog",
    },
    "cc_licenses": {
        "url": "https://creativecommons.org/share-your-work/cclicenses/",
        "title": "About CC Licenses",
        "publisher": "Creative Commons",
    },
    "plausible_stats": {
        "url": "https://plausible.io/docs/stats-api",
        "title": "Plausible Stats API reference",
        "publisher": "Plausible Analytics",
    },
}


def _entry(agent_name: str, title: str, content: str, keywords: List[str], source: str) -> Dict:
    source_data = _SOURCES[source]
    return {
        "agent_name": agent_name,
        "knowledge_key": "specialist-core",
        "title": title,
        "content": content,
        "keywords": keywords,
              "url": source_data["url"],
              "source_title": source_data["title"],
              "publisher": source_data["publisher"],
              "license": source_data.get("license"),
    }


SPECIALIST_KNOWLEDGE: List[Dict] = [
    _entry("orchestrator", "Task routing and context selection",
           "Choose the coordination pattern from the task shape. Route to a specialist when focused domain context or tools are needed; keep each worker's context limited to its assignment and synthesize its returned evidence. Provide only the information needed for the current task.",
           ["orchestration", "routing", "context", "specialist", "delegation"], "langchain_multi_agent"),
    _entry("swarm_manager", "Scoped specialist work",
           "Use specialized workers for bounded work that benefits from separate context or parallel execution. Keep a parent responsible for routing and synthesis; give each worker only relevant knowledge and task context, and account for coordination overhead.",
           ["swarm", "worker", "scope", "parallel", "context"], "langchain_multi_agent"),
    _entry("coding_agent", "Readable Python changes",
           "Prefer consistency with the existing project over mechanical conformity to a general style guide. Optimize for readability, use clear names, handle exceptions specifically, and keep resource cleanup explicit. A code suggestion is not verified until the project checks run.",
           ["python", "code", "readability", "style", "exceptions"], "python_style"),
    _entry("debugging_agent", "Hypothesis-driven troubleshooting",
           "Start from the observed behavior, inspect telemetry and logs, then state plausible causes as testable hypotheses. Prefer low-risk tests that can disconfirm a hypothesis; distinguish correlation from causation, record negative results, and preserve evidence before changing a live system.",
           ["debugging", "troubleshooting", "hypothesis", "logs", "telemetry"], "sre_troubleshooting"),
    _entry("verifier", "Repeatable test evidence",
           "Make each test self-contained and deterministic. Keep state-changing setup and its cleanup together, assert observed behavior rather than intended behavior, and report the exact test outcome. A test fixture's success is not proof of a production provider integration.",
           ["verification", "tests", "pytest", "fixtures", "evidence"], "pytest_fixtures"),
    _entry("qa", "Isolated functional test design",
           "Use fixtures to make preconditions explicit and reusable. Prefer function-scoped state for isolation, parameterize meaningful input variants, and guarantee teardown after the test. Test externally observable behavior and retain failures rather than masking them.",
           ["quality", "qa", "pytest", "test", "isolation"], "pytest_fixtures"),
    _entry("devops", "Compose service lifecycle",
           "Use the Compose file as the declared service, network, and volume configuration. Validate the resolved configuration, then use Compose lifecycle and status/log commands to operate and inspect the same defined application stack across development, testing, staging, and production.",
           ["devops", "docker", "compose", "services", "deployment"], "compose"),
    _entry("infrastructure", "Single-server Compose in production",
           "Keep production differences in a separate Compose file layered over the base file with -f, so the base "
           "stays the shared definition. In production keep application code inside the image rather than bind "
           "mounts, set a restart policy, use production environment values such as lower log verbosity, and add "
           "supporting services such as log collection. Deploy a change by rebuilding the service image and "
           "recreating only that service with 'up --no-deps -d', so its dependencies are not restarted.",
           ["infrastructure", "compose", "production", "restart", "deploy", "server"], "compose_production"),
    _entry("monitoring", "Useful Prometheus instrumentation",
           "For request-serving systems, measure request volume, errors, and latency; for background processing, expose queue/progress and last-success signals. Use counters for cumulative events and gauges for values that can decrease. Prefer labels over generated metric names and keep label cardinality bounded.",
           ["monitoring", "prometheus", "metrics", "alerts", "instrumentation"], "prometheus_instrumentation"),
    _entry("self_healing", "Safe incident diagnosis and mitigation",
           "Triage user impact before root-cause work and preserve evidence. Examine system state, logs, and metrics, then test likely causes using controlled, low-risk experiments. Record the change and observed result; do not treat an unverified mitigation as a repair.",
           ["self-healing", "incident", "recovery", "diagnosis", "mitigation"], "sre_troubleshooting"),
    _entry("rollback", "Roll back first, then investigate",
           "Treat every release as possibly faulty and roll back first when it misbehaves; a hurried roll-forward "
           "fix can fail or expose other untested problems. Rollback is routine, not blame. Keep rollback trusted "
           "by exercising it while the release is healthy. Schema changes are the main obstacle: ship a "
           "feature-free release that tolerates the new schema, then change the schema, then ship the features, "
           "so either release can be rolled back without undoing the schema. Restoring data is a separate, "
           "heavier operation than rolling back a release.",
           ["rollback", "release", "deployment", "schema", "recovery", "revert"], "release_rollbacks"),
    _entry("security", "API security review priorities",
           "For every data access using a caller-supplied object ID, verify object-level authorization. Also review authentication, property/function authorization, resource limits, sensitive workflows, SSRF, configuration, endpoint inventory, and trust boundaries for third-party API responses.",
           ["security", "owasp", "api", "authorization", "ssrf"], "owasp_api"),
    _entry("company_operator", "Business planning and market evidence",
           "Separate market research, competitive analysis, operating assumptions, and funding needs. Use customer research to understand demand and competitive analysis to identify a defensible distinction; label estimates and validate them before making financial commitments.",
           ["company", "operations", "business", "market", "planning"], "sba_business"),
    _entry("workspace_manager", "Durable scoped knowledge storage",
           "Use durable stores for knowledge that must survive runs and threads; keep thread state separate. Namespace data by its owner and purpose, preserve timestamps, and retrieve only the matching scope. An in-memory store is suitable for tests, not persistence across process restarts.",
           ["workspace", "storage", "knowledge", "namespace", "persistence"], "langgraph_stores"),
    _entry("business", "Business model and competitive analysis",
           "Ground a business plan in customer and market research, then use competitive analysis to clarify differentiation. Estimate startup costs and break-even assumptions explicitly; distinguish sourced facts from projections and assumptions.",
           ["business", "strategy", "market", "competitive", "costs"], "sba_business"),
    _entry("finance", "Startup cost and break-even analysis",
           "Build a complete cost picture by identifying expenses, estimating each item, and summing them before evaluating funding needs. A break-even calculation depends on its stated assumptions; do not present an estimate as observed company financial data.",
           ["finance", "cost", "break-even", "funding", "budget"], "sba_business"),
    _entry("documentation", "Documentation information architecture",
           "Classify a documentation need before drafting: tutorials teach through a learning experience, how-to guides help accomplish a task, reference describes technical facts, and explanation gives context or rationale. Organize content around the reader's need, not the author's org chart.",
           ["documentation", "tutorial", "how-to", "reference", "explanation"], "diataxis"),
    _entry("research", "Sourced, people-first research",
           "Keep claims tied to sources actually consulted. Prefer original analysis that adds value over copying or lightly rewriting a source; identify uncertainty, avoid overstated conclusions, and make the evidence and its limits visible to the reader.",
           ["research", "sources", "evidence", "provenance", "analysis"], "google_content"),
    _entry("memory", "Cross-run memory retrieval and scope",
           "Use persistent storage for durable facts shared across threads and a separate checkpoint for thread-specific state. Namespace by owner and memory purpose, retrieve within that namespace, track creation/update times, and use semantic ranking only when a configured embedding backend actually supplies it.",
           ["memory", "retrieval", "persistence", "semantic", "namespace"], "langgraph_stores"),
    _entry("self_evolution", "Risk-managed AI system changes",
           "Treat AI changes as a lifecycle risk-management activity: govern responsibilities, map intended context and risks, measure outcomes, and manage identified risks. Record evidence and evaluate changes before activation; a framework is guidance, not a claim of certification or safety proof.",
           ["self-evolution", "ai", "risk", "governance", "verification"], "nist_ai_rmf"),
    _entry("marketing", "Truthful marketing and endorsement review",
           "Endorsements must reflect the endorser's honest experience and must not make unsupported product claims. Disclose material relationships clearly where the audience sees the endorsement; assess the actual medium and context rather than assuming a profile bio or platform label is sufficient.",
           ["marketing", "endorsement", "disclosure", "claims", "campaign"], "ftc_endorsements"),
    _entry("growth", "Measuring growth with privacy-friendly analytics",
           "Query visitors, visits, pageviews, bounce rate and visit duration for an explicit date range; conversion "
           "rates need goals configured first and are read through the goal dimension. Session metrics cannot be "
           "combined with event dimensions other than page and hostname, and time buckets follow the site's "
           "reporting timezone. Keep measured counts separate from hypotheses, and plan each experiment against a "
           "measured baseline.",
           ["growth", "analytics", "conversion", "goals", "visitors", "experiment"], "plausible_stats"),
    _entry("customer_support", "Clear customer-facing responses",
           "Write for the specific audience and the task they need to complete. Use plain, direct wording, structure information for scanning, and test whether readers understand it; do not confuse internal terminology with customer understanding.",
           ["support", "customer", "plain language", "response", "understanding"], "plain_language"),
    _entry("sales", "Evidence-led prospect qualification",
           "Use market research to identify customers and competitive analysis to understand alternatives and differentiation. Keep prospect claims tied to evidence, distinguish confirmed CRM facts from assumptions, and do not imply an endorsement or business result that has not been established.",
           ["sales", "prospect", "market research", "pipeline", "competitive"], "sba_business"),
    _entry("onboarding", "Measure user onboarding outcomes",
           "Define the user outcome and event measures before interpreting onboarding performance. The Analytics Data API can report dimensions and metrics for a property and date range; results follow its configured reporting identity. Respect consent requirements and do not infer causality from descriptive counts alone.",
           ["onboarding", "activation", "analytics", "events", "consent"], "ga4_data_api"),
    _entry("community", "Community conduct and fair enforcement",
           "Set clear expectations for respectful participation, privacy, constructive feedback, and accountability. Publish a usable reporting path and review reports promptly and fairly; enforcement contacts and rules must be adapted and completed by the community that adopts the policy.",
           ["community", "moderation", "conduct", "privacy", "enforcement"], "contributor_covenant"),
    _entry("partnerships", "Partner fit and market advantage",
           "Use customer and market research to establish why a partnership fits, and competitive analysis to identify the advantage it could create. Separate validated partner facts from hypotheses; document mutual value, risks, and assumptions before making commitments.",
           ["partnership", "business development", "market", "fit", "competitive"], "sba_business"),
    _entry("content", "Useful, reliable content planning",
           "Create for an identifiable audience and purpose. Add original information or analysis, substantiate factual claims, make authorship and sourcing clear, and avoid producing material solely to attract search traffic. Evaluate how automation contributed when readers would reasonably care.",
           ["content", "people-first", "quality", "sources", "authorship"], "google_content"),
    _entry("creation", "Licensing creative assets",
           "Creative Commons licences combine elements: BY requires credit to the creator; SA requires adaptations to "
           "carry the same licence; NC permits only non-commercial use; ND permits no adaptations. A commercial "
           "product can use BY and BY-SA works (with share-alike obligations for adaptations) and ND works only "
           "unmodified; NC works are excluded. Record the creator, source and licence of every asset when it is "
           "obtained, keep the credits current, and do not use an asset whose licence cannot be established.",
           ["creation", "assets", "licence", "license", "attribution", "creative commons"], "cc_licenses"),
    _entry("legal", "Endorsement compliance review boundaries",
           "Review whether an endorsement reflects truthful experience, whether product claims are substantiated, and whether material connections are disclosed clearly and conspicuously. The FTC guide explains agency guidance and examples, not a legal safe harbor; refer fact-specific legal conclusions to qualified counsel.",
           ["legal", "compliance", "endorsement", "disclosure", "claims"], "ftc_endorsements"),
    _entry("analytics", "Analytics reports and data consistency",
           "Define the property, date range, dimensions, and metrics for each report. Google Analytics Data API results follow the property's reporting identity settings, so document that identity with interpretations. Treat alpha features as early preview and separate reported observations from causal claims.",
           ["analytics", "data api", "dimensions", "metrics", "reporting identity"], "ga4_data_api"),
]


def specialist_knowledge() -> List[Dict]:
    """Every agent's core brief plus its field library (app.core.knowledge.library), as fresh dictionaries."""
    from app.core.knowledge.library import library_entries

    return [dict(item) for item in SPECIALIST_KNOWLEDGE] + library_entries()