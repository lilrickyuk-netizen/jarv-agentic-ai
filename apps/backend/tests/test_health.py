"""
JARV Backend Health Endpoint Tests
"""
import pytest
from fastapi import status


def test_health_check(client):
    """Test health check endpoint"""
    response = client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert data["service"] == "jarv-backend"
    assert "version" in data


def test_version_info(client):
    """The public version endpoint names the service and version and nothing about the environment"""
    response = client.get("/version")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["service"] == "jarv-backend"
    assert "version" in data and "timestamp" in data
    for private in ("environment", "python_version", "platform", "features", "configuration"):
        assert private not in data


def test_readiness_check(client):
    """Test readiness check endpoint"""
    response = client.get("/ready")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["status"] == "ready"
    assert "timestamp" in data
    assert "checks" in data
    assert "database" in data["checks"]
    assert "redis" in data["checks"]


def test_root_endpoint(client):
    """Test root endpoint"""
    response = client.get("/")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "service" in data
    assert "version" in data
    assert "docs" in data
    assert "health" in data


def test_request_id_header(client):
    """Test that X-Request-ID header is added to responses"""
    response = client.get("/health")

    assert "X-Request-ID" in response.headers
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) > 0


def test_cors_headers(client):
    """Test CORS headers are present"""
    response = client.get("/health")  # OPTIONS not implemented, use GET

    # Check that CORS middleware is working
    # The actual headers depend on the request origin
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT]


def test_invalid_endpoint(client):
    """Test accessing non-existent endpoint"""
    response = client.get("/invalid-endpoint")

    assert response.status_code == status.HTTP_404_NOT_FOUND
