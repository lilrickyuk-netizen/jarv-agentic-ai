"""Field knowledge for orchestration, swarm, workspace, memory, self-evolution and research agents."""
from __future__ import annotations

from app.core.knowledge.library._base import topic

ENTRIES = [
    # ----- orchestrator ----------------------------------------------------------------------------
    topic("orchestrator", "delegation", "Delegating to specialists", """
        Give every delegated task four things: a clear objective, the expected output format, guidance on which
        tools and sources to use, and explicit boundaries so two workers do not duplicate or leave gaps. Scale
        effort to the request: a simple fact needs one agent and a few tool calls, a comparison two to four
        workers, broad research more workers with divided responsibilities. Do not spawn workers for simple
        tasks; multi-agent runs cost many times the tokens of a single agent and only pay off for valuable,
        parallelisable work. Workers return condensed findings (or write full results to storage and return a
        reference); the orchestrator decides whether more work is needed and synthesises the answer.""",
        ["delegation", "orchestration", "subagents", "planning", "effort", "routing", "task"],
        "anthropic_multiagent"),
    topic("orchestrator", "context-budget", "Managing context for long missions", """
        Context is finite and quality drops as it fills, so give each step the smallest set of high-signal
        information. Keep instructions at the right altitude: clear principles and sections, not brittle
        if-else rules or vague exhortations. Load data just in time through tools using lightweight references
        (paths, ids, links) rather than pasting everything up front. For long missions, write the plan and
        progress to persistent notes and reload them, compact or summarise old history when near the limit, and
        hand focused sub-problems to sub-agents that return summaries. Start with the simplest approach that
        works.""",
        ["context", "long mission", "notes", "compaction", "summarise", "planning", "memory"],
        "anthropic_context"),
    topic("orchestrator", "reliable-missions", "Keeping long-running missions reliable", """
        Errors compound in long stateful runs, so checkpoint progress and resume from the last checkpoint after a
        failure instead of starting over; add deterministic safeguards such as retries with limits around tool
        calls; and let the agent adapt when a tool fails rather than aborting. Judge a mission by the final state
        it produced and whether it met its success criteria, not by whether it followed one expected path. Trace
        decisions and tool calls so failures can be diagnosed, and roll out changes to the agent system
        gradually so missions already running are not disrupted.""",
        ["mission", "checkpoint", "resume", "reliability", "retries", "tracing", "failure"],
        "anthropic_multiagent"),
    topic("orchestrator", "success-criteria", "Defining done before starting", """
        Turn each mission into success criteria that are specific, measurable, achievable and relevant, with
        several dimensions where needed (correctness, completeness, latency, cost, safety). 'Build passes and the
        three named endpoints return the documented responses' is checkable; 'make it good' is not. Check results
        against the criteria with the cheapest reliable grader: exact or code-based checks first, a rubric-based
        model judgement for qualities such as tone or completeness, and a human for anything consequential.""",
        ["success criteria", "acceptance", "definition of done", "verification", "goals", "evaluation"],
        "anthropic_evals"),

    # ----- swarm manager -----------------------------------------------------------------------------
    topic("swarm_manager", "when-to-swarm", "When a swarm is worth it", """
        Parallel workers help when a task breaks into independent directions that can be explored at once (broad
        research, many separate files or records, comparisons) and when the extra context windows add useful
        capacity. They are a poor fit when work needs shared context, has heavy dependencies between steps, or
        offers little parallelism, which describes much coding. Multi-agent work costs far more tokens than one
        agent, so the value of the result must justify it. Typical sizing: one agent for a simple fact, two to
        four for a comparison, more only for genuinely broad work.""",
        ["swarm", "parallel", "subagents", "cost", "tokens", "sizing", "when to use"], "anthropic_multiagent"),
    topic("swarm_manager", "worker-briefs", "Briefing sub-agents", """
        Each sub-agent needs a specific objective, an output format, guidance on tools and sources, and clear
        boundaries that separate its work from its siblings'; vague briefs cause duplicated searches and
        missed areas. Launch independent workers in parallel rather than one after another, and let each run its
        own tool calls in parallel. Ask workers to return condensed findings with evidence, or to store large
        outputs and return a reference, so the lead's context is not flooded. The lead remains responsible for
        checking results, filling gaps and synthesising.""",
        ["subagent", "brief", "instructions", "parallel", "scope", "output format", "swarm"],
        "anthropic_multiagent"),
    topic("swarm_manager", "worker-context", "Giving workers clean context", """
        Sub-agents work best in a clean, focused context: give each only the knowledge and task material relevant
        to its assignment, and have it return a short summary rather than its whole exploration. This keeps the
        coordinator's context small and high-signal. Choose the technique to the work: parallel sub-agents for
        breadth, persistent notes for milestone-driven work, summarisation for long back-and-forth.""",
        ["context", "subagent", "summary", "focus", "swarm", "coordination"], "anthropic_context"),

    # ----- workspace manager -------------------------------------------------------------------------
    topic("workspace_manager", "branching", "Branching in a workspace", """
        Keep the main branch stable and releasable. Do each piece of work on a short-lived topic branch dedicated
        to one change, so it can be reviewed on its own, merged when ready regardless of order, or thrown away if
        the approach loses. Branches are cheap; create, merge and delete them freely. Larger projects may add an
        integration branch that is merged upward once stable. Branching and merging are local until pushed, so
        nothing reaches the shared remote, or production, without an explicit push.""",
        ["git", "branch", "topic branch", "merge", "main", "workflow", "repository"], "git_branching"),
    topic("workspace_manager", "tool-design", "Tools and records an agent can use well", """
        Prefer a few well-scoped operations that match real workflows over exposing every low-level call; name
        them with clear service and resource prefixes; return meaningful names and types rather than opaque ids;
        paginate, filter or truncate large outputs with a note on how to narrow the request; and return specific,
        actionable errors. The same applies to how a workspace is organised: clear folder structure, naming
        conventions and timestamps let agents find the right material without reading everything.""",
        ["tools", "workspace", "naming", "errors", "pagination", "organisation"], "anthropic_tools"),
    topic("workspace_manager", "workspace-metadata", "Making a workspace legible", """
        Agents navigate a workspace through lightweight signals: folder hierarchy, file naming conventions and
        timestamps tell them what something is and how current it is. Keep a short, current notes file for each
        workspace (purpose, stack, commands, decisions, open work) that agents read at the start of a mission and
        update at milestones, and retrieve file contents just in time instead of loading the whole tree.""",
        ["workspace", "notes", "structure", "metadata", "onboarding", "files"], "anthropic_context"),

    # ----- memory --------------------------------------------------------------------------------------
    topic("memory", "memory-types", "Kinds of memory and how to store them", """
        Separate short-term, thread-scoped state (the current conversation or mission, persisted through
        checkpoints) from long-term memory shared across runs. Long-term memory comes in three kinds: semantic
        facts (a user's preferences, a product's stack), episodic experiences (what happened on a past task,
        useful as examples), and procedural knowledge (instructions and rules that shape behaviour). Store facts
        either as one profile document per entity, which gives a unified view but grows error-prone, or as a
        collection of small documents, which is easier to write and recalls better but is harder to update.
        Namespace every memory by owner and purpose, and decide deliberately whether to write memories during a
        task (immediately available, slower) or in the background (no latency, may lag).""",
        ["memory", "semantic", "episodic", "procedural", "profile", "namespace", "long-term"], "langchain_memory"),
    topic("memory", "vector-search", "Vector search with pgvector", """
        pgvector compares embeddings with L2 distance (<->), cosine distance (<=>), negative inner product (<#>)
        or L1 (<+>). Without an index, search is exact. HNSW indexes give the best speed and recall but build
        slower and use more memory, and can be created on an empty table; tune ef_search at query time for
        recall. IVFFlat builds faster with less memory but must be created after data is loaded (lists about
        rows/1000, probes about sqrt(lists)). Approximate indexes filter after scanning, so filtered searches
        can return too few rows: enable iterative scans or add a regular index on the filter column. Normalise
        vectors to use inner product, and keep indexed vectors at or under 2,000 dimensions (4,000 with halfvec).""",
        ["vector", "embeddings", "pgvector", "similarity", "hnsw", "index", "semantic search"], "pgvector"),
    topic("memory", "minimisation", "Remembering only what is needed", """
        Personal data held must be adequate, relevant and limited to what is necessary for a stated purpose. Do
        not store information just in case it is useful later; review stored memories periodically and delete
        what is no longer needed; take extra care with sensitive categories; and correct or erase memories when
        they are inaccurate or a person asks. Record opinions as opinions, with who recorded them and when, and
        keep facts separate. Being able to show why each kind of memory is kept is part of accountability.""",
        ["privacy", "personal data", "retention", "deletion", "gdpr", "minimisation", "memory"],
        "ico_minimisation"),
    topic("memory", "recall-in-context", "Bringing memory into a task", """
        Recall should add a small amount of high-signal context, not everything known. Retrieve the few memories
        most relevant to the current task, prefer recent and verified ones, and pass references that can be
        expanded on demand. For long missions, keep structured notes outside the context window and reload them
        at milestones; compress old history into summaries tuned to keep what matters.""",
        ["recall", "retrieval", "context", "relevance", "notes", "memory"], "anthropic_context"),

    # ----- self-evolution --------------------------------------------------------------------------------
    topic("self_evolution", "evaluating-changes", "Evaluating a proposed improvement", """
        Before activating a change to prompts, rules, runbooks or tool selection, define what better means with
        specific, measurable criteria across the dimensions that matter (task success, accuracy, safety, latency,
        cost) and test against a set of realistic tasks that includes edge cases. Many automatically graded
        cases beat a few hand-graded ones. Grade with code where possible, with a rubric-based model judge for
        qualitative aspects (ideally a different model from the one being evaluated), and with people for
        consequential changes. Compare against the current version on the same tasks; activate only a measured
        improvement, and keep the previous version for rollback.""",
        ["evaluation", "evals", "improvement", "metrics", "rubric", "regression", "self-evolution"],
        "anthropic_evals"),
    topic("self_evolution", "improving-tools", "Improving tools and instructions from evidence", """
        Read transcripts of real runs to find where agents struggle: redundant calls, wrong tool choice,
        malformed inputs, errors. Improve tool descriptions as if briefing a new colleague (formats, terms,
        relationships), make parameter names unambiguous, consolidate overlapping tools, return higher-signal
        results, and make errors actionable. Letting an agent test a flawed tool and rewrite its description has
        been shown to cut task time substantially. Confirm each change on held-out tasks so the system does not
        overfit to the examples it was tuned on.""",
        ["tools", "descriptions", "transcripts", "improvement", "evaluation", "prompts"], "anthropic_tools"),
    topic("self_evolution", "prompt-altitude", "Writing instructions that generalise", """
        Good instructions sit at the right altitude: specific enough to guide behaviour, general enough to give
        the model strong heuristics instead of brittle hard-coded branches. Start minimal, test, and add
        instructions only in response to observed failures; organise them in clear sections; use a few
        canonical, diverse examples rather than a long list of edge cases. A proposed rule change that only adds
        special cases for past failures is usually a sign the underlying instruction needs rewriting.""",
        ["prompts", "instructions", "rules", "examples", "generalise", "self-evolution"], "anthropic_context"),

    # ----- research ----------------------------------------------------------------------------------------
    topic("research", "sift", "Checking sources quickly", """
        Stop before using a claim and ask whether you know the source. Investigate the source: who published it,
        their expertise, agenda and record for accuracy. Find better coverage when the claim matters more than
        the particular article: look for authoritative or more thorough reporting and see whether experts agree.
        Trace claims, quotes and data to their original context, checking what was cut or reframed, and confirm
        cited studies actually say what is claimed. Match the depth of checking to the stakes.""",
        ["sources", "fact-checking", "verification", "credibility", "evidence", "research"], "sift"),
    topic("research", "search-strategy", "Searching like an expert", """
        Start with short, broad queries to see what exists, then narrow; long, over-specific queries return
        little. Prefer specialised sources and tools over generic web search when they exist (official
        documentation, registries, primary data), and use broad search to discover. Run independent searches in
        parallel. After each result, judge its quality and what is still missing before choosing the next query.
        Watch for a bias towards search-optimised content farms over authoritative primary sources, and attribute
        every claim to the source it came from.""",
        ["search", "queries", "sources", "research", "breadth", "authoritative", "citations"],
        "anthropic_multiagent"),
    topic("research", "reporting", "Reporting research", """
        Return condensed findings with their evidence and sources, not the whole exploration. Separate what the
        sources say from inference and assumption, state uncertainty and disagreement between sources, and keep
        quotes short with a link to the original. Large raw material belongs in storage with a reference, so the
        reader gets a high-signal summary and can expand on demand.""",
        ["report", "findings", "summary", "citations", "uncertainty", "research"], "anthropic_context"),
]
