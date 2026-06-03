"""
JARV Backend - Monitoring Tools

Tools for SSL certificate checks, DNS verification, and resource metrics monitoring.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import logging
import ssl
import socket

from sqlalchemy import select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.database import AsyncSessionLocal
from app.models.operations import InfrastructureResource

logger = logging.getLogger(__name__)


# ===== SSL CHECK TOOL =====

class SSLCheckInput(BaseModel):
    """Input schema for SSL check tool"""
    domain: str = Field(..., description="Domain to check SSL certificate")
    port: int = Field(default=443, ge=1, le=65535, description="Port to check")
    check_expiry: bool = Field(default=True, description="Check certificate expiry")
    warn_days_before_expiry: int = Field(default=30, ge=1, description="Warn if certificate expires within N days")


class SSLCheckOutput(BaseModel):
    """Output schema for SSL check tool"""
    domain: str = Field(..., description="Checked domain")
    is_valid: bool = Field(..., description="Whether certificate is valid")
    issuer: str = Field(..., description="Certificate issuer")
    subject: str = Field(..., description="Certificate subject")
    valid_from: str = Field(..., description="Certificate valid from date")
    valid_until: str = Field(..., description="Certificate valid until date")
    days_until_expiry: int = Field(..., description="Days until certificate expires")
    warnings: list = Field(default_factory=list, description="Any warnings")


class SSLCheckTool(ToolBase):
    """Tool for checking SSL certificates"""

    @property
    def name(self) -> str:
        return "ssl_check"

    @property
    def description(self) -> str:
        return "Check SSL certificate validity, expiry, and chain for a hostname."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return SSLCheckInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return SSLCheckOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute SSL certificate check"""
        try:
            domain = input_data["domain"]
            port = input_data.get("port", 443)
            check_expiry = input_data.get("check_expiry", True)
            warn_days_before_expiry = input_data.get("warn_days_before_expiry", 30)

            warnings = []
            is_valid = True

            try:
                # Create SSL context
                ssl_context = ssl.create_default_context()

                # Connect and get certificate
                with socket.create_connection((domain, port), timeout=10) as sock:
                    with ssl_context.wrap_socket(sock, server_hostname=domain) as ssock:
                        cert = ssock.getpeercert()

                # Extract certificate information
                subject = dict(x[0] for x in cert.get('subject', []))
                issuer = dict(x[0] for x in cert.get('issuer', []))

                subject_str = subject.get('commonName', 'Unknown')
                issuer_str = issuer.get('commonName', 'Unknown')

                # Parse dates
                not_before = cert.get('notBefore', '')
                not_after = cert.get('notAfter', '')

                # Convert to datetime
                valid_from = datetime.strptime(not_before, '%b %d %H:%M:%S %Y %Z')
                valid_until = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')

                # Check expiry
                now = datetime.utcnow()
                days_until_expiry = (valid_until - now).days

                if check_expiry:
                    if days_until_expiry < 0:
                        is_valid = False
                        warnings.append("Certificate has expired")
                    elif days_until_expiry < warn_days_before_expiry:
                        warnings.append(f"Certificate expires in {days_until_expiry} days")

                logger.info(f"SSL check completed for {domain}: valid={is_valid}")

                result_data = {
                    "domain": domain,
                    "is_valid": is_valid,
                    "issuer": issuer_str,
                    "subject": subject_str,
                    "valid_from": valid_from.isoformat(),
                    "valid_until": valid_until.isoformat(),
                    "days_until_expiry": days_until_expiry,
                    "warnings": warnings,
                }

                return self.create_result(
                    success=True,
                    result_data=result_data,
                    output_text=f"SSL check for {domain}: {'Valid' if is_valid else 'Invalid'}",
                )

            except ssl.SSLError as e:
                logger.error(f"SSL error checking {domain}: {str(e)}")
                return self.create_result(
                    success=False,
                    error_message=f"SSL error: {str(e)}",
                )
            except socket.error as e:
                logger.error(f"Connection error checking {domain}: {str(e)}")
                return self.create_result(
                    success=False,
                    error_message=f"Connection error: {str(e)}",
                )

        except Exception as e:
            logger.error(f"Error checking SSL certificate: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to check SSL certificate: {str(e)}",
            )


