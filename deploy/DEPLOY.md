# Deploying Vyber on EC2 (Docker Compose)

One box, two containers, one data directory. The same images later run
on ECS Fargate unchanged (swap the data mount for EFS and the SQLite
path for the RDS URL in `.env`).

## 1. The box

- EC2 **t4g.small** (ARM, 2 vCPU / 2 GB) or larger, Amazon Linux 2023 or
  Ubuntu 24.04, with a gp3 root/data volume (20 GB is plenty to start).
- Security group: inbound **80** (and 22 from your IP only, or use SSM
  Session Manager and skip 22 entirely). The API port is *not* exposed —
  the UI's nginx proxies to it.

## 2. Install Docker

```bash
# Amazon Linux 2023
sudo dnf install -y docker && sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user   # log out/in after this
# Compose v2 plugin if the distro didn't bundle it:
sudo dnf install -y docker-compose-plugin || \
  sudo yum install -y docker-compose-plugin
docker compose version
```

(Ubuntu: `sudo apt install -y docker.io docker-compose-v2` and enable
the service the same way.)

## 3. Lay out the repos

```bash
cd ~
git clone https://github.com/revanthsamavedam/vyber.git
git clone https://github.com/revanthsamavedam/vyber-ui.git   # sibling!
mkdir -p ~/vyber-data
```

## 4. Configure

```bash
cd ~/vyber/deploy
cp .env.example .env
chmod 600 .env
# edit .env: Azure OpenAI deployment name + endpoint + key
```

## 5. Launch

```bash
docker compose up -d --build
docker compose ps          # both healthy/running
curl http://127.0.0.1:8091/healthz     # API direct (host-local port)
curl http://<box-public-dns>/          # UI through nginx
```

Open the box's address in a browser: chat, send a message, and watch a
run card stream in the Live activity panel.

## 6. Day-2 operations

- **Update:** `git pull` in both repos → `docker compose up -d --build`.
- **Logs:** `docker compose logs -f api` (or `ui`).
- **Backup:** the whole product state is `~/vyber-data` (plus the two
  repos, which are on GitHub). Snapshot the EBS volume, or
  `tar` the data dir — restore = put it back and `compose up`.
- **TLS:** put Caddy in front, an ALB with ACM in front, or
  CloudFront the UI — any of them terminates HTTPS and forwards to
  port 80. Do this before inviting anyone else; the demo auth header is
  a stub, not real SSO.

## Notes

- nginx `proxy_buffering` is **off** for `/api/` on purpose — the live
  activity stream (SSE) dies behind a buffering proxy.
- A second API container is *not* a scale-out yet: the run queue and
  SSE subscribers live in one process. Scaling out means SQS for the
  queue + a pub/sub for events — known step, not done.
