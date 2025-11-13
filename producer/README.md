# RTSP Producer

Python service that captures RTSP video streams, transcodes frames to WebP format, and publishes them to the Axum ingest server via HTTP/2.

## Features

- RTSP stream capture using OpenCV
- WebP frame encoding (better compression than JPEG)
- HTTP/2 POST to broker (multiplexing, header compression)
- Automatic reconnection on stream failure
- FPS regulation (30 FPS default)
- Two-loop pattern for resilience

## Installation

### Using Virtual Environment (Recommended)

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Linux/Mac
# or
venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt
```

### Direct Installation (Not Recommended)

```bash
pip install -r requirements.txt
```

## Configuration

### Using .env File (Recommended)

The easiest way to configure the producer is using a `.env` file:

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your settings:
   ```bash
   # RTSP stream URL
   RTSP_URL=rtsp://admin:KAQSML@172.16.6.77:554
   
   # Broker configuration
   # For Docker/Caddy setup (HTTPS/HTTP/2): USE_HTTPS=true, BROKER_PORT=3090
   # For direct HTTP access: USE_HTTPS=false, BROKER_PORT=3091
   USE_HTTPS=true
   BROKER_PORT=3090
   VERIFY_SSL=false  # Set to false for self-signed certificates
   
   # Stream identifier
   STREAM_ID=stream1
   
   # Target frames per second
   TARGET_FPS=30
   ```

3. Run the producer - it will automatically load the `.env` file:
   ```bash
   source venv/bin/activate
   python main.py
   ```

### Environment Variables

You can also set environment variables directly:

- `RTSP_URL`: RTSP stream URL (default: `rtsp://admin:KAQSML@172.16.6.77:554`)
- `USE_HTTPS`: Use HTTPS (default: `true` for Docker/Caddy setup)
- `BROKER_PORT`: Broker port (default: `3090` for HTTPS, `3091` for HTTP)
- `BROKER_URL`: Broker URL (auto-generated from `USE_HTTPS` and `BROKER_PORT`)
- `VERIFY_SSL`: Verify SSL certificates (default: `false` for self-signed)
- `STREAM_ID`: Stream identifier (default: `stream1`)
- `TARGET_FPS`: Target frames per second (default: `30`)

**Note**: Environment variables take precedence over `.env` file values.

## Usage

### With Docker/Caddy (HTTPS/HTTP/2 - Recommended)

```bash
# Activate virtual environment
source venv/bin/activate

# Run with HTTPS (default)
python main.py

# Or explicitly set HTTPS
USE_HTTPS=true BROKER_PORT=3090 VERIFY_SSL=false python main.py
```

### With Direct HTTP Access

```bash
source venv/bin/activate
USE_HTTPS=false BROKER_PORT=3091 python main.py
```

### Using .env File

```bash
# Edit .env file first
cp .env.example .env
# Edit .env with your settings

source venv/bin/activate
python main.py
```

## Architecture

The producer implements a two-loop pattern:

1. **Outer loop**: Handles RTSP connection and reconnection
2. **Inner loop**: Reads frames, transcodes to WebP, and sends to broker

This pattern ensures resilience against network failures and stream interruptions.

## Broker Connection

### With Docker/Caddy (Recommended)

The producer is configured by default to connect to the Docker/Caddy setup:
- **Protocol**: HTTPS
- **Port**: 3090
- **SSL Verification**: Disabled (for self-signed certificates)
- **HTTP/2**: Enabled automatically

### Direct HTTP Access

For direct connection to Axum server (without Caddy):
- **Protocol**: HTTP
- **Port**: 3091
- Set `USE_HTTPS=false` and `BROKER_PORT=3091`

## Testing

Run the test suite:

```bash
source venv/bin/activate
python test_producer.py
```

## Troubleshooting

### Can't connect to RTSP stream

- Verify RTSP URL is correct and accessible
- Check network connectivity
- Ensure OpenCV can access the stream

### Can't connect to broker (HTTPS)

- Verify `USE_HTTPS=true` and `BROKER_PORT=3090` are set
- Set `VERIFY_SSL=false` for self-signed certificates
- Check that Docker/Caddy is running: `docker compose ps` in ingest-server directory
- Verify broker URL: `https://localhost:3090` (not `http://`)

### Can't connect to broker (HTTP)

- Verify `USE_HTTPS=false` and `BROKER_PORT=3091` are set
- Check that Axum server is running on port 3091
