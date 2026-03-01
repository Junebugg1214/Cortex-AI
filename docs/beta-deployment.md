# Beta Deployment Guide

> The simplest path to getting Cortex-AI running in production for a beta.
> One cheap server, everything in Docker, automatic HTTPS.

**Cost:** ~$10/month | **Time:** ~30 minutes

```
You -> Domain -> DigitalOcean VPS -> Caddy (auto-HTTPS) -> Cortex
```

---

## Step 1: Buy a Domain (~2 min)

Go to [Namecheap](https://namecheap.com) or [Porkbun](https://porkbun.com) and buy a domain. Cheapest option is fine (~$8/year).

Don't configure anything yet — just buy it.

---

## Step 2: Create a Server (~5 min)

1. Go to [DigitalOcean](https://digitalocean.com) and create an account
2. Click **Create > Droplets**
3. Pick these settings:
   - **Region:** Closest to you (e.g., New York)
   - **Image:** Ubuntu 24.04
   - **Size:** Basic, $6/mo (1 GB RAM, 25 GB disk) — plenty for beta
   - **Authentication:** Password (simpler) or SSH key (more secure)
4. Click **Create Droplet**
5. Copy the **IP address** it gives you (e.g., `143.198.xxx.xxx`)

---

## Step 3: Point Your Domain to the Server (~3 min)

Go back to where you bought your domain. Find **DNS settings** and add two records:

| Type | Name  | Value                             |
|------|-------|-----------------------------------|
| A    | `@`   | `143.198.xxx.xxx` (your droplet IP) |
| A    | `www` | `143.198.xxx.xxx` (your droplet IP) |

Save. Takes 5-30 minutes to propagate (you can keep going while it does).

---

## Step 4: Set Up the Server (~15 min)

Open your terminal and SSH into the server:

```bash
ssh root@143.198.xxx.xxx
```

Then run these commands one at a time.

### Install Docker

```bash
curl -fsSL https://get.docker.com | sh
```

### Create a folder for Cortex

```bash
mkdir -p /opt/cortex && cd /opt/cortex
```

### Create your context file

This is your data file — start with an empty one:

```bash
echo '{"nodes":[],"edges":[]}' > context.json
```

### Create a Caddyfile

This gives you automatic HTTPS — no certificate management needed:

```
yourdomain.com {
    reverse_proxy cortex:8421
}
```

Replace `yourdomain.com` with your actual domain. Save this as `Caddyfile`:

```bash
cat > Caddyfile << 'EOF'
yourdomain.com {
    reverse_proxy cortex:8421
}
EOF
```

### Create docker-compose.yml

```bash
cat > docker-compose.yml << 'EOF'
services:
  cortex:
    build: https://github.com/Junebugg1214/Cortex-AI.git
    restart: unless-stopped
    volumes:
      - cortex-data:/data
      - ./context.json:/data/context.json
    command: >
      cortex serve /data/context.json
        --storage sqlite
        --db-path /data/cortex.db
        --store-dir /data/.cortex
        --enable-webapp
        --enable-sse
        --hsts
        --port 8421

  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
      - caddy-config:/config

volumes:
  cortex-data:
  caddy-data:
  caddy-config:
EOF
```

### Launch everything

```bash
docker compose up -d
```

Wait about 60 seconds for it to build and start.

---

## Step 5: Verify It Works

Open your browser and go to:

```
https://yourdomain.com/app
```

You should see the Cortex dashboard with a login screen.

### Troubleshooting commands

```bash
# Check if containers are running
docker compose ps

# See logs if something looks wrong
docker compose logs -f

# Check if the API responds
curl https://yourdomain.com/.well-known/cortex
```

---

## Common Tasks

### View logs

```bash
cd /opt/cortex
docker compose logs -f cortex
```

### Restart the server

```bash
cd /opt/cortex
docker compose restart
```

### Update to the latest version

```bash
cd /opt/cortex
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Back up your data

```bash
# Copy the SQLite database out of the Docker volume
docker compose cp cortex:/data/cortex.db ./cortex-backup.db
```

---

## What You Get

- **HTTPS** — automatic, free, auto-renewing via Caddy + Let's Encrypt
- **Dashboard UI** at `/app` — upload, memory graph, sharing, profile
- **Full API** at all standard endpoints
- **SQLite storage** — survives restarts via Docker volume
- **Security** — rate limiting, CSRF, HSTS, security headers all enabled
- **SSE** — real-time event stream at `/events`

---

## What This Does NOT Include

These are things you can add later as you grow beyond beta:

| Feature | Why skip for beta | When to add |
|---------|-------------------|-------------|
| **Automated backups** | Manual `docker compose cp` is fine | When you have real user data you can't lose |
| **Monitoring (Prometheus/Grafana)** | Not needed until you have traffic | When you want uptime alerts and dashboards |
| **OAuth (Google/GitHub login)** | Password auth works for small beta | When you have multiple users |
| **PostgreSQL** | SQLite handles hundreds of users | When you need multiple server instances |
| **CDN** | Latency is fine for a single region | When users are spread globally |
| **Tracing** | Overkill for beta | When you need to debug distributed issues |

---

## Next Steps After Beta

When you're ready to scale beyond beta, see the full [Deployment Guide](deployment.md) which covers:

- PostgreSQL backend with connection pooling
- Prometheus + Grafana monitoring stack
- OAuth provider setup
- Kubernetes deployment with Helm
- Terraform modules for AWS and GCP
- Systemd service for non-Docker VPS deployments
