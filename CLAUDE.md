# CLAUDE CODE BUILD GUARDRAILS FOR JARV
## STRICT BUILD RULES - MUST BE FOLLOWED AT ALL TIMES

**Project**: JARV Agentic AI System
**Owner**: Richard Curley
**Build Type**: First, last, final, and only production build

---

## ABSOLUTE BUILD POSITION

This is not an MVP.

This is not a prototype.

This is not a chatbot.

This is not a demo.

This is not a partial version.

This is not "phase one now, real system later".

**This is the complete final production system.**

ClaudeCode must build the whole system from start to finish.

Build phases are allowed only as construction order.

No core feature is optional.

No agent can be skipped.

No tool can be fake.

No folder can be empty.

No file can be TODO-only.

No "coming soon".

No "future work".

No "implement later".

No hard-coded fixed modes for Richard's platforms.

No fake completion.

No unverified output.

No unlogged action.

No unsafe hidden execution.

No weakening safety rules.

No self-modification without verification.

No sub-agent authority escalation.

No unscoped sub-agents.

---

## STRICT CLAUDECODE GUARDRAILS

ClaudeCode must obey these rules at all times:

1. **Complete tasks in exact order**
2. **Do not move to the next task until the current task is implemented, wired, tested, logged, and recorded**
3. **Create /BUILD_LEDGER.md first**
4. **Update /BUILD_LEDGER.md after every task**
5. **Every feature must connect to the real system**
6. **Every agent must connect to the orchestrator**
7. **Every tool must connect to the tool registry**
8. **Every dashboard page must connect to real backend data**
9. **Every database model must have migrations**
10. **Every action must be logged**
11. **Every risky action must pass authority checks**
12. **Every sub-agent action must be logged with parent agent reference**
13. **No fake data except clearly labelled seed/demo data**
14. **No mock-only implementation for core features**
15. **No unconnected UI**
16. **No dead buttons**
17. **No placeholder agents**
18. **No placeholder tools**
19. **No empty files**
20. **No empty folders**
21. **No fake success reports**
22. **No hidden unsafe execution**
23. **No direct tool execution outside the authority checker**
24. **No self-evolution change can weaken safety, hard boundaries, authority, logging, verifier checks, or secret handling**
25. **No swarm sub-agent can exceed the authority, workspace scope, or tool access of the Lead Agent that spawned it**
26. **If an API key or external account is required, create the adapter, config, disabled state, validation, and setup instructions, then continue building everything possible without the live key**
27. **If a task cannot be completed, stop and record the blocker in /BUILD_LEDGER.md**
28. **Do not claim the system is complete until the final acceptance test passes**

---

## FORBIDDEN IMPLEMENTATION PHRASES

The following phrases are **ABSOLUTELY FORBIDDEN** in code, comments, or documentation (except in this guardrail section):

- TODO
- placeholder
- coming soon
- implement later
- future version
- not implemented
- mock only
- stub
- will be added
- to be completed
- pending implementation

If any of these phrases appear outside this guardrail document, the task is **NOT COMPLETE**.

---

## BUILD LEDGER REQUIREMENT

The file `/BUILD_LEDGER.md` is the source of truth.

It must contain:
- Project name
- Current phase
- Current task
- Completed tasks
- Pending tasks
- Files created
- Files modified
- Commands run
- Tests run
- Results
- Blockers
- Next action
- Final acceptance status

**Every task must be recorded using this format:**

```
TASK ID:
TASK NAME:
STATUS: NOT_STARTED / IN_PROGRESS / COMPLETE / BLOCKED
FILES CREATED:
FILES MODIFIED:
COMMANDS RUN:
TESTS RUN:
RESULT:
BLOCKERS:
NEXT TASK:
```

**The ledger must be updated after every task.**

---

## CORRECT OPERATING MODEL

Richard gives JARV a mission.

JARV creates a Dynamic Project Workspace.

JARV creates an Operating Plan.

JARV learns the workspace.

JARV plans the work.

JARV decides whether single-agent or swarm execution is needed.

JARV assigns agents.

JARV spawns scoped sub-agents only when safe and useful.

JARV uses tools.

JARV edits files.

JARV runs builds.

JARV fixes errors.

JARV sources assets.

JARV creates docs, content, onboarding, marketing, support, business, community, partnership, sales, revenue, and infrastructure outputs.

JARV monitors live systems.

JARV self-heals approved issues.

JARV captures experience.

JARV safely improves workflows, runbooks, prompts, rules, and swarm strategies.

JARV updates memory.

JARV produces a verified final report.

**JARV only stops when a true hard boundary is reached.**

---

## COMPLETION VERIFICATION RULES

**Do not say the foundation is complete if:**
- The agents are not wired
- Tools are not registered
- Authority checks are missing
- Database migrations are missing

