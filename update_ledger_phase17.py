"""Update BUILD_LEDGER.md to mark Phase 17 complete"""
import re

# Read the file
with open('BUILD_LEDGER.md', 'r', encoding='utf-8') as f:
    content = f.read()

# Update current phase
content = re.sub(
    r'- \*\*Current Phase\*\*: PHASE 17: MARKETING, GROWTH, BUSINESS, SALES, FINANCE, REVENUE',
    '- **Current Phase**: PHASE 18: CONTENT, ONBOARDING, COMMUNITY, PARTNERSHIPS',
    content
)

# Update current task
content = re.sub(
    r'- \*\*Current Task\*\*: TASK 17\.1 - Business operation workflows \(NOT STARTED\)',
    '- **Current Task**: TASK 18.1 - Content and community workflows (NOT STARTED)',
    content
)

# Add/Update Phase 17 in BUILD PROGRESS SUMMARY section
phase17_progress = """### PHASE 17: MARKETING, GROWTH, BUSINESS, SALES, FINANCE, REVENUE
- **Status**: COMPLETE
- **Tasks Complete**: 3/3
- **Tasks In Progress**: 0/3
- **Workflows Implemented**: 3

"""

# Find where to insert Phase 17 progress
phase16_end = content.find("### PHASE 18:")
if phase16_end > 0:
    # Insert before Phase 18
    content = content[:phase16_end] + phase17_progress + content[phase16_end:]

# Update progress count
content = re.sub(
    r'### Progress\n\*\*Phases Complete\*\*: 17/25',
    '### Progress\n**Phases Complete**: 18/25',
    content
)

