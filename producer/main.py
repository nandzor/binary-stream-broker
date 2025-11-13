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
import json
import random
from typing import Optional, List, Dict, Tuple

# Try to import dotenv, fallback if not available
try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    # If python-dotenv is not installed, create a no-op function
    def load_dotenv():
        pass

# Constants
DEFAULT_WEBP_QUALITY = 80
DEFAULT_FPS = 30
DEFAULT_RECONNECT_DELAY = 5
DEFAULT_FPS_CHECK_INTERVAL = 5.0
DEFAULT_RTSP_BUFFER_SIZE = 1
DEFAULT_HTTP_TIMEOUT = 10.0
DEFAULT_LABEL_OFFSET_ABOVE = -10
DEFAULT_LABEL_OFFSET_BELOW = 20
DEFAULT_LABEL_Y_THRESHOLD = 20
DEFAULT_BOX_THICKNESS = 2
DEFAULT_FONT_SCALE = 0.6
DEFAULT_COLOR_GREEN = "0,255,0"
DEFAULT_COLOR_WHITE = "255,255,255"
DEFAULT_COLOR_BLACK_BGR = (0, 0, 0)

# Random box colors (RGB format)
RANDOM_BOX_COLORS = [
    "0,255,0",    # Green
    "255,0,0",    # Red
    "0,0,255",    # Blue
    "255,255,0",  # Yellow
    "255,0,255",  # Magenta
    "0,255,255",  # Cyan
]

