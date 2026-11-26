# Deploying CallZest

Two ways, same addresses:

```
https://callzest.in      → website (it forwards /api to the backend)
https://api.callzest.in  → backend: phone call status updates and live call audio
```

- **Free hosting** (now): the website on Vercel, the backend on Render's free tier.
- **Your own server** (later): everything on one Linux server with Docker
  ([below](#your-own-server)).

# Free hosting: Vercel + Render

The website runs on **Vercel** (free Hobby plan: personal, non-commercial projects). The
backend runs on **Render**'s free tier from [`render.yaml`](../render.yaml): one web service
that runs the API and the background worker together (`RUN_WORKER_IN_API=true`), a free
Postgres and a free Key Value (Redis), in Singapore.

What the free tier means:

- The backend **sleeps after 15 idle minutes**; the next visit waits about a minute while it
  wakes up. Calls and scheduled retries only run while it's awake.
- The free **database expires 30 days** after it's created (Render emails before). Create a
  new one then (*New → Postgres*, free) and point `DATABASE_URL` at it; the app sets up its
  tables on start. The data doesn't carry over.

## 1. Backend on Render

1. Sign in at [render.com](https://render.com) with GitHub.
2. *New → Blueprint* → choose this repository. Render reads `render.yaml` and lists
   `callzest-api`, `callzest-redis` and `callzest-db`.
3. It asks for the provider keys: paste them from your development `.env` (same names).
   Leave the ones you don't use empty. *Apply*.
4. The first build takes several minutes. When `callzest-api` shows **Live**, open
   `https://callzest-api.onrender.com/health` (your service's address is at the top of its
   page): it answers `{"data":{"status":"ok",…}}`.
5. *callzest-api → Settings → Custom Domains → Add* `api.callzest.in`. Render shows a
   **CNAME** target (like `callzest-api.onrender.com`): add it at BigRock (step 3).

## 2. Website on Vercel

1. Sign in at [vercel.com](https://vercel.com) with GitHub. *Add New → Project* → import
   this repository.
2. **Root Directory:** `frontend` (Vercel detects Next.js).
3. **Environment Variables:** `BACKEND_INTERNAL_URL` = `https://api.callzest.in`
   (until that address works, use the Render address, e.g.
   `https://callzest-api.onrender.com`, and redeploy after changing it: it's read at build
   time).
4. *Deploy*.
5. *Project → Settings → Domains → Add* `callzest.in`, and `www.callzest.in` redirecting to it.
   Vercel shows the DNS records to add (step 3).

## 3. DNS at BigRock

*Domains → callzest.in → Manage DNS*. Use exactly the values Vercel and Render show; they
look like this:

| Host  | Type  | Value                                  | For        |
|-------|-------|----------------------------------------|------------|
| `@`   | A     | `76.76.21.21`                          | Vercel     |
| `www` | CNAME | `cname.vercel-dns.com`                 | Vercel     |
| `api` | CNAME | `callzest-api.onrender.com`            | Render     |

Remove other records for `@`, `www` or `api` (parking pages). Vercel and Render then issue the
HTTPS certificates themselves; it can take from minutes to a few hours.

## 4. First login

Sign-up is off (`SIGNUP_ENABLED=false`): a public sign-up could place real calls on your
accounts. To create your own account once:

1. Render → `callzest-api` → *Environment* → set `SIGNUP_ENABLED` to `true` → save (it
   restarts).
2. Open `https://callzest.in/signup` and create your company and login.
3. Set `SIGNUP_ENABLED` back to `false`.

Then add recruiter logins from the app (*Accounts*).

## 5. Phone calls

In the telephony provider's dashboard, point the call app and status callback URLs at
`https://api.callzest.in`. Wake the backend (open the site) before a test call.

---

# Your own server

One Linux server runs everything with Docker: the website, the API, the background worker,
the database and Redis. [Caddy](https://caddyserver.com) sits in front and handles HTTPS on its
own (free certificates, renewed automatically).

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