**Do not say the agents are complete if:**
- Tools are not wired
- Authority levels are not enforced
- Logging is missing
- Orchestrator connection is missing

**Do not say tools are complete if:**
- Authority checks are missing
- Logging is missing
- Tool registry registration is missing
- Boundary detection is missing

**Do not say dashboard is complete if:**
- Pages use fake data
- Backend endpoints don't exist
- UI is not connected to real API
- Charts show placeholder data

**Do not say memory is complete if:**
- Search doesn't work
- Update doesn't work
- Delete doesn't work
- Link to workspace doesn't work
- Link to task doesn't work

**Do not say self-healing is complete if:**
- It only alerts
- It doesn't actually fix issues
- Runbooks are not implemented
- Experience records are not created

**Do not say self-evolution is complete if:**
- It can weaken safety
- It cannot roll back changes
- Versioning doesn't work
- Safety guards are missing

**Do not say swarm is complete if:**
- Sub-agents can escalate authority
- Sub-agents can escape workspace scope
- Sub-agents avoid logs
- Sub-agents fail to dissolve
- Token cost tracking is missing

**Do not say approval handling is complete if:**
- Hard boundaries abandon the mission
- JARV doesn't pause only blocked actions
- Safe parallel work doesn't continue
- Resume from checkpoint doesn't work

**Do not say checkpoint resume is complete if:**
- JARV cannot resume from the last safe point
- Mission is abandoned after approval
- Safe work doesn't continue during wait

**Do not say Richard Boundary Operator is complete if:**
- JARV hands normal work back to Richard
- JARV cannot resume after Richard clears a gate
- JARV abandons the mission at approval checkpoints

**Do not say infrastructure is complete if:**
- Backup is missing
- Restore is missing
- Docker configuration is missing
- SSL checks are missing
- DNS checks are missing
- Resource checks are missing
- Cost estimation is missing

---

## TECH STACK - MANDATORY

Use this stack unless impossible. If impossible, record the reason in BUILD_LEDGER and choose the closest production-grade alternative.

### Frontend
- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- WebSockets

### Backend
- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- WebSockets
- JWT/session auth

### Database
- PostgreSQL
- pgvector
- Redis

### Workers
- Celery or Dramatiq
- Redis broker
- Multiple specialized workers

### Agent Orchestration
- LangGraph preferred
- Custom orchestrator allowed only if fully implemented
- Agent registry
- Tool registry
- Task state machine
- Model router
- Swarm manager
- Approval manager
- Checkpoint manager

### LLM Providers
- Claude API primary
- OpenAI adapter optional
- Gemini adapter optional
- Ollama/local adapter optional

### Cloud
- Docker
- Docker Compose
- Nginx-ready
- VPS-ready
- HTTPS-ready
- Persistent volumes
- Backup scripts
- Restore scripts

---

## AUTHORITY MODEL - MUST BE ENFORCED

### Level 1: Read Only
- Read files
- Scan folders
- Inspect logs
- Analyse code
- Create reports

### Level 2: Edit Workspace Files
- Create/edit/move/rename files
- Only inside approved workspace folders

### Level 3: Build and Test
- Run approved build commands
- Run approved test commands
- Fix build/test errors

### Level 4: Install Approved Tools and Packages
- Install from official package managers
- Use approved sources only

### Level 5: Staging Deploy
- Deploy to staging
- Test staging
- Roll back staging

### Level 6: Production Repair
- Restart services
- Clear approved caches
- Roll back latest deploy
- Scale within approved budget

### Level 7: Live Release
- Can execute only if Richard explicitly grants release authority

### Sub-Agent Authority Rule
- Sub-agent authority ≤ Lead Agent authority
- Sub-agent cannot exceed Lead Agent tool permissions
- Sub-agent cannot exceed Lead Agent workspace scope
- Sub-agent cannot spawn further sub-agents unless configured
- Any authority escalation must be blocked and reported

---

## HARD BOUNDARIES - MUST PAUSE FOR APPROVAL

JARV must pause (not abandon) at these boundaries:

1. Entering bank details
2. Spending money beyond approved budget
3. Entering passwords
4. Accessing password managers
5. Accessing private keys
6. Accessing seed phrases
7. Accessing crypto wallets
8. Signing contracts
9. Sending binding legal/commercial commitments
10. Deleting production data
11. Making irreversible database changes
12. Publishing public live release without release authority
13. Sending mass emails from Richard's accounts
14. Posting publicly from Richard's accounts
15. Running unknown executable files
16. Changing account security settings
17. Changing passwords
18. Disabling audit logs
19. Disabling verifier checks
20. Disabling boundary reports
21. Weakening authority rules
22. Removing hard-boundary rules
23. Allowing sub-agent authority escalation
24. Allowing sub-agent workspace escape
25. Performing unlawful activity
26. Testing systems without authorisation

