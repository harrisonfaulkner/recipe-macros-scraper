#!/bin/bash
# Initialize SSL certificates for calories.entitledosprey.com
# Run this ONCE on the VPS after setting up the Cloudflare DNS A record.
#
# Prerequisites:
#   1. DNS A record: calories.entitledosprey.com -> 158.101.19.175
#   2. Cloudflare proxy (orange cloud) OFF for initial cert generation
#   3. .env file with USDA_API_KEY set
#
# Usage: sudo ./init-ssl.sh

set -e

DOMAIN="calories.entitledosprey.com"
EMAIL="Harrisonfaulkner@gmail.com"

echo "=== Step 1: Start app with HTTP-only nginx ==="
# Use the init config (no SSL) to allow certbot challenge
cp nginx/nginx-init.conf nginx/active.conf
docker compose up -d app

# Start nginx with init config
docker run -d --name nginx-init \
    --network calorie-app_default \
    -p 80:80 \
    -v "$(pwd)/nginx/active.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v calorie-app_certbot-webroot:/var/www/certbot:ro \
    nginx:alpine

sleep 3

echo "=== Step 2: Request certificate ==="
docker run --rm \
    -v calorie-app_certbot-webroot:/var/www/certbot \
    -v calorie-app_certbot-certs:/etc/letsencrypt \
    certbot/certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

echo "=== Step 3: Stop init nginx, start full stack ==="
docker stop nginx-init && docker rm nginx-init
rm nginx/active.conf

echo "=== Step 4: Start full stack with SSL ==="
docker compose up -d

echo ""
echo "Done! Site should be live at https://$DOMAIN"
echo "Certbot will auto-renew certificates every 12 hours."
