# JARV AGENTIC AI SYSTEM - IMPLEMENTATION CHECKLIST

**Version**: Final Production Build
**Owner**: Richard Curley
**Last Updated**: 2026-06-03

This checklist contains every phase and task required to build the complete JARV system from start to finish.

**Important**: Every task must be completed before moving to the next task. After each task:
1. Run relevant checks/tests
2. Update /BUILD_LEDGER.md
3. Do not continue until complete

---

## PHASE 0: BUILD CONTROL

### TASK 0.1: Create repository structure
- [ ] Create /BUILD_LEDGER.md
- [ ] Create /README.md
- [ ] Create /docs directory
- [ ] Create /apps directory
- [ ] Create /services directory
- [ ] Create /infra directory
- [ ] Create /scripts directory
- [ ] Create /packages directory
- [ ] Update BUILD_LEDGER.md

### TASK 0.2: Create /docs/JARV_FINAL_SYSTEM_SPEC.md
- [ ] Create comprehensive system specification
- [ ] Document all 31 agents
- [ ] Document all tool groups
- [ ] Document architecture
- [ ] Document Richard Boundary Operator layer
- [ ] Document Approval and Resume system
- [ ] Document Swarm Management layer
- [ ] Document Self-Evolution layer
- [ ] Document Autonomous Company Operating layer
- [ ] Update BUILD_LEDGER.md

### TASK 0.3: Create /docs/IMPLEMENTATION_CHECKLIST.md
- [ ] Create detailed implementation checklist
- [ ] Include all 25 phases
- [ ] Include all tasks with acceptance criteria
- [ ] Update BUILD_LEDGER.md

### TASK 0.4: Create /CLAUDE.md
- [ ] Create strict guardrails document
- [ ] Document forbidden phrases
- [ ] Document build principles
- [ ] Document authority model
- [ ] Document safety requirements
- [ ] Update BUILD_LEDGER.md

---

## PHASE 1: FOUNDATION

### TASK 1.1: Create monorepo
- [ ] Add frontend app structure
- [ ] Add backend app structure
- [ ] Add local runner service structure
- [ ] Add worker service structure
- [ ] Add shared packages structure
- [ ] Update BUILD_LEDGER.md

### TASK 1.2: Create Docker Compose
- [ ] Add backend service
- [ ] Add frontend service
- [ ] Add postgres service
- [ ] Add redis service
- [ ] Add worker service
- [ ] Add scheduler service
- [ ] Test Docker Compose runs successfully
- [ ] Update BUILD_LEDGER.md

### TASK 1.3: Create env config
- [ ] Create .env.example
- [ ] Create backend config
- [ ] Create frontend config
- [ ] Create local runner config
- [ ] Create cloud config
- [ ] Verify no secrets hardcoded
- [ ] Update BUILD_LEDGER.md

### TASK 1.4: Build FastAPI backend
- [ ] Create health endpoint
- [ ] Create version endpoint
- [ ] Add structured logging
- [ ] Add error handling
- [ ] Add CORS
- [ ] Run backend test
- [ ] Update BUILD_LEDGER.md

### TASK 1.5: Build Next.js frontend
- [ ] Add Tailwind CSS
- [ ] Add shadcn/ui components
- [ ] Create dashboard shell
- [ ] Create API client
- [ ] Add backend health connection
- [ ] Run frontend build
- [ ] Update BUILD_LEDGER.md

### TASK 1.6: Add PostgreSQL, SQLAlchemy, Alembic
- [ ] Add PostgreSQL connection
- [ ] Add SQLAlchemy ORM
- [ ] Add Alembic migrations
- [ ] Create first migration
- [ ] Run migration successfully
- [ ] Update BUILD_LEDGER.md

### TASK 1.7: Add Redis and worker queue
- [ ] Add Redis connection
- [ ] Add worker queue foundation (Celery or Dramatiq)
- [ ] Add test background job
- [ ] Run worker test
- [ ] Update BUILD_LEDGER.md

### TASK 1.8: Add auth
- [ ] Add private local admin login
- [ ] Add session/JWT auth
- [ ] Add protected dashboard routes
- [ ] Add protected backend routes
- [ ] Test auth flow
- [ ] Update BUILD_LEDGER.md

---

## PHASE 2: DATABASE MODELS

### TASK 2.1: Create all database models
- [ ] Create User model
- [ ] Create Workspace model
- [ ] Create WorkspaceRule model
- [ ] Create WorkspaceRuleVersion model
- [ ] Create WorkspaceRunbook model
- [ ] Create WorkspaceScan model
- [ ] Create OperatingPlan model
- [ ] Create OperatingPlanVersion model
- [ ] Create DailyOperatingLoop model
- [ ] Create WeeklyExecutionPlan model
- [ ] Create AIStandup model
- [ ] Create KPIRecord model
- [ ] Create RevenueOperation model
- [ ] Create LiveOperationsFeedItem model
- [ ] Create RiskRegisterItem model
- [ ] Create DecisionLogItem model
- [ ] Create Agent model
- [ ] Create AgentStrategyVersion model
- [ ] Create Task model
- [ ] Create Tool model
- [ ] Create ToolRun model
- [ ] Create ToolSelectionRule model
- [ ] Create Memory model
- [ ] Create ExperienceRecord model
- [ ] Create SelfEvolutionRecord model
- [ ] Create VerificationResult model
- [ ] Create Runbook model
- [ ] Create RunbookVersion model
- [ ] Create SwarmRun model
- [ ] Create SubAgent model
- [ ] Create SubAgentTask model
- [ ] Create SubAgentLog model
- [ ] Create SwarmCostRecord model
- [ ] Create SwarmLimitPolicy model
- [ ] Create BoundaryReport model
- [ ] Create BoundaryApproval model
- [ ] Create ApprovalWindow model
- [ ] Create SafeCheckpoint model
- [ ] Create ResumeAction model
- [ ] Create RichardBoundaryInput model
- [ ] Create CommandRun model
- [ ] Create FileChange model
- [ ] Create Asset model
- [ ] Create AssetLicence model
- [ ] Create SupportTicket model
- [ ] Create MarketingCampaign model
- [ ] Create BusinessPlan model
- [ ] Create Incident model
- [ ] Create AuthorityPolicy model
- [ ] Create AuditLog model
- [ ] Create InfrastructureResource model
- [ ] Create BackupRecord model
- [ ] Create DeploymentRecord model
- [ ] Create ContentItem model
- [ ] Create OnboardingFlow model
- [ ] Create CommunityItem model
- [ ] Create PartnershipRecord model
- [ ] Create SalesRecord model
- [ ] Update BUILD_LEDGER.md

### TASK 2.2: Create Alembic migrations
- [ ] Create migrations for all models
- [ ] Run all migrations successfully
- [ ] Verify database schema
- [ ] Update BUILD_LEDGER.md

### TASK 2.3: Create optional editable seed workspaces
- [ ] Create seed workspace templates
- [ ] Ensure they are removable
- [ ] Ensure they are not hard-coded modes
- [ ] Update BUILD_LEDGER.md

---

## PHASE 3: MODEL ROUTER

### TASK 3.1: Create model provider interface
- [ ] Create base provider interface
- [ ] Update BUILD_LEDGER.md

### TASK 3.2: Implement Claude provider
- [ ] Implement Claude API provider
- [ ] Use env key (no hardcoding)
- [ ] Test Claude provider
- [ ] Update BUILD_LEDGER.md

### TASK 3.3: Implement OpenAI adapter
- [ ] Implement OpenAI adapter
- [ ] Can be disabled if no key
- [ ] Update BUILD_LEDGER.md

