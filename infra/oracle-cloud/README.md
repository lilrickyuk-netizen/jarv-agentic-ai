# Oracle Cloud Always Free Deployment

This guide walks through deploying JARV on Oracle Cloud's Always Free tier - perfect for zero-cost 24/7 operation.

## Oracle Cloud Always Free Resources

Oracle provides the following **permanently free** resources:
- 2 AMD-based Compute VMs (1/8 OCPU, 1 GB RAM each)
- OR 4 ARM-based Ampere A1 Compute instances (up to 4 OCPUs, 24 GB RAM total)
- 2 Block Volumes (200 GB total)
- 10 GB Object Storage
- Autonomous Database (20 GB)
- Load Balancer (1 instance, 10 Mbps)

**Recommended Setup**: Use 1 ARM VM (4 OCPUs, 24 GB RAM) for the entire JARV stack.

## Prerequisites

1. Oracle Cloud account (sign up at oracle.com/cloud/free)
2. SSH key pair for VM access
3. Domain name (optional but recommended)

## Step 1: Create Compute Instance

### Create ARM-Based VM

```bash
# Via OCI CLI (or use web console)
oci compute instance launch \
  --availability-domain <your-AD> \
  --compartment-id <your-compartment-id> \
  --shape VM.Standard.A1.Flex \
  --shape-config '{"ocpus":4,"memoryInGBs":24}' \
  --image-id <ubuntu-22.04-aarch64-image-id> \
  --subnet-id <your-subnet-id> \
  --display-name jarv-production \
  --ssh-authorized-keys-file ~/.ssh/id_rsa.pub
```

### Via Web Console

1. Navigate to **Compute > Instances**
2. Click **Create Instance**
3. Name: `jarv-production`
4. Image: **Ubuntu 22.04 ARM**
5. Shape: **VM.Standard.A1.Flex**
   - OCPUs: 4
   - Memory: 24 GB
6. Network: Use default VCN or create new
7. Add SSH Key: Upload your public key
8. Click **Create**

## Step 2: Configure Firewall Rules

### Add Ingress Rules

1. Go to **Networking > Virtual Cloud Networks**
2. Select your VCN
3. Click **Security Lists > Default Security List**
4. Add Ingress Rules:

```
Source CIDR: 0.0.0.0/0
Protocol: TCP
Destination Port: 80 (HTTP)

Source CIDR: 0.0.0.0/0
Protocol: TCP
Destination Port: 443 (HTTPS)
```

### Configure OS Firewall

SSH into your instance and open ports:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## Step 3: Install Docker and Docker Compose

```bash
# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt-get install docker-compose-plugin -y

# Verify installation
docker --version
docker compose version

# Log out and back in for group changes to take effect
exit
```

## Step 4: Deploy JARV

### Clone Repository

```bash
# SSH back into instance
ssh ubuntu@<your-instance-ip>

# Clone JARV repository
git clone https://github.com/yourusername/jarv.git
cd jarv
```

### Configure Environment

```bash
# Create production environment file
cp .env.production.example .env.production

# Edit with your credentials
nano .env.production
```

**Required Changes**:
- Set strong `SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`
- Add your `CLAUDE_API_KEY`, `OPENAI_API_KEY`, etc.
- Set `NEXT_PUBLIC_API_URL` to your domain or IP
- Set `CORS_ORIGINS` to your domain

### Generate SSL Certificate (Self-Signed for Testing)

```bash
cd infra/nginx/ssl
bash generate-selfsigned-cert.sh
cd ../../..
```

For production with real domain, use Let's Encrypt (see SSL README).

### Start Services

```bash
# Pull and build images
docker compose -f docker-compose.prod.yml build

# Start services
docker compose -f docker-compose.prod.yml up -d

# Check status
docker compose -f docker-compose.prod.yml ps

# View logs
docker compose -f docker-compose.prod.yml logs -f
```

## Step 5: Initialize Database

```bash
# Run database migrations
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head

# Create admin user (optional)
docker compose -f docker-compose.prod.yml exec backend python -m app.scripts.setup_admin
```

## Step 6: Access JARV

Your JARV instance is now running at:
- Dashboard: `https://<your-instance-ip>` or `https://yourdomain.com`
- API: `https://<your-instance-ip>/api` or `https://yourdomain.com/api`
- Health Check: `http://<your-instance-ip>/health`

## Step 7: Set Up Domain (Optional)

1. Point your domain's A record to your instance IP
2. Update `.env.production` with your domain
3. Generate Let's Encrypt certificate:

```bash
# Install certbot
sudo apt-get install certbot -y

# Stop nginx temporarily
docker compose -f docker-compose.prod.yml stop nginx

# Generate certificate
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com

# Copy certificates
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem infra/nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem infra/nginx/ssl/key.pem
sudo chown $USER:$USER infra/nginx/ssl/*.pem

# Restart nginx
docker compose -f docker-compose.prod.yml up -d nginx
```

## Step 8: Enable Auto-Start on Reboot

```bash
# Create systemd service
sudo nano /etc/systemd/system/jarv.service
```

Add:

```ini
[Unit]
Description=JARV Agentic AI System
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/jarv
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
User=ubuntu

[Install]
WantedBy=multi-user.target
```

Enable service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable jarv.service
sudo systemctl start jarv.service
```

## Monitoring and Maintenance

### View Logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f worker
```

### Check Service Health

```bash
# Health check
curl http://localhost/health

# Service status
docker compose -f docker-compose.prod.yml ps
```

### Backup Database

```bash
# Manual backup
docker compose -f docker-compose.prod.yml exec postgres pg_dump -U jarv_prod jarv_production > backup.sql

# Restore
cat backup.sql | docker compose -f docker-compose.prod.yml exec -T postgres psql -U jarv_prod jarv_production
```

### Update JARV

```bash
# Pull latest code
git pull

# Rebuild and restart
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# Run migrations
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

## Resource Usage Optimization

For 24GB RAM free tier:

```yaml
# In docker-compose.prod.yml, adjust resources:
backend:
  deploy:
    resources:
      limits:
        memory: 4G
worker:
  deploy:
    resources:
      limits:
        memory: 4G
postgres:
  deploy:
    resources:
      limits:
        memory: 8G
redis:
  deploy:
    resources:
      limits:
        memory: 2G
```

## Troubleshooting

### Out of Memory

```bash
# Add swap space
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Container Won't Start

```bash
# Check logs
docker compose -f docker-compose.prod.yml logs <service-name>

# Restart service
docker compose -f docker-compose.prod.yml restart <service-name>
```

### Port Already in Use

```bash
# Find process using port
sudo lsof -i :80
sudo lsof -i :443

# Kill process if needed
sudo kill -9 <PID>
```

## Cost

**Total Cost: $0/month** (Oracle Cloud Always Free)

The entire JARV system runs on Oracle's generous free tier with:
- 4 vCPU ARM processor
- 24 GB RAM
- 200 GB storage
- 10 Gbps network bandwidth
- Public IP address
- No time limits

This is perfect for running JARV 24/7 with zero infrastructure costs.
