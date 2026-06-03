# JARV Security Configuration

Comprehensive security hardening and best practices for JARV production deployment.

## Security Overview

JARV implements defense-in-depth with multiple security layers:
- **Network Security**: Firewall, SSL/TLS, rate limiting
- **Application Security**: Input validation, CORS, CSRF protection
- **Data Security**: Encryption at rest and in transit
- **Access Control**: Authentication, authorization, RBAC
- **Monitoring**: Audit logging, intrusion detection
- **Backup Security**: Encrypted backups, secure storage

## Quick Security Checklist

Before deploying to production:

- [ ] Change all default passwords
- [ ] Generate strong SECRET_KEY and tokens
- [ ] Configure SSL/TLS certificates
- [ ] Set up firewall rules
- [ ] Enable rate limiting
- [ ] Configure CORS properly
- [ ] Set secure environment variables
- [ ] Enable audit logging
- [ ] Set up backup encryption
- [ ] Configure monitoring alerts
- [ ] Review permissions and roles
- [ ] Scan for vulnerabilities
- [ ] Update all dependencies
- [ ] Disable debug mode
- [ ] Remove development tools

## 1. Secrets Management

### Generate Strong Secrets

```bash
# Generate SECRET_KEY (32 bytes)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate database password (24 bytes)
python -c "import secrets; print(secrets.token_urlsafe(24))"

# Generate Redis password
python -c "import secrets; print(secrets.token_urlsafe(16))"

# Generate RUNNER_TOKEN
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Secure Storage

**Do NOT**:
- ❌ Commit `.env.production` to Git
- ❌ Store secrets in code
- ❌ Share secrets via email/chat
- ❌ Use default passwords
- ❌ Store secrets in Docker image

**Do**:
- ✅ Use `.env.production` (excluded from Git)
- ✅ Use environment variables
- ✅ Use secrets management service (Vault, AWS Secrets Manager)
- ✅ Rotate secrets regularly
- ✅ Use different secrets per environment

### Environment-Specific Secrets

```bash
# Development
cp .env.example .env

# Staging
cp .env.production.example .env.staging

# Production
cp .env.production.example .env.production
```

## 2. Network Security

### Firewall Configuration (Oracle Cloud)

```bash
# Allow only necessary ports
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT   # HTTP
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT  # HTTPS
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT   # SSH (restrict to your IP)
sudo iptables -A INPUT -j DROP                       # Drop all other

# Save rules
sudo netfilter-persistent save

# Restrict SSH to specific IP
sudo iptables -I INPUT -p tcp --dport 22 -s YOUR_IP_ADDRESS -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 22 -j DROP
```

### Oracle Cloud Security List

Add ingress rules in Oracle Cloud Console:
- HTTP (80): 0.0.0.0/0
- HTTPS (443): 0.0.0.0/0
- SSH (22): YOUR_IP_ADDRESS/32 only

**Never expose**:
- PostgreSQL (5432)
- Redis (6379)
- Prometheus (9090)
- Grafana (3001)

### SSL/TLS Configuration

**Production: Use Let's Encrypt**

```bash
# Install certbot
sudo apt-get install certbot -y

# Generate certificate
sudo certbot certonly --standalone \
  -d yourdomain.com \
  -d www.yourdomain.com \
  --email your-email@example.com \
  --agree-tos

