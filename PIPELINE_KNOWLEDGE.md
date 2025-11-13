# Arsitektur Teknis Lengkap: Pipeline Stream Video RTSP-ke-Web

Dokumen ini merinci arsitektur teknis end-to-end untuk membaca stream video RTSP, mentransformasikannya menjadi stream biner, dan menyiarkannya (broadcast) ke ribuan klien web real-time menggunakan Python, Rust (Axum), dan WebSocket.

## 1. Tinjauan Arsitektur Umum

Arsitektur ini adalah implementasi dari pola Publish/Subscribe (Pub/Sub) yang sangat ter-decoupling. Sistem ini dibagi menjadi tiga komponen logis yang berbeda yang berinteraksi melalui API biner yang terdefinisi dengan baik.

- **Produsen (Python)**: Sebuah adapter yang membaca stream RTSP, melakukan transcoding video 30fps menjadi frame biner (WebP), dan "mempublikasikan" frame tersebut ke Broker.

- **Broker (Axum/Rust)**: Jantung sistem. Sebuah service "pipa bodoh" (dumb pipe) yang sangat berperforma tinggi yang bertindak sebagai broker Pub/Sub in-memory. Ia menerima biner dari Produsen dan menyiarkannya ke semua Pelanggan.

- **Konsumen (Browser/JS)**: "Berlangganan" stream biner dari Broker melalui WebSocket dan merendernya ke `<canvas>`.

## Diagram Alur Arsitektur

```text
+---------------------------------------------------+
|      Zona Pribadi (Misal: Jaringan Internal)      |
+---------------------------------------------------+
|                                                   |
|          [📹 Kamera (Stream RTSP H.264)]          |
|                         |                         |
|                         v                         |
|          [🐍 Produsen (Python/OpenCV)]            |
|                  |                                |
|   (Proses: "Transcode (H.264 -> WebP)")           |
|                  |                                |
|                  v "POST /ingest/stream1 (HTTP/2)"|
|                                                   |
+--------------------|--------------------------------+
                     |
                     v
+--------------------|--------------------------------+
|       Zona Publik (Misal: Server / DMZ)            |
+--------------------|--------------------------------+
|                    v                                |
|           [🚀 Broker (Axum/Rust)]                   |
|                    |                                |
|                    v "HTTP/2 Ingest Endpoint"       |
|                                                     |
|          [In-Memory Broadcast Channel]              |
|                    |                                |
|                    v "Fan-Out (Satu-ke-Banyak)"     |
|                                                     |
|           [WebSocket Egress Endpoint]               |
|                    |                                |
|       +------------+------------+                   |
|       |            |            |                   |
|       v            v            v                   |
|  [🖥️ Klien 1] [🖥️ Klien 2] [🖥️ Klien ...N]         |
|  (Stream WebP) (Stream WebP) (Stream WebP)          |
|                                                     |
+---------------------------------------------------+
```

Tentu, ini dia dalam format Markdown:

## 🌐 Arsitektur Streaming Video

Diagram ini menjelaskan arsitektur streaming video, yang dibagi menjadi dua zona utama:

### 1. Zona Pribadi (Jaringan Internal)

Ini adalah tempat di mana video berasal dan diproses sebelum dikirim keluar.

* **Kamera**: Proses dimulai dari sebuah kamera (📹) yang menghasilkan stream video mentah dalam format **RTSP H.264**.
* **Produsen (Python/OpenCV)**: Stream dari kamera ditangkap oleh sebuah aplikasi "Produsen" (🐍) yang dibuat dengan Python/OpenCV.
* **Transcoding**: Produsen ini langsung melakukan *transcode* (perubahan format) video dari H.264 menjadi **WebP**.
* **Pengiriman**: Setelah diubah, Produsen mengirimkan frame-frame WebP tersebut ke server publik menggunakan metode **POST** melalui **HTTP/2** ke endpoint `/ingest/stream1`.

---

### 2. Zona Publik (Server / DMZ)

Ini adalah server yang dapat diakses publik yang bertugas menerima dan mendistribusikan stream ke banyak penonton.

* **Broker (Axum/Rust)**: Server "Broker" (🚀) yang dibuat dengan Axum/Rust menerima kiriman data melalui **Endpoint Ingest HTTP/2**.
* **Broadcast Channel**: Data yang masuk segera disalurkan ke sebuah **In-Memory Broadcast Channel**.
* **Fan-Out**: Channel ini bertugas menduplikasi stream dan melakukan "Fan-Out" (Satu-ke-Banyak), mengirimkannya ke **Endpoint Egress WebSocket**.
* **Distribusi ke Klien**: Akhirnya, Endpoint WebSocket menyiarkan **Stream Biner (WebP)** tersebut ke semua klien (🖥️) yang sedang terhubung, seperti **Klien Web 1, Klien Web 2,** hingga **Klien Web ke-N**.