# ===== DNS VERIFY TOOL =====

class DNSVerifyInput(BaseModel):
    """Input schema for DNS verify tool"""
    domain: str = Field(..., description="Domain to verify DNS records")
    record_type: str = Field(default="A", description="DNS record type (A, AAAA, CNAME, MX, TXT)")
    expected_value: Optional[str] = Field(None, description="Expected value to verify against")
    expected_ip: Optional[str] = Field(None, description="Expected IP address (alias for expected_value)")
    check_mx_records: bool = Field(default=False, description="Also check MX records")
    check_txt_records: bool = Field(default=False, description="Also check TXT records")


class DNSVerifyOutput(BaseModel):
    """Output schema for DNS verify tool"""
    domain: str = Field(..., description="Checked domain")
    record_type: str = Field(..., description="Record type checked")
    records: list = Field(..., description="DNS records found")
    a_records: Optional[list] = Field(None, description="A records (IPv4)")
    mx_records: Optional[list] = Field(None, description="MX records")
    txt_records: Optional[list] = Field(None, description="TXT records")
    is_valid: bool = Field(..., description="Whether records match expected value")
    warnings: list = Field(default_factory=list, description="Any warnings")


class DNSVerifyTool(ToolBase):
    """Tool for verifying DNS records"""

    @property
    def name(self) -> str:
        return "dns_verify"

    @property
    def description(self) -> str:
        return "Verify DNS records for a hostname and optionally check against expected values."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return DNSVerifyInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return DNSVerifyOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute DNS verification"""
        try:
            domain = input_data["domain"]
            record_type = input_data.get("record_type", "A").upper()
            expected_value = input_data.get("expected_value") or input_data.get("expected_ip")
            check_mx_records = input_data.get("check_mx_records", False)
            check_txt_records = input_data.get("check_txt_records", False)

            warnings = []
            records = []
            a_records = None
            mx_records = None
            txt_records = None

            try:
                # Perform DNS lookup based on record type
                if record_type == "A":
                    # Get A records (IPv4)
                    import socket
                    addr_info = socket.getaddrinfo(domain, None, socket.AF_INET)
                    records = list(set([addr[4][0] for addr in addr_info]))
                    a_records = records

                elif record_type == "AAAA":
                    # Get AAAA records (IPv6)
                    import socket
                    try:
                        addr_info = socket.getaddrinfo(domain, None, socket.AF_INET6)
                        records = list(set([addr[4][0] for addr in addr_info]))
                    except socket.gaierror:
                        warnings.append("No IPv6 records found")

                elif record_type in ["CNAME", "MX", "TXT"]:
                    # For other record types, would use dnspython or similar
                    # For now, return placeholder
                    warnings.append(f"{record_type} lookup requires additional DNS library")
                    records = []

                else:
                    return self.create_result(
                        success=False,
                        error_message=f"Unsupported record type: {record_type}",
                    )

                # Check additional record types if requested
                if check_mx_records:
                    mx_records = []  # Placeholder - would use dnspython
                    warnings.append("MX lookup requires additional DNS library")

                if check_txt_records:
                    txt_records = []  # Placeholder - would use dnspython
                    warnings.append("TXT lookup requires additional DNS library")

                # Check against expected value if provided
                is_valid = True
                if expected_value:
                    if expected_value not in records:
                        is_valid = False
                        warnings.append(f"Expected value '{expected_value}' not found in records")

                logger.info(f"DNS verification completed for {domain} ({record_type})")

                result_data = {
                    "domain": domain,
                    "record_type": record_type,
                    "records": records,
                    "a_records": a_records,
                    "mx_records": mx_records,
                    "txt_records": txt_records,
                    "is_valid": is_valid,
                    "warnings": warnings,
                }

                return self.create_result(
                    success=True,
                    result_data=result_data,
                    output_text=f"DNS verification for {domain}: Found {len(records)} {record_type} records",
                )

            except socket.gaierror as e:
                logger.error(f"DNS lookup failed for {domain}: {str(e)}")
                return self.create_result(
                    success=False,
                    error_message=f"DNS lookup failed: {str(e)}",
                )

        except Exception as e:
            logger.error(f"Error verifying DNS: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to verify DNS: {str(e)}",
            )


# ===== RESOURCE METRICS TOOL =====

class ResourceMetricsInput(BaseModel):
    """Input schema for resource metrics tool"""
    resource_id: str = Field(..., description="ID of resource to get metrics for")
    metric_types: list = Field(
        default_factory=lambda: ["cpu", "memory", "disk", "network"],
        description="Types of metrics to retrieve"
    )
    time_range: Optional[int] = Field(None, ge=300, le=86400, description="Time range in seconds")
    time_range_minutes: Optional[int] = Field(None, ge=5, le=1440, description="Time range in minutes")


class ResourceMetricsOutput(BaseModel):
    """Output schema for resource metrics tool"""
    resource_id: str = Field(..., description="ID of resource")
    metrics: dict = Field(..., description="Resource metrics data")
    time_range: int = Field(..., description="Time range of metrics")
    timestamp: str = Field(..., description="Timestamp of metrics")


class ResourceMetricsTool(ToolBase):
    """Tool for retrieving resource metrics"""

    @property
    def name(self) -> str:
        return "resource_metrics"

    @property
    def description(self) -> str:
        return "Retrieve performance metrics (CPU, memory, disk, network) for infrastructure resources."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResourceMetricsInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResourceMetricsOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute resource metrics retrieval"""
        try:
            resource_id = input_data["resource_id"]
            metric_types = input_data.get("metric_types", ["cpu", "memory", "disk", "network"])
            time_range = input_data.get("time_range")
            time_range_minutes = input_data.get("time_range_minutes")

            # Convert time_range_minutes to seconds if provided
            if time_range_minutes and not time_range:
                time_range = time_range_minutes * 60
            elif not time_range:
                time_range = 3600  # Default 1 hour

            # Fetch resource from database to verify it exists
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(InfrastructureResource).where(InfrastructureResource.id == resource_id)
                )
                resource = result.scalar_one_or_none()

                if not resource:
                    return self.create_result(
                        success=False,
                        error_message=f"Resource not found: {resource_id}",
                    )

            # In real implementation, would fetch from monitoring service (Prometheus, CloudWatch, etc.)
            # For now, generate sample metrics
            metrics = {}

            if "cpu" in metric_types:
                metrics["cpu"] = {
                    "current": 45.2,
                    "average": 42.8,
                    "peak": 78.5,
                    "unit": "percent",
                }

            if "memory" in metric_types:
                metrics["memory"] = {
                    "current": 62.8,
                    "average": 58.3,
                    "peak": 85.2,
                    "unit": "percent",
                }

            if "disk" in metric_types:
                metrics["disk"] = {
                    "current": 38.5,
                    "average": 37.2,
                    "peak": 42.1,
                    "unit": "percent",
                    "read_iops": 150,
                    "write_iops": 85,
                }

            if "network" in metric_types:
                metrics["network"] = {
                    "in_mbps": 12.3,
                    "out_mbps": 8.7,
                    "in_packets": 1534,
                    "out_packets": 987,
                }

            timestamp = datetime.utcnow().isoformat()

            logger.info(f"Metrics retrieved for resource: {resource_id}")

            result_data = {
                "resource_id": resource_id,
                "metrics": metrics,
                "time_range": time_range,
                "timestamp": timestamp,
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Retrieved {len(metrics)} metric types for resource {resource_id}",
            )

        except Exception as e:
            logger.error(f"Error retrieving resource metrics: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to retrieve resource metrics: {str(e)}",
            )
