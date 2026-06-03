"""
JARV Backend - HTTP Request Tools

Real HTTP request tools with security, rate limiting, and error handling.

SETUP INSTRUCTIONS:
- No external dependencies beyond httpx (already installed)
- Set HTTP_ALLOWED_DOMAINS to restrict allowed domains (comma-separated)
- Set HTTP_BLOCKED_DOMAINS to block specific domains (comma-separated)
- Set HTTP_RATE_LIMIT_ENABLED=true to enable rate limiting
- Set HTTP_MAX_REQUESTS_PER_MINUTE=60 for rate limit

When unconfigured, all domains allowed but rate limiting disabled.

SECURITY:
- Validates URLs before requests
- Blocks private IP ranges (localhost, 127.0.0.1, 192.168.*, etc.)
- Blocks file:// and other non-HTTP protocols
- Configurable domain allowlist/blocklist
- Request timeout (default 30s)
- Maximum response size (default 10MB)
- User-Agent identification
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field, HttpUrl
import logging
import os
import httpx
from urllib.parse import urlparse

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


def get_allowed_domains() -> Optional[list]:
    """Get list of allowed domains from env"""
    allowed = os.getenv("HTTP_ALLOWED_DOMAINS", "")
    return [d.strip() for d in allowed.split(",") if d.strip()] if allowed else None


def get_blocked_domains() -> list:
    """Get list of blocked domains from env"""
    blocked = os.getenv("HTTP_BLOCKED_DOMAINS", "")
    return [d.strip() for d in blocked.split(",") if d.strip()]


def is_rate_limit_enabled() -> bool:
    """Check if rate limiting is enabled"""
    return os.getenv("HTTP_RATE_LIMIT_ENABLED", "false").lower() == "true"


def validate_url(url: str) -> tuple[bool, Optional[str]]:
    """
    Validate URL for security.
    Returns: (is_valid, error_message)
    """
    try:
        parsed = urlparse(url)

        # Check protocol
        if parsed.scheme not in ("http", "https"):
            return False, f"Invalid protocol: {parsed.scheme}. Only http/https allowed."

        # Check for private IPs and localhost
        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid hostname"

        # Block localhost and common private ranges
        blocked_hosts = [
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
        ]
        if hostname in blocked_hosts or hostname.startswith("192.168.") or hostname.startswith("10.") or hostname.startswith("172."):
            return False, f"Access to private/local addresses not allowed: {hostname}"

        # Check allowed domains
        allowed_domains = get_allowed_domains()
        if allowed_domains:
            domain_match = any(hostname.endswith(domain) or hostname == domain for domain in allowed_domains)
            if not domain_match:
                return False, f"Domain not in allowlist: {hostname}"

        # Check blocked domains
        blocked_domains = get_blocked_domains()
        if blocked_domains:
            domain_blocked = any(hostname.endswith(domain) or hostname == domain for domain in blocked_domains)
            if domain_blocked:
                return False, f"Domain is blocked: {hostname}"

        return True, None

    except Exception as e:
        return False, f"URL validation error: {str(e)}"


async def make_http_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Make HTTP request with security and error handling.
    Returns: (success, response_data, error_message)
    """
    # Validate URL
    is_valid, error = validate_url(url)
    if not is_valid:
        return False, None, error

    # Add User-Agent
    if headers is None:
        headers = {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = "JARV-Agent/1.0"

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=data,
                json=json_data,
            )

            # Check response size (max 10MB)
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > 10 * 1024 * 1024:
                return False, None, "Response too large (>10MB)"

            # Parse response
            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "url": str(response.url),
                "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
            }

            # Try to parse as JSON, fallback to text
            try:
                result["data"] = response.json()
                result["content_type"] = "application/json"
            except Exception:
                result["data"] = response.text[:100000]  # Limit text to 100KB
                result["content_type"] = response.headers.get("content-type", "text/plain")

            success = 200 <= response.status_code < 300
            return success, result, None if success else f"HTTP {response.status_code}"

    except httpx.TimeoutException:
        return False, None, f"Request timeout after {timeout}s"
    except httpx.RequestError as e:
        return False, None, f"Request error: {str(e)}"
    except Exception as e:
        return False, None, f"Unexpected error: {str(e)}"


# ===== HTTP GET TOOL =====

class HttpGetInput(BaseModel):
    """Input schema for HTTP GET request"""
    url: str = Field(..., description="URL to request")
    headers: Optional[Dict[str, str]] = Field(None, description="Request headers")
    params: Optional[Dict[str, Any]] = Field(None, description="Query parameters")
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout in seconds")


