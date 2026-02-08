#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Polymarket Trading Bot — DigitalOcean Deploy Script
#
# Run this on your Droplet after cloning the repo:
#   bash deploy.sh
#
# It handles: swap setup, data directory, .env, Docker build & launch
# ─────────────────────────────────────────────────────────────
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}✅ $1${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Polymarket Trading Bot — Deploy"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Step 1: Swap file (prevents OOM during Docker build) ──────
echo "── Step 1: Checking swap..."
if [ "$(swapon --show | wc -l)" -eq 0 ]; then
    echo "   No swap detected. Creating 2GB swap file..."
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    # Persist across reboots
    if ! grep -q '/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
    info "Swap enabled (2GB)"
else
    info "Swap already active ($(free -h | awk '/Swap/{print $2}'))"
fi

# ── Step 2: Data directory ────────────────────────────────────
echo ""
echo "── Step 2: Setting up data directory..."
mkdir -p data

# Copy bot_config.json into data/ if it exists at project root but not in data/
if [ -f "bot_config.json" ] && [ ! -f "data/bot_config.json" ]; then
    cp bot_config.json data/bot_config.json
    info "Copied bot_config.json → data/"
elif [ -f "data/bot_config.json" ]; then
    info "data/bot_config.json already exists"
else
    warn "No bot_config.json found — bot will create one with defaults"
fi

info "Data directory ready"

# ── Step 3: Environment file ──────────────────────────────────
echo ""
echo "── Step 3: Checking .env file..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        warn "Created .env from template — you MUST edit it with your keys!"
        echo ""
        echo "   Required:"
        echo "   - POLYMARKET_PRIVATE_KEY  (hex string, no 0x prefix)"
        echo "   - POLYMARKET_PROXY_ADDRESS (CLOB operator address)"
        echo ""
        read -p "   Edit .env now? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            ${EDITOR:-nano} .env
        else
            warn "Remember to edit .env before starting the bot in live mode!"
        fi
    else
        error ".env.example not found! Make sure you're in the repo root."
        exit 1
    fi
else
    info ".env file exists"
fi

# ── Step 4: Docker build ──────────────────────────────────────
echo ""
echo "── Step 4: Building Docker image (this takes 2-5 minutes)..."
echo "   Using swap to prevent OOM during npm/pip install..."
docker compose build --progress=plain 2>&1 | tail -20
info "Docker build complete"

# ── Step 5: Launch services ───────────────────────────────────
echo ""
echo "── Step 5: Starting services..."
docker compose down 2>/dev/null || true
docker compose up -d
info "Services started"

# ── Step 6: Health check ──────────────────────────────────────
echo ""
echo "── Step 6: Waiting for bot to come up..."
MAX_WAIT=30
for i in $(seq 1 $MAX_WAIT); do
    if curl -sf http://localhost/api/status > /dev/null 2>&1; then
        echo ""
        info "API responding!"
        echo ""
        echo "   Status: $(curl -s http://localhost/api/status)"
        echo ""
        info "Dashboard: http://$(curl -s ifconfig.me 2>/dev/null || echo '<your-ip>')"
        echo ""
        echo "═══════════════════════════════════════════════════"
        echo "  Deployment complete! 🚀"
        echo ""
        echo "  Useful commands:"
        echo "    docker compose logs -f bot     # Watch bot logs"
        echo "    docker compose restart bot     # Restart bot"
        echo "    docker compose down            # Stop everything"
        echo "    docker compose up -d           # Start again"
        echo "═══════════════════════════════════════════════════"
        exit 0
    fi
    printf "   Waiting... (%d/%d)\r" "$i" "$MAX_WAIT"
    sleep 2
done

echo ""
error "Bot didn't respond within ${MAX_WAIT}s. Checking logs..."
echo ""
echo "── Bot container logs (last 30 lines):"
docker compose logs --tail=30 bot
echo ""
echo "── Container status:"
docker compose ps
echo ""
error "Something went wrong. Check the logs above for errors."
exit 1
