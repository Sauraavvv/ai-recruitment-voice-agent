# Deploying CallZest

One Linux server runs everything with Docker: the website, the API, the background worker,
the database and Redis. [Caddy](https://caddyserver.com) sits in front and handles HTTPS on its
own (free certificates, renewed automatically).

```
https://callzest.in      → website (it forwards /api to the backend)
https://api.callzest.in  → backend: phone call status updates and live call audio
```

Only ports 80 and 443 are open to the internet. The database, Redis, the backend and the
website talk to each other on Docker's internal network.

## What you need

- A **Linux server** (Ubuntu 24.04), ideally in **Mumbai** (lower delay on calls to Indian
  numbers): 2 vCPU and 4 GB RAM minimum, 8 GB recommended, 40 GB disk.
- The domain (**callzest.in**) and access to its DNS settings.
- Your provider keys (AI, speech, telephony): the ones in your development `.env`.

## 1. Point the domain at the server

In the domain registrar's panel (BigRock: *Domains → callzest.in → Manage DNS*) add three
**A records**, each with the server's public IP address:

| Host  | Type | Value          |
|-------|------|----------------|
| `@`   | A    | server's IP    |
| `www` | A    | server's IP    |
| `api` | A    | server's IP    |

Remove any existing A or CNAME records for `@`, `www` or `api` that point elsewhere (parking
pages). Changes take a few minutes to a few hours; `ping api.callzest.in` shows the server's IP
once it's done.

## 2. Prepare the server

```bash
# Docker (official script), then let your user run it
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out and back in

# Firewall: SSH and the web only
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw allow 443/udp
sudo ufw enable

sudo apt-get install -y make git
```

## 3. Get the code and fill in the settings

```bash
git clone <your repository URL> callzest && cd callzest
cp deploy/production.env.example .env
nano .env
```

In `.env`:

- `APP_SECRET_KEY`: run `openssl rand -hex 32` and paste the result.
- `POSTGRES_PASSWORD`: run `openssl rand -hex 24` and paste the result.
- `SIGNUP_ENABLED`: `true` if new companies may create accounts at `/signup` themselves.
- Add the provider keys from your development `.env` (same names). **Don't** copy
  `DATABASE_URL`, `REDIS_URL`, `APP_ENV`, `FRONTEND_*` or `PUBLIC_BACKEND_URL`: production
  sets those itself.

Keep `.env` private: it holds every secret. Use new secrets, not the development ones.

## 4. Start

```bash
make prod-up      # builds and starts everything; the first build takes several minutes
make prod-ps      # every service should be "Up" (postgres and redis "healthy")
```

Database migrations run automatically every time the backend starts. Caddy fetches the HTTPS
certificates within a minute of the DNS pointing at the server.

## 5. First login

```bash
make prod-user email=you@example.com name="Your Name" role=super_admin org="Your Company"
```

It asks for the password. Then open **https://callzest.in/login**.

## 6. Connect the phone calls

In your telephony provider's dashboard, point the call app and its status callback URLs at
`https://api.callzest.in` (the same paths as during development, with the new address). Then
open **https://callzest.in/status**: every service and provider should show as working.

## Everyday commands

| Command | What it does |
|---|---|
| `make prod-up` | Start, or update after `git pull` (rebuilds what changed) |
| `make prod-ps` | Services and their state |
| `make prod-logs` / `make prod-logs s=backend` | Follow the logs (all, or one service) |
| `make prod-backup` | Database backup to `backups/callzest-<date>.sql.gz` |
| `make prod-down` | Stop everything (data and certificates stay) |

### Updating to a new version

```bash
git pull
make prod-backup   # just in case
make prod-up
```

### Backups

Run `make prod-backup` daily, for example from cron (`crontab -e`):

```
0 2 * * * cd /home/<you>/callzest && make prod-backup >/dev/null 2>&1
```

Copy the files in `backups/` off the server now and then. To restore one into an empty
database:

```bash
gunzip -c backups/callzest-<date>.sql.gz | docker compose -p callzest -f docker-compose.prod.yml exec -T postgres psql -U callzest callzest
```

## If something doesn't work

- **The site doesn't open, or the browser warns about the certificate**: the DNS doesn't
  point at the server yet (`ping callzest.in`), or ports 80 and 443 are blocked
  (`sudo ufw status`). `make prod-logs s=caddy` shows certificate errors.
- **The backend keeps restarting**: `make prod-logs s=backend`. A setting is missing or wrong;
  the message says which (for example `APP_SECRET_KEY looks like a placeholder`).
- **Calls don't connect or don't update**: the telephony dashboard still points at the old
  development address, or a provider key is missing (`/status`).