### TASK 3.4: Implement Gemini adapter
- [ ] Implement Gemini adapter
- [ ] Can be disabled if no key
- [ ] Update BUILD_LEDGER.md

### TASK 3.5: Implement Ollama/local adapter
- [ ] Implement Ollama/local adapter
- [ ] Can be disabled if endpoint not available
- [ ] Update BUILD_LEDGER.md

### TASK 3.6: Implement model router
- [ ] Add task type routing
- [ ] Add agent preference
- [ ] Add workspace preference
- [ ] Add fallback logic
- [ ] Add retry logic
- [ ] Add token/cost logging
- [ ] Test model router
- [ ] Update BUILD_LEDGER.md

### TASK 3.7: Add model settings backend endpoints
- [ ] Create model settings endpoints
- [ ] Test endpoints
- [ ] Update BUILD_LEDGER.md

---

## PHASE 4: AGENT CORE

### TASK 4.1: Create AgentBase class
- [ ] Add name field
- [ ] Add role field
- [ ] Add input schema
- [ ] Add output schema
- [ ] Add allowed tools
- [ ] Add memory access
- [ ] Add authority level
- [ ] Add run method
- [ ] Add logging
- [ ] Add error handling
- [ ] Update BUILD_LEDGER.md

### TASK 4.2: Create agent registry
- [ ] Create agent registry system
- [ ] Register all 31 agents
- [ ] No empty agents allowed
- [ ] Update BUILD_LEDGER.md

### TASK 4.3: Implement Orchestrator Agent
- [ ] Receive mission
- [ ] Load workspace
- [ ] Load memory
- [ ] Load operating plan
- [ ] Create task plan
- [ ] Delegate tasks
- [ ] Call tools
- [ ] Enforce authority
- [ ] Request swarm execution where useful
- [ ] Request verification
- [ ] Update memory
- [ ] Produce final report
- [ ] Update BUILD_LEDGER.md

### TASK 4.4: Implement task state machine
- [ ] Add CREATED state
- [ ] Add PLANNED state
- [ ] Add ASSIGNED state
- [ ] Add RUNNING state
- [ ] Add WAITING_ON_TOOL state
- [ ] Add WAITING_ON_SWARM state
- [ ] Add WAITING_ON_APPROVAL state
- [ ] Add WAITING_ON_RICHARD_BOUNDARY_INPUT state
- [ ] Add RESUMING_FROM_CHECKPOINT state
- [ ] Add VERIFYING state
- [ ] Add COMPLETE state
- [ ] Add FAILED state
- [ ] Add BLOCKED state
- [ ] Add CANCELLED state
- [ ] Update BUILD_LEDGER.md

### TASK 4.5: Implement agent execution logs
- [ ] Every agent action must log to AuditLog
- [ ] Test logging
- [ ] Update BUILD_LEDGER.md

---

## PHASE 5: TOOL REGISTRY

### TASK 5.1: Create ToolBase class
- [ ] Create base tool class
- [ ] Update BUILD_LEDGER.md

### TASK 5.2: Create tool registry
- [ ] Create tool registry system
- [ ] Register all required tools
- [ ] Update BUILD_LEDGER.md

### TASK 5.3: Implement file tools
- [ ] list_files
- [ ] read_file
- [ ] write_file
- [ ] edit_file
- [ ] create_folder
- [ ] move_file
- [ ] copy_file
- [ ] delete_file_with_boundary
- [ ] search_files
- [ ] get_file_metadata
- [ ] Add approved folder enforcement
- [ ] Update BUILD_LEDGER.md

### TASK 5.4: Implement command tools
- [ ] run_command
- [ ] run_build
- [ ] run_tests
- [ ] install_package
- [ ] check_installed
- [ ] get_command_log
- [ ] cancel_command
- [ ] Add approved/banned command enforcement
- [ ] Update BUILD_LEDGER.md

### TASK 5.5: Implement Git tools
- [ ] git_status
- [ ] git_diff
- [ ] git_branch
- [ ] git_checkout
- [ ] git_commit
- [ ] git_pull
- [ ] git_push_with_boundary
- [ ] git_create_branch
- [ ] Update BUILD_LEDGER.md

### TASK 5.6: Implement workspace tools
- [ ] create_workspace
- [ ] import_folder_workspace
- [ ] import_repository_workspace
- [ ] import_document_pack_workspace
- [ ] import_live_platform_workspace
- [ ] scan_workspace
- [ ] detect_workspace_type
- [ ] detect_stack
- [ ] detect_commands
- [ ] find_missing_files
- [ ] generate_task_plan
- [ ] update_roadmap
- [ ] update_launch_checklist
- [ ] update_workspace_rules
- [ ] archive_workspace
- [ ] delete_workspace_with_boundary
- [ ] Update BUILD_LEDGER.md

### TASK 5.7: Implement company operation tools
- [ ] create_operating_plan
- [ ] update_operating_plan
- [ ] create_daily_operating_loop
- [ ] run_daily_operating_loop
- [ ] create_weekly_execution_plan
- [ ] update_weekly_execution_plan
- [ ] create_ai_standup
- [ ] update_ai_standup
- [ ] decide_next_best_actions
- [ ] create_kpi_dashboard
- [ ] update_kpi_dashboard
- [ ] create_risk_register
- [ ] update_risk_register
- [ ] create_decision_log
- [ ] update_decision_log
- [ ] create_live_operations_feed_item
- [ ] update_live_operations_feed
- [ ] Update BUILD_LEDGER.md

### TASK 5.8: Implement memory tools
- [ ] memory_add
- [ ] memory_search
- [ ] memory_update
- [ ] memory_delete
- [ ] memory_link_to_workspace
- [ ] memory_link_to_task
- [ ] Update BUILD_LEDGER.md

### TASK 5.9: Implement experience tools
- [ ] create_experience_record
- [ ] summarise_experience
- [ ] extract_lesson
- [ ] link_experience_to_workspace
- [ ] link_experience_to_task
- [ ] list_experience_records
- [ ] Update BUILD_LEDGER.md

### TASK 5.10: Implement self-evolution tools
- [ ] propose_rule_improvement
- [ ] propose_runbook_improvement
- [ ] propose_agent_instruction_update
- [ ] propose_tool_selection_update
- [ ] propose_operating_plan_update
- [ ] propose_swarm_strategy_update
- [ ] create_self_evolution_record
- [ ] verify_self_evolution_change
- [ ] approve_safe_self_evolution_change
- [ ] reject_self_evolution_change
- [ ] list_self_evolution_history
- [ ] rollback_self_evolution_change
- [ ] Update BUILD_LEDGER.md

### TASK 5.11: Implement swarm tools
- [ ] spawn_sub_agent
- [ ] assign_sub_agent_task
- [ ] check_sub_agent_status
- [ ] collect_sub_agent_output
- [ ] dissolve_sub_agent
- [ ] list_active_sub_agents
- [ ] set_max_sub_agent_limit
- [ ] report_swarm_activity
- [ ] calculate_swarm_token_cost
- [ ] pause_swarm
- [ ] resume_swarm
- [ ] cancel_swarm_with_boundary
- [ ] attach_sub_agent_log_to_parent_task
- [ ] Update BUILD_LEDGER.md

### TASK 5.12: Implement asset tools
- [ ] web_search
- [ ] fetch_url
- [ ] download_asset
- [ ] check_licence
- [ ] save_source_record
- [ ] generate_asset_manifest
- [ ] update_asset_licence_file
- [ ] Add licence recording
- [ ] Update BUILD_LEDGER.md

