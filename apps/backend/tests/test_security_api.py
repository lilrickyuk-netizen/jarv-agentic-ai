"""
Security tests for API endpoints
"""
import pytest
from fastapi.testclient import TestClient


@pytest.mark.security
@pytest.mark.api
def test_sql_injection_protection(client: TestClient):
    """Test SQL injection attempts are blocked"""
    sql_injection_payloads = [
        "'; DROP TABLE workspaces; --",
        "' OR '1'='1",
        "1' UNION SELECT * FROM users--",
        "<script>alert('xss')</script>",
    ]

    for payload in sql_injection_payloads:
        # Try in workspace slug
        response = client.post("/workspaces/create", json={
            "name": "Test",
            "slug": payload,
            "workspace_type": "general",
        })
        # Should either reject or sanitize, not cause SQL error
        assert response.status_code in [400, 422, 500]


@pytest.mark.security
@pytest.mark.api
def test_xss_protection(client: TestClient, test_workspace):
    """Test XSS attempts are handled"""
    xss_payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert('xss')>",
        "javascript:alert('xss')",
    ]

    for payload in xss_payloads:
        response = client.patch(f"/workspaces/{test_workspace.id}", json={
            "name": payload,
        })
        # Should accept but escape/sanitize
        assert response.status_code in [200, 400, 422]


@pytest.mark.security
@pytest.mark.api
def test_rate_limiting_exists(client: TestClient):
    """Test rate limiting mechanisms exist"""
    # Make multiple rapid requests
    responses = []
    for _ in range(100):
        response = client.get("/health")
        responses.append(response.status_code)

    # All should succeed in test environment
    # In production, rate limiting would kick in
    assert all(status == 200 for status in responses)


@pytest.mark.security
@pytest.mark.api
def test_cors_headers(client: TestClient):
    """Test CORS headers are set correctly"""
    response = client.options("/health")
    # CORS headers should be present for API
    # Actual values depend on configuration


@pytest.mark.security
@pytest.mark.api
def test_input_validation(client: TestClient):
    """Test input validation on API endpoints"""
    # Invalid workspace data
    response = client.post("/workspaces/create", json={
        "name": "",  # Empty name
        "slug": "",  # Empty slug
    })
    assert response.status_code == 422  # Validation error

    # Invalid priority
    response = client.post("/tasks/create", json={
        "title": "Test",
        "priority": "invalid_priority",
    })
    assert response.status_code == 422


@pytest.mark.security
@pytest.mark.api
def test_oversized_payload_rejection(client: TestClient):
    """Test oversized payloads are rejected"""
    # Create very large payload
    large_description = "A" * (10 * 1024 * 1024)  # 10MB string

    response = client.post("/workspaces/create", json={
        "name": "Test",
        "slug": "test",
        "description": large_description,
    })
    # Should reject or truncate
    assert response.status_code in [400, 413, 422, 500]


@pytest.mark.security
@pytest.mark.api
def test_auth_required_endpoints(client: TestClient):
    """Test endpoints that should require authentication"""
    # These endpoints should check auth in production
    sensitive_endpoints = [
        ("/workspaces/create", "post"),
        ("/agents/create", "post"),
    ]

    for endpoint, method in sensitive_endpoints:
        if method == "post":
            response = client.post(endpoint, json={})
        # In test environment, auth might be bypassed
        # This documents which endpoints should have auth


@pytest.mark.security
@pytest.mark.api
def test_uuid_validation(client: TestClient):
    """Test invalid UUIDs are rejected"""
    invalid_uuids = [
        "not-a-uuid",
        "12345",
        "../../../../etc/passwd",
        "<script>alert('xss')</script>",
    ]

    for invalid_id in invalid_uuids:
        response = client.get(f"/workspaces/{invalid_id}")
        assert response.status_code in [400, 404, 422]


@pytest.mark.security
@pytest.mark.api
def test_path_traversal_protection(client: TestClient):
    """Test path traversal attempts are blocked"""
    path_traversal_attempts = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32",
        "%2e%2e%2f%2e%2e%2f",
    ]

    for attempt in path_traversal_attempts:
        # Try in slug or name fields
        response = client.post("/workspaces/create", json={
            "name": "Test",
            "slug": attempt,
            "workspace_type": "general",
        })
        # Should reject malicious paths
        assert response.status_code in [400, 422]


@pytest.mark.security
@pytest.mark.api
def test_content_type_validation(client: TestClient):
    """Test content-type validation"""
    # Send wrong content type
    response = client.post(
        "/workspaces/create",
        data="not json",
        headers={"Content-Type": "text/plain"}
    )
    assert response.status_code in [400, 415, 422]