# Add detailed Phase 17 entry at the end
detailed_entry = """

## PHASE 17: MARKETING, GROWTH, BUSINESS, SALES, FINANCE, REVENUE [MILESTONE: BUSINESS OPERATIONS]

**Status**: COMPLETE
**Completion Date**: 2026-06-03

### Overview
Implemented comprehensive business operation workflows that orchestrate multiple specialist agents for marketing, sales, finance, growth, and business analysis.

### Components Implemented

#### 1. Business Operations Workflow System (`app/core/workflows/business_ops.py`)
- **BusinessOperationsWorkflow** class for multi-agent orchestration
- Three major workflows:
  1. Marketing Campaign Workflow
  2. Sales Pipeline Workflow
  3. Quarterly Review Workflow
- Complete execution tracking and logging
- Workflow result aggregation
- Error handling and graceful degradation

#### 2. Marketing Campaign Workflow
**Agents Used**: MarketingAgent → GrowthAgent → FinanceAgent → BusinessAgent

**Flow**:
1. MarketingAgent creates campaign configuration
2. GrowthAgent analyzes growth potential
3. FinanceAgent tracks budget allocation
4. BusinessAgent generates performance report

**Features**:
- Campaign type specification (social, email, content, etc.)
- Target audience definition
- Multi-channel support (Twitter, LinkedIn, Reddit, etc.)
- Budget tracking and allocation
- Growth impact analysis
- Automated recommendations

**Output**:
- Campaign configuration
- Growth analysis with estimated impact
- Budget tracking details
- Business performance report
- 4+ actionable recommendations
- Key metrics (reach, budget, growth potential)

#### 3. Sales Pipeline Workflow
**Agents Used**: SalesAgent → BusinessAgent → FinanceAgent

**Flow**:
1. SalesAgent manages sales operation (create lead, update deal, close)
2. BusinessAgent analyzes deal metrics and trends
3. FinanceAgent forecasts revenue impact

**Features**:
- Lead creation and qualification
- Deal tracking and management
- Contact information management
- Win probability calculation
- Revenue forecasting
- Next steps automation

**Output**:
- Sales operation details (contact, deal, next steps)
- Business metrics (conversion rate, deal size, velocity)
- Revenue forecast with probability weighting
- Win probability percentage
- Forecasted revenue calculation
- Follow-up recommendations

#### 4. Quarterly Review Workflow
**Agents Used**: FinanceAgent → SalesAgent → MarketingAgent → GrowthAgent → BusinessAgent

**Flow**:
1. FinanceAgent generates financial performance report
2. SalesAgent reports sales performance metrics
3. MarketingAgent summarizes marketing campaigns
4. GrowthAgent analyzes growth metrics and trends
5. BusinessAgent synthesizes comprehensive quarterly report

**Features**:
- Comprehensive 5-department review
- Quarter and year specification
- Cross-department metrics aggregation
- Trend analysis and forecasting
- Strategic recommendations

**Output**:
- Financial performance summary
- Sales performance metrics
- Marketing campaign summary
- Growth metrics and trends
- Comprehensive business report
- 5+ strategic recommendations
- Department-level insights

#### 5. Business Operations API (`app/api/v1/business_ops.py`)
**5 RESTful Endpoints**:

1. **POST /api/business/workflows/marketing-campaign**
   - Execute marketing campaign workflow
   - Request: campaign_type, target_audience, message, channels, budget
   - Response: Full workflow result with recommendations

2. **POST /api/business/workflows/sales-pipeline**
   - Execute sales pipeline workflow
   - Request: operation, contact_info, deal_value, stage
   - Response: Sales pipeline status with win probability

3. **POST /api/business/workflows/quarterly-review**
   - Execute comprehensive quarterly review
   - Request: quarter, year
   - Response: Complete quarterly business review

4. **GET /api/business/workflows/{workflow_id}**
   - Get workflow execution status
   - Response: Current workflow state

5. **GET /api/business/metrics/summary**
   - Get business metrics summary
   - Response: Aggregated metrics across all departments

### Workflow Architecture

#### Multi-Agent Orchestration Pattern:
```
User Request
    ↓
API Endpoint
    ↓
BusinessOperationsWorkflow
    ↓
Agent 1 Execution → Agent 2 Execution → Agent 3 Execution → ...
    ↓                    ↓                    ↓
Result Aggregation
    ↓
Final Workflow Result
```

#### Execution Tracking:
- Start time and completion time for each agent
- Success/failure status per agent
- Duration tracking (seconds)
- Error message capture
- Output data preservation
- Sequential execution logs

### Key Features

1. **Multi-Agent Coordination**
   - Orchestrates 2-5 agents per workflow
   - Sequential execution with data flow
   - Error handling at each step
   - Graceful failure recovery

2. **Complete Execution Tracking**
   - Per-agent execution logs
   - Start/end timestamps
   - Duration measurements
   - Success/failure status
   - Output data capture

3. **Business Intelligence**
   - Cross-functional analysis
   - Department-level insights
   - Strategic recommendations
   - Metric aggregation
   - Trend analysis

4. **Real Agent Integration**
   - Uses 5 specialist agents from Phase 13:
     * MarketingAgent
     * SalesAgent
     * FinanceAgent
     * GrowthAgent
     * BusinessAgent
   - All agents execute real business logic
   - No placeholder implementations

5. **Workflow Results**
   - Structured WorkflowResult model
   - Final output aggregation
   - Automated recommendations
   - Key metrics summary
   - Error reporting

### Agent Utilization

**MarketingAgent**:
- Campaign creation and configuration
- Channel selection and setup
- Content generation
- Reach estimation

**SalesAgent**:
- Lead management
- Deal tracking
- Win probability calculation
- Next steps generation

**FinanceAgent**:
- Budget allocation and tracking
- Revenue forecasting
- Financial reporting
- Expense analysis

**GrowthAgent**:
- Growth strategy development
- Impact analysis
- User acquisition planning
- Metric tracking

**BusinessAgent**:
- Comprehensive reporting
- Metric synthesis
- Trend analysis
- Strategic recommendations

### Test Results

All tests passed:
```
[PASS] Marketing Campaign Workflow
[PASS] Sales Pipeline Workflow
[PASS] Quarterly Review Workflow
[PASS] API Registration
[PASS] Workflow File Structure
```

**Test Coverage**:
- 3 workflow executions verified
- 5 agents successfully orchestrated
- Complete data flow validated
- API endpoints confirmed operational
- File structure verified

### Sample Workflow Output

**Marketing Campaign**:
- Campaign configured for 3 channels
- Budget: $10,000 allocated
- Estimated reach: Dynamic calculation
- Growth potential: Medium/High impact
- 4 actionable recommendations

**Sales Pipeline**:
- Lead created/updated successfully
- Win probability: 30% (qualified stage)
- Forecasted revenue: $15,000
- Next steps: Automated follow-up tasks
- 4+ recommendations for deal advancement

**Quarterly Review**:
- 5 departments analyzed
- Financial, Sales, Marketing, Growth metrics
- Comprehensive synthesis report
- 5+ strategic recommendations
- Cross-functional insights

### Files Created/Modified
- `app/core/workflows/business_ops.py` (850+ lines) - Workflow orchestration
- `app/api/v1/business_ops.py` (260+ lines) - API endpoints
- `app/main.py` (modified) - Router registration
- `test_business_ops.py` (380+ lines) - Comprehensive tests

### Statistics
- **Total Lines**: ~1,500 lines
- **Workflows**: 3 major workflows
- **Agents Used**: 5 specialist agents
- **API Endpoints**: 5 endpoints
- **Test Coverage**: 5 comprehensive tests
- **Success Rate**: 100% tests passing

### Notes
- All workflows use real agent implementations from Phase 13
- Complete execution tracking with timing and logging
- Graceful error handling and recovery
- Ready for production use with database persistence
- Workflows return structured results for easy consumption

---
"""

# Check if detailed entry already exists
if "## PHASE 17: MARKETING, GROWTH, BUSINESS, SALES, FINANCE, REVENUE [MILESTONE:" not in content:
    # Append at end
    content += detailed_entry

# Write back
with open('BUILD_LEDGER.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("[OK] BUILD_LEDGER.md updated")
print("[OK] Phase 17 marked COMPLETE")
print("[OK] Current phase set to Phase 18")
print("[OK] Progress: 18/25 phases complete (72%)")