### TASK 5.13: Implement support tools
- [ ] read_support_messages
- [ ] categorise_ticket
- [ ] draft_reply
- [ ] send_standard_reply_with_rules
- [ ] create_ticket
- [ ] update_faq
- [ ] summarise_feedback
- [ ] Build adapter interface
- [ ] Build local ticket inbox
- [ ] Update BUILD_LEDGER.md

### TASK 5.14: Implement marketing tools
- [ ] create_campaign
- [ ] create_post
- [ ] create_email_sequence
- [ ] create_landing_copy
- [ ] create_app_store_copy
- [ ] create_press_release
- [ ] create_video_script
- [ ] Update BUILD_LEDGER.md

### TASK 5.15: Implement content tools
- [ ] create_technical_blog
- [ ] create_tutorial
- [ ] create_changelog
- [ ] create_release_notes
- [ ] create_developer_guide
- [ ] create_api_example
- [ ] create_help_article
- [ ] update_knowledge_base
- [ ] create_comparison_article
- [ ] create_implementation_guide
- [ ] Update BUILD_LEDGER.md

### TASK 5.16: Implement onboarding tools
- [ ] create_onboarding_flow
- [ ] create_product_tour
- [ ] create_setup_checklist
- [ ] create_welcome_email
- [ ] create_activation_email
- [ ] analyse_activation_friction
- [ ] update_onboarding_copy
- [ ] create_empty_state_copy
- [ ] create_first_run_experience
- [ ] Update BUILD_LEDGER.md

### TASK 5.17: Implement community tools
- [ ] read_community_messages
- [ ] draft_community_reply
- [ ] moderate_community_item_with_rules
- [ ] summarise_community_feedback
- [ ] create_community_update
- [ ] create_github_discussion_reply
- [ ] create_discord_announcement
- [ ] create_forum_reply
- [ ] create_developer_relations_update
- [ ] Update BUILD_LEDGER.md

### TASK 5.18: Implement partnership tools
- [ ] create_partner_shortlist
- [ ] create_partner_outreach
- [ ] create_partner_follow_up
- [ ] create_integration_proposal
- [ ] create_reseller_plan
- [ ] create_affiliate_plan
- [ ] update_partner_pipeline
- [ ] create_partner_meeting_brief
- [ ] create_partnership_summary
- [ ] create_api_partnership_plan
- [ ] Update BUILD_LEDGER.md

### TASK 5.19: Implement sales tools
- [ ] create_sales_script
- [ ] create_sales_sequence
- [ ] create_follow_up_sequence
- [ ] update_sales_pipeline
- [ ] create_prospect_brief
- [ ] create_sales_summary
- [ ] Update BUILD_LEDGER.md

### TASK 5.20: Implement revenue tools
- [ ] check_revenue_metrics
- [ ] check_conversion_metrics
- [ ] check_subscription_metrics
- [ ] check_failed_payments
- [ ] create_revenue_experiment
- [ ] update_revenue_operations_loop
- [ ] create_offer_draft
- [ ] create_pricing_review
- [ ] Update BUILD_LEDGER.md

### TASK 5.21: Implement monitoring tools
- [ ] check_uptime
- [ ] check_logs
- [ ] check_errors
- [ ] check_crashes
- [ ] check_queue
- [ ] check_database_health
- [ ] check_payment_events
- [ ] check_reviews
- [ ] check_analytics
- [ ] Update BUILD_LEDGER.md

### TASK 5.22: Implement deployment tools
- [ ] deploy_staging
- [ ] deploy_production_with_boundary
- [ ] rollback
- [ ] restart_service
- [ ] check_health
- [ ] check_container_status
- [ ] check_service_logs
- [ ] Production tools require boundary checks
- [ ] Update BUILD_LEDGER.md

### TASK 5.23: Implement infrastructure tools
- [ ] inspect_server
- [ ] check_disk_space
- [ ] check_memory_usage
- [ ] check_cpu_usage
- [ ] check_docker_status
- [ ] check_container_logs
- [ ] restart_container
- [ ] create_backup
- [ ] restore_backup_with_boundary
- [ ] check_ssl_certificate
- [ ] check_domain_dns
- [ ] generate_nginx_config
- [ ] generate_docker_compose
- [ ] check_env_vars
- [ ] validate_cloud_config
- [ ] estimate_infrastructure_cost
- [ ] scale_service_with_budget_boundary
- [ ] Update BUILD_LEDGER.md

### TASK 5.24: Implement voice tools
- [ ] transcribe_voice
- [ ] speak_response
- [ ] listen_push_to_talk
- [ ] wake_word_detect
- [ ] route_voice_command
- [ ] Push-to-talk and text command routing must work
- [ ] Wake word support must be included
- [ ] Update BUILD_LEDGER.md

### TASK 5.25: Implement boundary tools
- [ ] detect_hard_boundary
- [ ] create_boundary_report
- [ ] list_boundary_reports
- [ ] resolve_boundary_report
- [ ] attach_boundary_report_to_task
- [ ] attach_boundary_report_to_workspace
- [ ] Update BUILD_LEDGER.md

---

## PHASE 6: AUTHORITY, SAFETY, APPROVAL, RESUME, RICHARD BOUNDARY OPERATOR

### TASK 6.1: Implement authority policy model
- [ ] Create authority policy model
- [ ] Update BUILD_LEDGER.md

### TASK 6.2: Implement authority checker middleware
- [ ] Every tool call must pass authority checker
- [ ] Test authority checker
- [ ] Update BUILD_LEDGER.md

### TASK 6.3: Implement hard boundary detector
- [ ] Implement all 27 hard boundaries from spec
- [ ] Test boundary detection
- [ ] Update BUILD_LEDGER.md

### TASK 6.4: Implement approved/banned folders
- [ ] Implement approved folders
- [ ] Implement banned folders
- [ ] Test folder enforcement
- [ ] Update BUILD_LEDGER.md

### TASK 6.5: Implement approved/banned commands
- [ ] Implement approved commands
- [ ] Implement banned commands
- [ ] Test command enforcement
- [ ] Update BUILD_LEDGER.md

### TASK 6.6: Implement audit log
- [ ] Audit log for every action
- [ ] Test audit logging
- [ ] Update BUILD_LEDGER.md

### TASK 6.7: Implement boundary report generation
- [ ] Create boundary report system
- [ ] Test boundary reports
- [ ] Update BUILD_LEDGER.md

### TASK 6.8: Implement secret redaction system
- [ ] Create secret redaction
- [ ] Test redaction
- [ ] Update BUILD_LEDGER.md

### TASK 6.9: Implement no-secrets-in-prompts guard
- [ ] Create prompt guard
- [ ] Test guard
- [ ] Update BUILD_LEDGER.md

### TASK 6.10: Implement no-secrets-in-logs guard
- [ ] Create log guard
- [ ] Test guard
- [ ] Update BUILD_LEDGER.md

### TASK 6.11: Implement self-evolution safety guard
- [ ] Create safety guard
- [ ] Test guard
- [ ] Update BUILD_LEDGER.md

### TASK 6.12: Implement sub-agent authority guard
- [ ] Create authority guard
- [ ] Test guard
- [ ] Update BUILD_LEDGER.md

### TASK 6.13: Implement sub-agent workspace scope guard
- [ ] Create scope guard
- [ ] Test guard
- [ ] Update BUILD_LEDGER.md

### TASK 6.14: Implement sub-agent count limit guard
- [ ] Create count limit guard
- [ ] Test guard
- [ ] Update BUILD_LEDGER.md

