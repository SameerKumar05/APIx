#!/usr/bin/env bash
# ==============================================================================
# APIx Master Verification Test Harness
# SIH 2026 Problem Statement 26056 - Real-time Airfare Price Index for India
#
# Single one-command test harness executing end-to-end verification across:
# 1. Database ORM Models & DGCA Seeding Baseline
# 2. Mathematical Invariants & Quant Statistical Pricing Formulations
# 3. Ingestion Scraper Framework & Synthetic Data Generator
# 4. FastAPI Backend Application Endpoints & Security Auth
# 5. Schema Contract Alignment (Ingestion <-> Database <-> API <-> Quant)
# 6. Master Pytest Suite (Coverage, Models, Contracts, Math)
# 7. Frontend SPA Types, Mock Contracts & TypeScript Build
# 8. Deployment Artifacts & Docker Compose Orchestration Verification
# 9. Data Provenance & Anti-Fabrication Telemetry Corroboration
# ==============================================================================

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Color formatting
BOLD="\033[1m"
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
CYAN="\033[36m"
BLUE="\033[34m"
RESET="\033[0m"

# Print banner
echo -e "${CYAN}${BOLD}"
echo "================================================================================"
echo "          APIx Master Verification & CI/CD Test Harness                         "
echo "  SIH 2026 PS 26056 - Real-time Airfare Price Index for CPI Augmentation        "
echo "================================================================================"
echo -e "${RESET}"

# Locate Python environment
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
    PYTEST_BIN="$REPO_ROOT/.venv/bin/pytest"
elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python"
    PYTEST_BIN="$VIRTUAL_ENV/bin/pytest"
elif [ -x "$REPO_ROOT/../../.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_ROOT/../../.venv/bin/python"
    PYTEST_BIN="$REPO_ROOT/../../.venv/bin/pytest"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
    PYTEST_BIN="$(command -v pytest 2>/dev/null || echo "$PYTHON_BIN -m pytest")"
else
    echo -e "${RED}[ERROR] Python 3 executable not found in .venv or PATH.${RESET}"
    exit 1
fi

echo -e "${BLUE}▶ Python Interpreter: ${BOLD}$("$PYTHON_BIN" --version)${RESET} (${PYTHON_BIN})"
echo -e "${BLUE}▶ Repository Root:    ${BOLD}$REPO_ROOT${RESET}"
echo ""

START_TIME=$(date +%s)
FAILED_STEPS=()
PASSED_STEPS=()

run_step() {
    local step_num="$1"
    local step_name="$2"
    local cmd="$3"

    echo -e "${YELLOW}${BOLD}[STEP $step_num] $step_name...${RESET}"
    echo -e "${CYAN}Executing:${RESET} $cmd"
    
    local step_start
    step_start=$(date +%s)

    (
        cd "$REPO_ROOT" || exit 1
        eval "$cmd"
    )
    local exit_code=$?
    local step_end
    step_end=$(date +%s)
    local step_duration=$((step_end - step_start))

    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}${BOLD}✓ [STEP $step_num PASSED]${RESET} ${step_name} (${step_duration}s)\n"
        PASSED_STEPS+=("$step_name")
    else
        echo -e "${RED}${BOLD}✗ [STEP $step_num FAILED]${RESET} ${step_name} (Exit code: $exit_code, ${step_duration}s)\n"
        FAILED_STEPS+=("$step_name")
    fi
    return $exit_code
}

# ------------------------------------------------------------------------------
# 1. Database ORM Models & DGCA Seeding Baseline
# ------------------------------------------------------------------------------
run_step "1/25" "Database Models & DGCA Seed Invariants" \
    "\"$PYTHON_BIN\" scripts/test_db_models.py"

# ------------------------------------------------------------------------------
# 2. Database Ingestion Repository, Bulk Insert & Retention Pruning
# ------------------------------------------------------------------------------
run_step "2/25" "Ingestion Repository & Automated Retention Pruning" \
    "\"$PYTHON_BIN\" scripts/test_ingestion_repo.py"

# ------------------------------------------------------------------------------
# 3. Mathematical Invariants & Statistical Quant Engine
# ------------------------------------------------------------------------------
run_step "3/25" "Mathematical Invariants & Quant Formulations" \
    "\"$PYTHON_BIN\" scripts/test_math_engine.py"

# ------------------------------------------------------------------------------
# 4. Statistical Daily Index Pipeline & DB Persistence
# ------------------------------------------------------------------------------
run_step "4/25" "Daily Index Pipeline & Anomaly Engine" \
    "\"$PYTHON_BIN\" scripts/test_index_pipeline.py"

# ------------------------------------------------------------------------------
# 5. Ingestion Scraper Framework & Synthetic Data Generator
# ------------------------------------------------------------------------------
run_step "5/25" "Ingestion Scraper Framework & Multi-Window Generator" \
    "\"$PYTHON_BIN\" scripts/test_ingestion_synthetic.py"

