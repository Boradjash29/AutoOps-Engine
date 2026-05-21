# 🚀 AutoOps Engine
> An advanced, AI-driven DevOps monitoring platform designed for real-time observability, automated security auditing, and intelligent infrastructure auto-healing.

![AutoOps Engine Dashboard](https://img.shields.io/badge/Status-Active-success)
![Docker](https://img.shields.io/badge/Docker-Containerized-blue)
![Python](https://img.shields.io/badge/Python-FastAPI%20%7C%20Flask-blueviolet)
![Machine Learning](https://img.shields.io/badge/AI-Isolation%20Forest-orange)

The **AutoOps Engine** is a comprehensive, microservice-based command center for your servers. It replaces fragmented monitoring tools by combining hardware metrics, container orchestration, AI anomaly detection, and security auditing into a single unified platform.

---

## ✨ Core Features
* ⚡ **Real-Time WebSockets:** Live dashboard updates with zero page polling.
* 📈 **Prometheus & Grafana:** Professional Time-Series Database (TSDB) integration with pre-provisioned data visualization.
* 🤖 **AI Anomaly Detection:** Machine learning (`scikit-learn` Isolation Forest) that learns your server's historical behavior patterns to predict failures before they happen.
* 🐳 **Auto-Healing Containers:** Automatically detects crashed Docker containers and restarts them within seconds.
* 🌍 **Distributed SSH Agents:** Add unlimited remote Linux servers and monitor them all from a single central command center.
* 🔒 **Security Auditing:** One-click vulnerability scans detecting open ports, root-running containers, world-writable files, and insecure SSH configurations.
* 📱 **Telegram Integrations:** Receive instant, noise-free alerts for critical system crashes and periodic 10-minute health reports.

---

## 🏗 Architecture & Services

AutoOps Engine is fully containerized and runs securely as a non-root user via Docker Compose.

| Service | Container Name | Port | Description |
|---------|---------------|------|-------------|
| **Dashboard** | `autoops-dashboard` | `:5000` | Serves the responsive, dark-theme Cyberpunk UI. |
| **API Backend** | `autoops-api` | `:8000` | Core FastAPI application handling WebSockets, DB transactions, and AI inference. |
| **Sys Monitor** | `autoops-monitor` | Internal | Hardware metric collection (CPU/RAM/Disk/Network). |
| **Docker Watcher**| `autoops-docker-monitor`| Internal | Watches for crashed containers, triggers auto-restarts and alerts. |
| **Prometheus** | `autoops-prometheus` | `:9090` | Scrapes raw metrics directly from the API backend. |
| **Grafana** | `autoops-grafana` | `:3000` | Professional metric dashboarding (Default: `admin` / `autoops123`). |
| **Nginx Proxy** | `autoops-nginx` | `:80` | Production reverse proxy (Optional, used via `deploy.sh`). |

---

## 🚀 Quick Start (Local Development)

1. **Clone & Configure**
   ```bash
   git clone https://github.com/your-username/AutoOps-Engine.git
   cd AutoOps-Engine
   cp .env.example .env
   ```
   *(Fill in your Telegram Bot credentials in the `.env` file)*

2. **Launch the Cluster**
   ```bash
   docker-compose up --build -d
   ```

3. **Access the Platform**
   * **Dashboard:** [http://localhost:5000](http://localhost:5000)
   * **API Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
   * **Grafana:** [http://localhost:3000](http://localhost:3000)

---

## 🌍 Production Deployment
A production-ready deployment script is included, which automatically installs Docker, configures Nginx, fixes host permissions, and exposes the engine on standard port 80.

To deploy on a remote VPS (AWS, DigitalOcean, etc.):
```bash
chmod +x deploy.sh
./deploy.sh
```

---
*Built as a showcase for Advanced DevOps & Python Engineering.*
# AutoOps-Engine
# AutoOps-Engine