### TASK 6.15: Implement Hard Boundary Continuation Rule
- [ ] JARV must pause only the blocked action, not whole mission
- [ ] Test continuation
- [ ] Update BUILD_LEDGER.md

### TASK 6.16: Implement approval window system
- [ ] Create approval window system
- [ ] Test approval windows
- [ ] Update BUILD_LEDGER.md

### TASK 6.17: Implement checkpoint resume system
- [ ] Create checkpoint system
- [ ] Test checkpoint resume
- [ ] Update BUILD_LEDGER.md

### TASK 6.18: Implement safe parallel continuation
- [ ] Create safe continuation
- [ ] Test parallel continuation
- [ ] Update BUILD_LEDGER.md

### TASK 6.19: Implement Richard Boundary Operator workflow
- [ ] JARV asks Richard only for required boundary input
- [ ] JARV resumes after Richard clears gate
- [ ] Test workflow
- [ ] Update BUILD_LEDGER.md

---

## PHASE 7: MEMORY SYSTEM

### TASK 7.1: Enable pgvector
- [ ] Enable pgvector extension
- [ ] Create embedding interface
- [ ] Update BUILD_LEDGER.md

### TASK 7.2: Implement all 23 memory types
- [ ] Global Memory
- [ ] Workspace Memory
- [ ] Company Operating Memory
- [ ] Task Memory
- [ ] Incident Memory
- [ ] Asset Memory
- [ ] Customer Memory
- [ ] Business Memory
- [ ] Revenue Memory
- [ ] Infrastructure Memory
- [ ] Content Memory
- [ ] Onboarding Memory
- [ ] Community Memory
- [ ] Partnership Memory
- [ ] Sales Memory
- [ ] Decision Memory
- [ ] Boundary Memory
- [ ] Experience Memory
- [ ] Self-Evolution Memory
- [ ] Swarm Memory
- [ ] Approval Memory
- [ ] Checkpoint Memory
- [ ] Richard Boundary Operator Memory
- [ ] Update BUILD_LEDGER.md

### TASK 7.3: Implement memory operations
- [ ] Add
- [ ] Search
- [ ] Update
- [ ] Delete
- [ ] Link to workspace
- [ ] Link to task
- [ ] Timestamp
- [ ] Confidence score
- [ ] Source/action reference
- [ ] Version reference
- [ ] Parent agent reference
- [ ] Sub-agent reference
- [ ] Approval reference
- [ ] Checkpoint reference
- [ ] Richard boundary input reference
- [ ] Test all memory operations
- [ ] Update BUILD_LEDGER.md

---

## PHASE 8: DYNAMIC WORKSPACES

### TASK 8.1: Build workspace registry
- [ ] Create workspace registry
- [ ] Update BUILD_LEDGER.md

### TASK 8.2: Build workspace creation flow
- [ ] Create workspace creation workflow
- [ ] Update BUILD_LEDGER.md

### TASK 8.3: Build folder import flow
- [ ] Create folder import
- [ ] Update BUILD_LEDGER.md

### TASK 8.4: Build repository import flow
- [ ] Create repository import
- [ ] Update BUILD_LEDGER.md

### TASK 8.5: Build document pack import flow
- [ ] Create document pack import
- [ ] Update BUILD_LEDGER.md

### TASK 8.6: Build live platform import flow
- [ ] Create live platform import
- [ ] Update BUILD_LEDGER.md

### TASK 8.7: Build stack detection
- [ ] Detect Next.js, React, Vue, Angular
- [ ] Detect Python, FastAPI, Django, Flask
- [ ] Detect Node.js, Express
- [ ] Detect mobile frameworks
- [ ] Update BUILD_LEDGER.md

### TASK 8.8: Build command detection
- [ ] Detect build commands
- [ ] Detect test commands
- [ ] Detect run commands
- [ ] Detect deploy commands
- [ ] Update BUILD_LEDGER.md

### TASK 8.9: Build workspace memory namespace
- [ ] Create memory namespace per workspace
- [ ] Update BUILD_LEDGER.md

### TASK 8.10: Build workspace rule engine
- [ ] Create workspace rules
- [ ] Update BUILD_LEDGER.md

### TASK 8.11: Build workspace launch checklist generator
- [ ] Create launch checklist generator
- [ ] Update BUILD_LEDGER.md

### TASK 8.12: Build workspace runbook generator
- [ ] Create runbook generator
- [ ] Update BUILD_LEDGER.md

### TASK 8.13: Build workspace operating plan generator
- [ ] Create operating plan generator
- [ ] Update BUILD_LEDGER.md

### TASK 8.14: Build workspace self-evolution rules
- [ ] Create self-evolution rules per workspace
- [ ] Update BUILD_LEDGER.md

### TASK 8.15: Build workspace swarm rules
- [ ] Create swarm rules per workspace
- [ ] Update BUILD_LEDGER.md

### TASK 8.16: Create optional editable seed workspaces
- [ ] Create seed workspaces
- [ ] Ensure they are not fixed modes
- [ ] Update BUILD_LEDGER.md

### TASK 8.17: Build workspace dashboard backend endpoints
- [ ] Create workspace endpoints
- [ ] Test endpoints
- [ ] Update BUILD_LEDGER.md

---

## PHASE 9: AUTONOMOUS COMPANY OPERATING LAYER

### TASK 9.1: Implement Operating Plan
- [ ] Create operating plan creation
- [ ] Create operating plan update
- [ ] Update BUILD_LEDGER.md

### TASK 9.2: Implement Daily Operating Loop
- [ ] Create daily loop creation
- [ ] Create daily loop runner
- [ ] Update BUILD_LEDGER.md

### TASK 9.3: Implement Weekly Execution Plan
- [ ] Create weekly plan creation
- [ ] Create weekly plan update
- [ ] Update BUILD_LEDGER.md

### TASK 9.4: Implement AI Standup generator
- [ ] Create AI standup generator
- [ ] Update BUILD_LEDGER.md

### TASK 9.5: Implement KPI dashboard backend
- [ ] Create KPI tracking
- [ ] Update BUILD_LEDGER.md

### TASK 9.6: Implement Revenue Operations Loop
- [ ] Create revenue operations loop
- [ ] Update BUILD_LEDGER.md

### TASK 9.7: Implement Risk Register
- [ ] Create risk register
- [ ] Update BUILD_LEDGER.md

### TASK 9.8: Implement Decision Log
- [ ] Create decision log
- [ ] Update BUILD_LEDGER.md

### TASK 9.9: Implement Live Operations Feed
- [ ] Create live operations feed
- [ ] Update BUILD_LEDGER.md

### TASK 9.10: Implement Next Best Action engine
- [ ] Create next best action engine
- [ ] Update BUILD_LEDGER.md

### TASK 9.11: Implement multi-workspace operating queue
- [ ] Create multi-workspace queue
- [ ] Update BUILD_LEDGER.md

### TASK 9.12: Build Company Operations dashboard backend
- [ ] Create company operations endpoints
- [ ] Test endpoints
- [ ] Update BUILD_LEDGER.md

---

## PHASE 10: SELF-EVOLUTION LAYER

### TASK 10.1: Implement Experience Record creation
- [ ] Create experience record system
- [ ] Update BUILD_LEDGER.md

### TASK 10.2: Implement experience summarisation
- [ ] Create summarisation
- [ ] Update BUILD_LEDGER.md

### TASK 10.3: Implement lesson extraction
- [ ] Create lesson extraction
- [ ] Update BUILD_LEDGER.md

### TASK 10.4: Implement rule improvement proposal
- [ ] Create rule improvement
- [ ] Update BUILD_LEDGER.md

