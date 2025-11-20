use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Path as AxumPath, State,
    },
    response::{Json, Response},
    routing::get,
    Router,
};
use serde_json::json;
use bytes::Bytes;
use futures_util::{SinkExt, StreamExt};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};
use tokio::sync::broadcast;
use tower::ServiceBuilder;
use tower_http::cors::CorsLayer;
use tracing::{error, info, warn};

// Tipe data biner kita (smart pointer, copy-on-write)
type Frame = Bytes;

// Peta (map) dari Stream ID (String) ke Pengirim (Sender) siarannya
type StreamMap = Arc<Mutex<HashMap<String, broadcast::Sender<Frame>>>>;

// State aplikasi kita
#[derive(Clone)]
struct AppState {
    streams: StreamMap,
}

/// Handler untuk GET / atau /health
/// Health check endpoint untuk monitoring service status
async fn health_handler(State(state): State<AppState>) -> Json<serde_json::Value> {
    let streams = state.streams.lock().unwrap();
    let active_streams = streams.len();
    let total_channels = streams.values().map(|tx| tx.receiver_count()).sum::<usize>();
    
    Json(json!({
        "status": "running",
        "service": "binary-stream-broker",
        "version": env!("CARGO_PKG_VERSION"),
        "active_streams": active_streams,
        "total_connections": total_channels,
        "endpoints": {
            "ingest": "WS /ws/ingest/:stream_id",
            "websocket": "WS /ws/:stream_id",
            "health": "GET /health"
        }
    }))
}

/// Handler untuk GET /ws/ingest/:stream_id
/// Menerima frame biner dari producer via WebSocket dan menyiarkannya ke channel
async fn websocket_ingest_handler(
    ws: WebSocketUpgrade,
    AxumPath(stream_id): AxumPath<String>,
    State(state): State<AppState>,
) -> Response {
    info!("Producer WebSocket connection request for stream: {}", stream_id);
    ws.on_upgrade(move |socket| websocket_ingest_connection(socket, stream_id, state))
}

/// Handle WebSocket connection dari producer
async fn websocket_ingest_connection(socket: WebSocket, stream_id: String, state: AppState) {
    info!("Producer WebSocket connected for stream: {}", stream_id);
    
    // Dapatkan atau buat channel untuk stream ini
    let tx = {
        let mut map = state.streams.lock().unwrap();
        map.entry(stream_id.clone())
            .or_insert_with(|| {
                info!("Creating new broadcast channel for stream: {}", stream_id);
                broadcast::channel(128).0
            })
            .clone()
    };
    
    // Split socket into sender and receiver
    let (mut sender, mut receiver) = socket.split();
    
    // Loop untuk menerima frame dari producer
    // Optimized: minimal logging di hot path untuk performa maksimal
    let mut frame_count = 0u64;
    loop {
        match receiver.next().await {
            Some(Ok(Message::Binary(frame_data))) => {
                // Kirim (siarkan) frame ke semua subscriber
                // Bytes::from() adalah zero-copy untuk Vec<u8>
                let frame = Bytes::from(frame_data);
                match tx.send(frame) {
                    Ok(subscriber_count) => {
                        // Log hanya setiap 150 frames (~5 detik pada 30 FPS) untuk mengurangi overhead
                        frame_count += 1;
                        if subscriber_count == 0 && frame_count % 150 == 0 {
                            warn!("No WebSocket clients connected for stream: {} (frame #{})", stream_id, frame_count);
                        }
                        // Skip info log untuk setiap frame - terlalu verbose untuk high FPS
                    }
                    Err(broadcast::error::SendError(_)) => {
                        // Log hanya jika channel closed (jarang terjadi)
                        warn!("Channel closed for stream: {} (no active receivers)", stream_id);
                    }
                }
            }
            Some(Ok(Message::Close(_))) => {
                info!("Producer closed connection for stream: {}", stream_id);
                break;
            }
            Some(Ok(Message::Ping(data))) => {
                // Respond to ping with pong
                if let Err(e) = sender.send(Message::Pong(data)).await {
                    error!("Failed to send pong: {}", e);
                    break;
                }
            }
            Some(Ok(_)) => {
                // Ignore other messages (text, pong)
            }
            Some(Err(e)) => {
                error!("WebSocket error from producer: {}", e);
                break;
            }
            None => {
                info!("Producer WebSocket connection closed for stream: {}", stream_id);
                break;
            }
        }
    }
    
    info!("Producer WebSocket disconnected for stream: {}", stream_id);
}

/// Handler untuk GET /ws/:stream_id
/// Membuat atau subscribe ke channel dan stream frames via WebSocket (untuk clients)
async fn websocket_handler(
    ws: WebSocketUpgrade,
    AxumPath(stream_id): AxumPath<String>,
    State(state): State<AppState>,
) -> Response {
    info!("Client WebSocket connection request for stream: {}", stream_id);
    ws.on_upgrade(move |socket| websocket_connection(socket, stream_id, state))
}

