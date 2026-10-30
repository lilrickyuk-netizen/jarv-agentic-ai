"""Field knowledge for the operations agents: devops, infrastructure, monitoring, self-healing, rollback."""
from __future__ import annotations

from app.core.knowledge.library._base import topic

ENTRIES = [
    # ----- devops ----------------------------------------------------------------------------------
    topic("devops", "image-builds", "Building container images", """
        Use multi-stage builds so the final image holds only what the app needs at run time; share common steps
        in a base stage. Start from trusted, minimal official images, pin their versions, and rebuild regularly
        (with --pull) so patched bases and dependencies are picked up. Order instructions so rarely changing
        layers (system packages, dependency manifests and installs) come before frequently changing source code,
        to keep the build cache effective. Exclude everything irrelevant with .dockerignore, install no
        unnecessary packages, keep one concern per container, and design containers to be ephemeral: stoppable,
        replaceable and configured from the environment. Run as a non-root user, use exec-form ENTRYPOINT/CMD so
        signals reach the process, and never put secrets in ENV, ARG or image layers.""",
        ["docker", "dockerfile", "image", "build", "multi-stage", "cache", "container"], "docker_build"),
    topic("devops", "ci-security", "Hardening CI workflows", """
        Keep credentials in the CI secret store, one secret per value (redaction matches exact strings), and
        register derived values such as encoded tokens as secrets too; still review logs, since tools can print
        secrets. Default the workflow token to read-only and grant extra permissions per job. Treat event data
        (pull request titles and bodies, branch names, commit emails) as untrusted: pass it through an
        environment variable and quote it rather than interpolating it into a shell script. Pin third-party
        actions to a full commit SHA from the original repository and keep them updated. Prefer OIDC to obtain
        short-lived cloud credentials over long-lived keys. Do not run untrusted pull requests on persistent
        self-hosted runners, and require code-owner review for workflow changes.""",
        ["ci", "github actions", "workflow", "secrets", "pipeline", "supply chain", "token"], "gha_hardening"),
    topic("devops", "delivery-metrics", "Measuring delivery performance", """
        Track throughput and stability together per service: change lead time (commit to running in production),
        deployment frequency, failed deployment recovery time, change fail rate (deployments needing an
        immediate rollback or hotfix) and deployment rework rate (unplanned deployments caused by incidents).
        Use them to improve a team's own trend, not to compare teams or as mandated targets, which invites
        gaming. Speed and stability are not a trade-off for most teams: the strongest lever for both is smaller
        batches, so ship small changes frequently. Improve in cycles: baseline, find the biggest constraint, fix
        it, measure again.""",
        ["dora", "metrics", "lead time", "deployment frequency", "change fail rate", "delivery"], "dora_metrics"),
    topic("devops", "release-flow", "Build, release, run", """
        Keep build, release and run as separate stages: a build turns a commit into an artifact once; a release
        combines that artifact with an environment's configuration and gets an immutable identifier; the run
        stage starts processes from a release. Never patch code in a running environment. Configuration comes
        from the environment, so the same artifact is promoted from staging to production. Run migrations and
        other admin tasks as one-off processes from the same release. Keep staging close to production (same
        backing services and versions) so a staging pass means something.""",
        ["release", "deploy", "staging", "production", "configuration", "artifact", "migrations"], "twelve_factor"),
    topic("devops", "safe-migrations", "Deploying breaking changes safely", """
        Ship a breaking interface or schema change in three releasable phases: expand (add the new column, field
        or endpoint alongside the old, with code that handles both), migrate (move readers and writers over
        incrementally, backfilling data), and contract (remove the old path once nothing uses it). Each phase can
        be deployed and rolled back on its own, so the database never forces a rollback to also undo the schema.
        Do not skip the contract phase, and mark the old path as deprecated so people know which to use.""",
        ["migration", "schema", "database", "breaking change", "expand contract", "deploy", "rollback"],
        "parallel_change"),

    # ----- infrastructure ----------------------------------------------------------------------------
    topic("infrastructure", "ssh-hardening", "Securing SSH access to servers", """
        Allow key-based login only: set PasswordAuthentication no and make sure PAM or keyboard-interactive
        cannot fall back to passwords; require AuthenticationMethods publickey (add a second factor through PAM
        where humans log in). Disable root login and have administrators escalate with sudo for an audit trail.
        Prefer Ed25519 host and user keys, modern ciphers (ChaCha20-Poly1305, AES-GCM), curve25519 key exchange
        and encrypt-then-MAC algorithms, and remove Diffie-Hellman moduli under 3072 bits. Set LogLevel VERBOSE
        so key fingerprints are logged. Do not forward SSH agents to servers; use ProxyJump through a bastion.
        Pin host keys (known_hosts) for automation such as deployment keys.""",
        ["ssh", "server", "vps", "hardening", "keys", "sshd", "access"], "openssh_mozilla"),
    topic("infrastructure", "postgres-backups", "PostgreSQL backup and point-in-time recovery", """
        Logical dumps (pg_dump) capture a consistent snapshot and are portable, but restore only to the moment
        they were taken. For point-in-time recovery, archive WAL continuously and take periodic base backups
        (pg_basebackup): any moment after a base backup can then be restored by replaying WAL to a
        recovery_target_time. The archive command must return success only when the file is safely stored and
        must never overwrite an existing file; monitor archiving, since a failing archive lets pg_wal grow until
        the disk fills and the server stops. Keep several backup sets and all WAL since the oldest one, store
        copies off the host, and rehearse restores on a separate machine: a backup is only proven by a restore.""",
        ["postgres", "backup", "restore", "pitr", "wal", "pg_dump", "database"], "pg_pitr"),
    topic("infrastructure", "redis-persistence", "Redis durability and backups", """
        RDB snapshots are compact and restart fast but can lose minutes of writes; the append-only file (AOF)
        with appendfsync everysec loses at most about a second, with always being safest and slowest. For data you
        cannot recreate, enable both: AOF for durability and periodic RDB snapshots for backups. Copying an RDB
        file while Redis runs is safe because snapshots are written to a temporary file and renamed atomically;
        do not copy AOF files during a rewrite. Keep hourly and daily snapshots off the machine, verify each
        transfer (size and checksum), and alert if fresh backups stop arriving. A pure cache may run without
        persistence.""",
        ["redis", "persistence", "aof", "rdb", "backup", "durability", "cache"], "redis_persistence"),
    topic("infrastructure", "capacity", "Finding resource bottlenecks", """
        For every resource, check utilisation, saturation and errors. Resources include CPUs, memory capacity,
        network interfaces, storage I/O and capacity, and software resources such as thread pools, connection
        pools, locks and file descriptors (and container or cgroup limits on a VPS). Sustained utilisation above
        roughly 70% can already hurt latency because averages hide bursts at 100%; any saturation (queued work,
        swapping, run-queue length) signals a constraint; any errors deserve investigation. A resource with low
        utilisation, no saturation and no errors can be ruled out, which narrows the search quickly.""",
        ["capacity", "cpu", "memory", "disk", "saturation", "utilization", "bottleneck", "scaling"], "use_method"),
    topic("infrastructure", "restart-policies", "Keeping containers running", """
        Use Docker restart policies rather than process managers inside containers. 'unless-stopped' restarts a
        container after crashes and daemon restarts but respects a deliberate stop; 'always' restarts even after
        a manual stop once the daemon restarts; 'on-failure[:N]' restarts only on non-zero exits, up to N times,
        and not on daemon restart. A policy only takes effect after the container has run for 10 seconds, so a
        container that fails at startup is not looped. Pair restart policies with health checks so crashed or
        hung services are visible, and investigate repeated restarts rather than relying on them.""",
        ["docker", "restart", "container", "uptime", "health check", "compose"], "docker_restart"),

    # ----- monitoring -----------------------------------------------------------------------------------
    topic("monitoring", "golden-signals", "The four golden signals", """
        For every user-facing service measure latency (separately for successful and failed requests, since slow
        errors are worse), traffic (requests per second or sessions), errors (explicit failures, wrong content
        behind a success code, and responses that break a latency commitment) and saturation (how full the most
        constrained resource is, watched before it reaches 100%). Use latency histograms and percentiles, not
        averages, so the slow tail is visible. Combine black-box probes, which show what users experience and are
        best for paging, with white-box metrics and logs for debugging. Keep monitoring simple and delete signals
        no alert or dashboard uses.""",
        ["latency", "traffic", "errors", "saturation", "golden signals", "percentiles", "monitoring"],
        "sre_monitoring"),
    topic("monitoring", "paging", "When to page a human", """
        Page only for conditions that are urgent, actionable, user-visible now or imminently, and that need human
        judgement; anything with a rote response should be automated instead. Alert on symptoms as high in the
        stack as possible (user-facing latency and error rate) rather than on every cause, and page on latency at
        one point only. For batch jobs, alert when the job has not succeeded for more than two run cycles. Allow
        slack so brief blips do not page, deduplicate related alerts, send sub-critical issues to dashboards
        rather than email, link each alert to the console that shows the cause, and monitor the monitoring with
        an end-to-end check of the alert path.""",
        ["alerting", "paging", "alerts", "on-call", "symptoms", "prometheus", "batch jobs"], "prometheus_alerting"),
    topic("monitoring", "slos", "Service level objectives", """
        Define a few SLIs per service from what users care about: availability, latency and throughput for
        request serving; latency, availability and durability for storage; throughput and end-to-end latency for
        pipelines; correctness everywhere. State each precisely (window, which requests count, where measured)
        and use percentiles. Set SLO targets from what users need, not from current performance, start loose and
        tighten, avoid 100%, and keep an internal target stricter than anything promised externally. The gap
        between the SLO and perfection is the error budget: while it lasts, ship changes; when it is spent,
        prioritise reliability work.""",
        ["slo", "sli", "error budget", "availability", "latency", "reliability", "targets"], "sre_slos"),
    topic("monitoring", "resource-checks", "Checking host and container resources", """
        Run a quick utilisation, saturation and errors pass over each resource: CPU (utilisation per core, run
        queue), memory (used versus limit, swapping, OOM kills), disk (space, I/O wait, queue length), network
        (throughput, drops, errors) and software resources (connection pools, worker pools, file descriptors).
        Report each as a measured value against its limit. High sustained utilisation, any saturation or any
        error count is a finding; a clean resource is evidence that the problem is elsewhere.""",
        ["cpu", "memory", "disk", "network", "container", "resources", "utilization"], "use_method"),

    # ----- self-healing ---------------------------------------------------------------------------------
    topic("self_healing", "incident-command", "Running an incident", """
        Declare an incident early: when another team is needed, customers can see the outage, or an hour of
        focused work has not solved it. Separate roles: an incident commander holds the overall picture and
        assigns work; only the operations role changes the system; a communications role sends regular
        updates; a planning role files follow-ups and tracks every temporary change so it can be reverted. Keep a
        live incident document with the current state at the top. Priorities are to stop the bleeding, restore
        service, and preserve evidence for root-cause analysis, in that order. Hand over command explicitly.""",
        ["incident", "outage", "commander", "mitigation", "communication", "response"], "sre_incidents"),
    topic("self_healing", "overload", "Recovering from overload and cascading failure", """
        Overload spreads: slow requests pile up, exhaust CPU, memory, threads or file descriptors, fail health
        checks, and push load onto the survivors. To recover, reduce load first (shed low-priority work, pause
        batch jobs, block abusive traffic, drop to a small share of traffic and ramp back slowly), stop health
        checks from killing busy-but-alive processes, and add capacity only if it is idle and will help. Restart
        servers only once the cause is known, gradually, with cold caches in mind. Prevent recurrence with
        deadlines on every call, retries with exponential backoff, jitter and a retry budget, bounded queues, and
        graceful degradation that is tested regularly.""",
        ["overload", "cascading failure", "load shedding", "retries", "timeouts", "backoff", "health checks"],
        "sre_cascading"),
    topic("self_healing", "safe-restarts", "Restarting services safely", """
        A restart is a mitigation, not a fix. Before restarting, capture evidence (logs, container state, resource
        readings) so the cause can still be found. Restart only stateless application services; databases,
        queues and caches need diagnosis first, because restarting them can lose in-flight data or deepen an
        overload. Rely on restart policies for crash recovery, and treat a container restarting repeatedly as a
        defect to investigate. After any restart, verify health end to end and record what was done.""",
        ["restart", "service", "container", "mitigation", "evidence", "verify"], "docker_restart"),
    topic("self_healing", "triage", "Triage by resource", """
        When a service degrades, start with a utilisation, saturation and errors pass over its resources: CPU,
        memory (including OOM kills), disk space and I/O, network, and software resources such as database
        connection pools, worker concurrency and file descriptors. Saturation or errors on one resource usually
        explains the symptom; fix that constraint (free disk, reduce concurrency, raise a pool limit within
        budget) and verify the symptom clears. If every resource is clean, look at dependencies and recent
        changes instead.""",
        ["triage", "diagnosis", "cpu", "memory", "disk", "saturation", "self-healing"], "use_method"),

    # ----- rollback --------------------------------------------------------------------------------------
    topic("rollback", "expand-contract", "Designing changes that can be rolled back", """
        A release can be rolled back cleanly only if the previous version still works with the current data.
        Split breaking schema or interface changes into expand, migrate and contract phases: add the new
        structure alongside the old, move code and data over, and only then remove the old structure. During the
        migrate phase both versions coexist, so rolling the application back does not require undoing the
        schema. Never couple a destructive migration to the release that first uses it.""",
        ["rollback", "schema", "migration", "expand contract", "compatibility", "release"], "parallel_change"),
    topic("rollback", "data-restore", "Restoring data versus rolling back a release", """
        Rolling back application code is fast and routine; restoring data is slower, destructive to anything
        written since, and needs approval. PostgreSQL can restore a logical dump to the moment it was taken, or,
        with continuous WAL archiving and a base backup, replay to any point in time after that backup. Restore
        into a new database or instance first, inspect it, and only then switch over; keep the damaged copy for
        investigation. Every recovery creates a new timeline, so later recoveries can still choose between
        histories.""",
        ["restore", "backup", "database", "pitr", "data loss", "recovery"], "pg_pitr"),
    topic("rollback", "rollback-metrics", "Rollbacks as a delivery signal", """
        Every rollback or hotfix counts towards the change fail rate, and the time to recover from a failed
        deployment is a core delivery metric. Track both per service. A rising change fail rate points to
        batches that are too large or checks that are too weak before production; slow recovery points to
        rollback that is hard to perform. Smaller, more frequent releases lower both.""",
        ["rollback", "change fail rate", "recovery time", "dora", "deployment", "metrics"], "dora_metrics"),
    topic("rollback", "cache-recovery", "Rolling back Redis-backed state", """
        Queue and cache state in Redis is restored from its RDB snapshots or AOF. Snapshots can be copied safely
        while Redis runs, so keep dated copies off the host; restoring a snapshot loses writes since it was taken,
        so prefer the AOF when it is intact. For caches, it is usually safer to flush and let them refill than
        to restore stale data, but expect higher load on the database while caches warm.""",
        ["redis", "rollback", "restore", "cache", "queue", "snapshot"], "redis_persistence"),
]
