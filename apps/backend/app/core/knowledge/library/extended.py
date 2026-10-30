"""Further field knowledge so every agent covers at least six topics, from the same read sources."""
from __future__ import annotations

from app.core.knowledge.library._base import topic

ENTRIES = [
    # ----- swarm manager -----------------------------------------------------------------------------
    topic("swarm_manager", "swarm-reliability", "Keeping a swarm reliable", """
        Long-running parallel work fails in compounding ways, so checkpoint each worker's progress and resume from
        the last checkpoint instead of restarting; wrap tool calls in bounded retries; let a worker adapt when a
        tool fails rather than aborting the run; and trace every worker's decisions and tool calls so failures can
        be diagnosed. A synchronous lead that waits for each batch is a bottleneck but keeps coordination simple;
        go asynchronous only when the gain justifies harder state and error handling. Dissolve workers when their
        task ends, fails or times out.""",
        ["swarm", "reliability", "checkpoint", "retries", "tracing", "workers", "failure"], "anthropic_multiagent"),
    topic("swarm_manager", "swarm-evaluation", "Judging a swarm's output", """
        Define success before launching: specific, measurable criteria for the combined result. Grade the final
        output, not whether workers followed an expected path: code checks for exact facts and formats, a rubric
        (accuracy, completeness, source quality, efficiency) for qualitative work, and a person for consequential
        results. Start with a small set of realistic tasks; large improvements show up early. Compare the swarm's
        result and cost with what a single agent would have produced.""",
        ["evaluation", "swarm", "quality", "rubric", "success criteria", "cost"], "anthropic_evals"),

    # ----- workspace manager ---------------------------------------------------------------------------
    topic("workspace_manager", "workspace-config", "Workspace configuration", """
        A workspace should run anywhere from its repository plus environment configuration: dependencies declared
        and pinned in a manifest, configuration (URLs, credentials, feature switches) read from environment
        variables and documented in an example file with blank or dummy values, backing services addressed by URL, and
        logs written to stdout. Nothing environment-specific belongs in code. This lets JARV build, test and
        deploy a workspace without hand edits.""",
        ["configuration", "environment", ".env.example", "dependencies", "workspace", "setup"], "twelve_factor"),
    topic("workspace_manager", "workspace-secrets", "Keeping secrets out of workspaces", """
        Real credentials never belong in a repository, a committed .env file, an image layer or a log. Keep them in
        the secret store or an ignored local file, provide an example file with blank values, and scan for secrets
        before every commit. If a secret is committed: revoke it, rotate it, then remove the copies; rewriting git
        history does not undo exposure, and a public repository should be treated as already leaked.""",
        ["secrets", "gitignore", "env", "credentials", "repository", "leak", "workspace"], "owasp_secrets"),

    # ----- business ------------------------------------------------------------------------------------
    topic("business", "pricing-tests", "Testing prices and offers", """
        Test pricing and offers like any experiment: choose the outcome (paid conversion, revenue per visitor,
        retention), fix the sample size or stopping rule in advance, and do not stop as soon as one variant looks
        ahead, which manufactures false winners. Allow for an inconclusive result and a maximum duration. Changes
        to live prices or charges are commitments for Richard.""",
        ["pricing", "experiment", "offer", "a/b test", "conversion", "revenue"], "ab_testing"),
    topic("business", "vat-threshold", "VAT and pricing", """
        A UK business must register for VAT when taxable turnover goes over, or is expected to go over, £90,000,
        and may deregister below £88,000. Taxable turnover is the value of everything sold that is not exempt.
        Registration changes the prices consumers see, which must include VAT, and requires the VAT number on the
        site. Plan the threshold into pricing and forecasts before it is crossed.""",
        ["vat", "tax", "pricing", "threshold", "turnover", "uk"], "uk_vat"),

    # ----- research ------------------------------------------------------------------------------------
    topic("research", "judging-research", "Judging research quality", """
        Judge a research result against explicit criteria: factual accuracy, accurate citations, completeness for
        the question asked, quality and independence of sources, and efficiency. Automated checks catch formats
        and exact facts; a rubric-based review catches the rest; a person should review consequential findings.
        Watch for answers built on search-optimised pages rather than primary or authoritative sources.""",
        ["research", "quality", "citations", "accuracy", "sources", "evaluation"], "anthropic_evals"),
    topic("research", "research-tools", "Using tools efficiently for research", """
        Prefer the most specific tool available (an official API, registry or documentation source) over general
        web search, ask for concise results and narrow queries rather than pulling large pages, and paginate or
        filter big result sets. When a tool errors, read the message and correct the input rather than retrying
        blindly.""",
        ["tools", "search", "research", "api", "efficiency", "queries"], "anthropic_tools"),

    # ----- self-evolution ------------------------------------------------------------------------------
    topic("self_evolution", "safe-rollout", "Rolling out a change to JARV safely", """
        Activate an approved improvement gradually and without disturbing missions already running: new missions
        pick up the new version while running ones finish on the old, progress is checkpointed, and tracing shows
        whether behaviour changed as intended. Keep the previous version ready, and roll back at the first sign
        that success rates, safety checks or costs moved the wrong way.""",
        ["rollout", "self-evolution", "versioning", "rollback", "checkpoint", "monitoring"], "anthropic_multiagent"),
    topic("self_evolution", "delivery-signals", "Measuring whether process changes help", """
        Judge changes to delivery workflows by delivery outcomes: change lead time, deployment frequency, failed
        deployment recovery time, change fail rate and rework rate, tracked per service over time. Improvements
        should move speed and stability together; a change that raises throughput while raising the fail rate is
        not an improvement. Use the metrics to find the next constraint, not as targets to game.""",
        ["metrics", "dora", "process", "improvement", "delivery", "self-evolution"], "dora_metrics"),

    # ----- community ------------------------------------------------------------------------------------
    topic("community", "community-email", "Emailing community members", """
        Community newsletters and announcements sent by email are marketing when they promote products or events,
        so individuals need consent (or the soft opt-in for customers) and every message must identify the sender
        and offer an easy, free unsubscribe. Record when and how each member opted in, and stop immediately when
        they opt out.""",
        ["newsletter", "email", "consent", "community", "unsubscribe", "pecr"], "ico_email"),
    topic("community", "accessible-posts", "Accessible community content", """
        Give images and screenshots text alternatives, keep text contrast high, never rely on colour alone, use
        real headings and descriptive link text, and caption video. Accessible posts reach more members and are
        easier to search.""",
        ["accessibility", "alt text", "posts", "community", "contrast", "captions"], "wcag22"),

    # ----- partnerships ---------------------------------------------------------------------------------
    topic("partnerships", "co-marketing", "Disclosing partner promotions", """
        Co-marketing, affiliate links, referral codes and promotions paid for or rewarded by a partner are
        advertising and must be labelled 'Ad' upfront on every placement. Both partners carry responsibility, so
        partnership agreements should require clear labelling, genuine reviews and evidence for any claims.""",
        ["co-marketing", "affiliate", "disclosure", "partner", "advertising", "referral"], "asa_influencers"),
    topic("partnerships", "partner-economics", "Measuring what a partner brings", """
        Attribute partner-sourced customers and measure them like any cohort: new MRR, retention, churn and ARPU.
        A referral or reseller margin is affordable only within the lifetime value those customers actually show
        (ARPU divided by churn rate), so revisit terms once there is a few months of cohort data.""",
        ["partner", "referral", "revenue share", "mrr", "ltv", "cohort"], "stripe_metrics"),

    # ----- one more for each remaining agent --------------------------------------------------------------
    topic("orchestrator", "tool-choice", "Choosing and exposing tools", """
        Give each agent a small set of distinct, well-described tools that match its workflows; overlapping tools
        confuse agents as much as people. Prefer tools that return meaningful names over opaque ids and support
        concise output, and make errors specific enough to correct the call. When agents repeatedly misuse a tool,
        fix its description or merge it with another before adding instructions elsewhere.""",
        ["tools", "agents", "routing", "descriptions", "errors", "orchestration"], "anthropic_tools"),
    topic("verifier", "grading-outputs", "Grading generated outputs", """
        Grade automatically where possible: exact or normalised matches for categorical answers, code checks for
        formats and invariants, similarity measures for consistency, and a model judge with a detailed rubric and
        constrained output (a number or yes/no) for qualities like tone or completeness, preferably a different
        model from the one being graded. Include edge cases (ambiguous, irrelevant or very long input) and keep a
        person in the loop for consequential outputs.""",
        ["grading", "evaluation", "rubric", "llm judge", "verification", "edge cases"], "anthropic_evals"),
    topic("qa", "testing-ai-features", "Testing AI-powered features", """
        AI features need test sets that mirror real usage plus edge cases (typos, rambling input, irrelevant or
        hostile requests), success criteria with thresholds across several dimensions (accuracy, safety, latency,
        cost), and automated grading run on every change. Many automatically graded cases beat a few hand-graded
        ones; review a sample by hand to keep the graders honest.""",
        ["ai", "llm", "testing", "evaluation", "edge cases", "quality"], "anthropic_evals"),
    topic("monitoring", "backup-monitoring", "Monitoring backups and WAL archiving", """
        A failing WAL archive command lets pg_wal grow until the disk fills and PostgreSQL shuts down, so alert on
        archive failures and on the age of the newest archived segment and base backup. Alert independently when
        fresh backups of any store stop arriving, since silent backup failure is the most common way to discover
        data loss too late.""",
        ["backup", "wal", "postgres", "disk", "alerting", "monitoring"], "pg_pitr"),
    topic("self_healing", "full-disk", "Recovering from a full disk on the database host", """
        When the database volume fills, check whether pg_wal is growing because WAL archiving is failing: fix the
        archive destination or command first, so PostgreSQL can recycle segments; never delete WAL files by hand.
        If the server has stopped, free space elsewhere on the volume, restart, and verify archiving catches up.
        Then add disk and archive-failure alerts.""",
        ["disk full", "postgres", "wal", "archive", "recovery", "self-healing"], "pg_pitr"),
    topic("rollback", "rollback-in-incidents", "Rollback as the first mitigation", """
        During an incident the priority is to stop the bleeding, restore service and preserve evidence. If a recent
        change is the likely cause, rolling it back is usually the fastest safe mitigation; investigate afterwards.
        Record the rollback in the incident document so the planning role can track what must be redone later.""",
        ["rollback", "incident", "mitigation", "release", "restore service"], "sre_incidents"),
    topic("company_operator", "decision-log", "Keeping a decision log", """
        Record each significant company decision in a short record: the decision first, the context and forces,
        alternatives considered, consequences, confidence, what would trigger revisiting it, and a status. Never
        rewrite an accepted decision; supersede it with a new record and link the two, so the history of why the
        company works as it does stays intact.""",
        ["decision", "log", "governance", "record", "strategy", "company"], "fowler_adr"),
    topic("finance", "director-responsibilities", "Directors' financial responsibilities", """
        Directors remain legally responsible for the company's records, accounts and filings even when an
        accountant prepares them, must exercise reasonable care, skill and diligence, and must declare personal
        interests in transactions. If the company becomes insolvent, directors' duties shift to protecting
        creditors. Keep books current so these duties can be met.""",
        ["director", "accounts", "records", "insolvency", "duties", "finance"], "uk_directors"),
    topic("memory", "agent-memory-practice", "Memory for long agent work", """
        A lead agent should save its plan to memory, since context beyond the window is truncated, and workers
        should write large outputs to storage and pass back lightweight references. This keeps context small,
        avoids information loss when results are relayed, and lets a mission resume from stored state after a
        failure.""",
        ["memory", "plan", "storage", "references", "context", "agents"], "anthropic_multiagent"),
    topic("marketing", "landing-tests", "Testing landing pages and campaigns", """
        Test one change at a time against a control with a sample size or stopping rule set in advance; peeking at
        results and stopping early produces false winners. Measure the outcome that matters (sign-ups, paid
        conversions) rather than clicks, and accept 'inconclusive' when the data does not separate the variants.""",
        ["landing page", "experiment", "a/b test", "campaign", "conversion", "marketing"], "ab_testing"),
    topic("growth", "lifecycle-email", "Lifecycle email that lands", """
        Onboarding, activation and win-back emails only work if they reach the inbox: authenticate with SPF and
        DKIM (DMARC at volume), keep spam complaints well under 0.3%, include one-click unsubscribe on promotional
        mail and honour it within two days, and send only to people who agreed to hear from you.""",
        ["email", "lifecycle", "deliverability", "activation", "retention", "unsubscribe"], "gmail_senders"),
    topic("customer_support", "personal-data", "Handling personal data in support", """
        Collect and keep only the personal data needed to resolve a request, delete it when it is no longer needed,
        correct inaccurate data and erase it on valid request, and record opinions as opinions with who wrote them
        and when. Never paste customer personal data into places it does not need to be, and take special care
        with sensitive information.""",
        ["personal data", "privacy", "gdpr", "tickets", "erasure", "support"], "ico_minimisation"),
    topic("sales", "sales-goals", "Sales targets that drive the right work", """
        Set sales objectives with measurable outcome key results (new MRR, deals closed, pipeline value at a stage)
        rather than activity counts, stretch them so 60 to 70% attainment is a good quarter, keep them visible, and
        review mid-period.""",
        ["sales", "targets", "okrs", "pipeline", "quota", "goals"], "okrs"),
    topic("onboarding", "onboarding-email", "Onboarding emails and consent", """
        Service messages needed to use the product (account confirmation, security notices) are not marketing.
        Promotional onboarding emails (tips that sell upgrades, offers) are marketing: they need consent or the
        soft opt-in, must identify the sender and must include an easy, free opt-out.""",
        ["onboarding", "email", "consent", "transactional", "marketing", "pecr"], "ico_email"),
    topic("content", "release-notes", "Writing release notes", """
        Release notes are written for users: newest version first, dated YYYY-MM-DD, grouped under Added, Changed,
        Deprecated, Removed, Fixed and Security, summarising what matters to readers rather than listing commits,
        and always calling out deprecations and breaking changes with what users should do.""",
        ["release notes", "changelog", "product updates", "content", "versioning"], "keep_changelog"),
    topic("creation", "ai-generated-assets", "Labelling AI-generated images", """
        When an image is generated by AI, record that in its metadata; shopping platforms require AI-generated
        product images to carry IPTC DigitalSourceType set to TrainedAlgorithmicMedia, and AI-written product
        titles and descriptions to be labelled. Review generated visuals for accuracy before publishing, as with
        any AI output.""",
        ["ai images", "metadata", "iptc", "generated", "assets", "labelling"], "google_ai_content"),
    topic("analytics", "delivery-analytics", "Analysing software delivery", """
        Report delivery per service: change lead time, deployment frequency, failed deployment recovery time,
        change fail rate and deployment rework rate. Present trends rather than cross-team rankings, show speed and
        stability together, and highlight the biggest constraint rather than a league table.""",
        ["dora", "delivery", "deployments", "lead time", "metrics", "reporting"], "dora_metrics"),
]
