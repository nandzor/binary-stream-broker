# Binary Stream Broker

Real-time RTSP video streaming system that transforms RTSP streams into WebP binary frames and broadcasts them to multiple web clients via WebSocket. Supports HTTPS/HTTP/2 with automatic TLS via Caddy.

## Architecture

This system implements a decoupled Publish/Subscribe (Pub/Sub) pattern with three main components:

1. **Producer (Python)**: Captures RTSP stream, transcodes frames to WebP, and publishes to broker via HTTP/2
2. **Broker (Rust/Axum)**: High-performance in-memory Pub/Sub broker that receives frames and broadcasts to WebSocket clients
3. **Client (Web/JS)**: Subscribes to stream via WebSocket and renders frames to HTML5 canvas

### Architecture Diagram

**With Caddy (HTTPS/HTTP/2 - Recommended):**
```
┌─────────────┐      HTTPS/HTTP/2      ┌──────────────┐      HTTP/1.1      ┌─────────────┐
│   RTSP      │ ───────────────────> │    Caddy     │ ─────────────────> │    Axum     │
│  Producer   │    POST /ingest/:id   │  (Port 3090) │   (Port 3091)      │   Broker    │
│  (Python)   │                       │  HTTPS/HTTP/2│                    │   (Rust)    │
└─────────────┘                       └──────────────┘                    └─────────────┘
                                             │                                    │
                                             │ WSS (WebSocket)                    │
                                             │                                    │
                                             ▼                                    │
                                      ┌─────────────┐                            │
                                      │   Browser   │ ◄──────────────────────────┘
                                      │   Client    │      WebSocket
                                      │  (HTML/JS)  │      /ws/:stream_id
                                      └─────────────┘
```

**Direct HTTP Mode:**
```
┌─────────────┐      HTTP/1.1 POST     ┌──────────────┐      WebSocket      ┌─────────────┐
│   RTSP      │ ───────────────────> │    Axum      │ ─────────────────> │   Browser   │
│  Producer   │    /ingest/:stream_id │   Broker     │   /ws/:stream_id   │   Client    │
│  (Python)   │                       │   (Rust)     │                    │   (HTML/JS) │
└─────────────┘                       └──────────────┘                    └─────────────┘
```

## Quick Start

### 1. Start the Broker (Rust/Axum)

**Option A: With HTTPS/HTTP/2 (Recommended)**
```bash
cd ingest-server
USE_CADDY=true ./run.sh
```
This will automatically setup Caddy with HTTPS/HTTP/2 on port 3090.

**Option B: Direct HTTP mode**
```bash
cd ingest-server
./run.sh
# Or
cargo run
```

The broker will start on:
- **With Caddy**: `https://localhost:3090` (HTTPS/HTTP/2)
- **Direct**: `http://0.0.0.0:3090` (HTTP/1.1)

### 2. Start the Producer (Python)

**With HTTPS (if using Caddy):**
```bash
cd producer
source venv/bin/activate
USE_HTTPS=true BROKER_PORT=3090 VERIFY_SSL=false python main.py
```

**With HTTP (direct access):**
```bash
cd producer
source venv/bin/activate
BROKER_PORT=3091 python main.py
```

**Or configure via `.env` file:**
```bash
cd producer
cp .env.example .env
# Edit .env:
# USE_HTTPS=true
# BROKER_PORT=3090
# VERIFY_SSL=false  # Set to false for self-signed certificates
source venv/bin/activate
python main.py
```

### 3. Start the Web Client Server

```bash
cd web-client
python3 server.py
```

The web client will be available at `http://localhost:3092`

Or use the helper script:
```bash
cd web-client
./run.sh
```

Then open `http://localhost:3092` in your browser and click "Connect".

**Note**: If using Caddy with HTTPS:
- WebSocket URL should be: `wss://localhost:3090/ws/stream1`
- Browser will show a security warning for self-signed certificate (click "Advanced" → "Proceed")

## Components

### Producer (`producer/`)

- **Technology**: Python 3.9+, OpenCV, httpx (HTTP/2)
- **Function**: RTSP capture → WebP encoding → HTTP/2 POST to broker
- **Features**:
  - Automatic reconnection on stream failure
  - FPS regulation (30 FPS default)
  - Two-loop pattern for resilience

### Ingest Server (`ingest-server/`)

- **Technology**: Rust, Axum, Tokio
- **Function**: Receives frames → In-memory broadcast → WebSocket distribution
- **Features**:
  - Multi-channel support (multiple streams)
  - Zero-copy frame forwarding using `Bytes`
  - Automatic backpressure handling
  - Lazy channel creation

### Web Client (`web-client/`)

- **Technology**: HTML5, JavaScript, WebSocket API, Python HTTP Server
- **Function**: WebSocket subscription → Frame decoding → Canvas rendering
- **Features**:
  - High-performance rendering with `createImageBitmap`
  - Auto-reconnect (3 second delay)
  - Real-time metrics display
  - Frame capture
  - HTTP server on port 3092

## Configuration

### Producer Configuration