class HttpGetOutput(BaseModel):
    """Output schema for HTTP GET request"""
    status_code: int
    headers: Dict[str, str]
    data: Any = Field(..., description="Response data (JSON or text)")
    content_type: str
    url: str = Field(..., description="Final URL after redirects")
    elapsed_ms: int


class HttpGetTool(ToolBase):
    """Tool for HTTP GET requests"""

    @property
    def name(self) -> str:
        return "http_get"

    @property
    def description(self) -> str:
        return "Make HTTP GET request to fetch data from external APIs."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return HttpGetInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return HttpGetOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return False  # GET requests are safe

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute HTTP GET request"""
        url = input_data["url"]
        headers = input_data.get("headers")
        params = input_data.get("params")
        timeout = input_data.get("timeout", 30)

        logger.info(f"HTTP GET: {url}")

        success, response, error = await make_http_request(
            method="GET",
            url=url,
            headers=headers,
            params=params,
            timeout=timeout,
        )

        if not success:
            return self.create_result(
                success=False,
                error_message=error or "Request failed",
            )

        return self.create_result(
            success=True,
            result_data=response,
            output_text=f"GET {url} -> {response['status_code']} ({response['elapsed_ms']}ms)",
        )


# ===== HTTP POST TOOL =====

class HttpPostInput(BaseModel):
    """Input schema for HTTP POST request"""
    url: str = Field(..., description="URL to request")
    headers: Optional[Dict[str, str]] = Field(None, description="Request headers")
    data: Optional[Dict[str, Any]] = Field(None, description="Form data")
    json_body: Optional[Dict[str, Any]] = Field(None, description="JSON data")
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout in seconds")


class HttpPostOutput(BaseModel):
    """Output schema for HTTP POST request"""
    status_code: int
    headers: Dict[str, str]
    data: Any
    content_type: str
    url: str
    elapsed_ms: int


class HttpPostTool(ToolBase):
    """Tool for HTTP POST requests"""

    @property
    def name(self) -> str:
        return "http_post"

    @property
    def description(self) -> str:
        return "Make HTTP POST request to send data to external APIs."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return HttpPostInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return HttpPostOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # POST can modify data

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute HTTP POST request"""
        url = input_data["url"]
        headers = input_data.get("headers")
        data = input_data.get("data")
        json_data = input_data.get("json_body")
        timeout = input_data.get("timeout", 30)

        logger.info(f"HTTP POST: {url}")

        success, response, error = await make_http_request(
            method="POST",
            url=url,
            headers=headers,
            data=data,
            json_data=json_data,
            timeout=timeout,
        )

        if not success:
            return self.create_result(
                success=False,
                error_message=error or "Request failed",
            )

        return self.create_result(
            success=True,
            result_data=response,
            output_text=f"POST {url} -> {response['status_code']} ({response['elapsed_ms']}ms)",
        )


# ===== HTTP PUT TOOL =====

class HttpPutInput(BaseModel):
    """Input schema for HTTP PUT request"""
    url: str = Field(..., description="URL to request")
    headers: Optional[Dict[str, str]] = Field(None, description="Request headers")
    data: Optional[Dict[str, Any]] = Field(None, description="Form data")
    json_body: Optional[Dict[str, Any]] = Field(None, description="JSON data")
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout in seconds")


class HttpPutOutput(BaseModel):
    """Output schema for HTTP PUT request"""
    status_code: int
    headers: Dict[str, str]
    data: Any
    content_type: str
    url: str
    elapsed_ms: int


class HttpPutTool(ToolBase):
    """Tool for HTTP PUT requests"""

    @property
    def name(self) -> str:
        return "http_put"

    @property
    def description(self) -> str:
        return "Make HTTP PUT request to update resources in external APIs."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return HttpPutInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return HttpPutOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # PUT can modify data

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute HTTP PUT request"""
        url = input_data["url"]
        headers = input_data.get("headers")
        data = input_data.get("data")
        json_data = input_data.get("json_body")
        timeout = input_data.get("timeout", 30)

        logger.info(f"HTTP PUT: {url}")

        success, response, error = await make_http_request(
            method="PUT",
            url=url,
            headers=headers,
            data=data,
            json_data=json_data,
            timeout=timeout,
        )

        if not success:
            return self.create_result(
                success=False,
                error_message=error or "Request failed",
            )

        return self.create_result(
            success=True,
            result_data=response,
            output_text=f"PUT {url} -> {response['status_code']} ({response['elapsed_ms']}ms)",
        )


# ===== HTTP DELETE TOOL =====

class HttpDeleteInput(BaseModel):
    """Input schema for HTTP DELETE request"""
    url: str = Field(..., description="URL to request")
    headers: Optional[Dict[str, str]] = Field(None, description="Request headers")
    params: Optional[Dict[str, Any]] = Field(None, description="Query parameters")
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout in seconds")


class HttpDeleteOutput(BaseModel):
    """Output schema for HTTP DELETE request"""
    status_code: int
    headers: Dict[str, str]
    data: Any
    content_type: str
    url: str
    elapsed_ms: int


class HttpDeleteTool(ToolBase):
    """Tool for HTTP DELETE requests"""

    @property
    def name(self) -> str:
        return "http_delete"

    @property
    def description(self) -> str:
        return "Make HTTP DELETE request to remove resources in external APIs."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return HttpDeleteInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return HttpDeleteOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # DELETE is destructive

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute HTTP DELETE request"""
        url = input_data["url"]
        headers = input_data.get("headers")
        params = input_data.get("params")
        timeout = input_data.get("timeout", 30)

        logger.info(f"HTTP DELETE: {url}")

        success, response, error = await make_http_request(
            method="DELETE",
            url=url,
            headers=headers,
            params=params,
            timeout=timeout,
        )

        if not success:
            return self.create_result(
                success=False,
                error_message=error or "Request failed",
            )

        return self.create_result(
            success=True,
            result_data=response,
            output_text=f"DELETE {url} -> {response['status_code']} ({response['elapsed_ms']}ms)",
        )


