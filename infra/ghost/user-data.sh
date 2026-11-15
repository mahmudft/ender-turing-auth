#!/usr/bin/env bash
# cloud-init user data: installs Docker and runs Ghost + MySQL behind a
# Cloudflare Tunnel. Nothing listens on a public port; the tunnel connects
# outbound to Cloudflare.
#
# deploy.sh replaces __CF_TUNNEL_TOKEN__ and __GHOST_URL__ before upload.
# Both empty -> Cloudflare "quick tunnel" (random *.trycloudflare.com URL).
set -euo pipefail
exec > >(tee -a /var/log/ghost-setup.log) 2>&1

CF_TUNNEL_TOKEN="__CF_TUNNEL_TOKEN__"
GHOST_URL="__GHOST_URL__"
APP_DIR=/opt/ghost

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y docker.io docker-compose-v2 curl jq openssl
systemctl enable --now docker

mkdir -p "$APP_DIR"
cd "$APP_DIR"

# Secrets are generated on the VM and never leave it.
if [[ ! -f .env ]]; then
  umask 077
  cat > .env <<EOF
MYSQL_ROOT_PASSWORD=$(openssl rand -hex 24)
MYSQL_PASSWORD=$(openssl rand -hex 24)
CF_TUNNEL_TOKEN=${CF_TUNNEL_TOKEN}
GHOST_URL=${GHOST_URL}
EOF
fi

cat > compose.yml <<'EOF'
services:
  db:
    image: mysql:8.0
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ghost
      MYSQL_USER: ghost
      MYSQL_PASSWORD: ${MYSQL_PASSWORD}
    volumes:
      - db:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "--silent"]
      interval: 5s
      retries: 30

  ghost:
    image: ghost:6-alpine
    restart: always
    depends_on:
      db:
        condition: service_healthy
    environment:
      url: ${GHOST_URL}
      database__client: mysql
      database__connection__host: db
      database__connection__user: ghost
      database__connection__password: ${MYSQL_PASSWORD}
      database__connection__database: ghost
    volumes:
      - ghost:/var/lib/ghost/content
    # No published ports: only the tunnel container can reach Ghost.

  tunnel:
    image: cloudflare/cloudflared:latest
    restart: always
    command: ${TUNNEL_COMMAND}
    ports:
      # Metrics only, bound to loopback; used to read the quick-tunnel URL.
      - "127.0.0.1:20241:20241"

volumes:
  db:
  ghost:
EOF

# start.sh runs on every boot. A quick tunnel gets a new hostname each time
# it starts, so Ghost's url is refreshed to match before Ghost starts.
cat > start.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/ghost
set -a; . ./.env; set +a

if [[ -n "$CF_TUNNEL_TOKEN" ]]; then
  export TUNNEL_COMMAND="tunnel --metrics 0.0.0.0:20241 run --token $CF_TUNNEL_TOKEN"
  url="$GHOST_URL"
else
  export TUNNEL_COMMAND="tunnel --metrics 0.0.0.0:20241 --url http://ghost:2368"
  export GHOST_URL=http://localhost:2368  # placeholder until the tunnel is up
  docker compose up -d --force-recreate tunnel
  url=""
  for _ in $(seq 1 60); do
    host=$(curl -fsS http://127.0.0.1:20241/quicktunnel 2>/dev/null | jq -r '.hostname // empty' || true)
    if [[ -n "$host" ]]; then url="https://$host"; break; fi
    sleep 2
  done
  [[ -n "$url" ]] || { echo "quick tunnel did not report a hostname" >&2; exit 1; }
fi

export GHOST_URL="$url"
# Without --force-recreate an already running quick tunnel keeps its
# hostname; Ghost is recreated because its url changed.
docker compose up -d
echo "$url" > /opt/ghost/url
echo "Ghost is available at $url (admin: $url/ghost)"
EOF
chmod 700 start.sh

cat > /etc/systemd/system/ghost.service <<'EOF'
[Unit]
Description=Ghost behind Cloudflare Tunnel
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/ghost/start.sh

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now ghost.service
