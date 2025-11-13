/**
 * RTSP Stream Player
 * Implements WebSocket client with createImageBitmap for high-performance rendering
 * Following PIPELINE_KNOWLEDGE.md specifications
 */

class RTSPStreamPlayer {
    constructor(canvasId, brokerUrl, streamId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.brokerUrl = brokerUrl;
        this.streamId = streamId;
        this.ws = null;
        this.reconnectTimeout = null;
        this.reconnectDelay = 3000; // 3 seconds as per spec
        
        // Metrics
        this.metrics = {
            framesReceived: 0,
            framesRendered: 0,
            framesDropped: 0,
            lastFrameTime: 0,
            fps: 0,
            latency: 0,
            bytesReceived: 0,
            bandwidth: 0
        };
        
        // FPS calculation
        this.fpsInterval = null;
        this.bandwidthInterval = null;
    }
    
    /**
     * Connect to WebSocket stream
     * Implements auto-reconnect pattern from PIPELINE_KNOWLEDGE.md
     */
    connect() {
        // Get configuration from UI
        let brokerUrl = document.getElementById('brokerUrl').value.trim();
        const streamId = document.getElementById('streamId').value.trim();
        
        // Convert http/https to ws/wss
        brokerUrl = brokerUrl.replace(/^http/, 'ws');
        
        // Remove trailing slash if present
        brokerUrl = brokerUrl.replace(/\/$/, '');
        
        // Remove /ws/stream_id if already present (to avoid duplication)
        brokerUrl = brokerUrl.replace(/\/ws\/[^\/]+$/, '');
        
        this.brokerUrl = brokerUrl;
        this.streamId = streamId;
        
        // Build WebSocket URL: ws://server/ws/:stream_id
        const wsUrl = `${this.brokerUrl}/ws/${this.streamId}`;
        
        console.log(`Connecting to: ${wsUrl}`);
        this.updateStatus('Connecting...', false);
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            // PENTING: Set binaryType ke 'arraybuffer' untuk performa optimal
            // Ini jauh lebih efisien daripada blob default
            this.ws.binaryType = 'arraybuffer';
            
            // Handler: onopen
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.updateStatus('Connected', true);
                this.startMetrics();
            };
            
            // Handler: onmessage - Hot path untuk performa
            this.ws.onmessage = async (event) => {
                await this.handleFrame(event.data);
            };
            
            // Handler: onclose - Auto-reconnect
            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                this.updateStatus('Disconnected', false);
                this.stopMetrics();
                // Auto-reconnect setelah 3 detik
                this.scheduleReconnect();
            };
            
            // Handler: onerror
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.updateStatus('Error', false);
            };
            
        } catch (error) {
            console.error('Failed to initialize WebSocket:', error);
            this.updateStatus('Connection failed', false);
            this.scheduleReconnect();
        }
    }
    
    /**
     * Handle incoming frame data
     * Hot path - optimized for performance using createImageBitmap
     */
    async handleFrame(arrayBuffer) {
        try {
            // event.data adalah ArrayBuffer
            const blob = new Blob([arrayBuffer], { type: 'image/webp' });
            
            // PENTING (Performa): createImageBitmap men-decode gambar di background thread
            // Ini mencegah main thread (UI) menjadi patah-patah
            const bitmap = await createImageBitmap(blob);
            
            // Update canvas size if needed
            if (this.canvas.width !== bitmap.width || this.canvas.height !== bitmap.height) {
                this.canvas.width = bitmap.width;
                this.canvas.height = bitmap.height;
                this.updateResolutionDisplay(`${bitmap.width}x${bitmap.height}`);
            }
            
            // Render frame ke canvas
            this.ctx.drawImage(bitmap, 0, 0, this.canvas.width, this.canvas.height);
            
            // Manajemen Memori: tutup bitmap untuk membebaskan memori
            bitmap.close();
            
            // Update metrics
            this.metrics.framesReceived++;
            this.metrics.framesRendered++;
            this.metrics.bytesReceived += arrayBuffer.byteLength;
            this.metrics.lastFrameTime = Date.now();
            
        } catch (error) {
            console.error('Failed to process frame:', error);
            this.metrics.framesDropped++;
        }
    }
    
    /**
     * Schedule reconnection after delay
     */
    scheduleReconnect() {
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
        }
        
        this.reconnectTimeout = setTimeout(() => {
            console.log('Attempting to reconnect...');
            this.connect();
        }, this.reconnectDelay);
    }
    
    /**
     * Disconnect from stream
     */
    disconnect() {
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        this.stopMetrics();
        this.updateStatus('Disconnected', false);
    }
    
    /**
     * Update connection status UI
     */
    updateStatus(text, connected) {
        document.getElementById('statusText').textContent = text;
        const indicator = document.getElementById('statusIndicator');
        if (connected) {
            indicator.classList.add('connected');
        } else {
            indicator.classList.remove('connected');
        }
    }
    
    /**
     * Start metrics collection
     */
    startMetrics() {
        // FPS calculation
        this.fpsInterval = setInterval(() => {
            this.metrics.fps = this.metrics.framesRendered;
            this.metrics.framesRendered = 0;
            this.updateMetricsDisplay();
        }, 1000);
        
        // Bandwidth calculation
        this.bandwidthInterval = setInterval(() => {
            this.metrics.bandwidth = this.metrics.bytesReceived / 1024; // KB/s
            this.metrics.bytesReceived = 0;
            this.updateMetricsDisplay();
        }, 1000);
    }
    
    /**
     * Stop metrics collection
     */
    stopMetrics() {
        if (this.fpsInterval) {
            clearInterval(this.fpsInterval);
            this.fpsInterval = null;
        }
        if (this.bandwidthInterval) {
            clearInterval(this.bandwidthInterval);
            this.bandwidthInterval = null;
        }
    }
    
    /**
     * Update metrics display
     */
    updateMetricsDisplay() {
        document.getElementById('fpsCounter').textContent = this.metrics.fps;
        document.getElementById('frameCounter').textContent = this.metrics.framesReceived;
        document.getElementById('droppedFrames').textContent = this.metrics.framesDropped;
        
        // Calculate latency (simplified - would need server timestamp for real latency)
        if (this.metrics.lastFrameTime > 0) {
            const latency = Date.now() - this.metrics.lastFrameTime;
            document.getElementById('latencyText').textContent = `Latency: ~${latency}ms`;
        }
    }
    
    /**
     * Update resolution display
     */
    updateResolutionDisplay(resolution) {
        document.getElementById('resolutionDisplay').textContent = resolution;
    }
}

// Global player instance
let player = null;

// Initialize player on page load
window.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('videoCanvas');
    const brokerUrl = document.getElementById('brokerUrl').value;
    const streamId = document.getElementById('streamId').value;
    
    player = new RTSPStreamPlayer('videoCanvas', brokerUrl, streamId);
});

// Global functions for UI buttons
function connect() {
    if (player) {
        player.connect();
    }
}

function disconnect() {
    if (player) {
        player.disconnect();
    }
}

function toggleStats() {
    const panel = document.getElementById('metricsPanel');
    panel.style.display = panel.style.display === 'none' ? 'grid' : 'none';
}

function captureFrame() {
    if (player && player.canvas) {
        // Convert canvas to data URL and download
        const dataUrl = player.canvas.toDataURL('image/png');
        const link = document.createElement('a');
        link.download = `frame-${Date.now()}.png`;
        link.href = dataUrl;
        link.click();
    }
}