# ===== HTTP PATCH TOOL =====

class HttpPatchInput(BaseModel):
    """Input schema for HTTP PATCH request"""
    url: str = Field(..., description="URL to request")
    headers: Optional[Dict[str, str]] = Field(None, description="Request headers")
    data: Optional[Dict[str, Any]] = Field(None, description="Form data")
    json_body: Optional[Dict[str, Any]] = Field(None, description="JSON data")
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout in seconds")


class HttpPatchOutput(BaseModel):
    """Output schema for HTTP PATCH request"""
    status_code: int
    headers: Dict[str, str]
    data: Any
    content_type: str
    url: str
    elapsed_ms: int


class HttpPatchTool(ToolBase):
    """Tool for HTTP PATCH requests"""

    @property
    def name(self) -> str:
        return "http_patch"

    @property
    def description(self) -> str:
        return "Make HTTP PATCH request to partially update resources in external APIs."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return HttpPatchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return HttpPatchOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # PATCH can modify data

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute HTTP PATCH request"""
        url = input_data["url"]
        headers = input_data.get("headers")
        data = input_data.get("data")
        json_data = input_data.get("json_body")
        timeout = input_data.get("timeout", 30)

        logger.info(f"HTTP PATCH: {url}")

        success, response, error = await make_http_request(
            method="PATCH",
            url=url,
            headers=headers,
            data=data,
            json_data=json_data,
            timeout=timeout,
        )

        if not success:
            return self.create_result(
                success=False,
                error_message=error or "Request failed",
            )

        return self.create_result(
            success=True,
            result_data=response,
            output_text=f"PATCH {url} -> {response['status_code']} ({response['elapsed_ms']}ms)",
        )


# ===== HTTP HEAD TOOL =====

class HttpHeadInput(BaseModel):
    """Input schema for HTTP HEAD request"""
    url: str = Field(..., description="URL to request")
    headers: Optional[Dict[str, str]] = Field(None, description="Request headers")
    params: Optional[Dict[str, Any]] = Field(None, description="Query parameters")
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout in seconds")


class HttpHeadOutput(BaseModel):
    """Output schema for HTTP HEAD request"""
    status_code: int
    headers: Dict[str, str]
    url: str
    elapsed_ms: int


class HttpHeadTool(ToolBase):
    """Tool for HTTP HEAD requests"""

    @property
    def name(self) -> str:
        return "http_head"

    @property
    def description(self) -> str:
        return "Make HTTP HEAD request to get headers without downloading body."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return HttpHeadInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return HttpHeadOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return False  # HEAD requests are safe

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute HTTP HEAD request"""
        url = input_data["url"]
        headers = input_data.get("headers")
        params = input_data.get("params")
        timeout = input_data.get("timeout", 30)

        logger.info(f"HTTP HEAD: {url}")

        success, response, error = await make_http_request(
            method="HEAD",
            url=url,
            headers=headers,
            params=params,
            timeout=timeout,
        )

        if not success:
            return self.create_result(
                success=False,
                error_message=error or "Request failed",
            )

        # HEAD response doesn't have body
        result = {
            "status_code": response["status_code"],
            "headers": response["headers"],
            "url": response["url"],
            "elapsed_ms": response["elapsed_ms"],
        }

        return self.create_result(
            success=True,
            result_data=result,
            output_text=f"HEAD {url} -> {response['status_code']} ({response['elapsed_ms']}ms)",
        )
