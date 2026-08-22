#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/enrui-ai-commerce-agent"
REPO_DIR="$APP_DIR/repository"
SHARED_DIR="$APP_DIR/shared"
ENV_FILE="$SHARED_DIR/.env"
REPO_URL="https://github.com/Dreamsmama/enrui-ai-commerce-agent.git"
BRANCH="${DEPLOY_BRANCH:-main}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 执行：sudo bash deploy.sh"
  exit 1
fi

install_runtime() {
  if ! command -v git >/dev/null; then
    apt-get update
    apt-get install -y git ca-certificates curl
  fi
  if ! command -v docker >/dev/null; then
    apt-get update
    apt-get install -y docker.io
    apt-get install -y docker-compose-v2 || apt-get install -y docker-compose
    systemctl enable --now docker
  fi
}

compose() {
  if docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi
}

install_runtime
mkdir -p "$SHARED_DIR"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
else
  git -C "$REPO_DIR" fetch origin "$BRANCH"
  git -C "$REPO_DIR" checkout "$BRANCH"
  git -C "$REPO_DIR" pull --ff-only origin "$BRANCH"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$REPO_DIR/deploy/.env.production.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "已创建 $ENV_FILE"
  echo "请填写其中所有 FILL_ 项，然后重新运行：bash $REPO_DIR/deploy.sh"
  exit 2
fi

if grep -q 'FILL_' "$ENV_FILE"; then
  echo "$ENV_FILE 仍包含 FILL_ 占位符，拒绝部署"
  exit 2
fi

cd "$REPO_DIR"
export APP_ENV_FILE="$ENV_FILE"
compose build --pull
compose run --rm backend python scripts/init_deployment.py
compose up -d --remove-orphans

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1/api/health >/dev/null; then
    docker image prune -f >/dev/null
    echo "部署成功：http://$(hostname -I | awk '{print $1}')"
    exit 0
  fi
  sleep 2
done

compose ps
compose logs --tail=120 backend frontend
echo "部署后健康检查失败"
exit 1