## 2. Filosofi Desain & Pilihan Teknis Kunci

Setiap pilihan teknologi dibuat untuk memaksimalkan performa, skalabilitas, dan kemudahan perawatan.

| Komponen | Pilihan Teknologi | Alasan (Kelebihan & Kekurangan) |
|----------|-------------------|----------------------------------|
| Runtime Broker | Rust (Axum) | **Kelebihan**: Performa setara C++, Keamanan Memori, dan yang terpenting: Bebas dari Garbage Collector (GC). Ini mengeliminasi "GC pauses" yang dapat menyebabkan stutter (patah-patah) pada stream 30fps.<br><br>**Kekurangan**: Kurva belajar lebih curam. |
| Pola Broker | In-Memory Pub/Sub | **Kelebihan**: Latensi terendah (nanodetik), sangat ringan.<br><br>**Kekurangan**: Tidak durable (data hilang jika server restart).<br><br>**Justifikasi**: Sempurna untuk streaming video real-time di mana frame yang hilang tidak sepenting latensi rendah. |
| "Kontrak" Biner | WebP | **Kelebihan**: Kualitas kompresi jauh lebih baik daripada JPEG (menghemat bandwidth), decoding sangat cepat di browser modern.<br><br>**Kekurangan**: Encoding (di Python) sedikit lebih lambat dari JPEG. |
| Transport Ingest | HTTP/2 (30x POST/detik) | **Kelebihan**: Multiplexing. Menggunakan 1 koneksi TCP untuk 30 request, menghilangkan overhead handshake TCP/TLS per frame.<br><br>**Kekurangan**: Overhead header per frame (minor, diatasi oleh kompresi HPACK). |
| Transport Egress | WebSocket | **Kelebihan**: Standar industri untuk komunikasi push dua arah dari server ke klien. Didukung secara universal. |
| Render Klien | `<canvas>` + createImageBitmap | **Kelebihan**: Decoding gambar di background thread, mencegah pemblokiran main thread (anti-patah-patah). Jauh lebih cepat daripada metode URL.createObjectURL. |

## 3. Rincian Komponen Teknis

### 3.1. Komponen 1: Produsen (Python "Transcoder")

**Tujuan**: Membaca 1 stream RTSP, menghasilkan 30 frame WebP per detik, mengirimkannya ke Broker.

**Tumpukan (Stack)**: `python`, `opencv-python`, `httpx`

**Pola Desain**: Adapter / Transcoder

**Alur Logika**:

1. **Inisialisasi**: Di luar loop utama, buat SATU instance `httpx.Client(http2=True)`. Ini adalah kunci performa HTTP/2.

2. **Koneksi (Loop Luar)**: Buat loop `while True` yang menangani koneksi ulang (reconnect).
   - Coba buat `cap = cv2.VideoCapture(RTSP_URL)`.
   - Jika gagal, `time.sleep(5)` dan `continue`.

3. **Membaca (Loop Dalam)**: Buat loop `while cap.isOpened()`.
   - `ret, frame = cap.read()`. Jika `not ret`, `break` (untuk memicu koneksi ulang).
   - **Transcoding**: `ret, buffer = cv2.imencode(".webp", frame, [cv2.IMWRITE_WEBP_QUALITY, 80])`.
   - **Mengirim**: `client.post(AXUM_URL, content=buffer.tobytes())`.
   - **Regulasi FPS**: Terapkan logika `time.sleep()` untuk memastikan loop ini berjalan tidak lebih dari 30 kali per detik. Ini mencegah pemborosan CPU dan traffic jaringan.

**Penanganan Error**:

- Produsen harus tangguh terhadap kegagalan jaringan dan crash pada stream RTSP.
- Penggunaan dua loop (luar untuk koneksi, dalam untuk membaca) adalah pola yang tangguh.

### 3.2. Komponen 2: Broker (Axum/Rust "Broker")

**Tujuan**: Menerima frame biner dari satu Produsen dan menyiarkannya (fan-out) ke banyak Konsumen.

**Tumpukan (Stack)**: `axum`, `tokio`, `bytes`

**Pola Desain**: Broker Pub/Sub In-Memory (Multi-Channel)

**Struktur Data Inti (Kunci Skalabilitas)**:

Kita akan menggunakan HashMap untuk mengelola channel siaran secara dinamis. Ini memungkinkan service Anda menangani stream1, stream2, dst., hanya dengan satu instance Axum.

