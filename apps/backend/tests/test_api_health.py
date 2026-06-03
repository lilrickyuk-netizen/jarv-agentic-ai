"""
Tests for health check endpoint
"""
import pytest
from fastapi.testclient import TestClient


@pytest.mark.api
@pytest.mark.smoke
def test_health_check(client: TestClient):
    """Test health check endpoint returns 200"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@pytest.mark.api
def test_health_check_structure(client: TestClient):
    """Test health check response structure"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()

    # Check required fields
    assert "status" in data
    assert "timestamp" in data
    assert "version" in data

    # Check types
    assert isinstance(data["status"], str)
    assert isinstance(data["timestamp"], str)


@pytest.mark.api
@pytest.mark.smoke
def test_root_endpoint(client: TestClient):
    """Test root endpoint returns welcome message"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data or "name" in data
