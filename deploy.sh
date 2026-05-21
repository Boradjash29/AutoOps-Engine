#!/bin/bash
set -e

echo "🚀 Starting AutoOps Engine Production Deployment..."

# 1. Install Docker if not installed
if ! command -v docker &> /dev/null; then
    echo "📦 Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
else
    echo "✅ Docker is already installed."
fi

# 2. Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️ No .env file found. Creating a default one..."
    echo "TELEGRAM_TOKEN=" > .env
    echo "TELEGRAM_CHAT_ID=" >> .env
    echo "CPU_THRESHOLD=85" >> .env
    echo "RAM_THRESHOLD=90" >> .env
    echo "DISK_THRESHOLD=90" >> .env
    echo "GRAFANA_ADMIN_PASSWORD=secure_password_123" >> .env
    echo "Please edit the .env file with your real Telegram credentials before running this script again."
    exit 1
fi

# 3. Create Nginx service in docker-compose.yml if it doesn't exist
if ! grep -q "nginx:" docker-compose.yml; then
    echo "🔧 Adding Nginx Reverse Proxy to docker-compose.yml..."
    cat <<EOT >> docker-compose.yml

  nginx:
    build: ./nginx
    container_name: autoops-nginx
    ports:
      - "80:80"
    restart: always
    depends_on:
      - api
      - dashboard
      - grafana
EOT
fi

# 4. Set correct permissions for logs directory
echo "🔐 Setting permissions for logs..."
mkdir -p logs
sudo chown -R 1000:1000 logs/

# 5. Build and Start
echo "🏗️ Building and starting containers..."
docker compose down
docker compose up --build -d

echo ""
echo "✅ Deployment Complete!"
echo "🌐 Your AutoOps Engine is now live on port 80!"
echo "If you have a domain name, point it to this server's IP address."