**When a hard boundary is reached:**
1. Pause ONLY the blocked action
2. Create Boundary Report
3. Continue safe parallel work
4. Wait for Richard's approval/input
5. Resume from safe checkpoint after approval
6. Complete the mission

---

## RICHARD BOUNDARY OPERATOR MODEL

Richard is the boundary operator, not the task manager.

**JARV must not ask Richard to:**
- Decide normal implementation details
- Choose routine file names
- Fix routine build errors
- Write routine code
- Debug normal errors
- Create routine documentation
- Run approved tests
- Check logs
- Restart approved services

**Richard may be required for:**
- Signing in
- Entering passwords
- Entering payment details
- Approving spend
- Approving account setup
- Approving live release
- Approving legal/commercial commitments
- Approving anything involving banking, private keys, or password managers

---

## SELF-EVOLUTION SAFETY RULES

JARV can improve:
- Workspace rules
- Operating plans
- Runbooks
- Agent instructions
- Tool selection rules
- Swarm strategies
- Debugging strategies
- Content plans
- Marketing experiments

JARV cannot automatically:
- Remove safety rules
- Increase authority
- Remove hard boundaries
- Change secret-handling rules
- Disable audit logs
- Disable verifier checks
- Disable boundary reports
- Remove sub-agent scope limits

Every self-evolution must:
- Create Self-Evolution Record
- Be versioned
- Be reversible
- Be verified before activation
- Block unsafe changes

---

## SWARM MANAGEMENT RULES

### Sub-Agent Rules
- Inherits Lead Agent role template
- Inherits Lead Agent tool access
- Inherits Lead Agent workspace scope
- Authority cannot exceed Lead Agent authority
- Scoped to one workspace
- Scoped to one task or task batch
- Dissolves on completion, failure, or timeout
- Actions logged with parent agent reference
- Cannot spawn further sub-agents unless configured
- Cannot increase authority
- Cannot override workspace rules
- Cannot override hard boundaries
- Cannot disable logging
- Cannot disable verification

---

## MEMORY SYSTEM RULES

### 23 Memory Types Required
1. Global Memory
2. Workspace Memory
3. Company Operating Memory
4. Task Memory
5. Incident Memory
6. Asset Memory
7. Customer Memory
8. Business Memory
9. Revenue Memory
10. Infrastructure Memory
11. Content Memory
12. Onboarding Memory
13. Community Memory
14. Partnership Memory
15. Sales Memory
16. Decision Memory
17. Boundary Memory
18. Experience Memory
19. Self-Evolution Memory
20. Swarm Memory
21. Approval Memory
22. Checkpoint Memory
23. Richard Boundary Operator Memory

Memory must support:
- Add
- Search
- Update
- Delete
- Link to workspace
- Link to task
- Timestamp
- Confidence score
- Source/action reference
- Version reference
- Parent agent reference
- Sub-agent reference
- Approval reference
- Checkpoint reference

Do not store random useless memory.

Do not mix workspace memory.

Do not lose task history.

---

## DASHBOARD REQUIREMENTS

Every page must use real backend data.

No static-only UI.

No disconnected buttons.

No fake charts.

No dead pages.

### Required Pages (31 total)
1. Command Center
2. Workspaces
3. Company Operations
4. AI Standups
5. Live Operations Feed
6. Self-Evolution
7. Swarm
8. Agents
9. Tasks
10. Memory
11. Experience
12. Tools
13. Permissions
14. Boundary Reports
15. Approvals
16. Checkpoints
17. Richard Boundary Operator
18. Assets
19. Support
20. Marketing
21. Content
22. Onboarding
23. Community
24. Partnerships
25. Sales
26. Business
27. Revenue Operations
28. Analytics
29. Operations
30. Infrastructure
31. Settings

---

## DATABASE MODELS - ALL REQUIRED

All 59 models must be created with migrations:
- User, Workspace, WorkspaceRule, WorkspaceRuleVersion, WorkspaceRunbook, WorkspaceScan
- OperatingPlan, OperatingPlanVersion, DailyOperatingLoop, WeeklyExecutionPlan, AIStandup
- KPIRecord, RevenueOperation, LiveOperationsFeedItem, RiskRegisterItem, DecisionLogItem
- Agent, AgentStrategyVersion, Task, Tool, ToolRun, ToolSelectionRule
- Memory, ExperienceRecord, SelfEvolutionRecord, VerificationResult
- Runbook, RunbookVersion
- SwarmRun, SubAgent, SubAgentTask, SubAgentLog, SwarmCostRecord, SwarmLimitPolicy
- BoundaryReport, BoundaryApproval, ApprovalWindow, SafeCheckpoint, ResumeAction, RichardBoundaryInput
- CommandRun, FileChange
- Asset, AssetLicence
- SupportTicket, MarketingCampaign, BusinessPlan, Incident
- AuthorityPolicy, AuditLog
- InfrastructureResource, BackupRecord, DeploymentRecord
- ContentItem, OnboardingFlow, CommunityItem, PartnershipRecord, SalesRecord