# HTTP Status Codes
HTTP_OK = 200
HTTP_ACCEPTED = 202

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RTSPProducer:
    """Producer that reads RTSP stream, transcodes to WebP, and sends to broker"""
    
    def __init__(self, rtsp_url: str, broker_url: str, stream_id: str = "stream1", target_fps: int = 30, bounding_boxes: Optional[List[Dict]] = None, 
                 random_boxes: bool = False, random_box_count: int = 3, random_box_min_size: float = 0.1, random_box_max_size: float = 0.3):
        self.rtsp_url = rtsp_url
        self.broker_url = broker_url.rstrip('/')
        self.stream_id = stream_id
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self.bounding_boxes = bounding_boxes or []
        
        # Random bounding box configuration
        self.random_boxes = random_boxes
        self.random_box_count = random_box_count
        self.random_box_min_size = random_box_min_size
        self.random_box_max_size = random_box_max_size
        
        # Frame buffer for 30 FPS guarantee
        self.last_frame = None
        self.last_frame_time = 0
        
        # HTTP/2 client - created once, reused for all requests
        self.client: Optional[httpx.Client] = None
        self.cap: Optional[cv2.VideoCapture] = None
        
        # Performance tracking
        self.frames_sent = 0
        self.last_fps_check = time.time()
        self.frames_duplicated = 0  # Track duplicated frames for 30 FPS
    
    def initialize_client(self):
        """Initialize HTTP client with HTTP/2 support (falls back to HTTP/1.1 if server doesn't support HTTP/2)"""
        try:
            # httpx will try HTTP/2 first, then fallback to HTTP/1.1 if server doesn't support it
            # For HTTPS, HTTP/2 is typically available. For HTTP, HTTP/1.1 is used with keep-alive
            # Verify SSL is disabled for self-signed certificates in development
            verify_ssl = os.getenv("VERIFY_SSL", "false").lower() == "true"
            
            self.client = httpx.Client(
                http2=True,  # Try HTTP/2, fallback to HTTP/1.1 automatically
                timeout=DEFAULT_HTTP_TIMEOUT,
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
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, DEFAULT_RTSP_BUFFER_SIZE)
            
            if not self.cap.isOpened():
                logger.error(f"Failed to open RTSP stream: {self.rtsp_url}")
                return False
            
            logger.info(f"Connected to RTSP stream: {self.rtsp_url}")
            return True
        except Exception as e:
            logger.error(f"RTSP connection error: {e}")
            return False
    
    @staticmethod
    def parse_color_string(color_str: str, default_color: Tuple[int, int, int] = (0, 255, 0)) -> Tuple[int, int, int]:
        """
        Parse RGB color string to BGR tuple for OpenCV
        
        Args:
            color_str: RGB color string in format "R,G,B"
            default_color: Default BGR color tuple if parsing fails
            
        Returns:
            Tuple[int, int, int]: BGR color tuple
        """
        try:
            color_parts = color_str.split(',')
            if len(color_parts) == 3:
                r, g, b = int(color_parts[0]), int(color_parts[1]), int(color_parts[2])
                return (b, g, r)  # Convert RGB to BGR
        except (ValueError, IndexError):
            pass
        return default_color
    
    @staticmethod
    def normalize_coordinates(x1: float, y1: float, x2: float, y2: float, 
                             frame_width: int, frame_height: int, 
                             use_percentage: bool = False) -> Tuple[int, int, int, int]:
        """
        Normalize and validate bounding box coordinates
        
        Args:
            x1, y1, x2, y2: Box coordinates
            frame_width, frame_height: Frame dimensions
            use_percentage: If True, coordinates are 0-1, else absolute pixels
            
        Returns:
            Tuple[int, int, int, int]: Normalized coordinates (x1, y1, x2, y2)
        """
        if use_percentage:
            x1 = int(x1 * frame_width)
            y1 = int(y1 * frame_height)
            x2 = int(x2 * frame_width)
            y2 = int(y2 * frame_height)
        else:
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        
        # Clamp to frame bounds
        x1 = max(0, min(x1, frame_width - 1))
        y1 = max(0, min(y1, frame_height - 1))
        x2 = max(0, min(x2, frame_width - 1))
        y2 = max(0, min(y2, frame_height - 1))
        
        return x1, y1, x2, y2
    
    def generate_random_boxes(self, frame_width: int, frame_height: int) -> List[Dict]:
        """Generate random bounding boxes with random positions, sizes, and colors"""
        boxes = []
        
        for i in range(self.random_box_count):
            # Random size between min and max
            box_size = random.uniform(self.random_box_min_size, self.random_box_max_size)
            
            # Random position ensuring box fits in frame
            max_x = int(frame_width * (1 - box_size))
            max_y = int(frame_height * (1 - box_size))
            
            if max_x <= 0 or max_y <= 0:
                continue
            
            x1 = random.randint(0, max_x)
            y1 = random.randint(0, max_y)
            x2 = int(x1 + frame_width * box_size)
            y2 = int(y1 + frame_height * box_size)
            
            boxes.append({
                'x1': x1,
                'y1': y1,
                'x2': x2,
                'y2': y2,
                'color': random.choice(RANDOM_BOX_COLORS),
                'thickness': random.randint(2, 4),
                'label': f"Box {i+1}",
                'font_scale': random.uniform(0.5, 0.8),
                'label_color': DEFAULT_COLOR_WHITE,
                'use_percentage': False
            })
        
        return boxes
    
    def _draw_single_box(self, frame, box: Dict, frame_width: int, frame_height: int) -> None:
        """Draw a single bounding box with label on frame (modifies frame in-place)"""
        try:
            # Normalize coordinates
            x1, y1, x2, y2 = self.normalize_coordinates(
                box.get('x1', 0),
                box.get('y1', 0),
                box.get('x2', 0),
                box.get('y2', 0),
                frame_width,
                frame_height,
                box.get('use_percentage', False)
            )
            
            # Validate coordinates
            if x1 >= x2 or y1 >= y2:
                logger.warning(f"Invalid box coordinates: ({x1}, {y1}) to ({x2}, {y2}), skipping")
                return
            
            # Parse colors
            box_color = self.parse_color_string(
                box.get('color', DEFAULT_COLOR_GREEN),
                default_color=(0, 255, 0)
            )
            
            thickness = int(box.get('thickness', DEFAULT_BOX_THICKNESS))
            
            # Draw rectangle (modifies frame in-place)
            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, thickness)
            
            # Draw label if provided
            label = box.get('label', '')
            if label:
                self._draw_box_label(frame, label, x1, y1, box, box_color, thickness)
        except Exception as e:
            logger.warning(f"Error in _draw_single_box: {e}", exc_info=True)
    
    def _draw_box_label(self, frame, label: str, x1: int, y1: int, 
                       box: Dict, box_color: Tuple[int, int, int], thickness: int) -> None:
        """Draw label text above or inside bounding box"""
        # Calculate text position
        label_y = y1 + DEFAULT_LABEL_OFFSET_ABOVE if y1 > DEFAULT_LABEL_Y_THRESHOLD else y1 + DEFAULT_LABEL_OFFSET_BELOW
        
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = box.get('font_scale', DEFAULT_FONT_SCALE)
        
        # Parse label color
        label_color_str = box.get('label_color', '')
        if label_color_str:
            label_color = self.parse_color_string(label_color_str, default_color=box_color)
        else:
            label_color = box_color
        
        # Get text size for background
        (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, thickness)
        
        # Draw background rectangle for text
        cv2.rectangle(
            frame,
            (x1, label_y - text_height - 5),
            (x1 + text_width, label_y + baseline),
            DEFAULT_COLOR_BLACK_BGR,
            -1
        )
        
        # Draw text
        cv2.putText(frame, label, (x1, label_y), font, font_scale, label_color, thickness)
    
    def draw_bounding_boxes(self, frame) -> None:
        """Draw custom bounding boxes on frame (static and/or random)"""
        try:
            frame_height, frame_width = frame.shape[:2]
            
            # Combine static and random boxes
            boxes_to_draw = list(self.bounding_boxes) if self.bounding_boxes else []
            
            # Generate random boxes if enabled
            if self.random_boxes:
                random_boxes = self.generate_random_boxes(frame_width, frame_height)
                boxes_to_draw.extend(random_boxes)
            
            if not boxes_to_draw:
                return
            
            # Draw each box
            for box in boxes_to_draw:
                try:
                    self._draw_single_box(frame, box, frame_width, frame_height)
                except Exception as e:
                    logger.warning(f"Error drawing box: {e}")
        except Exception as e:
            logger.error(f"Error drawing bounding boxes: {e}", exc_info=True)
    
    def process_frame(self, frame) -> Optional[bytes]:
        """
        Process frame dengan alur lengkap:
        1. Draw random bounding boxes (jika enabled)
        2. Encode frame ke format WebP
        3. Convert WebP numpy array ke binary bytes
        
        Returns:
            bytes: Binary WebP data siap dikirim ke ingest-server
        """
        try:
            # Step 1: Draw bounding boxes pada frame (random atau static)
            # draw_bounding_boxes() akan handle kedua kasus (static + random)
            if self.random_boxes or self.bounding_boxes:
                self.draw_bounding_boxes(frame)
            
            # Step 2: Encode frame ke format WebP
            # cv2.imencode mengembalikan (success: bool, encoded_image: numpy.ndarray)
            ret, buffer = cv2.imencode(
                ".webp",
                frame,
                [cv2.IMWRITE_WEBP_QUALITY, DEFAULT_WEBP_QUALITY]
            )
            
            if not ret:
                logger.warning("Failed to encode frame as WebP")
                return None
            
            # Step 3: Convert WebP numpy array ke binary bytes
            # buffer adalah numpy.ndarray, tobytes() mengkonversi ke binary bytes
            webp_binary = buffer.tobytes()
            
            return webp_binary
        except Exception as e:
            logger.error(f"Frame processing error: {e}", exc_info=True)
            return None
    
    def send_frame(self, frame_data: bytes) -> bool:
        """
        Kirim binary WebP data ke ingest-server via HTTP/2 POST
        
        Alur:
        1. frame_data adalah binary bytes dari WebP (hasil dari process_frame)
        2. httpx.Client dengan http2=True akan mengirim via HTTP/2
        3. Data dikirim sebagai raw binary content ke endpoint /ingest/:stream_id
        
        Args:
            frame_data: Binary WebP data (bytes) yang akan dikirim
            
        Returns:
            bool: True jika berhasil dikirim, False jika gagal
        """
        try:
            url = f"{self.broker_url}/ingest/{self.stream_id}"
            
            # Kirim binary WebP data ke ingest-server via HTTP/2
            # httpx akan mengirim bytes sebagai raw binary content
            # HTTP/2 akan digunakan otomatis jika server support
            response = self.client.post(
                url,
                content=frame_data,  # Binary WebP data (bytes)
                headers={"Content-Type": "image/webp"}  # MIME type untuk WebP
            )
            
            if response.status_code == HTTP_OK:
                # 200 OK: Frame berhasil diterima dan di-broadcast
                return True
            elif response.status_code == HTTP_ACCEPTED:
                # 202 Accepted: Frame diterima tapi tidak ada client yang terhubung
                return True
            else:
                logger.warning(f"Server returned status {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Frame send error: {e}", exc_info=True)
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
                logger.warning(f"RTSP connection failed, retrying in {DEFAULT_RECONNECT_DELAY} seconds...")
                time.sleep(DEFAULT_RECONNECT_DELAY)
                continue
            
            # Inner loop: reads frames from RTSP stream
            last_frame_time = 0
            while self.cap.isOpened():
                try:
                    current_time = time.time()
                    
                    # FPS regulation - ensure we maintain exactly target FPS
                    elapsed = current_time - last_frame_time
                    
                    # If we have a buffered frame and need to maintain 30 FPS, duplicate it
                    if elapsed >= self.frame_interval:
                        # Try to read new frame from RTSP
                        ret, frame = self.cap.read()
                        
                        if ret:
                            # New frame received, store original frame for duplication
                            # Note: We store BEFORE drawing bounding boxes, so duplicated frames
                            # will also have bounding boxes drawn (which is correct for 30 FPS)
                            self.last_frame = frame.copy()
                            self.last_frame_time = current_time
                        elif self.last_frame is not None:
                            # No new frame, but we have a buffered frame - duplicate it for 30 FPS
                            # Copy the buffered frame (will have bounding boxes drawn in process_frame)
                            frame = self.last_frame.copy()
                            self.frames_duplicated += 1
                        else:
                            # No frame available and no buffer, wait and retry
                            logger.warning("No frame available, reconnecting...")
                            break
                        
                        # Process frame: Draw Bounding Boxes → WebP → Binary
                        # draw_bounding_boxes() modifies frame in-place
                        # frame_data adalah binary bytes dari WebP yang sudah include bounding boxes
                        frame_data = self.process_frame(frame)
                        if frame_data:
                            # Kirim binary WebP data ke ingest-server via HTTP/2
                            # WebP sudah include bounding boxes yang di-draw pada frame
                            if self.send_frame(frame_data):
                                self.frames_sent += 1
                                last_frame_time = time.time()
                    else:
                        # Not time yet, sleep to maintain FPS
                        sleep_time = self.frame_interval - elapsed
                        time.sleep(sleep_time)
                        continue
                    
                    # FPS monitoring
                    if current_time - self.last_fps_check >= DEFAULT_FPS_CHECK_INTERVAL:
                        fps = self.frames_sent / DEFAULT_FPS_CHECK_INTERVAL
                        dup_pct = (self.frames_duplicated / max(self.frames_sent, 1)) * 100
                        logger.info(f"Streaming at {fps:.1f} FPS (duplicated: {self.frames_duplicated} frames, {dup_pct:.1f}%)")
                        self.frames_sent = 0
                        self.frames_duplicated = 0
                        self.last_fps_check = current_time
                
                except Exception as e:
                    logger.error(f"Error in frame loop: {e}")
                    break  # Break inner loop, triggers reconnection
            
            # Cleanup and reconnect
            if self.cap:
                self.cap.release()
                self.cap = None
            
            logger.info(f"Reconnecting in {DEFAULT_RECONNECT_DELAY} seconds...")
            time.sleep(DEFAULT_RECONNECT_DELAY)
    
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
    target_fps = int(os.getenv("TARGET_FPS", str(DEFAULT_FPS)))
    
    # Parse bounding boxes from environment variable (JSON format)
    bounding_boxes = None
    bounding_boxes_json = os.getenv("BOUNDING_BOXES", "")
    if bounding_boxes_json:
        try:
            bounding_boxes = json.loads(bounding_boxes_json)
            if not isinstance(bounding_boxes, list):
                logger.warning("BOUNDING_BOXES must be a JSON array, ignoring")
                bounding_boxes = None
            else:
                logger.info(f"Loaded {len(bounding_boxes)} bounding box(es)")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse BOUNDING_BOXES JSON: {e}, ignoring")
            bounding_boxes = None
    
    # Parse random bounding boxes configuration
    random_boxes = os.getenv("RANDOM_BOXES", "false").lower() == "true"
    random_box_count = int(os.getenv("RANDOM_BOX_COUNT", "3"))
    random_box_min_size = float(os.getenv("RANDOM_BOX_MIN_SIZE", "0.1"))
    random_box_max_size = float(os.getenv("RANDOM_BOX_MAX_SIZE", "0.3"))
    
    logger.info(f"Starting RTSP Producer")
    logger.info(f"  RTSP URL: {rtsp_url}")
    logger.info(f"  Broker URL: {broker_url} ({broker_protocol.upper()})")
    logger.info(f"  Stream ID: {stream_id}")
    logger.info(f"  Target FPS: {target_fps}")
    logger.info(f"  Processing Pipeline: Frame → Draw Bounding Boxes → WebP Encoding → Binary Conversion → Send to Ingest-Server")
    if bounding_boxes:
        logger.info(f"  Static Bounding Boxes: {len(bounding_boxes)} configured")
    if random_boxes:
        logger.info(f"  Random Bounding Boxes: ENABLED ({random_box_count} boxes per frame, size: {random_box_min_size:.1%}-{random_box_max_size:.1%})")
    else:
        logger.info(f"  Random Bounding Boxes: DISABLED (set RANDOM_BOXES=true to enable)")
    if use_https:
        logger.info(f"  SSL Verification: {os.getenv('VERIFY_SSL', 'false')}")
    
    producer = RTSPProducer(
        rtsp_url=rtsp_url,
        broker_url=broker_url,
        stream_id=stream_id,
        target_fps=target_fps,
        bounding_boxes=bounding_boxes,
        random_boxes=random_boxes,
        random_box_count=random_box_count,
        random_box_min_size=random_box_min_size,
        random_box_max_size=random_box_max_size
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

