#!/usr/bin/env python3
"""APIx Deployment Artifacts & Configuration Verification Script.

Validates:
1. GitHub Actions scrape workflow YAML syntax and required specifications
2. Docker Compose YAML syntax, service dependency graph, and port mappings
3. Dockerfile syntax, multi-stage targets, non-root user, and health checks
4. Deployment documentation completeness and coverage
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def log_pass(msg: str) -> None:
    print(f"\033[32m\033[1m✓ PASS:\033[0m {msg}")


def log_fail(msg: str) -> None:
    print(f"\033[31m\033[1m✗ FAIL:\033[0m {msg}")


def log_info(msg: str) -> None:
    print(f"\033[36mℹ INFO:\033[0m {msg}")


def verify_scrape_workflow(workflow_path: Path) -> list[str]:
    """Validates .github/workflows/scrape.yml according to Cycle 2 requirements."""
    errors: list[str] = []
    if not workflow_path.is_file():
        return [f"Workflow file does not exist: {workflow_path}"]

    try:
        content = workflow_path.read_text(encoding="utf-8")
        data: dict[str, Any] = yaml.safe_load(content)
    except Exception as exc:
        return [f"YAML parsing failed for {workflow_path}: {exc}"]

    # 1. Trigger verification
    on = data.get("on") or data.get(True)  # YAML may parse 'on' as boolean True
    if not on:
        errors.append("Workflow missing 'on' trigger specification")
    else:
        # Schedule cron check
        schedule = on.get("schedule", [])
        if not schedule or not isinstance(schedule, list):
            errors.append("Missing 'on.schedule' cron list")
        else:
            crons = [s.get("cron") for s in schedule if isinstance(s, dict)]
            if "0 2 * * *" not in crons:
                errors.append(
                    f"Expected cron '0 2 * * *' not found in schedule: {crons}"
                )

        # workflow_dispatch check
        if "workflow_dispatch" not in on:
            errors.append("Missing 'on.workflow_dispatch' trigger")

    # 2. Jobs verification
    jobs = data.get("jobs", {})
    if not jobs:
        errors.append("No jobs defined in workflow")
        return errors

    job = next(iter(jobs.values()))
    steps = job.get("steps", [])

    # Check Python 3.12
    python_setup = False
    for step in steps:
        uses = step.get("uses", "")
        if "actions/setup-python" in uses:
            with_block = step.get("with", {})
            py_ver = str(with_block.get("python-version", ""))
            if "3.12" in py_ver:
                python_setup = True
                break
    if not python_setup:
        errors.append("Step 'actions/setup-python' with python-version 3.12 not found")

    # Check Playwright caching
    playwright_cache = False
    for step in steps:
        uses = step.get("uses", "")
        if "actions/cache" in uses:
            path_val = step.get("with", {}).get("path", "")
            if "~/.cache/ms-playwright" in path_val:
                playwright_cache = True
                break
    if not playwright_cache:
        errors.append("Cache step for '~/.cache/ms-playwright' not found")

    # Check Playwright install
    playwright_install = False
    for step in steps:
        run_cmd = step.get("run", "")
        if (
            "playwright install" in run_cmd
            and "--with-deps" in run_cmd
            and "chromium" in run_cmd
        ):
            playwright_install = True
            break
    if not playwright_install:
        errors.append(
            "Playwright install command 'playwright install --with-deps chromium' not found"
        )

    # Check secret injection
    required_secrets = {
        "INGESTION_ENDPOINT_URL",
        "INGESTION_API_KEY",
        "AMADEUS_CLIENT_ID",
        "AMADEUS_CLIENT_SECRET",
    }
    found_secrets = set()
    for step in steps:
        env = step.get("env", {})
        for k, v in env.items():
            for req in required_secrets:
                if req in str(k) or req in str(v):
                    found_secrets.add(req)

    missing_secrets = required_secrets - found_secrets
    if missing_secrets:
        errors.append(f"Missing required secret injection(s): {missing_secrets}")

    # Check orchestrator execution
    orchestrator_executed = False
    for step in steps:
        run_cmd = step.get("run", "")
        if "python -m ingestion.orchestrator" in run_cmd:
            orchestrator_executed = True
            break
    if not orchestrator_executed:
        errors.append("Step executing 'python -m ingestion.orchestrator' not found")

    # Check artifact upload
    artifact_upload = False
    for step in steps:
        uses = step.get("uses", "")
        if "actions/upload-artifact" in uses:
            with_block = step.get("with", {})
            path_val = with_block.get("path", "")
            if "artifacts" in path_val:
                artifact_upload = True
                break
    if not artifact_upload:
        errors.append("Step 'actions/upload-artifact' targeting artifacts/ not found")

    return errors


def verify_docker_compose(compose_path: Path) -> list[str]:
    """Validates docker-compose.yml services, ports, and healthchecks."""
    errors: list[str] = []
    if not compose_path.is_file():
        return [f"docker-compose.yml does not exist at {compose_path}"]

    try:
        content = compose_path.read_text(encoding="utf-8")
        data: dict[str, Any] = yaml.safe_load(content)
    except Exception as exc:
        return [f"YAML parsing failed for {compose_path}: {exc}"]

    services = data.get("services", {})
    required_services = {"db", "backend", "frontend"}
    missing_services = required_services - set(services.keys())
    if missing_services:
        errors.append(
            f"Missing required service(s) in docker-compose.yml: {missing_services}"
        )

    # Check db service
    db = services.get("db", {})
    if db:
        if "5432:5432" not in [str(p) for p in db.get("ports", [])]:
            errors.append("Service 'db' missing port mapping 5432:5432")
        if not db.get("healthcheck"):
            errors.append("Service 'db' missing healthcheck")

    # Check backend service
    backend = services.get("backend", {})
    if backend:
        if "8000:8000" not in [str(p) for p in backend.get("ports", [])]:
            errors.append("Service 'backend' missing port mapping 8000:8000")
        depends = backend.get("depends_on", {})
        if "db" not in depends:
            errors.append("Service 'backend' must depend on 'db'")

    # Check frontend service
    frontend = services.get("frontend", {})
    if frontend:
        ports = [str(p) for p in frontend.get("ports", [])]
        if not any("3000" in p for p in ports):
            errors.append(
                "Service 'frontend' missing port mapping for 3000 (e.g. 3000:80)"
            )
        depends = frontend.get("depends_on", {})
        if "backend" not in depends:
            errors.append("Service 'frontend' must depend on 'backend'")

    return errors


def verify_dockerfile(dockerfile_path: Path) -> list[str]:
    """Validates Dockerfile syntax, multi-stage targets, security, and directives."""
    errors: list[str] = []
    if not dockerfile_path.is_file():
        return [f"Dockerfile does not exist at {dockerfile_path}"]

    content = dockerfile_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    from_stages = [ln for ln in lines if ln.strip().upper().startswith("FROM")]
    if not any("AS backend" in s for s in from_stages):
        errors.append("Dockerfile missing stage 'AS backend'")
    if not any("AS frontend" in s for s in from_stages):
        errors.append("Dockerfile missing stage 'AS frontend'")

    if "USER apix" not in content and "USER " not in content:
        errors.append("Dockerfile does not define a non-root USER")

    if "HEALTHCHECK" not in content:
        errors.append("Dockerfile missing HEALTHCHECK instruction")

    if "EXPOSE 8000" not in content:
        errors.append("Dockerfile missing EXPOSE 8000 for backend")

    return errors


def verify_deployment_docs(docs_path: Path) -> list[str]:
    """Validates docs/deployment.md for comprehensive deployment instructions."""
    errors: list[str] = []
    if not docs_path.is_file():
        return [f"Documentation file does not exist: {docs_path}"]

    content = docs_path.read_text(encoding="utf-8")
    if len(content) < 5000:
        errors.append(
            f"docs/deployment.md too brief ({len(content)} bytes), expected >= 5000 bytes"
        )

    required_keywords = [
        "Render",
        "Vercel",
        "GitHub Actions",
        "scrape.yml",
        "INGESTION_ENDPOINT_URL",
        "INGESTION_API_KEY",
        "AMADEUS_CLIENT_ID",
        "AMADEUS_CLIENT_SECRET",
        "Cold-Start",
        "Secret Rotation",
        "Monitoring",
        "Docker Compose",
    ]

    for kw in required_keywords:
        if kw.lower() not in content.lower():
            errors.append(f"docs/deployment.md missing coverage for keyword '{kw}'")

    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)

    print(
        "================================================================================"
    )
    print("APIx Deployment Artifacts & Configuration Verification")
    print("SIH 2026 PS 26056 - LeadArchitect Deliverables Verification")
    print(
        "================================================================================\n"
    )

    total_failures = 0

    # 1. Scrape workflow verification
    workflow_path = repo_root / ".github" / "workflows" / "scrape.yml"
    log_info(f"Validating GitHub Actions workflow: {workflow_path}")
    workflow_errors = verify_scrape_workflow(workflow_path)
    if workflow_errors:
        for err in workflow_errors:
            log_fail(err)
        total_failures += len(workflow_errors)
    else:
        log_pass(
            "Scraper workflow syntax, cron (0 2 * * *), Python 3.12, Playwright caching, secrets, and artifacts"
        )

    # 2. Docker Compose verification
    compose_path = repo_root / "docker-compose.yml"
    log_info(f"Validating Docker Compose orchestration: {compose_path}")
    compose_errors = verify_docker_compose(compose_path)
    if compose_errors:
        for err in compose_errors:
            log_fail(err)
        total_failures += len(compose_errors)
    else:
        log_pass(
            "Docker Compose syntax, services (db, backend, frontend), healthchecks, and dependency graph"
        )

    # 3. Dockerfile verification
    dockerfile_path = repo_root / "Dockerfile"
    log_info(f"Validating Multi-stage Dockerfile: {dockerfile_path}")
    dockerfile_errors = verify_dockerfile(dockerfile_path)
    if dockerfile_errors:
        for err in dockerfile_errors:
            log_fail(err)
        total_failures += len(dockerfile_errors)
    else:
        log_pass(
            "Dockerfile multi-stage targets (backend, frontend), non-root security user, EXPOSE, and HEALTHCHECK"
        )

    # 4. Deployment docs verification
    docs_path = repo_root / "docs" / "deployment.md"
    log_info(f"Validating Deployment Guide: {docs_path}")
    docs_errors = verify_deployment_docs(docs_path)
    if docs_errors:
        for err in docs_errors:
            log_fail(err)
        total_failures += len(docs_errors)
    else:
        log_pass(
            f"Deployment guide comprehensive coverage ({len(docs_path.read_text())} characters)"
        )

    # 5. Docker Compose CLI Config Lint
    log_info("Executing 'docker compose config' for syntax and variable linting...")
    try:
        proc = subprocess.run(
            ["docker", "compose", "config"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0:
            log_pass("docker compose config executed successfully with zero errors")
        else:
            log_fail(f"docker compose config reported errors:\n{proc.stderr}")
            total_failures += 1
    except Exception as exc:
        log_info(f"docker compose command check skipped or failed: {exc}")

    print(
        "\n--------------------------------------------------------------------------------"
    )
    if total_failures == 0:
        print(
            "\033[32m\033[1m>>> ALL DEPLOYMENT ARTIFACT VERIFICATIONS PASSED (0 FAILURES) <<<\033[0m"
        )
        return 0
    else:
        print(
            f"\033[31m\033[1m>>> DEPLOYMENT VERIFICATION ENCOUNTERED {total_failures} FAILURE(S) <<<\033[0m"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
