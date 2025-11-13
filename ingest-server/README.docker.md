# Docker Setup for Ingest Server

Docker setup untuk menjalankan ingest-server dengan Caddy (HTTPS/HTTP/2) menggunakan Docker Compose.

## Quick Start

### Prerequisites

- Docker (20.10+)
- Docker Compose (v2.0+ atau docker-compose v1.29+)

### Start Services

```bash
# Build and start all services
./docker-run.sh

# Or manually
docker compose up -d --build
```

Ini akan:
1. ✅ Build Docker image untuk ingest-server
2. ✅ Build Docker image untuk Caddy
3. ✅ Start kedua service dengan HTTPS/HTTP/2

### Access Endpoints

- **HTTPS/HTTP/2**: `https://localhost:3090`
- **Direct HTTP**: `http://localhost:3091` (optional, for direct access)
- **Health Check**: `curl -k https://localhost:3090/health`
  - Returns JSON: `{"status":"running","service":"binary-stream-broker","version":"0.1.0","active_streams":0,"total_connections":0}`

## Docker Compose Commands

### Start Services
```bash
docker compose up -d
```

### Stop Services
```bash
docker compose down
```

### View Logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f ingest-server
docker compose logs -f caddy
```

### Rebuild After Code Changes
```bash
docker compose up -d --build
```

### Check Service Status
```bash
docker compose ps
```

## Configuration

### Environment Variables

Edit `docker-compose.yml` untuk mengubah environment variables:

```yaml
services:
  ingest-server:
    environment:
      - BIND_ADDRESS=0.0.0.0
      - PORT=3091
      - RUST_LOG=ingest_server=info
```

### Custom Caddyfile

1. Edit `Caddyfile` sesuai kebutuhan
2. Rebuild: `docker compose up -d --build`

### Using .env File

1. Copy `docker-compose.override.yml.example` to `docker-compose.override.yml`
2. Uncomment volume mount untuk `.env`
3. Restart: `docker compose restart ingest-server`

## Architecture

```
┌─────────────┐      HTTPS/HTTP/2      ┌──────────────┐      HTTP/1.1      ┌─────────────┐
│   Producer  │ ───────────────────> │    Caddy     │ ─────────────────> │    Axum     │
│  (Python)   │  POST /ingest/:id    │  (Port 3090) │   (Port 3091)      │   Broker    │
│             │                       │  Container   │                    │  Container   │
└─────────────┘                       └──────────────┘                    └─────────────┘
                                             │                                    │
                                             │ WSS (WebSocket)                    │
                                             │                                    │
                                             ▼                                    │
                                      ┌─────────────┐                            │
                                      │   Browser   │ ◄──────────────────────────┘
                                      │   Client    │      WebSocket
                                      │  (HTML/JS)  │      /ws/:stream_id
                                      │             │      Real-time: FPS, MB/s
                                      └─────────────┘
```

**Container Details:**
- **ingest-server**: Axum Rust server (internal, port 3091)
- **caddy**: Reverse proxy with HTTPS/HTTP/2 (external, port 3090)
- **Network**: `broker-network` (bridge, internal communication)
- **Volumes**: `caddy-data`, `caddy-config` (persistent storage)

## Troubleshooting

### Services Not Starting

```bash
# Check logs
docker compose logs

# Check if ports are in use
lsof -i :3090 -i :3091
```

### Caddy Not Starting

```bash
# Check Caddy logs
docker compose logs caddy

# Validate Caddyfile
docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile
```

### Rebuild Everything

```bash
# Stop and remove containers, volumes
docker compose down -v

# Rebuild from scratch
docker compose build --no-cache

# Start again
docker compose up -d
```

### Access Container Shell

```bash
# Ingest server
docker compose exec ingest-server sh

# Caddy
docker compose exec caddy sh
```

## Production Deployment

Untuk production:

1. **Update Caddyfile** dengan domain yang sebenarnya
2. **Set environment variables** untuk production
3. **Use Docker secrets** untuk sensitive data
4. **Configure logging** dengan proper log rotation
5. **Set resource limits** in docker-compose.yml

Example production Caddyfile:
```caddy
your-domain.com {
    reverse_proxy ingest-server:3091 {
        header_up Connection {>Connection}
        header_up Upgrade {>Upgrade}
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_up X-Forwarded-For {remote}
        header_up X-Forwarded-Proto {scheme}
        transport http {
            versions h2c 1.1
        }
    }
}
```

## Volumes

Docker Compose creates volumes for:
- `caddy-data`: Caddy certificate storage
- `caddy-config`: Caddy configuration cache

These persist between container restarts.

## Health Monitoring

### Health Check Endpoint

Both services have health checks:
- **Ingest Server**: `curl http://localhost:3091/health`
- **Through Caddy**: `curl -k https://localhost:3090/health`

Health check returns:
```json
{
  "status": "running",
  "service": "binary-stream-broker",
  "version": "0.1.0",
  "active_streams": 1,
  "total_connections": 2,
  "endpoints": {
    "ingest": "POST /ingest/:stream_id",
    "websocket": "GET /ws/:stream_id",
    "health": "GET /health"
  }
}
```

### Monitoring Commands

```bash
# Check container health
docker compose ps

# View real-time logs
docker compose logs -f

# Check service health
curl -k https://localhost:3090/health | jq
```

