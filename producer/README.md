# RTSP Producer

Python service that captures RTSP video streams, transcodes frames to WebP format, and publishes them to the Axum ingest server via HTTP/2.

## Features

- RTSP stream capture using OpenCV
- WebP frame encoding (better compression than JPEG)
- HTTP/2 POST to broker (multiplexing, header compression)
- Automatic reconnection on stream failure
- FPS regulation (30 FPS default, but limited by RTSP stream rate)
- Two-loop pattern for resilience
- Detailed logging for performance analysis (timing for read, encode, send)
- Real-time FPS monitoring and reporting
- **Custom bounding boxes**: Draw configurable bounding boxes with labels on frames (maintains 30 FPS)

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
   
   # Optional: Custom bounding boxes (JSON array format)
   # See bounding_boxes.example.json for format
   # BOUNDING_BOXES='[{"x1":100,"y1":100,"x2":300,"y2":300,"color":"0,255,0","thickness":2,"label":"Region 1"}]'
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
- `BOUNDING_BOXES`: JSON array of bounding boxes to draw on frames (optional)
  - Format: `[{"x1":100,"y1":100,"x2":300,"y2":300,"color":"0,255,0","thickness":2,"label":"Region 1"}]`
  - See `bounding_boxes.example.json` for detailed examples
  - Supports both absolute pixel coordinates and percentage-based coordinates (0-1)

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

## Custom Bounding Boxes

The producer supports drawing custom bounding boxes on frames before encoding. This feature maintains 30 FPS performance by using efficient OpenCV drawing operations.

### Configuration

Bounding boxes are configured via the `BOUNDING_BOXES` environment variable as a JSON array. Each box supports:

- **Coordinates**: `x1`, `y1`, `x2`, `y2` (top-left and bottom-right corners)
  - Absolute pixels: `{"x1": 100, "y1": 100, "x2": 300, "y2": 300, "use_percentage": false}`
  - Percentage-based (0-1): `{"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5, "use_percentage": true}`
- **Color**: RGB string format `"R,G,B"` (default: `"0,255,0"` for green)
- **Thickness**: Line thickness in pixels (default: `2`)
- **Label**: Optional text label to display above the box
- **Label Color**: RGB string format for label text (default: same as box color)
- **Font Scale**: Text size multiplier (default: `0.6`)

### Example Configuration

**Using .env file:**
```bash
BOUNDING_BOXES='[{"x1":100,"y1":100,"x2":300,"y2":300,"color":"0,255,0","thickness":2,"label":"Region 1","font_scale":0.6}]'
```

**Using environment variable:**
```bash
export BOUNDING_BOXES='[{"x1":0.1,"y1":0.1,"x2":0.5,"y2":0.5,"color":"255,0,0","thickness":3,"label":"Detection Zone","use_percentage":true}]'
```

**Multiple boxes:**
```bash
BOUNDING_BOXES='[
  {"x1":100,"y1":100,"x2":300,"y2":300,"color":"0,255,0","thickness":2,"label":"Zone 1"},
  {"x1":400,"y1":200,"x2":600,"y2":400,"color":"255,0,0","thickness":2,"label":"Zone 2","label_color":"255,255,255"}
]'
```

See `bounding_boxes.example.json` for detailed examples.

### Performance

- Bounding box drawing adds minimal overhead (< 1ms per frame)
- Maintains 30 FPS target with multiple boxes
- Efficient OpenCV operations (in-place frame modification)

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

### Low FPS (6-7 FPS instead of 30)

**Most Common Cause**: RTSP stream from camera only sends 6-7 FPS

**Diagnosis Steps**:
1. Check producer logs for actual FPS: `"Streaming at X.X FPS"`
2. Verify RTSP stream frame rate:
   ```bash
   ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 rtsp://your-camera-url
   ```
3. Enable debug logging to see timing:
   ```bash
   # Set logging level to DEBUG in .env or environment
   # Check logs for: "RTSP read took Xms", "Frame encoding took Xms", "Frame sent in Xms"
   ```

**Possible Causes**:
- RTSP stream frame rate is 6-7 FPS (most common - check camera settings)
- Network latency causing delays
- WebP encoding taking too long (check encoding time in logs)
- HTTP POST taking too long (check send time in logs)

**Solutions**:
- If RTSP stream is 6-7 FPS: This is normal, cannot exceed stream rate
- Check camera settings for higher frame rate stream profile
- Reduce WebP quality if encoding is slow: Edit `process_frame()` quality parameter
- Check network conditions if HTTP POST is slow