### TASK 10.5: Implement runbook improvement proposal
- [ ] Create runbook improvement
- [ ] Update BUILD_LEDGER.md

### TASK 10.6: Implement agent instruction improvement
- [ ] Create agent instruction improvement
- [ ] Update BUILD_LEDGER.md

### TASK 10.7: Implement tool selection improvement
- [ ] Create tool selection improvement
- [ ] Update BUILD_LEDGER.md

### TASK 10.8: Implement swarm strategy improvement
- [ ] Create swarm strategy improvement
- [ ] Update BUILD_LEDGER.md

### TASK 10.9: Implement operating plan improvement
- [ ] Create operating plan improvement
- [ ] Update BUILD_LEDGER.md

### TASK 10.10: Implement self-evolution verification
- [ ] Create verification workflow
- [ ] Update BUILD_LEDGER.md

### TASK 10.11: Implement safe improvement approval
- [ ] Create approval workflow
- [ ] Update BUILD_LEDGER.md

### TASK 10.12: Implement unsafe improvement rejection
- [ ] Create rejection workflow
- [ ] Update BUILD_LEDGER.md

### TASK 10.13: Implement versioning system
- [ ] Create versioning
- [ ] Update BUILD_LEDGER.md

### TASK 10.14: Implement rollback self-evolution
- [ ] Create rollback workflow
- [ ] Update BUILD_LEDGER.md

### TASK 10.15: Build Self-Evolution dashboard backend
- [ ] Create self-evolution endpoints
- [ ] Test endpoints
- [ ] Update BUILD_LEDGER.md

---

## PHASE 11: SWARM SYSTEM

### TASK 11.1: Implement Swarm Manager Agent
- [ ] Create Swarm Manager Agent
- [ ] Update BUILD_LEDGER.md

### TASK 11.2: Implement SwarmRun workflow
- [ ] Create SwarmRun workflow
- [ ] Update BUILD_LEDGER.md

### TASK 11.3: Implement SubAgent workflow
- [ ] Create SubAgent workflow
- [ ] Update BUILD_LEDGER.md

### TASK 11.4: Implement SubAgentTask workflow
- [ ] Create SubAgentTask workflow
- [ ] Update BUILD_LEDGER.md

### TASK 11.5: Implement SubAgentLog workflow
- [ ] Create SubAgentLog workflow
- [ ] Update BUILD_LEDGER.md

### TASK 11.6: Implement SwarmCostRecord workflow
- [ ] Create cost tracking
- [ ] Update BUILD_LEDGER.md

### TASK 11.7: Implement SwarmLimitPolicy workflow
- [ ] Create limit policy
- [ ] Update BUILD_LEDGER.md

### TASK 11.8: Implement spawn_sub_agent
- [ ] Create spawn tool
- [ ] Update BUILD_LEDGER.md

### TASK 11.9: Implement assign_sub_agent_task
- [ ] Create assign tool
- [ ] Update BUILD_LEDGER.md

### TASK 11.10: Implement check_sub_agent_status
- [ ] Create status check
- [ ] Update BUILD_LEDGER.md

### TASK 11.11: Implement collect_sub_agent_output
- [ ] Create output collection
- [ ] Update BUILD_LEDGER.md

### TASK 11.12: Implement dissolve_sub_agent
- [ ] Create dissolve tool
- [ ] Update BUILD_LEDGER.md

### TASK 11.13: Implement list_active_sub_agents
- [ ] Create list tool
- [ ] Update BUILD_LEDGER.md

### TASK 11.14: Implement set_max_sub_agent_limit
- [ ] Create limit setter
- [ ] Update BUILD_LEDGER.md

### TASK 11.15: Implement report_swarm_activity
- [ ] Create activity reporter
- [ ] Update BUILD_LEDGER.md

### TASK 11.16: Implement calculate_swarm_token_cost
- [ ] Create cost calculator
- [ ] Update BUILD_LEDGER.md

### TASK 11.17: Implement pause_swarm
- [ ] Create pause tool
- [ ] Update BUILD_LEDGER.md

### TASK 11.18: Implement resume_swarm
- [ ] Create resume tool
- [ ] Update BUILD_LEDGER.md

### TASK 11.19: Implement cancel_swarm_with_boundary
- [ ] Create cancel tool with boundary
- [ ] Update BUILD_LEDGER.md

### TASK 11.20: Implement attach_sub_agent_log_to_parent_task
- [ ] Create log attachment
- [ ] Update BUILD_LEDGER.md

### TASK 11.21: Implement sub-agent timeout handling
- [ ] Create timeout handling
- [ ] Update BUILD_LEDGER.md

### TASK 11.22: Implement Swarm dashboard backend
- [ ] Create swarm endpoints
- [ ] Test endpoints
- [ ] Update BUILD_LEDGER.md

### TASK 11.23: Implement Swarm tests
- [ ] Test swarm spawning
- [ ] Test sub-agent authority
- [ ] Test sub-agent scope
- [ ] Test dissolve
- [ ] Test timeout
- [ ] Update BUILD_LEDGER.md

---

## PHASE 12: LOCAL RUNNER

### TASK 12.1: Build local runner Python service
- [ ] Create local runner service
- [ ] Update BUILD_LEDGER.md

### TASK 12.2: Add secure token auth
- [ ] Create token auth between backend and local runner
- [ ] Update BUILD_LEDGER.md

### TASK 12.3: Add file execution endpoints
- [ ] Create file execution
- [ ] Update BUILD_LEDGER.md

### TASK 12.4: Add command execution endpoints
- [ ] Create command execution
- [ ] Update BUILD_LEDGER.md

### TASK 12.5: Add log streaming
- [ ] Create log streaming
- [ ] Update BUILD_LEDGER.md

### TASK 12.6: Add task cancellation
- [ ] Create task cancellation
- [ ] Update BUILD_LEDGER.md

### TASK 12.7: Add timeouts
- [ ] Create timeout handling
- [ ] Update BUILD_LEDGER.md

### TASK 12.8: Add local audit log
- [ ] Create local audit log
- [ ] Update BUILD_LEDGER.md

### TASK 12.9: Add local runner installer/start script
- [ ] Create installer script
- [ ] Create start script
- [ ] Update BUILD_LEDGER.md

### TASK 12.10: Test local runner
- [ ] Test scan folder
- [ ] Test read file
- [ ] Test write file
- [ ] Test run safe command
- [ ] Test return logs
- [ ] Update BUILD_LEDGER.md

---

## PHASE 13: SPECIALIST AGENTS

(Each agent must connect to: Orchestrator, Agent registry, Tool registry, Memory system, Authority system, Audit log, Live Operations Feed where relevant)

### TASK 13.1: Implement Company Operator Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.2: Implement Workspace Manager Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.3: Implement Coding Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.4: Implement Debugging Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.5: Implement Verifier Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.6: Implement QA Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.7: Implement DevOps / Launch Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.8: Implement Documentation Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.9: Implement Research Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.10: Implement Memory Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.11: Implement Marketing Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.12: Implement Growth Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.13: Implement Customer Support Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.14: Implement Business Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.15: Implement Finance / Metrics Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.16: Implement Creation Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.17: Implement Monitoring Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.18: Implement Self-Healing Operations Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.19: Implement Rollback Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.20: Implement Security Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.21: Implement Legal / Compliance Drafting Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.22: Implement Sales Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.23: Implement Analytics Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.24: Implement Infrastructure Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.25: Implement Onboarding Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.26: Implement Community Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.27: Implement Partnerships / BD Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.28: Implement Content Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.29: Implement Self-Evolution Agent
- [ ] Full implementation with all connections
- [ ] Update BUILD_LEDGER.md

