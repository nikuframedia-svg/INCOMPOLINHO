#!/bin/bash
# PP1 VPS setup script — Hetzner CX32 (4 vCPU, 8GB, €8/mês)
# Run on a fresh Ubuntu 24.04 LTS server
#
# Usage: ssh root@<IP> 'bash -s' < deploy/setup-vps.sh

set -euo pipefail

echo "=== PP1 VPS Setup ==="

# 1. System updates
apt-get update && apt-get upgrade -y

# 2. Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# 3. Install Docker Compose plugin
apt-get install -y docker-compose-plugin

# 4. Create app user
useradd -m -s /bin/bash -G docker pp1 || true

# 5. Firewall
apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (redirect to HTTPS)
ufw allow 443/tcp   # HTTPS
ufw --force enable

# 6. Create app directory
mkdir -p /opt/pp1
chown pp1:pp1 /opt/pp1

# 7. Swap (for 8GB server running CP-SAT)
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. scp -r . pp1@<IP>:/opt/pp1/"
echo "  2. ssh pp1@<IP>"
echo "  3. cd /opt/pp1 && cp .env.example .env && nano .env"
echo "  4. DOMAIN=pp1.nikufra.ai EMAIL=admin@nikufra.ai ./deploy/init-letsencrypt.sh"
echo "  5. docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
