#!/bin/bash
# Initialize Let's Encrypt certificates for PP1
# Run ONCE on the VPS before starting production compose
#
# Usage: DOMAIN=pp1.nikufra.ai EMAIL=admin@nikufra.ai ./deploy/init-letsencrypt.sh

set -euo pipefail

DOMAIN="${DOMAIN:?Set DOMAIN env var (e.g. pp1.nikufra.ai)}"
EMAIL="${EMAIL:?Set EMAIL env var for Let's Encrypt notifications}"
STAGING="${STAGING:-0}"  # Set to 1 for testing

echo "=== PP1 SSL Init ==="
echo "Domain: $DOMAIN"
echo "Email:  $EMAIL"
echo "Staging: $STAGING"

# 1. Create volumes if needed
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d nginx

# 2. Request certificate
staging_flag=""
if [ "$STAGING" = "1" ]; then
  staging_flag="--staging"
fi

docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm certbot \
  certbot certonly --webroot \
  --webroot-path=/var/www/certbot \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  $staging_flag \
  -d "$DOMAIN"

# 3. Reload nginx
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec nginx nginx -s reload

echo "=== SSL certificate obtained for $DOMAIN ==="
echo "Now run: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