### TASK 13.30: Integration-test Orchestrator with all 31 agents
- [ ] Test all agent integrations
- [ ] Update BUILD_LEDGER.md

---

## PHASE 14: CODING DEBUG BUILD LOOP

### TASK 14.1: Implement workspace scan workflow
- [ ] Create scan workflow
- [ ] Update BUILD_LEDGER.md

### TASK 14.2: Implement missing file detection
- [ ] Create detection workflow
- [ ] Update BUILD_LEDGER.md

### TASK 14.3: Implement code edit workflow
- [ ] Create edit workflow
- [ ] Update BUILD_LEDGER.md

### TASK 14.4: Implement build run workflow
- [ ] Create build workflow
- [ ] Update BUILD_LEDGER.md

### TASK 14.5: Implement error diagnosis workflow
- [ ] Create diagnosis workflow
- [ ] Update BUILD_LEDGER.md

### TASK 14.6: Implement fix and retry workflow
- [ ] Create fix and retry workflow
- [ ] Update BUILD_LEDGER.md

### TASK 14.7: Implement test run workflow
- [ ] Create test workflow
- [ ] Update BUILD_LEDGER.md

### TASK 14.8: Implement verifier approval workflow
- [ ] Create verification workflow
- [ ] Update BUILD_LEDGER.md

### TASK 14.9: Implement final report workflow
- [ ] Create report workflow
- [ ] Update BUILD_LEDGER.md

---

## PHASE 15: CREATION ASSET SYSTEM

### TASK 15.1: Implement asset request workflow
- [ ] Create asset request
- [ ] Update BUILD_LEDGER.md

### TASK 15.2: Implement approved source adapters
- [ ] Pixabay adapter
- [ ] Pexels adapter
- [ ] Unsplash adapter
- [ ] Freesound adapter
- [ ] OpenGameArt adapter
- [ ] Google Fonts adapter
- [ ] Fontshare adapter
- [ ] Lucide Icons adapter
- [ ] Heroicons adapter
- [ ] SVG Repo adapter
- [ ] LottieFiles adapter
- [ ] Update BUILD_LEDGER.md

### TASK 15.3: Implement licence checking
- [ ] Create licence checker
- [ ] Update BUILD_LEDGER.md

### TASK 15.4: Implement asset download and rename
- [ ] Create download workflow
- [ ] Update BUILD_LEDGER.md

### TASK 15.5: Implement asset placement
- [ ] Create placement workflow
- [ ] Update BUILD_LEDGER.md

### TASK 15.6: Implement ASSET_LICENCES.md generation
- [ ] Create licence file generator
- [ ] Update BUILD_LEDGER.md

### TASK 15.7: Implement asset dashboard backend
- [ ] Create asset endpoints
- [ ] Test endpoints
- [ ] Update BUILD_LEDGER.md

---

## PHASE 16: CUSTOMER SUPPORT SYSTEM

### TASK 16.1: Create support inbox adapter interface
- [ ] Create adapter interface
- [ ] Update BUILD_LEDGER.md

### TASK 16.2: Create local ticket inbox
- [ ] Create local inbox
- [ ] Update BUILD_LEDGER.md

### TASK 16.3: Create ticket categorisation
- [ ] Create categorisation
- [ ] Update BUILD_LEDGER.md

### TASK 16.4: Create reply drafting
- [ ] Create reply drafter
- [ ] Update BUILD_LEDGER.md

### TASK 16.5: Create standard reply rules
- [ ] Create reply rules
- [ ] Update BUILD_LEDGER.md

### TASK 16.6: Create bug escalation
- [ ] Create escalation to Debugging Agent
- [ ] Update BUILD_LEDGER.md

### TASK 16.7: Create FAQ update workflow
- [ ] Create FAQ updater
- [ ] Update BUILD_LEDGER.md

### TASK 16.8: Create support memory workflow
- [ ] Create support memory
- [ ] Update BUILD_LEDGER.md

---

## PHASE 17: MARKETING, GROWTH, BUSINESS, SALES, FINANCE, REVENUE

### TASK 17.1: Create marketing campaign workflow
- [ ] Create campaign workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.2: Create founder post workflow
- [ ] Create founder post workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.3: Create landing page copy workflow
- [ ] Create landing page workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.4: Create app store copy workflow
- [ ] Create app store workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.5: Create email outreach workflow
- [ ] Create email workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.6: Create business model workflow
- [ ] Create business model workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.7: Create pricing workflow
- [ ] Create pricing workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.8: Create investor/partner strategy workflow
- [ ] Create strategy workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.9: Create KPI/metrics workflow
- [ ] Create metrics workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.10: Create sales workflow
- [ ] Create sales workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.11: Create revenue operations workflow
- [ ] Create revenue operations workflow
- [ ] Update BUILD_LEDGER.md

### TASK 17.12: Create growth experiment workflow
- [ ] Create growth workflow
- [ ] Update BUILD_LEDGER.md

---

## PHASE 18: CONTENT, ONBOARDING, COMMUNITY, PARTNERSHIPS

### TASK 18.1: Create technical blog workflow
- [ ] Create blog workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.2: Create tutorial workflow
- [ ] Create tutorial workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.3: Create changelog workflow
- [ ] Create changelog workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.4: Create release notes workflow
- [ ] Create release notes workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.5: Create developer guide workflow
- [ ] Create dev guide workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.6: Create API example workflow
- [ ] Create API example workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.7: Create help article workflow
- [ ] Create help article workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.8: Create knowledge base workflow
- [ ] Create knowledge base workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.9: Create onboarding flow workflow
- [ ] Create onboarding workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.10: Create product tour workflow
- [ ] Create product tour workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.11: Create setup checklist workflow
- [ ] Create setup checklist workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.12: Create welcome/activation email workflow
- [ ] Create email workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.13: Create community message workflow
- [ ] Create community message workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.14: Create community moderation workflow
- [ ] Create moderation workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.15: Create GitHub discussion workflow
- [ ] Create GitHub workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.16: Create Discord/community announcement workflow
- [ ] Create announcement workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.17: Create partner shortlist workflow
- [ ] Create shortlist workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.18: Create partner outreach workflow
- [ ] Create outreach workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.19: Create partner follow-up workflow
- [ ] Create follow-up workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.20: Create integration proposal workflow
- [ ] Create integration workflow
- [ ] Update BUILD_LEDGER.md

### TASK 18.21: Create partner pipeline workflow
- [ ] Create pipeline workflow
- [ ] Update BUILD_LEDGER.md

---

## PHASE 19: INFRASTRUCTURE AND CLOUD OPERATIONS

### TASK 19.1: Implement server inspection tools
- [ ] Create server tools
- [ ] Update BUILD_LEDGER.md

### TASK 19.2: Implement Docker tools
- [ ] Create Docker tools
- [ ] Update BUILD_LEDGER.md

### TASK 19.3: Implement Nginx config generator
- [ ] Create Nginx generator
- [ ] Update BUILD_LEDGER.md

### TASK 19.4: Implement SSL checks
- [ ] Create SSL checker
- [ ] Update BUILD_LEDGER.md

### TASK 19.5: Implement DNS checks
- [ ] Create DNS checker
- [ ] Update BUILD_LEDGER.md

### TASK 19.6: Implement backup workflow
- [ ] Create backup workflow
- [ ] Update BUILD_LEDGER.md

### TASK 19.7: Implement restore workflow with boundary checks
- [ ] Create restore workflow with boundaries
- [ ] Update BUILD_LEDGER.md

