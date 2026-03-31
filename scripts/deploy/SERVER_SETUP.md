# Server Setup Guide

One-time steps to prepare the remote server before the CI/CD pipeline can deploy.

## 1. Create a deploy user (optional but recommended)

```bash
sudo adduser deploy
sudo usermod -aG sudo deploy        # only if systemctl restart needs sudo
```

## 2. Clone the repo

```bash
sudo mkdir -p /opt/skyai_cctv
sudo chown deploy:deploy /opt/skyai_cctv
git clone git@github.com:<YOUR_ORG>/<YOUR_REPO>.git /opt/skyai_cctv
```

## 3. Create the virtual environment and install deps

```bash
cd /opt/skyai_cctv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 4. Create the .env file

```bash
# If your repo has .env.example:
cp .env.example .env

# Otherwise, create it manually:
touch .env
nano .env  # fill in DATABASE_URL, SECRET_KEY, CORS_ORIGINS, etc.
```

## 5. Install the systemd service

Edit the placeholders in `scripts/deploy/skyai-cctv.service` first:

```bash
sed -i 's|<APP_DIR>|/opt/skyai_cctv|g; s|<APP_USER>|deploy|g; s|<APP_GROUP>|deploy|g' \
    scripts/deploy/skyai-cctv.service

sudo cp scripts/deploy/skyai-cctv.service /etc/systemd/system/skyai-cctv.service
sudo systemctl daemon-reload
sudo systemctl enable --now skyai-cctv
sudo systemctl status skyai-cctv
```

## 6. Allow the deploy user to restart the service without a password

```bash
sudo visudo
# Add this line (replace 'deploy' and 'skyai-cctv' as needed):
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart skyai-cctv, /bin/systemctl is-active skyai-cctv, /bin/systemctl daemon-reload, /usr/bin/journalctl -u skyai-cctv *
```

## 7. Add the GitHub Actions SSH public key

On the server:
```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "<GITHUB_ACTIONS_PUBLIC_KEY>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Generate a dedicated deploy key pair (on your local machine):
```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/skyai_deploy_key -N ""
# Private key → GitHub secret SSH_PRIVATE_KEY
# Public key  → paste into server ~/.ssh/authorized_keys
```

## 8. Set GitHub Secrets

In your GitHub repo → Settings → Secrets and variables → Actions:

| Secret         | Value                                      |
|----------------|--------------------------------------------|
| `SSH_HOST`     | Server IP or hostname                      |
| `SSH_USER`     | deploy (or your user)                      |
| `SSH_PORT`     | 22 (omit to use default)                   |
| `SSH_PRIVATE_KEY` | Contents of `skyai_deploy_key` (private) |
| `APP_DIR`      | /opt/skyai_cctv                            |
| `SERVICE_NAME` | skyai-cctv                                 |
| `APP_PORT`     | 8000 (omit to use default)                 |

## 9. Verify manually

```bash
curl http://localhost:8000/health
# {"status": "ok", "uptime_seconds": 12.3}
```
