# Web Client

HTML5 Canvas-based video player that receives WebP frames via WebSocket and renders them in real-time.

## Quick Start

```bash
# Start the HTTP server
python3 server.py

# Or use the helper script
./run.sh

# Then open http://localhost:3092 in your browser
```

## Features

- WebSocket client with auto-reconnect (3 second delay)
- High-performance rendering using `createImageBitmap` (background thread decoding)
- WebP format support
- Real-time metrics (FPS, latency, frame count)
- Responsive UI with modern design
- Frame capture functionality

## Architecture

Following PIPELINE_KNOWLEDGE.md specifications:

1. **WebSocket Connection**: Connects to `ws://broker/ws/:stream_id` or `wss://broker/ws/:stream_id`
2. **Binary Frame Reception**: Receives WebP frames as `ArrayBuffer`
3. **Background Decoding**: Uses `createImageBitmap` for non-blocking image decoding
4. **Canvas Rendering**: Renders decoded frames to HTML5 canvas
5. **Auto-Reconnect**: Automatically reconnects after 3 seconds on disconnect

## Usage

### Using HTTP Server (Recommended)

1. **Start the HTTP server**:
   ```bash
   python3 server.py
   # Or use helper script
   ./run.sh
   ```

2. **Open your browser** and navigate to:
   ```
   http://localhost:3092
   ```

3. **Configure connection**:
   - **With Docker/Caddy (HTTPS)**: Use `wss://localhost:3090/ws/stream1` (default)
   - **Direct HTTP**: Use `ws://localhost:3091/ws/stream1`
   - Stream ID: `stream1` (must match producer)

4. **Accept security warning** (if using HTTPS with self-signed certificate):
   - Click "Advanced" → "Proceed to localhost"

5. **Click "Connect"** to start streaming.

### Direct File Access

You can also open `index.html` directly in your browser, but CORS restrictions may apply.

## Configuration

### UI Configuration

The player can be configured via the UI:

- **Broker URL**: WebSocket URL
  - **With Docker/Caddy (HTTPS)**: `wss://localhost:3090/ws/stream1` (default)
  - **Direct HTTP**: `ws://localhost:3091/ws/stream1`
- **Stream ID**: Must match producer's `STREAM_ID` (default: `stream1`)

**Note**: When using HTTPS with self-signed certificates, your browser will show a security warning. Click "Advanced" → "Proceed to localhost" to continue.

## Server Configuration

The HTTP server runs on port `3092` by default. You can change this in `server.py`:

```python
PORT = 3092  # Change to your preferred port
```

## Browser Compatibility

- **Modern browsers**: Chrome, Firefox, Edge, Safari (latest versions)
- **Required APIs**:
  - WebSocket API
  - `createImageBitmap` API
  - Canvas API
  - Fetch API

## Performance

- **Decoding**: Background thread decoding prevents UI blocking
- **Rendering**: Optimized canvas rendering for smooth playback
- **Memory**: Efficient frame handling with automatic cleanup

## Troubleshooting

### WebSocket connection fails

- Verify broker URL is correct:
  - HTTPS: `wss://localhost:3090/ws/stream1`
  - HTTP: `ws://localhost:3091/ws/stream1`
- Check that ingest-server is running
- For HTTPS, accept the security warning for self-signed certificate
- Check browser console for error messages

### No video displayed

- Verify WebSocket connection is established (check connection status)
- Ensure stream_id matches producer's `STREAM_ID`
- Check that frames are being received (check metrics)
- Verify browser supports `createImageBitmap` API

### High latency

- Check network conditions
- Verify broker is running on same network
- Check for frame dropping in metrics
- Reduce target FPS if needed

### Browser security warning (HTTPS)

When using HTTPS with self-signed certificates:
1. Click "Advanced" or "Show Details"
2. Click "Proceed to localhost" or "Accept the Risk"
3. The connection will work normally after accepting