---

## 31 AGENTS - ALL REQUIRED

1. Orchestrator Agent
2. Company Operator Agent
3. Workspace Manager Agent
4. Coding Agent
5. Debugging Agent
6. Verifier Agent
7. DevOps / Launch Agent
8. Documentation Agent
9. Research Agent
10. Memory Agent
11. Marketing Agent
12. Growth Agent
13. Customer Support Agent
14. Business Agent
15. Finance / Metrics Agent
16. Creation Agent
17. Self-Healing Operations Agent
18. Monitoring Agent
19. Rollback Agent
20. Security Agent
21. Legal / Compliance Drafting Agent
22. Sales Agent
23. Analytics Agent
24. QA Agent
25. Infrastructure Agent
26. Onboarding Agent
27. Community Agent
28. Partnerships / BD Agent
29. Content Agent
30. Self-Evolution Agent
31. Swarm Manager Agent

Every agent must have:
- Name, Role, Input schema, Output schema
- Allowed tools
- Memory access rules
- Authority rules
- Logging, Error handling
- Agent registry registration
- Orchestrator connection

---

## TOOL GROUPS - ALL REQUIRED

All tool groups must be fully implemented:
- File Tools (10 tools)
- Command Tools (7 tools)
- Git Tools (8 tools)
- Workspace Tools (11 tools)
- Company Operation Tools (16 tools)
- Swarm Tools (13 tools)
- Memory Tools (6 tools)
- Experience Tools (6 tools)
- Self-Evolution Tools (10 tools)
- Approval and Resume Tools (15 tools)
- Asset Tools (7 tools)
- Support Tools (7 tools)
- Marketing Tools (7 tools)
- Content Tools (10 tools)
- Onboarding Tools (9 tools)
- Community Tools (9 tools)
- Partnership Tools (10 tools)
- Sales Tools (6 tools)
- Revenue Tools (8 tools)
- Monitoring Tools (9 tools)
- Deployment Tools (7 tools)
- Infrastructure Tools (18 tools)
- Voice Tools (5 tools)
- Boundary Tools (6 tools)

Every tool must be:
- Real (not fake)
- Registered in tool registry
- Callable
- Logged
- Authority-checked

---

## MISSING CREDENTIALS POLICY

If a credential is missing during build:

**DO:**
- Build the full adapter
- Build settings UI
- Build validation flow
- Build disabled state
- Create setup instructions
- Create error handling
- Continue building everything possible without the live key

**DO NOT:**
- Skip the feature
- Leave placeholder code
- Leave TODO comments
- Claim it's "not implemented"
- Use missing credentials as an excuse

---

## FINAL ACCEPTANCE CRITERIA

The system is NOT complete until:

- [ ] All 31 agents fully implemented and wired
- [ ] All tool groups implemented and registered
- [ ] All dashboard pages with real backend data
- [ ] All database models with migrations
- [ ] Local runner operational
- [ ] Cloud runner operational
- [ ] Authority and safety system operational
- [ ] Swarm system operational with proper sub-agent scoping
- [ ] Self-evolution system operational with safety guards
- [ ] Autonomous company operating layer operational
- [ ] Approval and resume system operational
- [ ] Richard Boundary Operator system operational
- [ ] Final acceptance test passing

---

## WHAT SUCCESS LOOKS LIKE

Richard gives JARV any project.

JARV creates the workspace.

JARV creates the operating plan.

JARV learns it.

JARV completes it.

JARV launches it.

JARV operates it.

JARV fixes it.

JARV markets it.

JARV creates content for it.

JARV onboards users.

JARV supports users.

JARV manages community.

JARV builds partnerships.

JARV manages infrastructure.

JARV tracks revenue.

JARV captures experience.

JARV safely improves itself.

JARV scales its team when needed.

JARV pauses only blocked hard-boundary actions.

JARV asks Richard only to clear real gates.

JARV continues safe work while waiting for Richard.

JARV resumes from checkpoint after Richard clears the gate.

JARV launches MYCO.

JARV operates MYCO.

JARV scales the platform.

**That is the system you are building.**

---

## ENFORCEMENT

These rules are NON-NEGOTIABLE.

Any violation means the task is NOT COMPLETE.

Any placeholder, TODO, or "implement later" means the task is NOT COMPLETE.

Any fake data in production code means the task is NOT COMPLETE.

Any missing connection means the task is NOT COMPLETE.

**Build it right. Build it once. Build it complete.**

---

**END OF GUARDRAILS**
