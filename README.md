# JARV Agentic AI System

**Version**: 1.0.0 - Final Production Build
**Owner**: Richard Curley
**Status**: In Development

## Overview

JARV is a private autonomous multi-agent AI execution system that can finish, launch, operate, self-heal, market, support, onboard users, create content, manage community, build partnerships, manage infrastructure, run company operations, safely improve from experience, scale its own temporary sub-agent workforce, and scale any project given to it.

### What JARV Is

- **Full Production System**: Not an MVP, prototype, or demo - this is the complete final production system
- **31-Agent Architecture**: Fully autonomous multi-agent system with specialized roles
- **Company Operator**: Runs platforms like AI-operated companies with autonomous operating loops
- **Self-Evolving**: Learns from experience and safely improves its own workflows, runbooks, and strategies
- **Swarm-Capable**: Scales its agent team with scoped temporary sub-agents for parallel work
- **Approval-Resume System**: Pauses only blocked actions at hard boundaries, continues safe work, resumes after approval
- **Richard Boundary Operator**: Richard clears gates (sign-ins, passwords, payments, approvals), JARV does everything else

### What JARV Does

JARV can autonomously:
- Read, write, edit files and create folders
- Scan repositories and analyze document packs
- Detect project type, tech stack, package manager, build/test/run/deploy commands
- Find missing files and incomplete logic
- Create task plans and operating plans
- Run daily operating loops and weekly execution plans
- Write, debug, build, test, and deploy code
- Install approved tools and packages
- Create documentation, marketing campaigns, technical content
- Source creative assets and record asset licenses
- Create onboarding flows and handle support workflows
- Manage community workflows and build partnership pipelines
- Create sales workflows and business strategy
- Track metrics, revenue, and manage infrastructure
- Monitor platforms and self-heal approved incidents
- Roll back failed changes and prepare launches
- Use voice commands and store/search memory
- Store and learn from experience
- Propose safe self-evolution improvements
- Spawn scoped temporary sub-agents for parallel work
- Track swarm cost and runtime, dissolve sub-agents when complete

## Architecture

### System Components

- **Local Laptop Runner**: Executes file operations, terminal commands, builds, tests on Richard's laptop
- **24/7 Cloud Runner**: Runs autonomous company operations, monitoring, self-healing, scheduled tasks
- **Private Web Dashboard**: Control panel for monitoring all system operations
- **Dynamic Project Workspaces**: Not hard-coded platform modes - works with any project
- **Autonomous Company Operating Layer**: Runs each workspace like an AI-operated company
- **Self-Evolution Layer**: Safely improves from experience without weakening safety
- **Swarm Management Layer**: Controlled parallel execution with temporary scoped sub-agents
- **Approval and Resume Layer**: Pauses blocked actions, continues safe work, resumes from checkpoints
- **Richard Boundary Operator Layer**: Richard clears gates, JARV continues the mission

### The 31 Agents

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

## Tech Stack

### Frontend
- Next.js with TypeScript
- Tailwind CSS
- shadcn/ui components
- TanStack Query
- WebSockets

### Backend
- Python with FastAPI
- Pydantic for validation
- SQLAlchemy ORM
- Alembic for migrations
- WebSockets
- JWT/session authentication

### Database
- PostgreSQL with pgvector
- Redis for caching and job queues

### Workers
- Celery or Dramatiq with Redis broker
- Specialized workers for different operations

### Agent Orchestration
- LangGraph (preferred)
- Agent registry and tool registry
- Task state machine
- Model router with fallback and retry
- Swarm manager for parallel execution

### LLM Providers
- Claude API (primary)
- OpenAI (optional adapter)
- Gemini (optional adapter)
- Ollama/local models (optional adapter)

### Cloud & Infrastructure
- Docker and Docker Compose
- Nginx-ready configuration
- VPS-ready deployment
- HTTPS support
- Persistent volumes
- Backup and restore scripts

### Voice
- Push-to-talk interface
- Wake word support
- Speech-to-text integration
- Text-to-speech integration

## Getting Started

You need Docker (Docker Desktop with WSL on Windows) and Git.

```bash
git clone https://github.com/lilrickyuk-netizen/jarv-agentic-ai.git
cd jarv-agentic-ai
cp apps/backend/.env.example apps/backend/.env    # add CLAUDE_API_KEY (and any other services)
docker compose up -d                              # migrations run first, then everything else
docker compose exec backend python scripts/setup_admin.py --username richard
```

Open http://localhost:3000 and sign in. The **Settings** page shows which services are configured
and checks each one. Production on a VPS, upgrades, tests and troubleshooting are in the
[runbook](./docs/RUNBOOK.md).

## Documentation

- [Runbook](./docs/RUNBOOK.md) - running, using, upgrading, testing and troubleshooting JARV
- [Configuration](./docs/CONFIGURATION.md) - every setting
- [Deployment](./docs/DEPLOYMENT.md) - how JARV deploys your projects to your VPS
- [Operations](./docs/OPERATIONS.md) - self-healing, container operations, backups and restores
- [JARV Final System Spec](./docs/JARV_FINAL_SYSTEM_SPEC.md) - the complete system specification
- [Implementation Checklist](./docs/IMPLEMENTATION_CHECKLIST.md) - the build checklist
- [Build Ledger](./BUILD_LEDGER.md) - what was built, how it was tested, and the results
- [Build history](./docs/history/README.md) - superseded phase reports from the original build

## Project Structure

```
jarv/
├── apps/                    # Application packages
│   ├── dashboard/          # Next.js dashboard frontend
│   └── backend/            # FastAPI backend
├── services/               # Service packages
│   ├── local-runner/       # Local laptop runner service
│   ├── orchestrator/       # Main orchestrator service
│   └── workers/            # Worker services
├── packages/               # Shared packages
│   ├── agents/             # Agent implementations
│   ├── tools/              # Tool registry
│   └── models/             # Shared data models
├── infra/                  # Infrastructure configuration
│   ├── docker/             # Docker configurations
│   ├── nginx/              # Nginx configurations
│   └── scripts/            # Deployment scripts
├── scripts/                # Utility scripts
├── docs/                   # Documentation
├── BUILD_LEDGER.md         # Build tracking ledger
├── CLAUDE.md               # ClaudeCode guardrails
└── README.md               # This file
```

## Development

### Build Status

See [BUILD_LEDGER.md](./BUILD_LEDGER.md) for detailed build progress and task tracking.

### Build Principles

- This is the complete final production build - NOT an MVP or prototype
- Every task must be completed before moving to the next task
- No "TODO", "coming soon", "future work", or "implement later"
- Every feature must be fully implemented, wired, tested, and verified
- BUILD_LEDGER.md must be updated after every task completion

## Security & Safety

JARV includes comprehensive safety systems:

- Authority-based permission system with 7 levels
- Hard boundary detection and reporting
- Secret redaction system
- Audit logging for every action
- Sub-agent authority guards preventing escalation
- Sub-agent workspace scope enforcement
- Self-evolution safety guards
- Approval and resume system for hard boundaries
- Richard Boundary Operator workflow

## License

Private system - All rights reserved by Richard Curley

## Support

For questions or issues during development, see the BUILD_LEDGER.md for current status and blockers.