### TASK 19.8: Implement environment validation
- [ ] Create env validator
- [ ] Update BUILD_LEDGER.md

### TASK 19.9: Implement infrastructure cost estimation
- [ ] Create cost estimator
- [ ] Update BUILD_LEDGER.md

### TASK 19.10: Implement scaling rules with budget boundary
- [ ] Create scaling rules
- [ ] Update BUILD_LEDGER.md

### TASK 19.11: Implement infrastructure dashboard backend
- [ ] Create infrastructure endpoints
- [ ] Test endpoints
- [ ] Update BUILD_LEDGER.md

### TASK 19.12: Implement infrastructure memory workflow
- [ ] Create infrastructure memory
- [ ] Update BUILD_LEDGER.md

---

## PHASE 20: SELF-HEALING

### TASK 20.1: Create monitoring service
- [ ] Create monitoring service
- [ ] Update BUILD_LEDGER.md

### TASK 20.2: Create health check monitors
- [ ] Create health monitors
- [ ] Update BUILD_LEDGER.md

### TASK 20.3: Create log/error monitor adapters
- [ ] Create log monitors
- [ ] Update BUILD_LEDGER.md

### TASK 20.4: Create runbook model
- [ ] Create runbook model
- [ ] Update BUILD_LEDGER.md

### TASK 20.5: Create website down runbook
- [ ] Create website down runbook
- [ ] Update BUILD_LEDGER.md

### TASK 20.6: Create API error spike runbook
- [ ] Create API error runbook
- [ ] Update BUILD_LEDGER.md

### TASK 20.7: Create queue stuck runbook
- [ ] Create queue stuck runbook
- [ ] Update BUILD_LEDGER.md

### TASK 20.8: Create payment webhook runbook
- [ ] Create payment webhook runbook
- [ ] Update BUILD_LEDGER.md

### TASK 20.9: Create bug reports increasing runbook
- [ ] Create bug reports runbook
- [ ] Update BUILD_LEDGER.md

### TASK 20.10: Create server pressure runbook
- [ ] Create server pressure runbook
- [ ] Update BUILD_LEDGER.md

### TASK 20.11: Create SSL/domain runbook
- [ ] Create SSL/domain runbook
- [ ] Update BUILD_LEDGER.md

### TASK 20.12: Create self-healing execution workflow
- [ ] Create execution workflow
- [ ] Update BUILD_LEDGER.md

### TASK 20.13: Create rollback workflow
- [ ] Create rollback workflow
- [ ] Update BUILD_LEDGER.md

### TASK 20.14: Create incident memory workflow
- [ ] Create incident memory
- [ ] Update BUILD_LEDGER.md

### TASK 20.15: Create experience record after incident
- [ ] Create incident experience
- [ ] Update BUILD_LEDGER.md

---

## PHASE 21: VOICE COMMAND

### TASK 21.1: Implement push-to-talk UI
- [ ] Create push-to-talk UI
- [ ] Update BUILD_LEDGER.md

### TASK 21.2: Implement STT adapter
- [ ] Create speech-to-text adapter
- [ ] Update BUILD_LEDGER.md

### TASK 21.3: Implement TTS adapter
- [ ] Create text-to-speech adapter
- [ ] Update BUILD_LEDGER.md

### TASK 21.4: Implement wake word support
- [ ] Create wake word detection
- [ ] Update BUILD_LEDGER.md

### TASK 21.5: Route voice command to orchestrator
- [ ] Create voice routing
- [ ] Update BUILD_LEDGER.md

### TASK 21.6: Add spoken status replies
- [ ] Create spoken replies
- [ ] Update BUILD_LEDGER.md

---

## PHASE 22: DASHBOARD

(Build all pages with real backend data)

### TASK 22.1: Build Command Center page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.2: Build Workspaces page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.3: Build Company Operations page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.4: Build AI Standups page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.5: Build Live Operations Feed page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.6: Build Self-Evolution page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.7: Build Swarm page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.8: Build Agents page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.9: Build Tasks page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.10: Build Memory page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.11: Build Experience page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.12: Build Tools page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.13: Build Permissions page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.14: Build Boundary Reports page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.15: Build Approvals page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.16: Build Checkpoints page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.17: Build Richard Boundary Operator page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.18: Build Assets page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.19: Build Support page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.20: Build Marketing page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.21: Build Content page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.22: Build Onboarding page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.23: Build Community page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.24: Build Partnerships page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.25: Build Sales page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.26: Build Business page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.27: Build Revenue Operations page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.28: Build Analytics page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.29: Build Operations page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.30: Build Infrastructure page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

### TASK 22.31: Build Settings page
- [ ] Create page with real data
- [ ] Update BUILD_LEDGER.md

---

## PHASE 23: CLOUD DEPLOYMENT

### TASK 23.1: Create production Dockerfiles
- [ ] Create production Dockerfiles
- [ ] Update BUILD_LEDGER.md

### TASK 23.2: Create production Docker Compose
- [ ] Create production Docker Compose
- [ ] Update BUILD_LEDGER.md

### TASK 23.3: Create Nginx config
- [ ] Create Nginx configuration
- [ ] Update BUILD_LEDGER.md

### TASK 23.4: Create HTTPS setup instructions
- [ ] Create HTTPS instructions
- [ ] Update BUILD_LEDGER.md

### TASK 23.5: Create VPS deployment script
- [ ] Create deployment script
- [ ] Update BUILD_LEDGER.md

### TASK 23.6: Create backup script
- [ ] Create backup script
- [ ] Update BUILD_LEDGER.md

### TASK 23.7: Create restore script
- [ ] Create restore script
- [ ] Update BUILD_LEDGER.md

### TASK 23.8: Create cloud run documentation
- [ ] Create cloud documentation
- [ ] Update BUILD_LEDGER.md

---

## PHASE 24: TESTING

### TASK 24.1: Add backend tests
- [ ] Create backend tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.2: Add frontend build test
- [ ] Create frontend test
- [ ] Update BUILD_LEDGER.md

### TASK 24.3: Add tool registry tests
- [ ] Create tool tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.4: Add authority boundary tests
- [ ] Create authority tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.5: Add boundary report tests
- [ ] Create boundary report tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.6: Add secret redaction tests
- [ ] Create redaction tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.7: Add memory tests
- [ ] Create memory tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.8: Add local runner tests
- [ ] Create local runner tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.9: Add Company Operator workflow test
- [ ] Create company operator test
- [ ] Update BUILD_LEDGER.md

### TASK 24.10: Add Daily Operating Loop test
- [ ] Create daily loop test
- [ ] Update BUILD_LEDGER.md

### TASK 24.11: Add Live Operations Feed test
- [ ] Create live feed test
- [ ] Update BUILD_LEDGER.md

### TASK 24.12: Add Self-Evolution workflow test
- [ ] Create self-evolution test
- [ ] Update BUILD_LEDGER.md

### TASK 24.13: Add Self-Evolution safety test
- [ ] Create safety test
- [ ] Update BUILD_LEDGER.md

### TASK 24.14: Add Self-Evolution rollback test
- [ ] Create rollback test
- [ ] Update BUILD_LEDGER.md

### TASK 24.15: Add Swarm Manager workflow test
- [ ] Create swarm manager test
- [ ] Update BUILD_LEDGER.md

### TASK 24.16: Add sub-agent authority test
- [ ] Create authority test
- [ ] Update BUILD_LEDGER.md

### TASK 24.17: Add sub-agent scope test
- [ ] Create scope test
- [ ] Update BUILD_LEDGER.md

### TASK 24.18: Add sub-agent timeout test
- [ ] Create timeout test
- [ ] Update BUILD_LEDGER.md

