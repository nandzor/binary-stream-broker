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
            previousFrameTime: 0,  // Untuk menghitung latency antar frame
            fps: 0,
            latency: 0,
            bytesReceived: 0,
            bandwidth: 0
        };
        
        // FPS calculation
        this.fpsInterval = null;
        this.bandwidthInterval = null;
        this.latencyCheckInterval = null;
        this.overlayRedrawInterval = null;
        
        // Latency threshold untuk auto-disconnect (7 detik = 7000ms)
        this.maxLatency = 7000;
        
        // Flag untuk disconnected overlay
        this.showDisconnectedOverlay = false;
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
                this.showDisconnectedOverlay = false;
                // Stop overlay redraw jika masih berjalan
                if (this.overlayRedrawInterval) {
                    clearInterval(this.overlayRedrawInterval);
                    this.overlayRedrawInterval = null;
                }
                this.metrics.lastFrameTime = Date.now();
                this.metrics.previousFrameTime = Date.now();
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
                this.showDisconnectedMessage();
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
     * Supports multiple formats: WebP, JPEG, PNG, or raw binary
     */
    async handleFrame(arrayBuffer) {
        try {
            // Detect format dari magic bytes
            const format = this.detectImageFormat(arrayBuffer);
            
            // Jika raw binary, decode menggunakan ImageData (untuk raw BGR/RGB)
            if (format === 'raw') {
                await this.handleRawFrame(arrayBuffer);
                return;
            }
            
            // Untuk format image (WebP, JPEG, PNG), gunakan createImageBitmap
            const blob = new Blob([arrayBuffer], { type: `image/${format}` });
            
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
            
            // Update frame timing untuk latency calculation
            const currentTime = Date.now();
            this.metrics.previousFrameTime = this.metrics.lastFrameTime;
            this.metrics.lastFrameTime = currentTime;
            
            // Hide disconnected overlay jika ada frame baru
            if (this.showDisconnectedOverlay) {
                this.showDisconnectedOverlay = false;
                // Stop overlay redraw interval
                if (this.overlayRedrawInterval) {
                    clearInterval(this.overlayRedrawInterval);
                    this.overlayRedrawInterval = null;
                }
            }
            
        } catch (error) {
            console.error('Failed to process frame:', error);
            this.metrics.framesDropped++;
        }
    }
    
    /**
     * Detect image format dari magic bytes
     */
    detectImageFormat(arrayBuffer) {
        const bytes = new Uint8Array(arrayBuffer);
        
        // WebP: RIFF...WEBP
        if (bytes.length >= 12 && 
            bytes[0] === 0x52 && bytes[1] === 0x49 && 
            bytes[2] === 0x46 && bytes[3] === 0x46 &&
            bytes[8] === 0x57 && bytes[9] === 0x45 && 
            bytes[10] === 0x42 && bytes[11] === 0x50) {
            return 'webp';
        }
        
        // JPEG: FF D8 FF
        if (bytes.length >= 3 && bytes[0] === 0xFF && bytes[1] === 0xD8 && bytes[2] === 0xFF) {
            return 'jpeg';
        }
        
        // PNG: 89 50 4E 47
        if (bytes.length >= 4 && 
            bytes[0] === 0x89 && bytes[1] === 0x50 && 
            bytes[2] === 0x4E && bytes[3] === 0x47) {
            return 'png';
        }
        
        // Default: assume raw binary (BGR format dari OpenCV)
        return 'raw';
    }
    
    /**
     * Handle raw binary frame (BGR format dari OpenCV)
     * Note: Raw binary memerlukan informasi width/height yang harus dikirim terpisah
     * atau di-hardcode. Untuk saat ini, kita skip raw binary atau gunakan format image.
     */
    async handleRawFrame(arrayBuffer) {
        // Raw binary dari OpenCV adalah BGR format
        // Untuk decode, kita perlu width, height, dan channels
        // Karena tidak ada metadata, kita tidak bisa langsung decode
        // Solusi: gunakan format image (WebP/JPEG) atau kirim metadata terpisah
        
        console.warn('Raw binary frame received but cannot decode without width/height metadata');
        console.warn('Consider using image format (WebP/JPEG/PNG) instead');
        this.metrics.framesDropped++;
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
        this.showDisconnectedMessage();
        
        // Reset metrics display when disconnected
        document.getElementById('fpsText').textContent = 'FPS: 0';
        document.getElementById('bandwidthText').textContent = 'MB/s: 0.00';
        document.getElementById('latencyText').textContent = 'Latency: --ms';
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
        // FPS calculation - frames per second
        this.fpsInterval = setInterval(() => {
            this.metrics.fps = this.metrics.framesRendered;
            this.metrics.framesRendered = 0;
            this.updateMetricsDisplay();
        }, 1000);
        
        // Bandwidth calculation - MB per second
        this.bandwidthInterval = setInterval(() => {
            // Convert bytes to MB: bytes / (1024 * 1024)
            this.metrics.bandwidth = this.metrics.bytesReceived / (1024 * 1024); // MB/s
            this.metrics.bytesReceived = 0;
            this.updateMetricsDisplay();
        }, 1000);
        
        // Latency check - monitor untuk auto-disconnect jika latency >= 7 detik
        this.latencyCheckInterval = setInterval(() => {
            this.checkLatencyAndDisconnect();
        }, 1000); // Check setiap 1 detik
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
        if (this.latencyCheckInterval) {
            clearInterval(this.latencyCheckInterval);
            this.latencyCheckInterval = null;
        }
        if (this.overlayRedrawInterval) {
            clearInterval(this.overlayRedrawInterval);
            this.overlayRedrawInterval = null;
        }
    }
    
    /**
     * Check latency and auto-disconnect if >= 7 seconds
     */
    checkLatencyAndDisconnect() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            return; // Already disconnected
        }
        
        const currentTime = Date.now();
        const timeSinceLastFrame = currentTime - this.metrics.lastFrameTime;
        
        // Jika tidak ada frame baru dalam 7 detik, disconnect dan tampilkan overlay
        if (timeSinceLastFrame >= this.maxLatency) {
            console.warn(`Latency exceeded ${this.maxLatency}ms (${timeSinceLastFrame}ms), disconnecting...`);
            // Tampilkan overlay disconnected SEBELUM disconnect
            this.showDisconnectedOverlay = true;
            this.drawDisconnectedOverlay();
            // Lalu disconnect
            this.disconnectDueToLatency();
        } else if (timeSinceLastFrame >= 5000) {
            // Warning: jika latency >= 5 detik tapi belum 7 detik, tampilkan overlay warning
            // Tapi jangan disconnect dulu
            if (!this.showDisconnectedOverlay) {
                this.showDisconnectedOverlay = true;
                this.drawWarningOverlay(timeSinceLastFrame);
            }
        }
    }
    
    /**
     * Disconnect due to high latency
     */
    disconnectDueToLatency() {
        // Pastikan overlay sudah ditampilkan
        this.showDisconnectedOverlay = true;
        this.drawDisconnectedOverlay();
        
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        this.stopMetrics();
        this.updateStatus('Disconnected (High Latency)', false);
        
        // Start overlay redraw interval untuk memastikan overlay tetap terlihat
        this.showDisconnectedMessage();
        
        // Reset metrics display
        document.getElementById('fpsText').textContent = 'FPS: 0';
        document.getElementById('bandwidthText').textContent = 'MB/s: 0.00';
        document.getElementById('latencyText').textContent = 'Latency: --ms';
        
        // Auto-reconnect setelah 3 detik
        this.scheduleReconnect();
    }
    
    /**
     * Show disconnected message overlay on canvas
     */
    showDisconnectedMessage() {
        this.showDisconnectedOverlay = true;
        this.drawDisconnectedOverlay();
        
        // Redraw overlay setiap 100ms untuk memastikan tetap terlihat
        if (this.overlayRedrawInterval) {
            clearInterval(this.overlayRedrawInterval);
        }
        this.overlayRedrawInterval = setInterval(() => {
            if (this.showDisconnectedOverlay) {
                this.drawDisconnectedOverlay();
            } else {
                clearInterval(this.overlayRedrawInterval);
                this.overlayRedrawInterval = null;
            }
        }, 100);
    }
    
    /**
     * Draw disconnected overlay on canvas
     */
    drawDisconnectedOverlay() {
        if (!this.canvas) {
            return;
        }
        
        // Pastikan canvas memiliki ukuran yang valid
        let width = this.canvas.width;
        let height = this.canvas.height;
        
        // Jika canvas belum di-set ukurannya, gunakan ukuran default atau dari container
        if (width === 0 || height === 0) {
            // Coba ambil dari computed style atau gunakan default
            const rect = this.canvas.getBoundingClientRect();
            width = rect.width || 640;
            height = rect.height || 480;
            
            // Set canvas size
            this.canvas.width = width;
            this.canvas.height = height;
        }
        
        // Clear canvas dengan background hitam
        this.ctx.fillStyle = '#000000';
        this.ctx.fillRect(0, 0, width, height);
        
        // Draw disconnected message
        const message = 'DISCONNECTED';
        const reason = 'High Latency Detected';
        const subMessage = 'Reconnecting...';
        
        // Calculate center
        const centerX = width / 2;
        const centerY = height / 2;
        
        // Set font properties untuk message utama
        const fontSize = Math.min(width, height) * 0.08; // 8% dari ukuran canvas, min 32px
        this.ctx.font = `bold ${Math.max(fontSize, 32)}px Arial`;
        this.ctx.fillStyle = '#ff4444';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        
        // Draw main message
        this.ctx.fillText(message, centerX, centerY - 20);
        
        // Draw reason
        this.ctx.font = `${Math.max(fontSize * 0.5, 18)}px Arial`;
        this.ctx.fillStyle = '#ff8888';
        this.ctx.fillText(reason, centerX, centerY + 30);
        
        // Draw sub message
        this.ctx.font = `${Math.max(fontSize * 0.4, 16)}px Arial`;
        this.ctx.fillStyle = '#aaaaaa';
        this.ctx.fillText(subMessage, centerX, centerY + 70);
    }
    
    /**
     * Draw warning overlay (latency tinggi tapi belum disconnect)
     */
    drawWarningOverlay(latencyMs) {
        if (!this.canvas) {
            return;
        }
        
        // Pastikan canvas memiliki ukuran yang valid
        let width = this.canvas.width;
        let height = this.canvas.height;
        
        if (width === 0 || height === 0) {
            const rect = this.canvas.getBoundingClientRect();
            width = rect.width || 640;
            height = rect.height || 480;
            this.canvas.width = width;
            this.canvas.height = height;
        }
        
        // Draw semi-transparent overlay (jangan clear canvas, overlay saja)
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        this.ctx.fillRect(0, 0, width, height);
        
        const centerX = width / 2;
        const centerY = height / 2;
        
        // Warning message
        const fontSize = Math.min(width, height) * 0.06;
        this.ctx.font = `bold ${Math.max(fontSize, 24)}px Arial`;
        this.ctx.fillStyle = '#ffaa00';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        
        this.ctx.fillText('HIGH LATENCY WARNING', centerX, centerY - 20);
        
        this.ctx.font = `${Math.max(fontSize * 0.6, 18)}px Arial`;
        this.ctx.fillStyle = '#ffcc88';
        this.ctx.fillText(`${(latencyMs / 1000).toFixed(1)}s - Disconnecting soon...`, centerX, centerY + 20);
    }
    
    /**
     * Update metrics display
     */
    updateMetricsDisplay() {
        // Update detailed metrics panel
        document.getElementById('fpsCounter').textContent = this.metrics.fps;
        document.getElementById('frameCounter').textContent = this.metrics.framesReceived;
        document.getElementById('droppedFrames').textContent = this.metrics.framesDropped;
        
        // Update status bar with real-time info
        document.getElementById('fpsText').textContent = `FPS: ${this.metrics.fps}`;
        document.getElementById('bandwidthText').textContent = `MB/s: ${this.metrics.bandwidth.toFixed(2)}`;
        
        // Calculate latency berdasarkan waktu sejak frame terakhir diterima
        if (this.metrics.lastFrameTime > 0) {
            const latency = Date.now() - this.metrics.lastFrameTime;
            this.metrics.latency = latency;
            
            // Warn jika latency tinggi (>= 5 detik)
            let latencyText = `Latency: ~${latency}ms`;
            if (latency >= 5000) {
                latencyText = `Latency: ~${(latency / 1000).toFixed(1)}s ⚠️`;
            }
            document.getElementById('latencyText').textContent = latencyText;
        } else {
            document.getElementById('latencyText').textContent = `Latency: --ms`;
        }
        
        // Redraw disconnected overlay jika perlu
        if (this.showDisconnectedOverlay) {
            this.drawDisconnectedOverlay();
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

