#!/usr/bin/env python3
"""
Simple test script for RTSPProducer
Tests basic functionality without requiring actual RTSP stream
"""

import sys
import os
import numpy as np
import cv2
from main import RTSPProducer

def test_producer_initialization():
    """Test that producer can be initialized"""
    print("Testing producer initialization...")
    producer = RTSPProducer(
        rtsp_url="rtsp://test:554/stream",
        broker_url="http://localhost:3090",
        stream_id="test_stream",
        target_fps=30
    )
    
    assert producer.rtsp_url == "rtsp://test:554/stream"
    assert producer.broker_url == "http://localhost:3090"
    assert producer.stream_id == "test_stream"
    assert producer.target_fps == 30
    assert producer.frame_interval == 1.0 / 30
    print("✓ Producer initialization: PASSED")
    return producer

def test_http_client_initialization(producer):
    """Test HTTP/2 client initialization"""
    print("Testing HTTP/2 client initialization...")
    result = producer.initialize_client()
    assert result == True
    assert producer.client is not None
    print("✓ HTTP/2 client initialization: PASSED")
    return producer

def test_frame_processing(producer):
    """Test frame processing (WebP encoding)"""
    print("Testing frame processing...")
    
    # Create a dummy frame (640x480 RGB)
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    dummy_frame[:, :] = [128, 128, 128]  # Gray frame
    
    # Process frame
    frame_data = producer.process_frame(dummy_frame)
    
    assert frame_data is not None
    assert isinstance(frame_data, bytes)
    assert len(frame_data) > 0
    
    # Verify it's valid WebP (starts with RIFF)
    assert frame_data[:4] == b'RIFF'
    print("✓ Frame processing: PASSED")
    return True

def test_cleanup(producer):
    """Test cleanup"""
    print("Testing cleanup...")
    producer.cleanup()
    assert producer.client is None or producer.client.is_closed
    print("✓ Cleanup: PASSED")

def main():
    """Run all tests"""
    print("=" * 50)
    print("RTSP Producer Test Suite")
    print("=" * 50)
    print()
    
    try:
        # Test 1: Initialization
        producer = test_producer_initialization()
        print()
        
        # Test 2: HTTP Client
        producer = test_http_client_initialization(producer)
        print()
        
        # Test 3: Frame Processing
        test_frame_processing(producer)
        print()
        
        # Test 4: Cleanup
        test_cleanup(producer)
        print()
        
        print("=" * 50)
        print("All tests PASSED! ✓")
        print("=" * 50)
        return 0
        
    except AssertionError as e:
        print(f"\n✗ Test FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())