# Copy to nginx
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem infra/nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem infra/nginx/ssl/key.pem
sudo chown $USER:$USER infra/nginx/ssl/*.pem

# Auto-renewal
sudo certbot renew --dry-run
```

**Development: Self-Signed**

```bash
cd infra/nginx/ssl
bash generate-selfsigned-cert.sh
```

### Rate Limiting

Nginx rate limiting is configured in `infra/nginx/nginx.conf`:

```nginx
# API: 10 requests/second
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

# Dashboard: 30 requests/second
limit_req_zone $binary_remote_addr zone=dashboard_limit:10m rate=30r/s;
```

Adjust as needed for your traffic.

## 3. Application Security

### CORS Configuration

In `.env.production`:

```bash
# Restrict to your domains
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Never use wildcard in production
CORS_ORIGINS=*  # ❌ INSECURE
```

### Input Validation

All API endpoints use Pydantic validation:

```python
# Example: apps/backend/app/api/example.py
from pydantic import BaseModel, Field, validator

class UserInput(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, regex="^[a-zA-Z0-9_-]+$")
    email: str = Field(..., regex="^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

    @validator('username')
    def validate_username(cls, v):
        if v.lower() in ['admin', 'root', 'system']:
            raise ValueError('Reserved username')
        return v
```

### SQL Injection Prevention

Use SQLAlchemy ORM (never raw SQL):

```python
# ✅ Safe: ORM query
user = db.query(User).filter(User.username == username).first()

# ❌ Unsafe: Raw SQL
db.execute(f"SELECT * FROM users WHERE username = '{username}'")
```

### XSS Prevention

Frontend sanitization in Next.js:

```typescript
import DOMPurify from 'isomorphic-dompurify';

// Sanitize user input before rendering
const cleanHTML = DOMPurify.sanitize(userInput);
```

### CSRF Protection

FastAPI automatically includes CSRF protection for state-changing operations.

## 4. Authentication & Authorization

### Password Requirements

Enforce strong passwords:

```python
# apps/backend/app/core/security.py
import re

def validate_password(password: str) -> bool:
    """
    Password must:
    - Be at least 12 characters
    - Include uppercase and lowercase
    - Include numbers
    - Include special characters
    """
    if len(password) < 12:
        return False

    if not re.search(r'[A-Z]', password):
        return False

    if not re.search(r'[a-z]', password):
        return False

    if not re.search(r'\d', password):
        return False

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False

    return True
```

### JWT Token Security

```python
# Token expiration
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Use strong algorithm
ALGORITHM = "HS256"  # or RS256 for asymmetric

# Rotate signing keys regularly
```

### API Key Security

```bash
# Use strong, unique API keys
CLAUDE_API_KEY=sk-ant-...  # Never commit real keys
OPENAI_API_KEY=sk-...

# Rotate API keys quarterly
# Monitor API usage for anomalies
# Set usage limits and alerts
```

## 5. Database Security

### PostgreSQL Hardening

```sql
-- Create dedicated user (not superuser)
CREATE USER jarv_prod WITH PASSWORD 'strong-password';
GRANT CONNECT ON DATABASE jarv_production TO jarv_prod;
GRANT USAGE ON SCHEMA public TO jarv_prod;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO jarv_prod;

-- Disable public schema for production
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- Enable connection limits
ALTER USER jarv_prod CONNECTION LIMIT 100;
```

### Encryption at Rest

```bash
# PostgreSQL: Enable encryption
# In docker-compose.prod.yml
postgres:
  command: >
    postgres
    -c ssl=on
    -c ssl_cert_file=/var/lib/postgresql/server.crt
    -c ssl_key_file=/var/lib/postgresql/server.key
```

### Backup Encryption

```bash
# Encrypt backups before uploading
gpg --encrypt --recipient your-email@example.com backup.tar.gz

# Decrypt for restore
gpg --decrypt backup.tar.gz.gpg > backup.tar.gz
```

## 6. Docker Security

### Run as Non-Root User

All Dockerfiles use non-root users:

```dockerfile
# Create user
RUN groupadd -r jarv && useradd -r -g jarv jarv

# Switch to user
USER jarv
```

### Scan Images for Vulnerabilities

```bash
# Install Trivy
wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo apt-key add -
echo "deb https://aquasecurity.github.io/trivy-repo/deb $(lsb_release -sc) main" | sudo tee /etc/apt/sources.list.d/trivy.list
sudo apt-get update
sudo apt-get install trivy

# Scan images
trivy image jarv-backend:latest
trivy image jarv-dashboard:latest

# Scan for HIGH and CRITICAL only
trivy image --severity HIGH,CRITICAL jarv-backend:latest
```

### Limit Container Resources

In `docker-compose.prod.yml`:

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
```

### Use Read-Only Filesystems

```yaml
services:
  backend:
    read_only: true
    tmpfs:
      - /tmp
      - /var/tmp
```

## 7. Monitoring & Logging

### Enable Audit Logging

In `.env.production`:

```bash
AUDIT_LOGGING_ENABLED=true
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### Security Event Logging

Log security-relevant events:
- Authentication attempts (success/failure)
- Authorization failures
- API key usage
- Sensitive data access
- Configuration changes
- Privilege escalations

### Log Retention

```bash
# Retain logs for compliance
LOG_RETENTION_DAYS=90

# Archive old logs
find /var/log/jarv -name "*.log" -mtime +90 -exec gzip {} \;
```

### Intrusion Detection

Monitor for suspicious activity:
- Multiple failed login attempts
- Unusual API usage patterns
- Large data exports
- After-hours access
- Geographic anomalies

## 8. Dependency Security

### Keep Dependencies Updated

```bash
# Backend: Update Python packages
cd apps/backend
poetry update

# Check for vulnerabilities
poetry run pip-audit

# Frontend: Update npm packages
cd apps/dashboard
npm audit
npm audit fix

# Update to latest secure versions
npm update
```

### Automated Dependency Scanning

GitHub Actions (`.github/workflows/security.yml`):

```yaml
name: Security Scan

on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly
  push:
    branches: [ main ]

jobs:
  scan-dependencies:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Snyk security scan
        uses: snyk/actions/python@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}

      - name: Run npm audit
        run: |
          cd apps/dashboard
          npm audit --audit-level=moderate
```

### Pin Dependency Versions

```python
# pyproject.toml: Use exact versions for production
fastapi = "0.109.0"  # Not "^0.109.0"
```

## 9. Incident Response

### Security Incident Playbook

1. **Detect**: Alert triggers
2. **Assess**: Determine severity
3. **Contain**: Isolate affected systems
4. **Eradicate**: Remove threat
5. **Recover**: Restore services
6. **Review**: Post-mortem analysis

### Emergency Procedures

**Suspected compromise**:

```bash
# 1. Take system offline
docker compose -f docker-compose.prod.yml down

# 2. Create snapshot/backup
./scripts/backup.sh full

# 3. Review logs
docker compose -f docker-compose.prod.yml logs > incident-logs.txt

# 4. Rotate all secrets
# Generate new SECRET_KEY, passwords, API keys

# 5. Restore from known-good backup
./scripts/restore.sh jarv_full_<last-known-good>

# 6. Update .env.production with new secrets
nano .env.production

# 7. Bring system back online
docker compose -f docker-compose.prod.yml up -d

# 8. Monitor closely for 24-48 hours
```

### Contact Information

Maintain security contact list:
- Security team lead
- Infrastructure administrator
- Legal/compliance
- External security consultant
- Cloud provider support

## 10. Compliance

### GDPR Compliance

For EU users:
- Encrypt personal data
- Implement data retention policies
- Provide data export functionality
- Support data deletion requests
- Maintain audit logs
- Document data processing

### SOC 2 Compliance

For enterprise customers:
- Access control
- Change management
- Encryption in transit and at rest
- Backup and recovery
- Incident response plan
- Security monitoring
- Vendor management

## Security Checklist (Pre-Production)

### Infrastructure

- [ ] Firewall configured (only 80, 443, 22 open)
- [ ] SSH restricted to specific IPs
- [ ] SSL/TLS certificates installed
- [ ] Let's Encrypt auto-renewal configured
- [ ] Rate limiting enabled
- [ ] DDoS protection configured

### Application

- [ ] All default passwords changed
- [ ] Strong SECRET_KEY generated
- [ ] CORS properly configured
- [ ] Input validation implemented
- [ ] SQL injection prevention verified
- [ ] XSS protection enabled
- [ ] CSRF protection enabled
- [ ] Authentication working
- [ ] Authorization rules tested

### Data

- [ ] Database encryption enabled
- [ ] Backup encryption enabled
- [ ] Data retention policy defined
- [ ] PII properly protected
- [ ] Backups tested and working
- [ ] Recovery procedures documented

### Monitoring

- [ ] Audit logging enabled
- [ ] Security alerts configured
- [ ] Log retention policy set
- [ ] Intrusion detection active
- [ ] Vulnerability scanning scheduled

### Dependencies

- [ ] All packages updated
- [ ] Vulnerability scan passed
- [ ] Dependency versions pinned
- [ ] No critical CVEs present

### Documentation

- [ ] Security policies documented
- [ ] Incident response plan created
- [ ] Access control list maintained
- [ ] Security contacts updated
- [ ] Recovery procedures tested

## Security Resources

- OWASP Top 10: https://owasp.org/www-project-top-ten/
- CIS Benchmarks: https://www.cisecurity.org/cis-benchmarks/
- NIST Cybersecurity Framework: https://www.nist.gov/cyberframework
- Docker Security Best Practices: https://docs.docker.com/engine/security/
- FastAPI Security: https://fastapi.tiangolo.com/tutorial/security/

## Regular Security Tasks

### Daily
- Monitor security alerts
- Review failed authentication attempts
- Check system logs for anomalies

### Weekly
- Review access logs
- Update dependencies
- Scan for vulnerabilities
- Review firewall rules

### Monthly
- Rotate API keys
- Review user permissions
- Test backup restore
- Security patch updates
- Incident response drill

### Quarterly
- Comprehensive security audit
- Penetration testing
- Update security documentation
- Review and update policies
- Rotate SSL certificates (if not auto-renewed)

## Contact

For security concerns or to report vulnerabilities:
- Email: security@yourdomain.com
- PGP Key: [Include public key fingerprint]
- Security Policy: https://yourdomain.com/security
