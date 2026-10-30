"""Field knowledge for the engineering agents: coding, debugging, verifier, QA, security, documentation."""
from __future__ import annotations

from app.core.knowledge.library._base import topic

ENTRIES = [
    # ----- coding agent --------------------------------------------------------------------------
    topic("coding_agent", "review-standard", "Reviewing and preparing a change", """
        Judge a change on design (does it belong here and fit the system), functionality (does it do what the
        author intended, and is that good for users, including edge cases and concurrency), complexity (could a
        reader understand and safely change it; avoid speculative generality), tests (correct, meaningful,
        failing when the code breaks), naming, comments that explain why rather than what, consistency with the
        style guide, and updated documentation. Keep changes small and single-purpose so they can be reviewed
        quickly and reverted cleanly. Review every line you are asked to review, look at the change in the
        context of the whole file, and prefer approving a change that clearly improves the code base over
        demanding perfection.""",
        ["code review", "design", "complexity", "tests", "naming", "small change"], "google_code_review"),
    topic("coding_agent", "twelve-factor", "Building services that deploy cleanly", """
        Keep one codebase per app with many deploys. Declare every dependency explicitly and pin it; never rely
        on system packages being present. Read configuration (URLs, credentials, feature switches) from the
        environment, never from code, so the same build runs in every environment. Treat databases, queues and
        caches as attached resources addressed by configuration. Keep build, release and run separate: a release
        is a build plus config and is immutable. Run as stateless processes that keep shared state in backing
        services, bind their own port, scale by adding processes, start fast and shut down gracefully on SIGTERM.
        Keep development and production as similar as possible, write logs to stdout as an event stream, and run
        admin tasks (migrations, one-off scripts) as one-off processes against the same release.""",
        ["configuration", "environment", "stateless", "dependencies", "deploy", "logs"], "twelve_factor"),
    topic("coding_agent", "react-effects", "React state and effects done right", """
        Effects synchronise a component with something outside React; if no external system is involved, an
        effect is usually wrong. Compute derived values during render instead of copying them into state, and
        cache expensive pure calculations with useMemo. Reset a subtree's state by giving it a different key.
        Put logic caused by a user action in the event handler, not in an effect watching state. Avoid chains of
        effects that set state to trigger other effects; compute the next state in one handler. Call a parent's
        callback in the same event that changes local state, or lift the state up. Subscribe to external stores
        with useSyncExternalStore. When fetching in an effect, guard against out-of-order responses with a
        cleanup flag, and prefer the framework's data-fetching mechanism or a dedicated hook.""",
        ["react", "useeffect", "state", "frontend", "nextjs", "hooks", "rendering"], "react_effects"),
    topic("coding_agent", "async-sqlalchemy", "Async SQLAlchemy without surprises", """
        An AsyncSession represents one transaction for one task; never share it across concurrently running
        coroutines (for example inside asyncio.gather); give each its own session. Configure sessions with
        expire_on_commit=False so attributes stay readable after commit. Lazy loading performs implicit IO,
        which fails under asyncio: eager-load relationships in the query (selectinload), use awaitable_attrs, or
        declare lazy='raise' so accidental lazy loads fail loudly. Initialise collections on new objects before
        reading them, use session.refresh(obj, [names]) to load attributes explicitly, and list cascades instead
        of using 'all'. Stream large result sets with conn.stream(). Dispose engines before the event loop ends,
        and do not reuse a pooled engine on a different event loop (use NullPool or dispose first).""",
        ["sqlalchemy", "async", "asyncio", "database", "orm", "session", "lazy loading"], "sqlalchemy_asyncio"),
    topic("coding_agent", "logging-in-code", "Logging that helps the next person", """
        Use a module-level logger (logging.getLogger(__name__)) so events carry their origin. Choose the level by
        meaning: DEBUG for diagnostic detail, INFO for confirmation that things work, WARNING for something
        unexpected the program survives, ERROR when a function could not be performed, CRITICAL when the program
        may not continue. Raise exceptions to report errors to callers; log and continue only where the error is
        handled (for example in a long-running worker), and then use logger.exception inside the except block so
        the traceback is kept. Pass values as arguments (logger.info('loaded %s rows', n)) so formatting is lazy.
        Libraries never configure handlers; applications configure logging once at their entry point. Never log
        secrets, tokens or personal data.""",
        ["logging", "exceptions", "errors", "levels", "python", "observability"], "python_logging"),

    # ----- debugging agent ------------------------------------------------------------------------
    topic("debugging_agent", "log-evidence", "Reading and adding log evidence", """
        Logs are only evidence if their level and origin are trustworthy: module-level loggers name the component
        that emitted an event, and logger.exception records the traceback at the point the error was handled.
        When a failure leaves no trace, add targeted DEBUG or INFO statements with the identifiers needed to
        follow one request or task (ids, sizes, branch taken), reproduce, then remove or demote the noise.
        Distinguish errors that were raised to a caller from errors that were logged and swallowed; the second
        kind often hides the real fault. Check that logging is configured once in the application entry point,
        since a library that configures handlers, or disable_existing_loggers in dictConfig, can silence the
        loggers you are relying on.""",
        ["logs", "traceback", "exception", "logging", "evidence", "reproduce"], "python_logging"),
    topic("debugging_agent", "postmortem", "Writing up an incident without blame", """
        Write a postmortem when users saw downtime or degradation beyond the agreed threshold, data was lost,
        someone had to intervene (rollback, rerouting), resolution took too long, or monitoring failed to
        detect the problem. Record the impact, the timeline, what was done to mitigate and resolve it, the root
        causes understood in depth, and follow-up actions that are tracked to completion. Keep it blameless:
        assume everyone acted reasonably on the information they had, describe the gap in tooling or process
        rather than the person, and never include end-user identifying information. Have the draft reviewed for
        depth of root cause and fit of the action plan, then share it widely; an unreviewed postmortem has little
        value.""",
        ["postmortem", "incident", "root cause", "blameless", "action items", "timeline"], "sre_postmortems"),
    topic("debugging_agent", "async-db-faults", "Typical async database faults", """
        In async Python services a family of bugs comes from session misuse: 'greenlet_spawn has not been called'
        or MissingGreenlet means a lazy load or expired attribute triggered implicit IO; fix it with eager
        loading, explicit refresh, or expire_on_commit=False, not by sprinkling run_sync. Interleaved or
        'concurrent operations are not permitted' errors mean one AsyncSession was shared between concurrent
        tasks. 'Event loop is closed' at shutdown means an engine was not disposed, or a pooled engine was reused
        on another loop (common in tests and Celery tasks that call asyncio.run per job). Objects reading stale
        values after commit point to expiry settings or a second session holding an older snapshot.""",
        ["sqlalchemy", "async", "greenlet", "event loop", "session", "database error"], "sqlalchemy_asyncio"),
    topic("debugging_agent", "frontend-effects", "Diagnosing React rendering bugs", """
        Flicker, double requests, stale data and infinite render loops in React usually come from effects used
        where they are not needed. Look for state that is copied from props or other state (derive it during
        render instead), effects that set state which triggers another effect (compute in one event handler),
        parent callbacks fired from an effect (call them in the event), and data fetches without a cleanup guard,
        which let a slow earlier response overwrite a newer one. In development, effects run twice on mount to
        surface missing cleanup; a bug that appears only then is a missing cleanup, not a React fault.""",
        ["react", "frontend", "render loop", "effect", "stale data", "race condition"], "react_effects"),
    topic("debugging_agent", "regression-test", "Proving a fix", """
        A bug is fixed when a test that failed before the change passes after it. Write the failing test at the
        lowest level that reproduces the fault: a unit test for logic, an integration test for one boundary such
        as the database or an HTTP client. If only an end-to-end test catches it, add the lower-level test as
        well so the cause is pinned precisely. Assert observable behaviour rather than internal calls, so later
        refactoring does not break the test. Keep the test deterministic: no reliance on wall-clock time,
        ordering or shared state between tests.""",
        ["regression", "test", "fix", "unit test", "integration test", "verification"], "test_pyramid"),

    # ----- verifier ---------------------------------------------------------------------------------
    topic("verifier", "test-portfolio", "Judging whether the tests prove anything", """
        A healthy suite has many fast unit tests, fewer integration tests that each exercise one external
        boundary (database, filesystem, HTTP, queue), and very few end-to-end journeys. Check that unit tests
        cover the public interface and the non-trivial paths, including edge cases, and assert outcomes rather
        than implementation details. Integration tests must run against real or locally-run dependencies, never
        production. A higher-level test failing without a lower-level test failing means coverage is missing at
        the lower level. Treat test code with the same care as production code: one behaviour per test, readable
        over clever.""",
        ["test", "coverage", "unit", "integration", "end-to-end", "pyramid", "verification"], "test_pyramid"),
    topic("verifier", "review-criteria", "Verification criteria for a change", """
        Before accepting work, verify: the change does what was asked and nothing unasked; behaviour for users,
        including error cases and concurrency, is correct; the design fits the system and is no more complex than
        needed; tests exist, fail without the change and pass with it; names and comments are clear; style
        matches the project; documentation and changelog are updated. Prefer evidence over assertions: run the
        build and tests, read the diff in full, and check the claimed files actually changed. A change that
        improves the code base can be accepted with follow-ups; a change that breaks behaviour or hides failures
        cannot.""",
        ["verify", "acceptance", "review", "evidence", "criteria", "change"], "google_code_review"),
    topic("verifier", "accessibility-checks", "Accessibility checks for user interfaces", """
        Verify against WCAG 2.2 level AA: every non-text element has a text alternative; text contrast is at
        least 4.5:1 (3:1 for large text) and UI component boundaries and states at least 3:1; colour is never the
        only signal; text resizes to 200% and content reflows at 320 CSS pixels wide without horizontal
        scrolling; everything works by keyboard with a visible focus indicator that is not hidden behind sticky
        content; pointer targets are at least 24 by 24 CSS pixels or adequately spaced; form fields have labels
        and errors are identified in text; components expose name, role and value; status messages are announced
        without moving focus; and sign-in does not depend on a memory or puzzle test without an alternative.""",
        ["accessibility", "wcag", "contrast", "keyboard", "focus", "aria", "ui"], "wcag22"),
    topic("verifier", "security-weaknesses", "Weaknesses to check every time", """
        The 2025 CWE Top 25 is led by cross-site scripting, SQL injection, CSRF and missing authorization, with
        path traversal, OS command and code injection, unrestricted file upload, unsafe deserialization,
        incorrect authorization, information exposure, missing authentication for critical functions, SSRF,
        authorization bypass through user-controlled keys, and unbounded resource use also high. For web
        services verify specifically: output encoding, parameterised queries, CSRF protection on cookie-based
        sessions, an authorization check on every object access, path normalisation within an allowed root, no
        shell string building, file type and size checks on uploads, and limits on request size and rate.""",
        ["security", "cwe", "xss", "sql injection", "authorization", "path traversal", "csrf"], "cwe_top25"),

    # ----- QA -----------------------------------------------------------------------------------------
    topic("qa", "browser-tests", "Reliable browser tests", """
        Test what users see and do, not implementation details. Keep each test isolated with its own storage,
        cookies and data; share sign-in through a setup step rather than test order. Locate elements the way a
        user or assistive technology would (getByRole, getByLabel, getByText) instead of CSS or XPath tied to
        markup. Use web-first assertions that wait and retry (toBeVisible, toHaveText) and never fixed sleeps;
        always await them. Mock third-party services you do not control. On CI, keep traces for failures and
        retries, run in parallel and shard large suites, and run tests on every change. Lint for floating
        promises so a missing await cannot silently pass a test.""",
        ["playwright", "browser", "e2e", "locators", "flaky", "ui test", "assertions"], "playwright_practices"),
    topic("qa", "test-strategy", "Planning a test strategy", """
        Push each check as low in the pyramid as it can go: logic in unit tests, each external boundary
        (database, HTTP client, queue, filesystem) in its own integration test, and only a handful of high-value
        user journeys end to end. Use test doubles for slow or side-effecting collaborators but keep some tests
        against real dependencies run locally or in a dedicated test instance, never production. For services
        consumed by other teams, use consumer-driven contract tests. Order the pipeline from fastest to slowest
        so feedback arrives early. Follow exploratory testing with automated tests for whatever it finds.""",
        ["test strategy", "pyramid", "contract test", "test doubles", "pipeline", "integration"], "test_pyramid"),
    topic("qa", "accessibility-testing", "Testing accessibility", """
        Include accessibility in functional testing: navigate each journey by keyboard only, checking order and a
        visible, unobscured focus indicator; zoom to 200% and narrow to 320 CSS pixels to check reflow; check text
        and component contrast (4.5:1 text, 3:1 large text and UI parts); confirm images and icons have text
        alternatives, inputs have labels, and errors are described in text next to the field; confirm status
        updates are announced; and check pointer targets are at least 24 by 24 CSS pixels. Role-based locators in
        automated tests double as a check that controls expose correct roles and names.""",
        ["accessibility", "wcag", "keyboard", "contrast", "testing", "screen reader"], "wcag22"),
    topic("qa", "bug-reports", "Bug reports that get fixed", """
        A good report states the expected and observed behaviour, exact steps to reproduce from a clean state,
        the environment and version, frequency, and evidence (logs, trace, screenshot) with secrets removed. For
        serious incidents follow up with a blameless write-up: impact, timeline, root cause, mitigation and
        tracked action items. Rate severity by user impact, not by how interesting the bug is. Each fixed bug
        should leave a regression test at the lowest level that reproduces it.""",
        ["bug report", "reproduce", "severity", "evidence", "regression", "incident"], "sre_postmortems"),

    # ----- security -----------------------------------------------------------------------------------
    topic("security", "secrets-management", "Handling secrets", """
        Keep secrets in one managed store with per-secret, least-privilege access and an audit trail of who read
        or changed each one. Never hardcode secrets in source, commit them to git, bake them into container
        images (Docker ENV or ARG), or print them in logs or CI output; prefer injection at runtime as mounted
        files or from the secret store, since environment variables can leak through dumps and child processes.
        Prefer short-lived credentials; rotate static ones on a schedule and immediately on suspected exposure.
        Scan for secrets before commit and in CI. When a secret leaks: revoke it first, rotate, remove the copies
        from code and logs, and review where it was used. Encrypt with authenticated encryption and keep keys
        apart from the data they protect.""",
        ["secrets", "credentials", "api key", "rotation", "leak", "vault", "env"], "owasp_secrets"),
    topic("security", "cwe-top25", "The weaknesses attackers use most", """
        The 2025 CWE Top 25 ranks cross-site scripting first, then SQL injection, cross-site request forgery and
        missing authorization (which rose sharply, alongside incorrect authorization and authorization bypass
        through user-controlled keys). Memory-safety weaknesses dominate native code; for web services the
        priorities are output encoding, parameterised queries, CSRF tokens or SameSite cookies, an
        authorization check on every object, path traversal defences, avoiding shell and code injection,
        restricting uploaded file types and sizes, never deserialising untrusted data with unsafe loaders,
        authenticating every critical function, preventing SSRF, and limiting resource use per request and per
        client. OS command injection has the most known-exploited vulnerabilities.""",
        ["cwe", "top 25", "xss", "sql injection", "csrf", "authorization", "ssrf", "upload"], "cwe_top25"),
    topic("security", "ci-hardening", "Securing CI/CD", """
        Treat CI/CD as production: patch and monitor it, give people only the pipeline rights they need, manage
        pipeline configuration as code, block shell access to runners, keep powerful secrets out of jobs that
        build untrusted code (forks must not inherit them), fetch secrets at run time with short-lived job-scoped
        credentials, keep pipeline logs free of secrets, and keep caller attribution so every deployment traces
        to a person or service. Keep CI logs queryable long enough to investigate (at least 90 days).""",
        ["ci", "cd", "pipeline", "github actions", "supply chain", "runners", "secrets"], "owasp_secrets"),
    topic("security", "security-review", "Running a security review", """
        Review authentication and authorization first: every endpoint that acts on an object must check the
        caller owns or may act on that object, and critical functions must require authentication. Then input
        handling (parameterised queries, output encoding, path normalisation, no shell string building), file
        uploads, outbound requests (SSRF), deserialisation, secrets handling, dependency vulnerabilities, and
        resource limits. Report each finding with severity, location, evidence, impact and a concrete fix; never
        include a secret's value. Prefer fixing classes of bugs (a shared authorization helper, a safe query
        layer) over patching single instances.""",
        ["security review", "authorization", "authentication", "findings", "severity", "fix"], "cwe_top25"),
    topic("security", "accessible-auth", "Authentication that is secure and usable", """
        WCAG 2.2 adds accessible authentication: signing in must not depend on a cognitive function test such
        as remembering a password, transcribing a code or solving a puzzle unless there is an alternative or
        assistance, for example allowing password managers and paste, supporting passkeys or email links, and
        letting users copy one-time codes. Blocking paste into password fields therefore harms both security and
        accessibility. Pair this with strong server-side controls: rate limiting, credential-stuffing defences,
        and multi-factor options.""",
        ["authentication", "login", "password manager", "passkeys", "mfa", "accessibility"], "wcag22"),

    # ----- documentation ------------------------------------------------------------------------------
    topic("documentation", "style", "Developer documentation style", """
        Write in a conversational, friendly but not frivolous tone. Address the reader as 'you', use active voice
        and present tense, and put conditions before instructions ('To deploy, run ...', 'If the build fails,
        ...'). Use sentence case for titles and headings, numbered lists for sequential steps and bulleted lists
        otherwise, code font for code, commands, file names and values, and descriptive link text rather than
        'click here'. Write for a global audience: short sentences, one idea each, defined terms, no idioms.
        Make content accessible: alt text for images, real headings, tables only for tabular data.""",
        ["documentation", "style", "voice", "headings", "procedures", "readme", "writing"], "google_style"),
    topic("documentation", "changelog", "Keeping a changelog", """
        A changelog is for people. Keep an Unreleased section at the top and a section per released version,
        newest first, each with its date in ISO 8601 (YYYY-MM-DD) and linkable. Group entries under Added,
        Changed, Deprecated, Removed, Fixed and Security. Summarise notable changes for users rather than dumping
        commit messages, and always record deprecations, removals and breaking changes so users can upgrade
        safely. State whether the project follows Semantic Versioning.""",
        ["changelog", "release notes", "versioning", "semver", "deprecated", "unreleased"], "keep_changelog"),
    topic("documentation", "decision-records", "Recording architecture decisions", """
        Capture each significant decision in a short Architecture Decision Record, one or two pages: the decision
        first, then the context and forces, the alternatives seriously considered with their trade-offs, the
        consequences, the confidence level and what would trigger revisiting it, and a status (proposed,
        accepted, superseded). Never rewrite an accepted record; write a new one that supersedes it and link
        both. Store records as numbered Markdown files in the repository (for example docs/adr/0007-use-postgres.
        md) so they are reviewed and versioned with the code.""",
        ["adr", "architecture", "decision", "design doc", "trade-offs", "documentation"], "fowler_adr"),
    topic("documentation", "operational-docs", "Documenting how to run a service", """
        A service is documented when someone new can configure, build, deploy and operate it from the docs
        alone. List every configuration variable with its meaning and whether it is required, since configuration
        lives in the environment and must not be hardcoded; document backing services and how to point the app
        at them; give the exact build, release and run commands; explain how logs are emitted and where to read
        them; and document one-off admin tasks such as migrations and how to run them safely. Keep an example
        environment file with blank or dummy values, never real ones.""",
        ["runbook", "configuration", "deployment", "operations", "environment variables", "readme"], "twelve_factor"),
    topic("documentation", "incident-docs", "Postmortems and incident records", """
        Incident documentation should let a reader learn without being in the room: impact in user terms, a
        timestamped timeline, how the problem was detected, mitigation and resolution steps, root causes in
        depth, and action items with owners that are tracked to completion. Write it blamelessly, describing
        gaps in systems and information rather than people, and leave out anything that identifies end users.
        Get it reviewed, then publish it where future responders will look.""",
        ["postmortem", "incident", "timeline", "root cause", "documentation", "blameless"], "sre_postmortems"),
]
