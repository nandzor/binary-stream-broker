use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Path as AxumPath, State,
    },
    http::StatusCode,
    response::{Json, Response},
    routing::{get, post},
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

/// Handler untuk POST /ingest/:stream_id
/// Menerima frame biner dari producer dan menyiarkannya ke channel
async fn http_ingest_handler(
    AxumPath(stream_id): AxumPath<String>,
    State(state): State<AppState>,
    body: Bytes,
) -> StatusCode {
    // Kunci (lock) HashMap
    let map = state.streams.lock().unwrap();
    
    // Cari channel yang ada
    if let Some(tx) = map.get(&stream_id) {
        // Kirim (siarkan) frame ke semua subscriber
        match tx.send(body) {
            Ok(subscriber_count) => {
                if subscriber_count == 0 {
                    warn!("No WebSocket clients connected for stream: {}", stream_id);
                } else {
                    info!("Broadcasted frame to {} clients for stream: {}", subscriber_count, stream_id);
                }
                StatusCode::OK
            }
            Err(broadcast::error::SendError(_)) => {
                // Channel closed - no receivers, but channel still exists
                // This is normal when all WebSocket clients disconnect
                // Return 202 Accepted instead of 500
                warn!("Channel closed for stream: {} (no active receivers)", stream_id);
                StatusCode::ACCEPTED
            }
        }
    } else {
        // Channel belum ada (belum ada WebSocket client yang connect)
        // Kita tidak membuat channel di sini sesuai spesifikasi
        warn!("No channel exists for stream: {} (waiting for WebSocket connection)", stream_id);
        StatusCode::ACCEPTED // 202 - Accepted but not processed yet
    }
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
            "ingest": "POST /ingest/:stream_id",
            "websocket": "GET /ws/:stream_id",
            "health": "GET /health"
        }
    }))
}

/// Handler untuk GET /ws/:stream_id
/// Membuat atau subscribe ke channel dan stream frames via WebSocket
async fn websocket_handler(
    ws: WebSocketUpgrade,
    AxumPath(stream_id): AxumPath<String>,
    State(state): State<AppState>,
) -> Response {
    info!("WebSocket connection request for stream: {}", stream_id);
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
                broadcast::channel(128).0
            })
            .clone();
        sender.subscribe()
    };

    info!("WebSocket client connected for stream: {}", stream_id);

    // Split socket into sender and receiver
    let (mut sender, mut receiver) = socket.split();

    // Loop Siaran: menggunakan tokio::select! untuk menangani multiple events
    loop {
        tokio::select! {
            // Terima frame baru dari broadcast
            result = rx.recv() => {
                match result {
                    Ok(frame) => {
                        // Kirim frame ke client sebagai binary message
                        if let Err(e) = sender.send(Message::Binary(frame.to_vec())).await {
                            error!("Failed to send frame to client: {}", e);
                            break;
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(skipped)) => {
                        // Backpressure! Klien ini lambat
                        warn!("Client lagged, skipped {} frames for stream: {}", skipped, stream_id);
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

    // Buat Router yang me-routing /ingest/:stream_id, /ws/:stream_id, dan /health
    let app = Router::new()
        .route("/", get(health_handler))
        .route("/health", get(health_handler))
        .route("/ingest/:stream_id", post(http_ingest_handler))
        .route("/ws/:stream_id", get(websocket_handler))
        .layer(
            ServiceBuilder::new()
                .layer(CorsLayer::permissive())
        )
        .with_state(state);

    // Note: TLS/HTTPS support requires additional setup
    // For production, consider using a reverse proxy (nginx/caddy) for TLS termination
    // This allows HTTP/2 with minimal overhead
    let listener = tokio::net::TcpListener::bind(&bind_addr).await?;
    info!("Axum ingest server running on http://{}", bind_addr);
    info!("  GET  /                  - Health check endpoint");
    info!("  GET  /health            - Health check endpoint");
    info!("  POST /ingest/:stream_id - Ingest endpoint for producers");
    info!("  GET  /ws/:stream_id     - WebSocket endpoint for clients");
    info!("  Note: For HTTPS/HTTP/2, use a reverse proxy (nginx/caddy) in front of this server");

    axum::serve(listener, app).await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::Request;
    use tower::util::ServiceExt;

    #[tokio::test]
    async fn test_app_state_creation() {
        let state = AppState {
            streams: Arc::new(Mutex::new(HashMap::new())),
        };
        assert!(state.streams.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn test_ingest_handler_no_channel() {
        let state = AppState {
            streams: Arc::new(Mutex::new(HashMap::new())),
        };

        let app = Router::new()
            .route("/ingest/:stream_id", post(http_ingest_handler))
            .with_state(state);

        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/ingest/test_stream")
                    .header("content-type", "image/webp")
                    .body(Body::from("test frame data"))
                    .unwrap(),
            )
            .await
            .unwrap();

        // Should return 202 ACCEPTED when no channel exists
        assert_eq!(response.status(), StatusCode::ACCEPTED);
    }

    #[tokio::test]
    async fn test_ingest_handler_with_channel() {
        let state = AppState {
            streams: Arc::new(Mutex::new(HashMap::new())),
        };

        // Create a channel for the stream
        let (tx, _rx) = broadcast::channel::<Frame>(128);
        state.streams.lock().unwrap().insert("test_stream".to_string(), tx);

        let app = Router::new()
            .route("/ingest/:stream_id", post(http_ingest_handler))
            .with_state(state);

        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/ingest/test_stream")
                    .header("content-type", "image/webp")
                    .body(Body::from("test frame data"))
                    .unwrap(),
            )
            .await
            .unwrap();

        // Should return 200 OK when channel exists (even with no subscribers)
        assert_eq!(response.status(), StatusCode::OK);
    }
}
