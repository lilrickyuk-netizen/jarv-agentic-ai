# SSL Certificate Setup

## Development (Self-Signed Certificate)

For development and testing, generate a self-signed certificate:

```bash
cd infra/nginx/ssl
bash generate-selfsigned-cert.sh
```

This creates:
- `cert.pem` - SSL certificate
- `key.pem` - Private key

## Production (Let's Encrypt)

For production, use Let's Encrypt with Certbot:

### Option 1: Standalone Mode (before starting Docker)

```bash
# Install certbot
sudo apt-get install certbot

# Generate certificate
sudo certbot certonly --standalone \
  --preferred-challenges http \
  -d your-domain.com \
  -d www.your-domain.com

# Copy certificates to nginx ssl directory
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ./cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem ./key.pem
sudo chmod 644 ./cert.pem
sudo chmod 600 ./key.pem
```

### Option 2: Using Docker Certbot

```bash
# Use certbot docker container
docker run -it --rm \
  -v ./infra/nginx/ssl:/etc/letsencrypt \
  -p 80:80 \
  certbot/certbot certonly --standalone \
  --email your-email@example.com \
  --agree-tos \
  --no-eff-email \
  -d your-domain.com
```

### Option 3: Cloud Provider Certificate

If using AWS, GCP, or Azure, use their managed certificate services:

- **AWS**: Use AWS Certificate Manager (ACM) with Application Load Balancer
- **GCP**: Use Google-managed SSL certificates with Load Balancer
- **Azure**: Use Azure Application Gateway with managed certificates

## Certificate Renewal

Let's Encrypt certificates expire every 90 days. Set up auto-renewal:

```bash
# Add to crontab
0 0 * * * certbot renew --quiet && docker-compose -f docker-compose.prod.yml restart nginx
```

## Validate Certificate

```bash
# Check certificate expiration
openssl x509 -in cert.pem -noout -enddate

# Verify certificate chain
openssl verify -CAfile cert.pem cert.pem
```
