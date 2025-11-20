#!/usr/bin/env python3
"""
RTSP Producer - Transcodes RTSP stream to WebP frames and sends to Axum broker via WebSocket
Following PIPELINE_KNOWLEDGE.md specifications
"""

import cv2
import asyncio
import websockets
import time
import logging
import os
from typing import Optional

# Try to import dotenv, fallback if not available
try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    # If python-dotenv is not installed, create a no-op function
    def load_dotenv():
        pass

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RTSPProducer:
    """Producer that reads RTSP stream, optionally transcodes, and sends to broker via WebSocket
    
    Optimized for low CPU usage and network bandwidth:
    - JPEG encoding (faster than WebP, good compression)
    - Optional frame resizing to reduce data size
    - Optimized encoding parameters
    """
    
    def __init__(self, rtsp_url: str, broker_url: str, stream_id: str = "stream1", target_fps: int = 30, 
                 encode_format: Optional[str] = "jpeg", encode_quality: int = 75, max_width: Optional[int] = None):
        self.rtsp_url = rtsp_url
        self.broker_url = broker_url.rstrip('/')
        self.stream_id = stream_id
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self.encode_format = encode_format.lower() if encode_format else None  # None = raw binary
        self.encode_quality = encode_quality
        self.max_width = max_width  # Resize frame if width > max_width (reduces network & CPU)
        
        # WebSocket connection
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.cap: Optional[cv2.VideoCapture] = None
        
        # Performance tracking
        self.frames_sent = 0
        self.last_fps_check = time.time()
    
    def get_websocket_url(self) -> str:
        """Convert broker URL to WebSocket URL"""
        # Convert http/https to ws/wss
        ws_url = self.broker_url.replace("http://", "ws://").replace("https://", "wss://")
        # Build WebSocket URL: ws://server/ws/ingest/:stream_id
        return f"{ws_url}/ws/ingest/{self.stream_id}"
    
    async def connect_websocket(self) -> bool:
        """Connect to broker via WebSocket"""
        try:
            ws_url = self.get_websocket_url()
            verify_ssl = os.getenv("VERIFY_SSL", "false").lower() == "true"
            
            # For wss (secure WebSocket), we need to handle SSL verification
            ssl_context = None
            if ws_url.startswith("wss://") and not verify_ssl:
                import ssl
                ssl_context = ssl.SSLContext()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            
            self.ws = await websockets.connect(
                ws_url,
                ssl=ssl_context,
                ping_interval=20,  # Send ping every 20 seconds
                ping_timeout=10,   # Wait 10 seconds for pong
                close_timeout=10
            )
            
            protocol = "WSS" if ws_url.startswith("wss://") else "WS"
            logger.info(f"WebSocket client connected ({protocol}) to: {ws_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect WebSocket: {e}")
            return False
    
    def connect_rtsp(self) -> bool:
        """Connect to RTSP stream"""
        try:
            self.cap = cv2.VideoCapture(self.rtsp_url)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize buffer lag
            
            if not self.cap.isOpened():
                logger.error(f"Failed to open RTSP stream: {self.rtsp_url}")
                return False
            
            logger.info(f"Connected to RTSP stream: {self.rtsp_url}")
            return True
        except Exception as e:
            logger.error(f"RTSP connection error: {e}")
            return False
    
    def process_frame(self, frame) -> Optional[bytes]:
        """Process frame: resize if needed, then encode to specified format
        
        Optimized for speed and network efficiency:
        - Resize large frames to reduce encoding time and network bandwidth
        - Use optimized encoding parameters
        """
        try:
            # Resize frame jika diperlukan (mengurangi ukuran data dan waktu encoding)
            if self.max_width is not None:
                height, width = frame.shape[:2]
                if width > self.max_width:
                    scale = self.max_width / width
                    new_width = self.max_width
                    new_height = int(height * scale)
                    # INTER_LINEAR lebih cepat daripada INTER_CUBIC, cukup untuk streaming
                    frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
            
            # Jika tidak ada format encoding, kirim raw frame bytes
            if self.encode_format is None:
                # Convert frame to raw bytes (BGR format dari OpenCV)
                height, width, channels = frame.shape
                return frame.tobytes()
            
            # Encode frame sesuai format yang dipilih dengan optimasi
            if self.encode_format == "jpeg" or self.encode_format == "jpg":
                # JPEG: encoding cepat, kompresi bagus
                # Optimize JPEG: optimize Huffman tables untuk ukuran lebih kecil
                encode_params = [
                    cv2.IMWRITE_JPEG_QUALITY, self.encode_quality,
                    cv2.IMWRITE_JPEG_OPTIMIZE, 1  # Optimize Huffman tables (smaller file)
                ]
                ext = ".jpg"
            elif self.encode_format == "webp":
                # WebP: kompresi lebih baik tapi encoding lebih lambat
                encode_params = [cv2.IMWRITE_WEBP_QUALITY, self.encode_quality]
                ext = ".webp"
            elif self.encode_format == "png":
                # PNG: lossless tapi file besar, tidak disarankan untuk streaming
                png_quality = min(9, max(0, self.encode_quality // 10))
                encode_params = [cv2.IMWRITE_PNG_COMPRESSION, png_quality]
                ext = ".png"
            else:
                logger.warning(f"Unknown encode format: {self.encode_format}, using JPEG")
                encode_params = [
                    cv2.IMWRITE_JPEG_QUALITY, self.encode_quality,
                    cv2.IMWRITE_JPEG_OPTIMIZE, 1
                ]
                ext = ".jpg"
            
            ret, buffer = cv2.imencode(ext, frame, encode_params)
            
            if not ret:
                logger.warning(f"Failed to encode frame as {self.encode_format}")
                return None
            
            return buffer.tobytes()
        except Exception as e:
            logger.error(f"Frame processing error: {e}")
            return None
    
    async def send_frame(self, frame_data: bytes) -> bool:
        """Send frame to broker via WebSocket"""
        try:
            if self.ws is None:
                logger.error("WebSocket not connected")
                return False
            
            await self.ws.send(frame_data)
            return True
        except Exception as e:
            logger.error(f"Frame send error: {e}")
            return False
    
    async def run_async(self):
        """Main entry point - implements two-loop pattern for resilience"""
        try:
            # Outer loop: handles reconnection
            while True:
                # Try to connect to WebSocket
                if not await self.connect_websocket():
                    logger.warning("WebSocket connection failed, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue
                
                # Try to connect to RTSP stream
                if not self.connect_rtsp():
                    logger.warning("RTSP connection failed, retrying in 5 seconds...")
                    if self.ws:
                        await self.cleanup_websocket()
                    await asyncio.sleep(5)
                    continue
                
                # Inner loop: reads frames from RTSP stream
                last_frame_time = 0
                while self.cap.isOpened() and self.ws is not None:
                    try:
                        current_time = time.time()
                        
                        # FPS regulation - ensure we don't exceed target FPS
                        elapsed = current_time - last_frame_time
                        if elapsed < self.frame_interval:
                            await asyncio.sleep(self.frame_interval - elapsed)
                            continue
                        
                        # Read frame from RTSP
                        ret, frame = self.cap.read()
                        if not ret:
                            logger.warning("Failed to read frame, reconnecting...")
                            break  # Break inner loop, triggers reconnection
                        
                        # Process frame (transcode to WebP)
                        frame_data = self.process_frame(frame)
                        if frame_data:
                            # Send to broker
                            if await self.send_frame(frame_data):
                                self.frames_sent += 1
                                last_frame_time = time.time()
                        
                        # FPS monitoring
                        if current_time - self.last_fps_check >= 5.0:
                            fps = self.frames_sent / 5.0
                            logger.info(f"Streaming at {fps:.1f} FPS")
                            self.frames_sent = 0
                            self.last_fps_check = current_time
                    
                    except asyncio.CancelledError:
                        # Task cancelled (e.g., KeyboardInterrupt)
                        logger.info("Frame loop cancelled")
                        raise
                    except Exception as e:
                        logger.error(f"Error in frame loop: {e}")
                        break  # Break inner loop, triggers reconnection
                
                # Cleanup and reconnect
                await self.cleanup_connections()
                
                logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("Producer task cancelled, cleaning up...")
            await self.cleanup_connections()
            raise
    
    async def cleanup_websocket(self):
        """Close WebSocket connection properly"""
        if self.ws is not None:
            try:
                logger.info("Closing WebSocket connection...")
                await self.ws.close()
                logger.info("WebSocket connection closed")
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None
    
    async def cleanup_connections(self):
        """Clean up all connections (WebSocket and RTSP)"""
        await self.cleanup_websocket()
        
        if self.cap is not None:
            try:
                self.cap.release()
                logger.info("RTSP connection released")
            except Exception as e:
                logger.warning(f"Error releasing RTSP: {e}")
            finally:
                self.cap = None
    
    def run(self):
        """Synchronous wrapper for async run"""
        loop = None
        try:
            # Create event loop and run async code
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.run_async())
        except KeyboardInterrupt:
            logger.info("Received shutdown signal (Ctrl+C)")
            # Ensure cleanup happens
            if loop and not loop.is_closed():
                try:
                    # Cancel all running tasks
                    tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
                    for task in tasks:
                        task.cancel()
                    # Wait for tasks to complete cancellation (with timeout)
                    if tasks:
                        loop.run_until_complete(
                            asyncio.wait_for(
                                asyncio.gather(*tasks, return_exceptions=True),
                                timeout=2.0
                            )
                        )
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"Error during task cancellation: {e}")
                finally:
                    # Always try to cleanup connections
                    try:
                        loop.run_until_complete(self.cleanup_connections())
                    except Exception as e:
                        logger.warning(f"Error during cleanup: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            # Try cleanup if loop exists
            if loop and not loop.is_closed():
                try:
                    loop.run_until_complete(self.cleanup_connections())
                except Exception:
                    pass
        finally:
            # Close event loop
            if loop and not loop.is_closed():
                try:
                    # Cancel remaining tasks
                    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                    for task in pending:
                        task.cancel()
                    # Run one more time to let cancellations complete
                    if pending:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    loop.close()
                except Exception as e:
                    logger.warning(f"Error closing event loop: {e}")
            logger.info("Producer stopped")
    
    def cleanup(self):
        """Synchronous cleanup (deprecated, use cleanup_connections instead)"""
        # This method is kept for backward compatibility but should not be used
        # WebSocket cleanup requires async, so use cleanup_connections() instead
        if self.cap:
            self.cap.release()


def main():
    """Main entry point"""
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, ".env")
    
    # Load environment variables from .env file
    # Explicitly specify the path to ensure .env is found
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
        logger.info(f"Loaded environment variables from: {env_path}")
    else:
        # Try to load from current directory as fallback
        load_dotenv()
        if os.path.exists(".env"):
            logger.info("Loaded environment variables from: .env (current directory)")
        else:
            logger.warning("No .env file found, using environment variables or defaults")
    
    # Configuration from environment variables or defaults
    rtsp_url = os.getenv("RTSP_URL", "rtsp://admin:KAQSML@172.16.6.77:554")
    # Default to HTTPS (port 3090) for Docker/Caddy setup, or HTTP (port 3091) for direct access
    use_https = os.getenv("USE_HTTPS", "true").lower() == "true"  # Default to HTTPS
    broker_port = os.getenv("BROKER_PORT", "3090" if use_https else "3091")
    broker_protocol = "https" if use_https else "http"
    broker_url = os.getenv("BROKER_URL", f"{broker_protocol}://localhost:{broker_port}")
    stream_id = os.getenv("STREAM_ID", "stream1")
    target_fps = int(os.getenv("TARGET_FPS", "30"))
    
    # Encoding configuration: "jpeg" (default, fastest), "webp", "png", atau None/"" untuk raw binary
    # JPEG adalah default karena encoding lebih cepat daripada WebP dengan kompresi yang masih bagus
    encode_format = os.getenv("ENCODE_FORMAT", "jpeg")
    if encode_format.lower() in ["none", "raw", ""]:
        encode_format = None
    # Quality 75 adalah sweet spot: ukuran kecil, encoding cepat, kualitas masih bagus
    encode_quality = int(os.getenv("ENCODE_QUALITY", "75"))
    
    # Max width untuk resize frame (None = tidak resize, mengurangi network & CPU jika di-set)
    max_width_str = os.getenv("MAX_WIDTH", "")
    max_width = int(max_width_str) if max_width_str.isdigit() else None
    
    # Convert to WebSocket protocol
    ws_protocol = "wss" if use_https else "ws"
    ws_broker_url = broker_url.replace("https://", "wss://").replace("http://", "ws://")
    
    logger.info(f"Starting RTSP Producer (Optimized for Speed & Efficiency)")
    logger.info(f"  RTSP URL: {rtsp_url}")
    logger.info(f"  Broker URL: {broker_url} ({broker_protocol.upper()})")
    logger.info(f"  WebSocket URL: {ws_broker_url}/ws/ingest/{stream_id} ({ws_protocol.upper()})")
    logger.info(f"  Stream ID: {stream_id}")
    logger.info(f"  Target FPS: {target_fps}")
    logger.info(f"  Encode Format: {encode_format if encode_format else 'RAW (no encoding)'}")
    if encode_format:
        logger.info(f"  Encode Quality: {encode_quality}")
    if max_width:
        logger.info(f"  Max Width: {max_width}px (frames will be resized if larger)")
    else:
        logger.info(f"  Max Width: No resize (use MAX_WIDTH env var to enable)")
    if use_https:
        logger.info(f"  SSL Verification: {os.getenv('VERIFY_SSL', 'false')}")
    
    producer = RTSPProducer(
        rtsp_url=rtsp_url,
        broker_url=broker_url,
        stream_id=stream_id,
        target_fps=target_fps,
        encode_format=encode_format,
        encode_quality=encode_quality,
        max_width=max_width
    )
    
    producer.run()
    logger.info("Producer stopped")


if __name__ == "__main__":
    main()

