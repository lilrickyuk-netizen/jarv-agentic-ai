"""
JARV Backend Test Configuration
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """Create a test client"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    """Create authentication headers for testing"""
    return {"Authorization": "Bearer test_token"}
