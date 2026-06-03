#!/bin/bash
#
# JARV Test Runner
# Runs all test suites with proper configuration
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}JARV Test Suite Runner${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Change to backend directory
cd apps/backend

# Set test database URL
export TEST_DATABASE_URL="sqlite:///./test.db"
export ENVIRONMENT="test"
export SECRET_KEY="test-secret-key-for-testing-only"

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest not installed${NC}"
    echo "Install with: poetry install"
    exit 1
fi

echo -e "${BLUE}Running Backend Tests...${NC}"
echo ""

# Run smoke tests first
echo -e "${YELLOW}1. Running Smoke Tests (Quick Verification)${NC}"
pytest -v -m smoke --tb=short

if [ $? -ne 0 ]; then
    echo -e "${RED}Smoke tests failed! Fix critical issues before continuing.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Smoke tests passed${NC}"
echo ""

# Run unit tests
echo -e "${YELLOW}2. Running Unit Tests${NC}"
pytest -v -m unit --tb=short

if [ $? -ne 0 ]; then
    echo -e "${RED}Unit tests failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Unit tests passed${NC}"
echo ""

# Run API tests
echo -e "${YELLOW}3. Running API Tests${NC}"
pytest -v -m api --tb=short

if [ $? -ne 0 ]; then
    echo -e "${RED}API tests failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ API tests passed${NC}"
echo ""

# Run agent tests
echo -e "${YELLOW}4. Running Agent Tests${NC}"
pytest -v -m agent --tb=short

if [ $? -ne 0 ]; then
    echo -e "${RED}Agent tests failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Agent tests passed${NC}"
echo ""

# Run workflow tests
echo -e "${YELLOW}5. Running Workflow Tests${NC}"
pytest -v -m workflow --tb=short

if [ $? -ne 0 ]; then
    echo -e "${RED}Workflow tests failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Workflow tests passed${NC}"
echo ""

# Run security tests
echo -e "${YELLOW}6. Running Security Tests${NC}"
pytest -v -m security --tb=short

if [ $? -ne 0 ]; then
    echo -e "${RED}Security tests failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Security tests passed${NC}"
echo ""

# Run regression tests
echo -e "${YELLOW}7. Running Regression Tests${NC}"
pytest -v -m regression --tb=short

if [ $? -ne 0 ]; then
    echo -e "${RED}Regression tests failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Regression tests passed${NC}"
echo ""

# Run Docker tests (skip if Docker not available)
echo -e "${YELLOW}8. Running Docker Tests${NC}"
if command -v docker &> /dev/null; then
    pytest -v -m docker --tb=short || echo -e "${YELLOW}Some Docker tests skipped (expected if not in container)${NC}"
    echo -e "${GREEN}✓ Docker tests completed${NC}"
else
    echo -e "${YELLOW}Docker not available, skipping Docker tests${NC}"
fi
echo ""

# Run all tests with coverage
echo -e "${YELLOW}9. Running Full Test Suite with Coverage${NC}"
pytest -v --cov=app --cov-report=term-missing --cov-report=html --cov-report=xml

if [ $? -ne 0 ]; then
    echo -e "${RED}Full test suite failed!${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}All Tests Passed Successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Coverage report generated:"
echo "  - Terminal: (shown above)"
echo "  - HTML: htmlcov/index.html"
echo "  - XML: coverage.xml"
echo ""

# Return to project root
cd ../..

exit 0
