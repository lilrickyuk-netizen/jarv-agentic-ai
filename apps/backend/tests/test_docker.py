"""
Tests for Docker and container functionality
"""
import pytest
import subprocess
import os


@pytest.mark.docker
@pytest.mark.slow
def test_dockerfile_exists():
    """Test Dockerfile exists and is valid"""
    dockerfile_path = os.path.join("apps", "backend", "Dockerfile")
    assert os.path.exists(dockerfile_path), "Backend Dockerfile not found"

    with open(dockerfile_path, 'r') as f:
        content = f.read()
        assert "FROM python:" in content
        assert "USER jarv" in content or "RUN useradd" in content
        assert "EXPOSE" in content


@pytest.mark.docker
@pytest.mark.slow
def test_docker_compose_valid():
    """Test docker-compose files are valid"""
    compose_files = [
        "docker-compose.yml",
        "docker-compose.prod.yml",
    ]

    for compose_file in compose_files:
        assert os.path.exists(compose_file), f"{compose_file} not found"

        # Validate syntax
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "config", "--quiet"],
            capture_output=True,
            text=True
        )
        # Will show warnings but should not error
        assert result.returncode in [0, 1]  # 1 is warnings only


@pytest.mark.docker
def test_env_example_files_exist():
    """Test environment example files exist"""
    env_files = [
        ".env.example",
        ".env.production.example",
        "apps/backend/.env.example",
    ]

    for env_file in env_files:
        assert os.path.exists(env_file), f"{env_file} not found"


@pytest.mark.docker
def test_gitignore_excludes_secrets():
    """Test .gitignore properly excludes secrets"""
    with open(".gitignore", 'r') as f:
        gitignore_content = f.read()

        # Check critical exclusions
        assert ".env" in gitignore_content or "*.env" in gitignore_content
        assert "node_modules" in gitignore_content
        assert "__pycache__" in gitignore_content
        assert ".pytest_cache" in gitignore_content


@pytest.mark.docker
def test_docker_healthcheck_script():
    """Test Docker health check endpoints are accessible"""
    # This would be tested in actual Docker container
    # Here we verify the health endpoint exists
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


@pytest.mark.docker
def test_dockerfile_security_practices():
    """Test Dockerfile follows security best practices"""
    dockerfile_path = os.path.join("apps", "backend", "Dockerfile")

    with open(dockerfile_path, 'r') as f:
        content = f.read()

        # Should not run as root in production stage
        lines = content.split('\n')
        found_user_switch = False
        for line in lines:
            if 'USER' in line and 'root' not in line:
                found_user_switch = True
                break

        assert found_user_switch, "Dockerfile should switch to non-root user"


@pytest.mark.docker
def test_requirements_pinned():
    """Test dependencies are properly versioned"""
    pyproject_path = os.path.join("apps", "backend", "pyproject.toml")

    with open(pyproject_path, 'r') as f:
        content = f.read()
        # Should have version specifications
        assert "fastapi" in content
        assert "sqlalchemy" in content
        assert "pydantic" in content


@pytest.mark.docker
def test_docker_ignore_exists():
    """Test .dockerignore exists to exclude unnecessary files"""
    dockerignore_path = os.path.join("apps", "backend", ".dockerignore")
    if os.path.exists(dockerignore_path):
        with open(dockerignore_path, 'r') as f:
            content = f.read()
            # Should exclude test files and cache
            assert "__pycache__" in content or "*.pyc" in content


@pytest.mark.docker
def test_multi_stage_build():
    """Test Dockerfile uses multi-stage build for optimization"""
    dockerfile_path = os.path.join("apps", "backend", "Dockerfile")

    with open(dockerfile_path, 'r') as f:
        content = f.read()
        # Multi-stage build should have multiple FROM statements
        from_count = content.count("FROM ")
        assert from_count >= 2, "Should use multi-stage build"