# ------------------------------------------------------------------------------
# 6. FastAPI Backend Application Endpoints & Security
# ------------------------------------------------------------------------------
rm -f "$REPO_ROOT/apix.db" "$REPO_ROOT/airfare_index.db" "$REPO_ROOT/test_airfare_index.db"
run_step "6/25" "FastAPI Backend Endpoints & API Authentication" \
    "\"$PYTHON_BIN\" scripts/test_api_endpoints.py"

# ------------------------------------------------------------------------------
# 7. Schema Contract Alignment (Ingestion <-> DB <-> API)
# ------------------------------------------------------------------------------
run_step "7/25" "Schema Contract Alignment Verification" \
    "\"$PYTHON_BIN\" -m pytest tests/test_contracts.py -v"

# ------------------------------------------------------------------------------
# 8. Cycle 2 End-to-End Pipeline Integration Test
# ------------------------------------------------------------------------------
run_step "8/25" "Cycle 2 End-to-End Pipeline Integration Test" \
    "\"$PYTHON_BIN\" -m pytest tests/test_e2e_pipeline.py -v"

# ------------------------------------------------------------------------------
# 9. Cycle 3 Telemetry & Proxy Health DB Persistence
# ------------------------------------------------------------------------------
run_step "9/25" "Cycle 3 Telemetry & Proxy Health DB Persistence" \
    "\"$PYTHON_BIN\" scripts/test_telemetry_db.py"

# ------------------------------------------------------------------------------
# 10. Cycle 3 Real-time Streaming Dedup & Cross-Platform Arbitrage Engine
# ------------------------------------------------------------------------------
run_step "10/25" "Cycle 3 Streaming Dedup & Cross-Platform Arbitrage Engine" \
    "\"$PYTHON_BIN\" scripts/test_streaming_dedup.py"

# ------------------------------------------------------------------------------
# 11. Cycle 3 Ingestion Scheduler & Proxy Pool Architecture
# ------------------------------------------------------------------------------
run_step "11/25" "Cycle 3 Ingestion Scheduler & Proxy Pool Architecture" \
    "\"$PYTHON_BIN\" scripts/test_scheduler_and_proxies.py"

# ------------------------------------------------------------------------------
# 12. Cycle 3 Multi-Source Ingestion & Orchestration
# ------------------------------------------------------------------------------
run_step "12/25" "Cycle 3 Multi-Source Ingestion & Orchestration" \
    "\"$PYTHON_BIN\" scripts/test_ingestion_multi_source.py"

# ------------------------------------------------------------------------------
# 13. Cycle 3 Backend API: Telemetry, Streaming & Arbitrage Endpoints
# ------------------------------------------------------------------------------
run_step "13/25" "Cycle 3 Backend API: Telemetry, Streaming & Arbitrage" \
    "\"$PYTHON_BIN\" scripts/test_api_cycle3.py"

# ------------------------------------------------------------------------------
# 14. Cycle 3 Integration Pytest Suite (Telemetry & Streaming Arbitrage)
# ------------------------------------------------------------------------------
run_step "14/25" "Cycle 3 Integration Pytest Suite (Telemetry & Arbitrage)" \
    "\"$PYTHON_BIN\" -m pytest tests/test_cycle3_telemetry.py tests/test_streaming_arbitrage.py -v"

# 15. Cycle 4 Econometric Engine: Paasche, Fisher & Substitution Bias
# ------------------------------------------------------------------------------
run_step "15/25" "Cycle 4 Econometric Engine: Paasche, Fisher & Substitution Bias" \
    "if [ -f \"$REPO_ROOT/scripts/test_econometric_engine.py\" ]; then \"$PYTHON_BIN\" scripts/test_econometric_engine.py; else \"$PYTHON_BIN\" -m pytest tests/test_cycle4_econometrics.py -k 'TestFisherPaascheCalculations or TestSubstitutionBiasInvariants' -v; fi"

# ------------------------------------------------------------------------------
# 16. Cycle 4 Architectural Econometric Specifications & Invariants
# ------------------------------------------------------------------------------
run_step "16/25" "Cycle 4 Econometric Specifications & Invariant Bounds" \
    "if [ -f \"$REPO_ROOT/scripts/test_econometric_specs.py\" ]; then \"$PYTHON_BIN\" scripts/test_econometric_specs.py; else \"$PYTHON_BIN\" -m pytest tests/test_cycle4_econometrics.py -k 'TestSubstitutionBiasInvariants' -v; fi"

# ------------------------------------------------------------------------------
# 17. Cycle 4 Database Persistence: Econometric Indices & Violations
# ------------------------------------------------------------------------------
run_step "17/25" "Cycle 4 Database Persistence: Econometric Indices & Violations" \
    "if [ -f \"$REPO_ROOT/scripts/test_econometrics_db.py\" ]; then \"$PYTHON_BIN\" scripts/test_econometrics_db.py; else \"$PYTHON_BIN\" -m pytest tests/test_cycle4_econometrics.py -k 'TestEconometricDatabaseModels' -v; fi"