/// Handle WebSocket connection
async fn websocket_connection(socket: WebSocket, stream_id: String, state: AppState) {
    // Dapatkan/Buat Channel: Kunci (lock) HashMap dan dapatkan receiver (penerima)
    let mut rx = {
        let mut map = state.streams.lock().unwrap();
        // or_insert_with: Buat channel baru jika stream_id ini belum ada
        let sender = map
            .entry(stream_id.clone())
            .or_insert_with(|| {
                info!("Creating new broadcast channel for stream: {}", stream_id);
                // Channel size 128 cukup untuk buffering tanpa boros memory
                broadcast::channel(128).0
            })
            .clone();
        sender.subscribe()
    };

    info!("WebSocket client connected for stream: {}", stream_id);

    // Split socket into sender and receiver
    let (mut sender, mut receiver) = socket.split();

    // Loop Siaran: menggunakan tokio::select! untuk menangani multiple events
    // Optimized: minimal logging di hot path
    loop {
        tokio::select! {
            // Terima frame baru dari broadcast
            result = rx.recv() => {
                match result {
                    Ok(frame) => {
                        // Kirim frame ke client sebagai binary message
                        // frame.to_vec() - perlu copy karena Bytes mungkin shared
                        // Ini trade-off: copy kecil untuk memastikan thread safety
                        if let Err(e) = sender.send(Message::Binary(frame.to_vec())).await {
                            error!("Failed to send frame to client: {}", e);
                            break;
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(skipped)) => {
                        // Backpressure! Klien ini lambat
                        // Log hanya jika skip banyak frame (>= 10) untuk mengurangi spam
                        if skipped >= 10 {
                            warn!("Client lagged, skipped {} frames for stream: {}", skipped, stream_id);
                        }
                        // Continue, jangan putus koneksi
                        continue;
                    }
                    Err(broadcast::error::RecvError::Closed) => {
                        warn!("Broadcast channel closed for stream: {}", stream_id);
                        break;
                    }
                }
            }
            // Tangani pesan dari klien
            msg = receiver.next() => {
                match msg {
                    Some(Ok(Message::Close(_))) => {
                        info!("Client closed connection for stream: {}", stream_id);
                        break;
                    }
                    Some(Ok(Message::Ping(data))) => {
                        // Respond to ping with pong
                        if let Err(e) = sender.send(Message::Pong(data)).await {
                            error!("Failed to send pong: {}", e);
                            break;
                        }
                    }
                    Some(Ok(_)) => {
                        // Ignore other messages
                    }
                    Some(Err(e)) => {
                        error!("WebSocket error: {}", e);
                        break;
                    }
                    None => {
                        info!("WebSocket connection closed for stream: {}", stream_id);
                        break;
                    }
                }
            }
        }
    }

    info!("WebSocket client disconnected for stream: {}", stream_id);
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Load environment variables from .env file
    // dotenvy::dotenv() searches for .env in current directory and parent directories
    // Note: Load .env before initializing tracing so we can use env vars for logging config
    let env_loaded = match dotenvy::dotenv() {
        Ok(path) => {
            eprintln!("Loaded environment variables from: {:?}", path);
            true
        }
        Err(dotenvy::Error::Io(io_err)) if io_err.kind() == std::io::ErrorKind::NotFound => {
            // .env file not found, use environment variables or defaults
            eprintln!("No .env file found, using environment variables or defaults");
            false
        }
        Err(e) => {
            eprintln!("Failed to load .env file: {}, using environment variables or defaults", e);
            false
        }
    };

    // Initialize tracing (after loading .env so RUST_LOG can be set from .env)
    tracing_subscriber::fmt()
        .with_env_filter("ingest_server=info,tower_http=debug")
        .init();
    
    if env_loaded {
        info!("Environment variables loaded from .env file");
    }

    // Read configuration from environment variables
    let bind_address = std::env::var("BIND_ADDRESS").unwrap_or_else(|_| "127.0.0.1".to_string());
    let port = std::env::var("PORT")
        .unwrap_or_else(|_| "3091".to_string())  // Default to 3091 (internal, behind Caddy)
        .parse::<u16>()
        .map_err(|e| format!("Invalid PORT value: {}", e))?;
    
    let bind_addr = format!("{}:{}", bind_address, port);

    // Buat state aplikasi
    let state = AppState {
        streams: Arc::new(Mutex::new(HashMap::new())),
    };

    // Buat Router yang me-routing /ws/ingest/:stream_id, /ws/:stream_id, dan /health
    let app = Router::new()
        .route("/", get(health_handler))
        .route("/health", get(health_handler))
        .route("/ws/ingest/:stream_id", get(websocket_ingest_handler))
        .route("/ws/:stream_id", get(websocket_handler))
        .layer(
            ServiceBuilder::new()
                .layer(CorsLayer::permissive())
        )
        .with_state(state);

    // Note: TLS/HTTPS support requires additional setup
    // For production, consider using a reverse proxy (nginx/caddy) for TLS termination
    let listener = tokio::net::TcpListener::bind(&bind_addr).await?;
    info!("Axum ingest server running on http://{}", bind_addr);
    info!("  GET  /                        - Health check endpoint");
    info!("  GET  /health                  - Health check endpoint");
    info!("  WS   /ws/ingest/:stream_id    - WebSocket ingest endpoint for producers");
    info!("  WS   /ws/:stream_id           - WebSocket endpoint for clients");
    info!("  Note: For HTTPS/WSS, use a reverse proxy (nginx/caddy) in front of this server");

    axum::serve(listener, app).await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_app_state_creation() {
        let state = AppState {
            streams: Arc::new(Mutex::new(HashMap::new())),
        };
        assert!(state.streams.lock().unwrap().is_empty());
    }
}