### TASK 24.19: Add swarm token cost test
- [ ] Create cost test
- [ ] Update BUILD_LEDGER.md

### TASK 24.20: Add swarm dissolve test
- [ ] Create dissolve test
- [ ] Update BUILD_LEDGER.md

### TASK 24.21: Add approval window test
- [ ] Create approval window test
- [ ] Update BUILD_LEDGER.md

### TASK 24.22: Add checkpoint resume test
- [ ] Create checkpoint test
- [ ] Update BUILD_LEDGER.md

### TASK 24.23: Add safe parallel continuation test
- [ ] Create continuation test
- [ ] Update BUILD_LEDGER.md

### TASK 24.24: Add Richard Boundary Operator workflow test
- [ ] Create boundary operator test
- [ ] Update BUILD_LEDGER.md

### TASK 24.25: Add orchestrator workflow test
- [ ] Create orchestrator test
- [ ] Update BUILD_LEDGER.md

### TASK 24.26: Add agent registry tests
- [ ] Create registry tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.27: Add asset licence tests
- [ ] Create licence tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.28: Add content workflow tests
- [ ] Create content tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.29: Add onboarding workflow tests
- [ ] Create onboarding tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.30: Add community workflow tests
- [ ] Create community tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.31: Add partnership workflow tests
- [ ] Create partnership tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.32: Add revenue workflow tests
- [ ] Create revenue tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.33: Add infrastructure tests
- [ ] Create infrastructure tests
- [ ] Update BUILD_LEDGER.md

### TASK 24.34: Add self-healing runbook tests
- [ ] Create runbook tests
- [ ] Update BUILD_LEDGER.md

---

## PHASE 25: FINAL ACCEPTANCE TEST

### TASK 25.1: Create test workspace
- [ ] Create /test_workspaces/test_launch_workspace
- [ ] Include intentional missing files
- [ ] Include fixable errors
- [ ] Update BUILD_LEDGER.md

### TASK 25.2: Run comprehensive acceptance command
- [ ] Run full acceptance test command through JARV
- [ ] Verify workspace created
- [ ] Verify workspace scanned
- [ ] Verify type detected
- [ ] Verify stack detected
- [ ] Verify operating plan created
- [ ] Verify daily operating loop executed
- [ ] Verify AI standup created
- [ ] Verify next best actions created
- [ ] Verify Swarm Manager Agent runs
- [ ] Verify sub-agent limit respected
- [ ] Verify sub-agents inherit Lead Agent authority
- [ ] Verify sub-agents scoped to workspace
- [ ] Verify sub-agents scoped to task batch
- [ ] Verify sub-agents cannot escalate authority
- [ ] Verify sub-agents cannot access banned folders
- [ ] Verify sub-agents cannot spawn further sub-agents unless configured
- [ ] Verify sub-agent actions logged
- [ ] Verify parent agent reference recorded
- [ ] Verify token cost tracked
- [ ] Verify sub-agent output collected
- [ ] Verify Verifier Agent checks swarm output
- [ ] Verify sub-agents dissolve after completion
- [ ] Verify swarm activity in Live Operations Feed
- [ ] Verify swarm dashboard shows real data
- [ ] Verify missing files identified
- [ ] Verify tasks created
- [ ] Verify code edited
- [ ] Verify build run
- [ ] Verify errors fixed
- [ ] Verify tests run
- [ ] Verify asset sourced if needed
- [ ] Verify asset licence recorded
- [ ] Verify docs updated
- [ ] Verify technical/help content created
- [ ] Verify changelog/release notes drafted
- [ ] Verify onboarding flow created
- [ ] Verify welcome/activation email drafted
- [ ] Verify community launch post drafted
- [ ] Verify support responses drafted
- [ ] Verify partnership target list created
- [ ] Verify partner outreach drafted
- [ ] Verify launch checklist updated
- [ ] Verify revenue operations checked
- [ ] Verify infrastructure readiness checked
- [ ] Verify live operations feed updated
- [ ] Verify experience records created
- [ ] Verify self-evolution improvement proposed
- [ ] Verify self-evolution safety verified
- [ ] Verify unsafe self-evolution blocked if attempted
- [ ] Verify hard boundary creates Boundary Report
- [ ] Verify blocked action pauses only
- [ ] Verify safe parallel work continues
- [ ] Verify Richard Boundary Operator request created
- [ ] Verify approval window recorded
- [ ] Verify checkpoint resume works
- [ ] Verify memory updated
- [ ] Verify final report produced
- [ ] Update BUILD_LEDGER.md

### TASK 25.3: Verify dashboard pages
- [ ] Verify every dashboard page loads
- [ ] Verify every page shows real backend data
- [ ] Update BUILD_LEDGER.md

### TASK 25.4: Verify authority boundaries
- [ ] Verify banned command blocks
- [ ] Verify banned folder blocks
- [ ] Verify unknown download blocks
- [ ] Verify production release boundary blocks
- [ ] Verify hard boundary report created
- [ ] Verify sub-agent escalation blocked
- [ ] Verify sub-agent workspace escape blocked
- [ ] Verify approval checkpoint created
- [ ] Verify Richard boundary operator request created
- [ ] Verify resume from checkpoint works
- [ ] Verify safe parallel work continues
- [ ] Update BUILD_LEDGER.md

### TASK 25.5: Run self-healing test
- [ ] Use simulated down service
- [ ] Verify JARV detects
- [ ] Verify JARV diagnoses
- [ ] Verify JARV fixes
- [ ] Verify JARV tests recovery
- [ ] Verify JARV logs incident
- [ ] Verify experience record created
- [ ] Verify memory updated
- [ ] Update BUILD_LEDGER.md

### TASK 25.6: Run self-evolution safety test
- [ ] Verify JARV proposes safe improvement
- [ ] Verify JARV blocks unsafe improvement
- [ ] Update BUILD_LEDGER.md

### TASK 25.7: Run swarm test
- [ ] Verify JARV spawns scoped sub-agents
- [ ] Verify JARV collects output
- [ ] Verify JARV verifies output
- [ ] Verify JARV tracks token cost
- [ ] Verify JARV dissolves sub-agents
- [ ] Update BUILD_LEDGER.md

### TASK 25.8: Run hard-boundary continuation test
- [ ] Verify JARV pauses blocked action only
- [ ] Verify JARV continues safe work
- [ ] Verify Richard boundary request created
- [ ] Verify approval window recorded
- [ ] Verify resume from checkpoint works
- [ ] Update BUILD_LEDGER.md

### TASK 25.9: Run Richard Boundary Operator test
- [ ] Verify JARV pauses only blocked action
- [ ] Verify JARV explains exactly what Richard must do
- [ ] Verify JARV continues safe work
- [ ] Verify JARV records Richard's input
- [ ] Verify JARV resumes from checkpoint
- [ ] Verify JARV finishes mission
- [ ] Update BUILD_LEDGER.md

### TASK 25.10: Run infrastructure backup/restore test
- [ ] Verify backup workflow works safely
- [ ] Verify restore workflow works safely
- [ ] Update BUILD_LEDGER.md

### TASK 25.11: Run final test suite
- [ ] Run all tests
- [ ] Verify all pass
- [ ] Update BUILD_LEDGER.md

### TASK 25.12: Mark final acceptance status
- [ ] Mark final acceptance in BUILD_LEDGER.md
- [ ] Confirm all completion criteria met
- [ ] Update BUILD_LEDGER.md

---

## COMPLETION CRITERIA

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

**END OF IMPLEMENTATION CHECKLIST**