# ------------------------------------------------------------------------------
# 18. Cycle 4 Benchmark Loaders: MoSPI CPI Series & DGCA Traffic Weights
# ------------------------------------------------------------------------------
run_step "18/25" "Cycle 4 Benchmark Loaders: MoSPI CPI & DGCA Traffic Weights" \
    "if [ -f \"$REPO_ROOT/scripts/test_benchmark_loaders.py\" ]; then \"$PYTHON_BIN\" scripts/test_benchmark_loaders.py; else \"$PYTHON_BIN\" -m pytest tests/test_cycle4_econometrics.py -k 'TestMospiCpiDivergenceTracking' -v; fi"

# ------------------------------------------------------------------------------
# 19. Cycle 4 Backend API: Econometrics, Divergence & Surveillance Endpoints
# ------------------------------------------------------------------------------
run_step "19/25" "Cycle 4 Backend API: Econometrics, Divergence & Surveillance" \
    "if [ -f \"$REPO_ROOT/scripts/test_api_cycle4.py\" ]; then \"$PYTHON_BIN\" scripts/test_api_cycle4.py; else \"$PYTHON_BIN\" -m pytest tests/test_cycle4_econometrics.py -k 'TestCycle4FastApiEndpoints or TestDgcaRegulatoryViolationSurveillance' -v; fi"

# ------------------------------------------------------------------------------
# 20. Cycle 4 Lead-Time Price Elasticity & Horizon Dynamics
# ------------------------------------------------------------------------------
run_step "20/25" "Cycle 4 Lead-Time Price Elasticity & Horizon Dynamics" \
    "\"$PYTHON_BIN\" -m pytest tests/test_cycle4_econometrics.py -k 'TestLeadTimeElasticityDynamics' -v"

# ------------------------------------------------------------------------------
# 21. Cycle 4 Comprehensive Integration Pytest Suite
# ------------------------------------------------------------------------------
run_step "21/25" "Cycle 4 Comprehensive Integration Pytest Suite" \
    "\"$PYTHON_BIN\" -m pytest tests/test_cycle4_econometrics.py -v"

# ------------------------------------------------------------------------------
# 22. Master Pytest Full Suite (Cycles 1-4)
# ------------------------------------------------------------------------------
run_step "22/25" "Master Pytest Full Test Suite (Cycles 1-4)" \
    "\"$PYTHON_BIN\" -m pytest tests/ -v"

# ------------------------------------------------------------------------------
# 23. Frontend SPA Types & Verification
# ------------------------------------------------------------------------------
if command -v bun >/dev/null 2>&1 && [ -d "$REPO_ROOT/frontend" ]; then
    if [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
        echo -e "${YELLOW}Installing frontend dependencies via bun...${RESET}"
        (cd "$REPO_ROOT/frontend" && bun install)
    fi
    # The verification checks the production build output, so build first. Without
    # this the step passed only on a machine that happened to have a stale dist/.
    run_step "23/25" "Frontend Types, Mock Contracts & Verification" \
        "cd \"$REPO_ROOT/frontend\" && bun run build && bun scripts/verify-mock-data.ts"
elif [ -d "$REPO_ROOT/frontend" ]; then
    echo -e "${YELLOW}[STEP 23/25 SKIPPED] Bun not found; skipping frontend mock data execution.${RESET}\n"
fi

# ------------------------------------------------------------------------------
# 24. Deployment Artifacts & Build Configuration Verification
# ------------------------------------------------------------------------------
run_step "24/25" "Deployment Artifacts & Configuration Verification" \
    "\"$PYTHON_BIN\" scripts/verify_deployment_artifacts.py"

# ------------------------------------------------------------------------------
# 25. Data Provenance & Anti-Fabrication Telemetry Audit
# ------------------------------------------------------------------------------
run_step "25/25" "Data Provenance & Anti-Fabrication Telemetry Audit" \
    "\"$PYTHON_BIN\" -m scripts.audit_provenance apix.db"
# ------------------------------------------------------------------------------
# Final Summary & Exit
# ------------------------------------------------------------------------------
END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))

echo "================================================================================"
echo -e "${BOLD}APIx MASTER VERIFICATION SUMMARY${RESET}"
echo "================================================================================"
echo -e "Total Elapsed Time: ${TOTAL_DURATION}s"
echo -e "Steps Passed: ${GREEN}${BOLD}${#PASSED_STEPS[@]}${RESET}"
echo -e "Steps Failed: ${RED}${BOLD}${#FAILED_STEPS[@]}${RESET}"
echo "--------------------------------------------------------------------------------"

if [ ${#FAILED_STEPS[@]} -eq 0 ]; then
    echo -e "${GREEN}${BOLD}>>> ALL MASTER VERIFICATION STEPS PASSED SUCCESSFULLY! <<<\n${RESET}"
    exit 0
else
    echo -e "${RED}${BOLD}>>> VERIFICATION FAILED ON THE FOLLOWING STEPS: <<<\n${RESET}"
    for failed in "${FAILED_STEPS[@]}"; do
        echo -e "  ${RED}✗ $failed${RESET}"
    done
    echo ""
    exit 1
fi