```rust
// Tipe data biner kita (smart pointer, copy-on-write)
type Frame = bytes::Bytes;

// Peta (map) dari Stream ID (String) ke Pengirim (Sender) siarannya
type StreamMap = Arc<Mutex<HashMap<String, broadcast::Sender<Frame>>>>;

// State aplikasi kita
#[derive(Clone)]
struct AppState {
    streams: StreamMap,
}
```

**Alur Logika**:

1. **Inisialisasi main**:
   - Buat `let state = AppState { streams: Arc::new(Mutex::new(HashMap::new())) };`.
   - Buat Router yang me-routing `/ingest/:stream_id` dan `/ws/:stream_id`.
   - Jalankan server dengan `.with_state(state)`.

2. **Handler Ingest (POST /ingest/:stream_id)**:
   ```rust
   async fn http_ingest_handler(Path(stream_id): Path<String>, State(state): State<AppState>, body: Bytes)
   ```
   - Kunci handler ini `body: Bytes`. Axum akan membaca seluruh body request (satu frame) ke dalam `Bytes` sebelum memanggil handler ini.
   - **Logika**:
     - Kunci (lock) HashMap: `let map = state.streams.lock().unwrap();`.
     - Cari channel yang ada: `if let Some(tx) = map.get(&stream_id)`.
     - Kirim (siarkan): `let _ = tx.send(body);`.
   - **Catatan**: Kita sengaja tidak membuat channel di sini. Kita berasumsi channel dibuat oleh koneksi WebSocket pertama.

3. **Handler Egress (GET /ws/:stream_id)**:
   ```rust
   async fn websocket_handler(ws: WebSocketUpgrade, Path(stream_id): Path<String>, State(state): State<AppState>)
   ```
   - **Logika**:
     - **Dapatkan/Buat Channel**: Kunci (lock) HashMap dan dapatkan receiver (penerima).
       ```rust
       let mut rx = {
           let mut map = state.streams.lock().unwrap();
           // or_insert_with: Buat channel baru jika stream_id ini belum ada
           map.entry(stream_id)
              .or_insert_with(|| broadcast::channel(128).0)
              .subscribe()
       };
       ```
     - **Upgrade Koneksi**: `ws.on_upgrade(move |socket| async move { ... })`.
     - **Loop Siaran**: Di dalam `async move`, buat `loop { tokio::select! { ... } }`.
     - `tokio::select!` harus menangani 3 kasus:
       - `Ok(frame) = rx.recv()`: Terima frame baru dari broadcast, kirim ke `socket.send(Message::Binary(...))`.
       - `Some(Ok(msg)) = socket.recv()`: Tangani pesan dari klien (misal, `Message::Close`).
       - `Err(RecvError::Lagged(_))`: Backpressure! Klien ini lambat. Catat (log) peringatan, tapi `continue` (jangan putus koneksi).

### 3.3. Komponen 3: Konsumen (Browser/JS "Renderer")

**Tujuan**: Menerima frame biner WebP 30fps dan merendernya ke `<canvas>`.

**Tumpukan (Stack)**: WebSocket API, `<canvas>`, Blob, createImageBitmap

**Pola Desain**: Renderer Canvas Real-time

**Alur Logika**:

1. **Inisialisasi**:
   - Dapatkan stream ID (misal, dari URL).
   - `const WS_URL = "ws://server.anda/ws/" + stream_id;`.
   - Dapatkan referensi ke `<canvas>` dan `ctx = canvas.getContext('2d')`.

2. **Koneksi (Fungsi connect())**:
   - `ws = new WebSocket(WS_URL)`.
   - **Penting**: `ws.binaryType = 'arraybuffer';`. Ini jauh lebih efisien daripada blob default.
   - Tentukan handler `onopen`, `onclose`, `onerror`, `onmessage`.
   - `onclose`: Harus secara otomatis memanggil `setTimeout(connect, 3000)` untuk koneksi ulang (reconnect) yang tangguh.

3. **Menerima Frame (ws.onmessage)**:
   - Ini adalah hot path (jalur kritis) performa.
   - `async (event) => { ... }`.
   - `event.data` adalah `ArrayBuffer`.
   - **Kontrak Biner**: Buat Blob dengan tipe MIME yang benar: `const blob = new Blob([event.data], { type: 'image/webp' });`.
   - **Penting (Performa)**: `const bitmap = await createImageBitmap(blob);`. Fungsi ini men-decode gambar di background thread, mencegah main thread (UI) menjadi patah-patah.
   - **Render**: `ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);`.
   - **Manajemen Memori**: `bitmap.close();`.
