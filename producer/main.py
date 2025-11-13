#!/usr/bin/env python3
"""
RTSP Producer - Transcodes RTSP stream to WebP frames and sends to Axum broker
Following PIPELINE_KNOWLEDGE.md specifications
"""

import cv2
import httpx
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
    """Producer that reads RTSP stream, transcodes to WebP, and sends to broker"""
    
    def __init__(self, rtsp_url: str, broker_url: str, stream_id: str = "stream1", target_fps: int = 30):
        self.rtsp_url = rtsp_url
        self.broker_url = broker_url.rstrip('/')
        self.stream_id = stream_id
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        
        # HTTP/2 client - created once, reused for all requests
        self.client: Optional[httpx.Client] = None
        self.cap: Optional[cv2.VideoCapture] = None
        
        # Performance tracking
        self.frames_sent = 0
        self.last_fps_check = time.time()
    
    def initialize_client(self):
        """Initialize HTTP client with HTTP/2 support (falls back to HTTP/1.1 if server doesn't support HTTP/2)"""
        try:
            # httpx will try HTTP/2 first, then fallback to HTTP/1.1 if server doesn't support it
            # For HTTPS, HTTP/2 is typically available. For HTTP, HTTP/1.1 is used with keep-alive
            # Verify SSL is disabled for self-signed certificates in development
            verify_ssl = os.getenv("VERIFY_SSL", "false").lower() == "true"
            
            self.client = httpx.Client(
                http2=True,  # Try HTTP/2, fallback to HTTP/1.1 automatically
                timeout=10.0,
                verify=verify_ssl,  # Set to False for self-signed certificates
                limits=httpx.Limits(
                    max_keepalive_connections=1,  # Reuse single connection (key to performance)
                    max_connections=1
                )
            )
            protocol = "HTTPS/HTTP/2" if self.broker_url.startswith("https") else "HTTP/2 preferred, HTTP/1.1 fallback"
            logger.info(f"HTTP client initialized ({protocol})")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize HTTP client: {e}")
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
        """Transcode frame to WebP binary"""
        try:
            # Encode frame as WebP
            ret, buffer = cv2.imencode(
                ".webp",
                frame,
                [cv2.IMWRITE_WEBP_QUALITY, 80]
            )
            
            if not ret:
                logger.warning("Failed to encode frame as WebP")
                return None
            
            return buffer.tobytes()
        except Exception as e:
            logger.error(f"Frame processing error: {e}")
            return None
    
    def send_frame(self, frame_data: bytes) -> bool:
        """Send frame to broker via HTTP/2 POST"""
        try:
            url = f"{self.broker_url}/ingest/{self.stream_id}"
            response = self.client.post(
                url,
                content=frame_data,
                headers={"Content-Type": "image/webp"}
            )
            
            if response.status_code == 200:
                return True
            else:
                logger.warning(f"Server returned status {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Frame send error: {e}")
            return False
    
    def run(self):
        """Main entry point - implements two-loop pattern for resilience"""
        # Initialize HTTP/2 client once
        if not self.initialize_client():
            logger.error("Failed to initialize HTTP/2 client")
            return
        
        # Outer loop: handles reconnection
        while True:
            # Try to connect to RTSP stream
            if not self.connect_rtsp():
                logger.warning("RTSP connection failed, retrying in 5 seconds...")
                time.sleep(5)
                continue
            
            # Inner loop: reads frames from RTSP stream
            last_frame_time = 0
            while self.cap.isOpened():
                try:
                    current_time = time.time()
                    
                    # FPS regulation - ensure we don't exceed target FPS
                    elapsed = current_time - last_frame_time
                    if elapsed < self.frame_interval:
                        time.sleep(self.frame_interval - elapsed)
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
                        if self.send_frame(frame_data):
                            self.frames_sent += 1
                            last_frame_time = time.time()
                    
                    # FPS monitoring
                    if current_time - self.last_fps_check >= 5.0:
                        fps = self.frames_sent / 5.0
                        logger.info(f"Streaming at {fps:.1f} FPS")
                        self.frames_sent = 0
                        self.last_fps_check = current_time
                
                except Exception as e:
                    logger.error(f"Error in frame loop: {e}")
                    break  # Break inner loop, triggers reconnection
            
            # Cleanup and reconnect
            if self.cap:
                self.cap.release()
                self.cap = None
            
            logger.info("Reconnecting in 5 seconds...")
            time.sleep(5)
    
    def cleanup(self):
        """Clean up resources"""
        if self.cap:
            self.cap.release()
        if self.client:
            self.client.close()


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
    
    logger.info(f"Starting RTSP Producer")
    logger.info(f"  RTSP URL: {rtsp_url}")
    logger.info(f"  Broker URL: {broker_url} ({broker_protocol.upper()})")
    logger.info(f"  Stream ID: {stream_id}")
    logger.info(f"  Target FPS: {target_fps}")
    if use_https:
        logger.info(f"  SSL Verification: {os.getenv('VERIFY_SSL', 'false')}")
    
    producer = RTSPProducer(
        rtsp_url=rtsp_url,
        broker_url=broker_url,
        stream_id=stream_id,
        target_fps=target_fps
    )
    
    try:
        producer.run()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        producer.cleanup()
        logger.info("Producer stopped")


if __name__ == "__main__":
    main()

