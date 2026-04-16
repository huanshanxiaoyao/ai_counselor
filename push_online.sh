#!/bin/bash
# push_online.sh — 拉取最新代码并重启生产服务
# 用法: bash push_online.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PROJECT_DIR/venv/bin"
SERVICE="ai-counselor"

echo "==> [1/5] 拉取最新代码..."
git -C "$PROJECT_DIR" pull --ff-only

echo "==> [2/5] 安装/更新 Python 依赖..."
"$VENV/pip" install -q -r "$PROJECT_DIR/requirements.txt"

echo "==> [3/5] 执行数据库迁移..."
PYTHONPATH="$PROJECT_DIR" "$VENV/python" "$PROJECT_DIR/backend/manage.py" migrate --noinput

echo "==> [4/5] 收集静态文件..."
PYTHONPATH="$PROJECT_DIR" "$VENV/python" "$PROJECT_DIR/backend/manage.py" collectstatic --noinput

echo "==> [5/5] 重启服务..."
sudo systemctl restart "$SERVICE"
sleep 2
sudo systemctl status "$SERVICE" --no-pager -l | head -15

echo ""
echo "✓ 部署完成。访问 https://makebetter.top/roundtable/"
