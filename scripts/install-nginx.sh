#!/usr/bin/env bash
# Radeski CRM: nginx site crm.devflix.uz + Let's Encrypt certificate.
# Run on the server: sudo bash scripts/install-nginx.sh (from /home/radeski-crm).
# Only ADDS files for this one domain; never touches other sites; nginx is reloaded (not restarted)
# and only after `nginx -t` passes.
set -euo pipefail

DOMAIN=crm.devflix.uz
SITE=/etc/nginx/sites-available/$DOMAIN
UPSTREAM=http://127.0.0.1:9250

if [ -e "$SITE" ]; then
    cp "$SITE" "/root/$DOMAIN.nginx.bak-$(date +%F-%H%M%S)"
fi
mkdir -p /var/www/certbot

proxy_block() {
cat <<EOF
    client_max_body_size 50m;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass $UPSTREAM;
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        # WebSocket: softphone (/ws), live updates
        proxy_set_header Upgrade    \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }
EOF
}

# 1) plain HTTP first, so certbot can prove the domain
{
    echo "server {"
    echo "    listen 80;"
    echo "    listen [::]:80;"
    echo "    listen 192.168.0.101:80;"
    echo "    server_name $DOMAIN;"
    proxy_block
    echo "}"
} > "$SITE"
ln -sf "$SITE" "/etc/nginx/sites-enabled/$DOMAIN"
if ! nginx -t; then
    # never leave a broken file behind: the next reload of ANY site would fail
    rm -f "/etc/nginx/sites-enabled/$DOMAIN" "$SITE"
    echo "!! nginx -t failed; the CRM site was removed again, nothing was reloaded" >&2
    exit 1
fi
systemctl reload nginx
cp "$SITE" "$SITE.http-only"
echo "== HTTP site enabled"

# 2) certificate (webroot: nginx keeps serving everything else meanwhile)
certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --keep-until-expiring
echo "== certificate ready"

# 3) final config: HTTPS (also on the LAN address, like the other sites) + redirect + HSTS
{
    echo "server {"
    echo "    listen 443 ssl;"
    echo "    listen [::]:443 ssl;"
    echo "    listen 192.168.0.101:443 ssl;"
    echo "    server_name $DOMAIN;"
    echo "    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;"
    echo "    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;"
    echo "    include /etc/letsencrypt/options-ssl-nginx.conf;"
    echo "    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;"
    echo "    add_header Strict-Transport-Security \"max-age=31536000\" always;"
    proxy_block
    echo "}"
    echo ""
    echo "server {"
    echo "    listen 80;"
    echo "    listen [::]:80;"
    echo "    listen 192.168.0.101:80;"
    echo "    server_name $DOMAIN;"
    echo "    location /.well-known/acme-challenge/ { root /var/www/certbot; }"
    echo "    location / { return 301 https://\$host\$request_uri; }"
    echo "}"
} > "$SITE.new"
mv "$SITE.new" "$SITE"
if nginx -t; then
    systemctl reload nginx
    echo "== HTTPS site enabled: https://$DOMAIN"
else
    mv "$SITE.http-only" "$SITE"
    nginx -t && systemctl reload nginx
    echo "!! HTTPS config failed nginx -t; the working HTTP-only site was restored" >&2
    exit 1
fi
rm -f "$SITE.http-only"