**Environment Variables:**
- `RTSP_URL`: RTSP stream URL (default: `rtsp://admin:KAQSML@172.16.6.77:554`)
- `BROKER_URL`: Broker URL (auto-generated from `USE_HTTPS` and `BROKER_PORT`)
- `USE_HTTPS`: Use HTTPS (default: `false`)
- `BROKER_PORT`: Broker port (default: `3090` for Caddy, `3091` for direct)
- `VERIFY_SSL`: Verify SSL certificates (default: `false` for self-signed)
- `STREAM_ID`: Stream identifier (default: `stream1`)
- `TARGET_FPS`: Target frames per second (default: `30`)

**Using `.env` file (Recommended):**
```bash
cd producer
cp .env.example .env
# Edit .env with your settings
```

### Broker Configuration

**With Caddy (HTTPS/HTTP/2):**
- **Caddy Port**: `3090` (HTTPS/HTTP/2, external)
- **Axum Port**: `3091` (HTTP, internal, behind Caddy)
- **Environment Variables**:
  - `USE_CADDY=true`: Enable Caddy mode
  - `PORT=3091`: Internal Axum port
  - `CADDY_PORT=3090`: External Caddy port
  - `BIND_ADDRESS=127.0.0.1`: Bind address (default for behind Caddy)

**Direct HTTP Mode:**
- **Port**: `3090` (configurable via `PORT` env var or `.env`)
- **Bind Address**: `0.0.0.0` (configurable via `BIND_ADDRESS`)

**Logging**: Set via `RUST_LOG` environment variable (e.g., `RUST_LOG=debug`)

### Web Client Configuration

- **Server Port**: `3092` (configurable in `server.py`)
- **UI Configuration**:
  - **Broker URL**: 
    - With Caddy: `wss://localhost:3090/ws/stream1` (WSS for HTTPS)
    - Direct: `ws://localhost:3090/ws/stream1` (WS for HTTP)
  - **Stream ID**: Must match producer's `STREAM_ID`

## Performance

- **Frame Rate**: 30 FPS (configurable)
- **Latency**: < 200ms end-to-end
- **Concurrent Clients**: Supports hundreds of WebSocket connections
- **Memory**: Efficient zero-copy frame forwarding

## Design Decisions

### Why Rust for Broker?

- **No GC Pauses**: Eliminates stutter in 30 FPS streams
- **Memory Safety**: Prevents crashes and security issues
- **Performance**: C++-level performance with safety guarantees

### Why WebP?

- **Better Compression**: ~30% smaller than JPEG at same quality
- **Fast Decoding**: Optimized for modern browsers
- **Quality**: Better quality-to-size ratio

### Why HTTP/2 for Ingest?

- **Multiplexing**: Single TCP connection for 30 requests/second
- **Reduced Overhead**: Eliminates TCP handshake per frame
- **HPACK Compression**: Header compression reduces bandwidth
- **TLS Security**: HTTPS encryption for secure data transmission

### Why Caddy?

- **Automatic HTTPS**: Self-signed certificates for development, Let's Encrypt for production
- **HTTP/2 Support**: Built-in HTTP/2 with minimal configuration
- **Easy Setup**: One command to enable HTTPS/HTTP/2
- **WebSocket Support**: Native WebSocket proxy with proper header forwarding

### Why createImageBitmap?

- **Background Thread**: Decodes images without blocking UI
- **Performance**: Faster than `URL.createObjectURL` + `Image`
- **Memory Efficient**: Better memory management

## Development

### Building the Broker

```bash
cd ingest-server
cargo build --release
```

### Running Tests

```bash
# Producer (manual testing)
cd producer
python main.py

# Broker (manual testing)
cd ingest-server
cargo run
```

## Troubleshooting

### Producer can't connect to RTSP stream

- Verify RTSP URL is correct and accessible
- Check network connectivity
- Ensure OpenCV can access the stream

### Producer can't connect to broker (HTTPS)

- Verify `USE_HTTPS=true` and `BROKER_PORT=3090` are set
- Set `VERIFY_SSL=false` for self-signed certificates
- Check that Caddy is running: `USE_CADDY=true ./run.sh`
- Verify broker URL: `https://localhost:3090` (not `http://`)

### Broker not receiving frames

- Verify producer is sending to correct endpoint: `POST /ingest/:stream_id`
- Check broker logs for errors
- Ensure stream_id matches between producer and client
- If using Caddy, verify Axum is running on internal port (3091)

### Web client not displaying video

- Verify WebSocket connection (check browser console)
- **With Caddy**: Use `wss://localhost:3090/ws/stream1` (WSS, not WS)
- **Direct HTTP**: Use `ws://localhost:3090/ws/stream1` (WS)
- Accept browser security warning for self-signed certificate (if using HTTPS)
- Ensure stream_id matches producer
- Check that frames are being received (check metrics)
- Verify browser supports `createImageBitmap` API

### Caddy not starting

- Check if Caddy is installed: `caddy version`
- Run setup script: `./setup-caddy.sh`
- Check port 3090 is not in use: `lsof -i :3090`
- Verify Caddyfile syntax: `caddy validate --config Caddyfile`

### High latency

- Check network conditions
- Verify broker is running on same network
- Check for frame dropping in metrics
- Reduce target FPS if needed
- With Caddy, ensure HTTP/2 is enabled (check Caddy logs)

## License

MIT

