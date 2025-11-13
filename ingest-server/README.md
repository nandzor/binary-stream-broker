# Axum Ingest Server

High-performance Rust broker service that receives binary frames from producers and broadcasts them to multiple WebSocket clients in real-time.

## Features

- Multi-channel support (multiple streams via `:stream_id`)
- In-memory Pub/Sub pattern using Tokio broadcast channels
- WebSocket streaming with automatic backpressure handling
- HTTP/2 ingest endpoint for producers
- Zero-copy frame forwarding using `Bytes`
- Graceful handling of client lag and disconnections

## Architecture

The server implements a "dumb pipe" broker pattern:

1. **Ingest Endpoint** (`POST /ingest/:stream_id`): Receives WebP frames from Python producer
2. **WebSocket Endpoint** (`GET /ws/:stream_id`): Streams frames to connected clients
3. **Broadcast Channel**: In-memory channel that fans out frames to all subscribers

Channels are created lazily when the first WebSocket client connects to a stream.

## Installation

### Build Dependencies

```bash
cargo build
```

### Build Release Version (Optimized)

```bash
cargo build --release
```

## Usage

### Option 1: Docker (Recommended)

```bash
# Build and start with Docker Compose
./docker-run.sh

# Or manually
docker compose up -d --build
```

This will:
- ✅ Build Docker images for ingest-server and Caddy
- ✅ Start both services with HTTPS/HTTP/2
- ✅ Handle TLS termination automatically

**Access**: `https://localhost:3090` (HTTP/2 enabled)

See [README.docker.md](README.docker.md) for detailed Docker documentation.

### Option 2: Native with Caddy

```bash
# One command to setup and run with Caddy
USE_CADDY=true ./run.sh
```

This automatically:
- ✅ Installs Caddy if needed
- ✅ Starts Axum on internal port (3091)
- ✅ Starts Caddy with HTTPS/HTTP/2 on port 3090
- ✅ Handles TLS termination

### Option 3: Direct HTTP Mode

```bash
# Development mode
cargo run

# Release mode
./run.sh
```

The server will start on `http://0.0.0.0:3090` (or port specified in `.env`)

## Endpoints

- `GET /` or `GET /health` - Health check endpoint
  - Returns: JSON with service status, version, active streams, total connections
  - Example: `{"status":"running","service":"binary-stream-broker","version":"0.1.0","active_streams":1,"total_connections":2}`

- `POST /ingest/:stream_id` - Ingest binary frame (WebP format)
  - Body: Raw WebP binary data
  - Returns: `200 OK` if broadcasted, `202 Accepted` if no clients connected or channel closed

- `GET /ws/:stream_id` - WebSocket connection for clients
  - Upgrades to WebSocket protocol
  - Streams binary frames to connected clients

## Configuration

### Using .env File (Recommended)

The easiest way to configure the server is using a `.env` file:

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your settings:
   ```bash
   # Ingest Server Configuration
   BIND_ADDRESS=0.0.0.0
   PORT=3090
   ```

3. Run the server - it will automatically load the `.env` file:
   ```bash
   cargo run
   ```

### Environment Variables

You can also set environment variables directly:

- `BIND_ADDRESS`: Server bind address (default: `0.0.0.0`)
- `PORT`: Server port (default: `3090`)
- `RUST_LOG`: Logging level (default: `ingest_server=info`)

**Note**: Environment variables take precedence over `.env` file values.

## HTTPS/HTTP/2 Support

### Quick Start with Caddy (Recommended)

Caddy provides automatic HTTPS/HTTP/2 with minimal configuration:

```bash
# Enable Caddy mode
USE_CADDY=true ./run.sh
```

This will:
1. ✅ Automatically install Caddy if needed
2. ✅ Start Axum server on internal port (3091)
3. ✅ Start Caddy with HTTPS/HTTP/2 on port 3090
4. ✅ Handle TLS termination automatically

**Access**: `https://localhost:3090` (HTTP/2 enabled)

### Manual Setup

1. **Install Caddy** (if not already installed):
   ```bash
   ./setup-caddy.sh
   ```

2. **Start with Caddy**:
   ```bash
   USE_CADDY=true ./run.sh
   ```

3. **Or start manually**:
   ```bash
   # Terminal 1: Start Axum server
   PORT=3091 cargo run
   
   # Terminal 2: Start Caddy
   caddy run --config Caddyfile
   ```

### Configuration

- **Caddy Port**: `3090` (HTTPS/HTTP/2, external)
- **Axum Port**: `3091` (HTTP, internal, behind Caddy)
- **Caddyfile**: Edit `Caddyfile` to customize configuration

### Production Setup

For production with a domain:

1. Edit `Caddyfile` and uncomment the production section
2. Replace `your-domain.com` with your actual domain
3. Caddy will automatically get Let's Encrypt certificate
4. Run: `USE_CADDY=true ./run.sh`

Example:
```bash
RUST_LOG=debug cargo run
```

## Performance

- Handles 30 FPS streams with minimal latency
- Supports hundreds of concurrent WebSocket clients
- Automatic frame dropping on client lag (backpressure handling)
- Zero-copy frame forwarding using `Bytes` smart pointer
- Health check endpoint for monitoring
- Graceful error handling (202 Accepted instead of 500 for no clients)

