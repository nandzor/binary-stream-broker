# Real-Time RTSP Streaming Architecture Documentation

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [System Components](#system-components)
3. [Python RTSP Producer](#python-rtsp-producer)
4. [Axum Ingest Service](#axum-ingest-service)
5. [WebSocket Streaming](#websocket-streaming)
6. [Web Client Implementation](#web-client-implementation)
7. [Performance Considerations](#performance-considerations)
8. [Security Considerations](#security-considerations)
9. [Error Handling Strategies](#error-handling-strategies)
10. [Deployment Guide](#deployment-guide)
11. [Monitoring and Logging](#monitoring-and-logging)
12. [Troubleshooting](#troubleshooting)

## Architecture Overview

### High-Level Design
```text
┌─────────────────────────────────────────────────────────────────┐
│                         RTSP CAMERA                             │
│              rtsp://admin:KAQSML@172.16.6.77:554                │
└────────────────────────────┬────────────────────────────────────┘
                             │ RTSP Stream
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PYTHON PRODUCER SERVICE                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │ RTSP Capture │→ │ Frame Buffer │→ │ Binary Encoder     │     │
│  │ (OpenCV)     │  │ (30 FPS)     │  │ (JPEG/H.264)       │     │
│  └──────────────┘  └──────────────┘  └────────────────────┘     │
│                                              │                  │
│                                              ▼                  │
│                                    ┌──────────────────┐         │
│                                    │ HTTP/2 Client    │         │
│                                    │ (httpx/aiohttp)  │         │
│                                    └──────────────────┘         │
└───────────────────────────────────────────┬─────────────────────┘
                                            │ POST /ingest
                                            │ (Binary Payload)
                                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AXUM INGEST SERVER (RUST)                    │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │ HTTP/2 Endpoint  │→ │ Frame Validator  │→ │ Broadcast    │   │
│  │ POST /ingest     │  │ & Buffer         │  │ Channel      │   │
│  └──────────────────┘  └──────────────────┘  └──────────────┘   │
│                                                      │          │
│                                                      ▼          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │            WebSocket Connection Manager                   │  │
│  │  - Client Registry                                        │  │
│  │  - Frame Broadcasting                                     │  │
│  │  - Connection Health Monitoring                           │  │
│  └──────────────────────────────────────────────────────────┘   │
│                                                      │          |
└──────────────────────────────────────────────────────┼──────────|
                                                       │ WS Stream
                                                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    WEB CLIENT (BROWSER)                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │ WebSocket Client │→ │ Frame Decoder    │→ │ Canvas       │   │
│  │                  │  │ (Blob→ImageData) │  │ Renderer     │   │
│  └──────────────────┘  └──────────────────┘  └──────────────┘   │
│                                                      │          │
│                                              ┌───────▼────────┐ │
│                                              │ Video Player   │ │
│                                              │ Controls       │ │
│                                              └────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Design Patterns

**Producer-Consumer Pattern**: Python producer generates frames, Axum consumes and redistributes
**Observer Pattern**: Multiple WebSocket clients can subscribe to the same stream
**Circuit Breaker Pattern**: Automatic failover and recovery mechanisms
**Buffer Pattern**: Frame buffering for smooth playback and network resilience

### Technology Stack

- **Producer**: Python 3.9+ with OpenCV, FFmpeg
- **Ingest Service**: Rust with Axum framework
- **Transport**: HTTP/2, WebSockets
- **Client**: HTML5 Canvas, JavaScript ES6+
- **Serialization**: Protocol Buffers or MessagePack

## System Components

### Data Flow Architecture

1. **RTSP Ingestion**: Python captures RTSP stream from IP camera
2. **Frame Processing**: Conversion to 30fps, resolution optimization
3. **Binary Encoding**: Frame serialization for network transport
4. **HTTP/2 Transport**: Efficient payload delivery to Axum service
5. **WebSocket Distribution**: Real-time streaming to connected clients
6. **Client Rendering**: Binary decoding and Canvas-based video playback

### Performance Requirements

| Metric | Target | Maximum |
|--------|---------|---------|
| Frame Rate | 30 FPS | 60 FPS |
| Latency | < 200ms | < 500ms |
| Concurrent Clients | 100+ | 1000+ |
| Network Bandwidth | 2-5 Mbps | 10 Mbps |
| Memory Usage | < 512MB | < 1GB |

## Python RTSP Producer

### Core Implementation

import cv2
import asyncio
import aiohttp
import numpy as np
from datetime import datetime
import msgpack
import logging
from typing import Optional, Tuple
import time

class RTSPProducer:
    def __init__(self, rtsp_url: str, axum_endpoint: str, target_fps: int = 30):
        self.rtsp_url = rtsp_url
        self.axum_endpoint = axum_endpoint
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self.session: Optional[aiohttp.ClientSession] = None
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_running = False
        
        # Performance tracking
        self.frames_sent = 0
        self.last_fps_check = time.time()
        
        # Logging setup
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    async def initialize(self):
        """Initialize RTSP connection and HTTP session"""
        try:
            # Initialize OpenCV VideoCapture
            self.cap = cv2.VideoCapture(self.rtsp_url)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize buffer lag
            self.cap.set(cv2.CAP_PROP_FPS, self.target_fps)
            
            if not self.cap.isOpened():
                raise ConnectionError(f"Failed to open RTSP stream: {self.rtsp_url}")
            
            # Initialize HTTP/2 session
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=10)
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={'Content-Type': 'application/octet-stream'}
            )
            
            self.logger.info(f"Producer initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            await self.cleanup()
            return False

    def process_frame(self, frame: np.ndarray) -> bytes:
        """Process and encode frame for network transmission"""
        try:
            # Resize frame for optimal streaming (720p)
            height, width = frame.shape[:2]
            if width > 1280:
                scale = 1280 / width
                new_width = 1280
                new_height = int(height * scale)
                frame = cv2.resize(frame, (new_width, new_height), 
                                 interpolation=cv2.INTER_LINEAR)
            
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Compress frame
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
            _, buffer = cv2.imencode('.jpg', frame_rgb, encode_param)
            
            # Create frame metadata
            frame_data = {
                'timestamp': int(time.time() * 1000),  # milliseconds
                'width': frame_rgb.shape[1],
                'height': frame_rgb.shape[0],
                'data': buffer.tobytes()
            }
            
            # Serialize with MessagePack
            return msgpack.packb(frame_data)
            
        except Exception as e:
            self.logger.error(f"Frame processing failed: {e}")
            return b''

    async def send_frame(self, frame_data: bytes) -> bool:
        """Send frame data to Axum ingest endpoint"""
        try:
            async with self.session.post(
                f"{self.axum_endpoint}/ingest",
                data=frame_data,
                headers={'X-Frame-Format': 'msgpack-jpeg'}
            ) as response:
                if response.status == 200:
                    return True
                else:
                    self.logger.warning(f"Server returned status: {response.status}")
                    return False
                    
        except asyncio.TimeoutError:
            self.logger.error("Frame send timeout")
            return False
        except Exception as e:
            self.logger.error(f"Frame send failed: {e}")
            return False

    async def stream_loop(self):
        """Main streaming loop"""
        self.is_running = True
        last_frame_time = 0
        
        while self.is_running:
            try:
                current_time = time.time()
                
                # Maintain target FPS
                if current_time - last_frame_time < self.frame_interval:
                    await asyncio.sleep(0.001)
                    continue
                
                # Capture frame
                ret, frame = self.cap.read()
                if not ret:
                    self.logger.error("Failed to read frame from RTSP stream")
                    await asyncio.sleep(1)
                    continue
                
                # Process and send frame
                frame_data = self.process_frame(frame)
                if frame_data:
                    success = await self.send_frame(frame_data)
                    if success:
                        self.frames_sent += 1
                        last_frame_time = current_time
                
                # FPS monitoring
                if current_time - self.last_fps_check >= 5.0:
                    fps = self.frames_sent / 5.0
                    self.logger.info(f"Streaming at {fps:.1f} FPS")
                    self.frames_sent = 0
                    self.last_fps_check = current_time
                
            except Exception as e:
                self.logger.error(f"Stream loop error: {e}")
                await asyncio.sleep(1)

    async def cleanup(self):
        """Clean up resources"""
        self.is_running = False
        
        if self.cap:
            self.cap.release()
            
        if self.session:
            await self.session.close()
        
        self.logger.info("Producer cleanup completed")

    async def run(self):
        """Main entry point"""
        if await self.initialize():
            try:
                await self.stream_loop()
            except KeyboardInterrupt:
                self.logger.info("Received shutdown signal")
            finally:
                await self.cleanup()

# Usage example
async def main():
    producer = RTSPProducer(
        rtsp_url="rtsp://admin:KAQSML@172.16.6.77:554",
        axum_endpoint="http://localhost:3000"
    )
    await producer.run()

if __name__ == "__main__":
    asyncio.run(main())

### Configuration Management

# config.py
from pydantic import BaseSettings
from typing import Optional

class ProducerConfig(BaseSettings):
    rtsp_url: str = "rtsp://admin:KAQSML@172.16.6.77:554"
    axum_endpoint: str = "http://localhost:3000"
    target_fps: int = 30
    max_width: int = 1280
    jpeg_quality: int = 85
    buffer_size: int = 1
    retry_attempts: int = 3
    retry_delay: int = 5
    
    class Config:
        env_file = ".env"
        env_prefix = "RTSP_"

### Best Practices for Python Producer

1. **Connection Management**: Implement connection pooling and automatic reconnection
2. **Frame Rate Control**: Use precise timing to maintain consistent FPS
3. **Memory Management**: Limit buffer sizes and implement garbage collection
4. **Error Recovery**: Graceful handling of network and stream interruptions
5. **Performance Monitoring**: Real-time FPS and latency tracking

## Axum Ingest Service

### Core Service Implementation

use axum::{
    extract::{ws::WebSocket, WebSocketUpgrade, State},
    http::StatusCode,
    response::Response,
    routing::{get, post},
    Router,
    body::Bytes,
};
use tokio::sync::broadcast;
use tower::ServiceBuilder;
use tower_http::cors::CorsLayer;
use tracing::{info, error, warn};
use std::sync::Arc;
use serde::{Deserialize, Serialize};

// Frame data structure
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FrameData {
    pub timestamp: u64,
    pub width: u32,
    pub height: u32,
    pub data: Vec<u8>,
}

// Application state
#[derive(Clone)]
pub struct AppState {
    pub frame_sender: broadcast::Sender<FrameData>,
    pub metrics: Arc<StreamMetrics>,
}

#[derive(Default)]
pub struct StreamMetrics {
    pub frames_received: std::sync::atomic::AtomicU64,
    pub clients_connected: std::sync::atomic::AtomicU64,
    pub bytes_processed: std::sync::atomic::AtomicU64,
}

// Ingest endpoint handler
pub async fn ingest_frame(
    State(state): State<AppState>,
    body: Bytes,
) -> Result<StatusCode, StatusCode> {
    match process_ingest_frame(&state, body).await {
        Ok(_) => Ok(StatusCode::OK),
        Err(e) => {
            error!("Ingest processing failed: {}", e);
            Err(StatusCode::INTERNAL_SERVER_ERROR)
        }
    }
}

async fn process_ingest_frame(
    state: &AppState,
    body: Bytes,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // Deserialize frame data
    let frame_data: FrameData = rmp_serde::from_slice(&body)?;
    
    // Update metrics
    state.metrics.frames_received
        .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    state.metrics.bytes_processed
        .fetch_add(body.len() as u64, std::sync::atomic::Ordering::Relaxed);
    
    // Broadcast to WebSocket clients
    match state.frame_sender.send(frame_data) {
        Ok(subscriber_count) => {
            if subscriber_count == 0 {
                warn!("No WebSocket clients connected");
            }
        }
        Err(_) => {
            error!("Failed to broadcast frame");
        }
    }
    
    Ok(())
}

// WebSocket upgrade handler
pub async fn websocket_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> Response {
    ws.on_upgrade(|socket| websocket_connection(socket, state))
}

// WebSocket connection handler
async fn websocket_connection(mut socket: WebSocket, state: AppState) {
    // Update client count
    state.metrics.clients_connected
        .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    
    // Subscribe to frame broadcasts
    let mut frame_receiver = state.frame_sender.subscribe();
    
    info!("WebSocket client connected");
    
    // Send frames to client
    while let Ok(frame_data) = frame_receiver.recv().await {
        match send_frame_to_client(&mut socket, &frame_data).await {
            Ok(_) => continue,
            Err(e) => {
                error!("Failed to send frame to client: {}", e);
                break;
            }
        }
    }
    
    // Cleanup
    state.metrics.clients_connected
        .fetch_sub(1, std::sync::atomic::Ordering::Relaxed);
    
    info!("WebSocket client disconnected");
}

async fn send_frame_to_client(
    socket: &mut WebSocket,
    frame_data: &FrameData,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // Serialize frame for client
    let serialized = rmp_serde::to_vec(frame_data)?;
    
    // Send as binary WebSocket message
    socket.send(axum::extract::ws::Message::Binary(serialized)).await?;
    
    Ok(())
}

// Metrics endpoint
pub async fn metrics_handler(State(state): State<AppState>) -> axum::Json<serde_json::Value> {
    let frames_received = state.metrics.frames_received
        .load(std::sync::atomic::Ordering::Relaxed);
    let clients_connected = state.metrics.clients_connected
        .load(std::sync::atomic::Ordering::Relaxed);
    let bytes_processed = state.metrics.bytes_processed
        .load(std::sync::atomic::Ordering::Relaxed);
    
    axum::Json(serde_json::json!({
        "frames_received": frames_received,
        "clients_connected": clients_connected,
        "bytes_processed": bytes_processed,
        "timestamp": chrono::Utc::now().timestamp()
    }))
}

// Main application setup
pub async fn create_app() -> Router {
    // Create broadcast channel for frames
    let (frame_sender, _) = broadcast::channel::<FrameData>(100);
    
    let state = AppState {
        frame_sender,
        metrics: Arc::new(StreamMetrics::default()),
    };
    
    Router::new()
        .route("/ingest", post(ingest_frame))
        .route("/ws", get(websocket_handler))
        .route("/metrics", get(metrics_handler))
        .layer(
            ServiceBuilder::new()
                .layer(CorsLayer::permissive())
        )
        .with_state(state)
}

// Server startup
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::init();
    
    let app = create_app().await;
    
    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000")
        .await
        .unwrap();
    
    info!("Axum server running on http://0.0.0.0:3000");
    
    axum::serve(listener, app).await?;
    
    Ok(())
}

### Cargo.toml Dependencies

[package]
name = "rtsp-streaming-server"
version = "0.1.0"
edition = "2021"

[dependencies]
axum = { version = "0.7", features = ["ws", "macros"] }
tokio = { version = "1.0", features = ["full"] }
tower = "0.4"
tower-http = { version = "0.5", features = ["cors"] }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
rmp-serde = "1.1"
tracing = "0.1"
tracing-subscriber = "0.3"
chrono = { version = "0.4", features = ["serde"] }

### Best Practices for Axum Service

1. **Backpressure Management**: Implement proper channel buffering and flow control
2. **Connection Limits**: Set maximum concurrent WebSocket connections
3. **Memory Efficiency**: Use streaming serialization for large payloads
4. **Health Monitoring**: Implement comprehensive metrics and health checks
5. **Graceful Shutdown**: Handle service termination cleanly

## WebSocket Streaming

### Advanced WebSocket Management

// Enhanced WebSocket handler with connection management
use std::collections::HashMap;
use uuid::Uuid;
use tokio::sync::RwLock;

pub struct WebSocketManager {
    connections: Arc<RwLock<HashMap<Uuid, WebSocketClient>>>,
    frame_sender: broadcast::Sender<FrameData>,
}

pub struct WebSocketClient {
    id: Uuid,
    sender: tokio::sync::mpsc::UnboundedSender<FrameData>,
    connected_at: std::time::Instant,
}

impl WebSocketManager {
    pub fn new(frame_sender: broadcast::Sender<FrameData>) -> Self {
        Self {
            connections: Arc::new(RwLock::new(HashMap::new())),
            frame_sender,
        }
    }
    
    pub async fn add_client(&self, socket: WebSocket) -> Uuid {
        let client_id = Uuid::new_v4();
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
        
        let client = WebSocketClient {
            id: client_id,
            sender: tx,
            connected_at: std::time::Instant::now(),
        };
        
        self.connections.write().await.insert(client_id, client);
        
        // Spawn client handler
        tokio::spawn(async move {
            while let Some(frame) = rx.recv().await {
                // Handle frame sending to specific client
                // Implementation details...
            }
        });
        
        client_id
    }
    
    pub async fn remove_client(&self, client_id: Uuid) {
        self.connections.write().await.remove(&client_id);
    }
    
    pub async fn broadcast_frame(&self, frame: FrameData) {
        let connections = self.connections.read().await;
        for client in connections.values() {
            let _ = client.sender.send(frame.clone());
        }
    }
}

### Quality of Service Implementation

// Frame rate adaptation and quality control
pub struct QoSManager {
    client_capabilities: HashMap<Uuid, ClientCapability>,
    current_quality: StreamQuality,
}

#[derive(Clone)]
pub struct ClientCapability {
    max_bandwidth: u32,
    preferred_fps: u8,
    max_resolution: Resolution,
}

#[derive(Clone)]
pub struct StreamQuality {
    fps: u8,
    resolution: Resolution,
    compression_level: u8,
}

impl QoSManager {
    pub fn adapt_quality_for_client(&self, client_id: Uuid) -> StreamQuality {
        // Implement adaptive quality based on client capabilities
        // Network conditions, processing power, etc.
        self.current_quality.clone()
    }
}

## Web Client Implementation

### HTML5 Canvas Video Player

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Real-Time RTSP Stream Viewer</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background: #1a1a1a;
            color: white;
        }

        .video-container {
            max-width: 1280px;
            margin: 0 auto;
            position: relative;
            background: #000;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }

        #videoCanvas {
            width: 100%;
            height: auto;
            display: block;
            cursor: pointer;
        }

        .controls {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            background: linear-gradient(transparent, rgba(0,0,0,0.8));
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            opacity: 0;
            transition: opacity 0.3s ease;
        }

        .video-container:hover .controls {
            opacity: 1;
        }

        .control-button {
            background: rgba(255,255,255,0.2);
            border: none;
            color: white;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            margin: 0 4px;
        }

        .control-button:hover {
            background: rgba(255,255,255,0.3);
        }

        .status {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-top: 12px;
            font-size: 14px;
        }

        .status-indicator {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #ff4444;
        }

        .status-indicator.connected {
            background: #44ff44;
        }

        .metrics {
            background: rgba(255,255,255,0.1);
            padding: 12px;
            border-radius: 4px;
            margin-top: 12px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 12px;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="video-container">
        <canvas id="videoCanvas"></canvas>
        <div class="controls">
            <div>
                <button class="control-button" onclick="togglePlayPause()">
                    <span id="playPauseText">Pause</span>
                </button>
                <button class="control-button" onclick="toggleFullscreen()">Fullscreen</button>
            </div>
            <div>
                <button class="control-button" onclick="captureFrame()">Capture</button>
                <button class="control-button" onclick="toggleStats()">Stats</button>
            </div>
        </div>
    </div>
    
    <div class="status">
        <div class="status-indicator" id="connectionStatus"></div>
        <span id="connectionText">Connecting...</span>
        <span id="latencyText">Latency: --ms</span>
    </div>
    
    <div class="metrics" id="metricsPanel" style="display: none;">
        <div>FPS: <span id="fpsCounter">0</span></div>
        <div>Resolution: <span id="resolutionDisplay">--</span></div>
        <div>Bandwidth: <span id="bandwidthDisplay">-- KB/s</span></div>
        <div>Frames: <span id="frameCounter">0</span></div>
        <div>Dropped: <span id="droppedFrames">0</span></div>
        <div>Buffer: <span id="bufferHealth">--</span></div>
    </div>

    <script src="stream-player.js"></script>
</body>
</html>

### JavaScript Stream Player

```javascript
// stream-player.js
class RTSPStreamPlayer {
    constructor(canvasId, wsUrl = 'ws://localhost:3000/ws') {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.wsUrl = wsUrl;
        this.ws = null;
        this.isPlaying = true;
        this.frameBuffer = [];
        this.maxBufferSize = 10;
        
        // Performance metrics
        this.metrics = {
            framesReceived: 0,
            framesRendered: 0,
            framesDropped: 0,
            lastFrameTime: 0,
            fps: 0,
            latency: 0,
            bandwidth: 0,
            bytesReceived: 0
        };
        
        // Timing for FPS calculation
        this.fpsInterval = setInterval(() => this.updateFPS(), 1000);
        this.bandwidthInterval = setInterval(() => this.updateBandwidth(), 1000);
        
        this.initializeWebSocket();
        this.setupEventListeners();
    }
    
    initializeWebSocket() {
        try {
            this.ws = new WebSocket(this.wsUrl);
            this.ws.binaryType = 'arraybuffer';
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.updateConnectionStatus(true);
            };
            
            this.ws.onmessage = (event) => {
                this.handleFrameData(event.data);
            };
            
            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                this.updateConnectionStatus(false);
                this.scheduleReconnect();
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.updateConnectionStatus(false);
            };
            
        } catch (error) {
            console.error('Failed to initialize WebSocket:', error);
            this.scheduleReconnect();
        }
    }
    
    handleFrameData(arrayBuffer) {
        if (!this.isPlaying) return;
        
        try {
            // Decode MessagePack data
            const frameData = msgpack.decode(new Uint8Array(arrayBuffer));
            
            // Update metrics
            this.metrics.framesReceived++;
            this.metrics.bytesReceived += arrayBuffer.byteLength;
            this.metrics.latency = Date.now() - frameData.timestamp;
            
            // Add to buffer
            if (this.frameBuffer.length >= this.maxBufferSize) {
                this.frameBuffer.shift(); // Remove oldest frame
                this.metrics.framesDropped++;
            }
            
            this.frameBuffer.push(frameData);
            this.processFrameBuffer();
            
        } catch (error) {
            console.error('Failed to decode frame data:', error);
        }
    }
    
    processFrameBuffer() {
        if (this.frameBuffer.length === 0 || !this.isPlaying) return;
        
        // Get next frame from buffer
        const frameData = this.frameBuffer.shift();
        
        // Create image from frame data
        const blob = new Blob([frameData.data], { type: 'image/jpeg' });
        const img = new Image();
        
        img.onload = () => {
            this.renderFrame(img, frameData.width, frameData.height);
            this.metrics.framesRendered++;
            this.metrics.lastFrameTime = Date.now();
        };
        
        img.onerror = () => {
            console.error('Failed to load frame image');
            this.metrics.framesDropped++;
        };
        
        img.src = URL.createObjectURL(blob);
    }
    
    renderFrame(image, width, height) {
        // Update canvas size if needed
        if (this.canvas.width !== width || this.canvas.height !== height) {
            this.canvas.width = width;
            this.canvas.height = height;
            this.updateResolutionDisplay(`${width}x${height}`);
        }
        
        // Clear and draw frame
        this.ctx.clearRect(0, 0, width, height);
        this.ctx.drawImage(image, 0, 0, width, height);
        
        // Cleanup blob URL
        URL.revokeObjectURL(image.src);
    }
    
    updateFPS() {
        this.metrics.fps = this.metrics.framesRendered;
        this.metrics.framesRendered = 0;
        this.updateMetricsDisplay();
    }
    
    updateBandwidth() {
        this.metrics.bandwidth = this.metrics.bytesReceived / 1024; // KB/s
        this.metrics.bytesReceived = 0;
    }
    
    updateConnectionStatus(connected) {