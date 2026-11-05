# HerdSense - Group Travel Tracker

Ponsel mengirim data GPS dan akselerometer lewat MQTT. Detector menjalankan aturan keselamatan
dan model Gradient Boosting yang dilatih dari trip berlabel. Dashboard web menampilkan status
aturan, prediksi AI beserta probabilitas, dan peringatan secara langsung.

**Presented by Group 8 - IoT Kelas A Informatika UNDIP**

## Anggota Kelompok

| Nama | NIM |
|---|---|
| Fathin Arva A. | 24060125130056 |
| Nabil Al Gazaska | 24060125130096 |
| Adelia Rafalina | 24060125140236 |
| Eugene N. Serafhina | 24060125140242 |

```text
ponsel (Termux)  <--MQTT-->  broker  <--MQTT-->  detector.py
                               |
                               +--MQTT over WebSocket--> dashboard/index.html
```

| Bagian | File |
|---|---|
| Edge: baca sensor, proses, publish telemetri, terima peringatan | `phone.py` |
| Aturan fusi jarak dan gerakan, murni dan teruji | `rules.py`, `tests/` |
| Detector, pencatatan fitur, dan peringatan | `detector.py`, `data_logger.py`, `features.py` |
| Simulator data berlabel ground-truth dan fitur bersama | `generate_dataset.py`, `features.py`, `ml_labels.py` |
| Training, evaluasi held-out, dan ekspor model Gradient Boosting | `train_model.py`, `ai_model.py` |
| Dashboard | `dashboard/index.html` |
| Pengecekan kesiapan ponsel dan MQTT | `check_phone.py` |
| Konfigurasi bersama dan helper MQTT | `common.py` |

## Infrastruktur

Semua komponen berkomunikasi lewat broker MQTT; komponen tidak membuat koneksi langsung satu
sama lain. Mereka menggunakan alamat broker dan `GROUP_ID` yang sama.

| Komponen | Peran | Berjalan di |
|---|---|---|
| Broker MQTT | Meneruskan pesan publish/subscribe; tidak mengambil keputusan. Default: `broker.hivemq.com` | Server internet |
| `phone.py` (edge) | Membaca GPS dan akselerometer setiap `SEND_INTERVAL_S`, mengirim telemetri, menerima peringatan | Setiap ponsel Android dengan Termux |
| `detector.py` | Mengumpulkan telemetri anggota, menjalankan aturan dan inferensi AI, menerbitkan status dan peringatan | Satu perangkat dengan Python dan internet |
| `dashboard/index.html` | Menampilkan status dan peringatan yang diterima; tidak menghitung status | Browser melalui Live Server/file statis dan MQTT WebSocket |

Detector sebaiknya dijalankan **tepat satu kali per grup**. Ponsel simulator mengirim format
JSON yang sama seperti ponsel fisik, jadi bisa dipakai untuk demo tanpa sensor sungguhan.

### `GROUP_ID` dan privasi

`GROUP_ID` menjadi bagian setiap topik MQTT (`trip/<GROUP_ID>/...`) dan berfungsi sebagai
identifier grup, bukan autentikasi. Siapa pun yang mengetahui nilai ini dapat mencoba membaca
topik grup pada broker publik. Jangan bagikan `GROUP_ID` di laporan publik, screenshot, atau chat
publik. Gunakan nilai panjang dan acak, dan untuk penggunaan nyata pilih broker dengan akun,
ACL, serta TLS. Koordinat lokasi adalah data sensitif.

### Topik MQTT

```text
trip/<GROUP_ID>/edge/<member>/telemetry   ponsel -> broker    {device_id, sequence, lat, lon, accuracy_m, motion_rms, sent_at_ms}
trip/<GROUP_ID>/alerts                    detector -> ponsel  {level, member, message, ts}
trip/<GROUP_ID>/status                    detector -> dashboard (retained)
```

| Perangkat | Publish | Subscribe |
|---|---|---|
| Ponsel | `.../edge/<member>/telemetry` | `.../alerts` |
| Detector | `.../status` (retained), `.../alerts` | `.../edge/+/telemetry` |
| Dashboard | - | `.../status`, `.../alerts` |

Wildcard `+` berarti satu level topik; detector menerima telemetri semua anggota dengan satu
subscription. Anggota muncul otomatis setelah mengirim telemetri pertama. Setiap anggota perlu
`MEMBER_NAME` yang unik.

## Logika Detector

Detector mengevaluasi data setiap sekitar **4 detik**. Interval kirim ponsel secara default
**3 detik** (`SEND_INTERVAL_S`).

1. **Terima dan validasi:** detector memeriksa format koordinat, akurasi, gerakan, dan sequence,
   membuang pesan rusak atau sequence duplikat, lalu mencatat waktu penerimaan lokal agar tidak
   bergantung pada perbedaan jam ponsel.
2. **Hitung status:** `rules.evaluate()` menggabungkan jarak dan gerakan, memeriksa sinyal kedaluwarsa,
   serta menyaring noise jarak.
3. **Bangun fitur dan prediksi:** gunakan jendela sensor 30 detik yang sama untuk CSV dan model;
   model Gradient Boosting mengeluarkan satu dari empat label beserta probabilitas kelas.
4. **Stabilkan dan publikasikan:** status operasional dan peringatan tetap memakai rules dengan
   satu debounce. Model adalah prediksi evaluasi dan tidak menggantikan rules keselamatan.
5. **Catat:** detector menerbitkan status lengkap ke topik `status` (retained) dan menulis fitur,
   prediksi, probabilitas, serta baseline rules ke CSV.

### Fusi sensor berbasis aturan

- **Jarak:** jarak haversine ke anggota lain yang paling dekat dan masih memiliki data layak.
  Jarak disaring dengan median dari beberapa sampel terakhir. Ambang efektif sekurangnya
  `MIN_SEPARATION_M` dan `SEPARATION_M`, serta dapat naik mengikuti akurasi GPS gabungan kedua
  anggota (`sqrt(akurasi_a² + akurasi_b²)`).
- **Gerakan:** `motion_rms` adalah deviasi standar magnitudo percepatan pada jendela sensor ponsel.
  Nilai di bawah `STILL_RMS` dianggap diam. Nilai yang tidak tersedia dianggap bergerak untuk
  keputusan aturan, tetapi ditandai sebagai data hilang pada fitur model.
- **Histeresis:** setelah jauh, anggota perlu kembali ke bawah 80% dari ambang efektif untuk
  dinyatakan bersama lagi.
- **Debounce:** kandidat status harus berurutan sebanyak `DEBOUNCE_SAMPLES` siklus. Dengan interval
  detector empat detik dan nilai default tiga sampel, transisi dapat tertunda sekitar 8-12 detik.

### AI: input, output, dan keselamatan

Detector menghitung **15 fitur numerik dari jendela 30 detik per anggota**: jarak dan tren jarak
yang dinormalisasi terhadap ambang pemisahan efektif, kecepatan GPS, RMS gerakan, akurasi GPS,
usia data, statistik jarak/kecepatan/gerakan/akurasi dalam jendela, jumlah sampel, dan durasi
jendela. Normalisasi jarak membuat model memahami posisi relatif terhadap batas, bukan menghafal
jarak meter tertentu. Fitur yang sama dipakai saat membuat dataset, melatih model, dan inferensi.

Model Gradient Boosting menghasilkan:

| Label model | Makna |
|---|---|
| `AMAN` | Bergerak bersama / tidak menunjukkan pola menjauh |
| `MULAI MENJAUH` | Jarak bertambah tetapi belum mencapai pola terpisah |
| `TERTINGGAL` | Jauh dan relatif diam |
| `TERPISAH` | Jauh serta bergerak menjauhi rombongan |

Dashboard menampilkan prediksi dan probabilitas kelas tertinggi. Label AI **tidak menggantikan**
status operasional, alarm, maupun rules: peringatan tetap memakai rules dan satu tahap debounce.
`LOST_SIGNAL` selalu menjadi safety override rules dan tidak diprediksi oleh model.

Model bukan lagi dilatih dari pseudo-label rules. `generate_dataset.py` membuat sesi perjalanan
simulasi dengan posisi ground-truth dan pembacaan GPS/gerakan yang diberi noise; label berasal
dari skenario/kondisi sebenarnya, bukan keluaran rules. `train_model.py` melatih
`GradientBoostingClassifier`, memisahkan sesi utuh ke training/validation/test agar jendela yang
berdekatan tidak bocor, memakai batas jarak simulasi yang bervariasi dan perjalanan kontinu, lalu
membandingkan model dengan rules pada baris test yang sama untuk tiga kelas yang bisa dibandingkan
(AMAN dan MULAI MENJAUH digabung untuk baseline karena rules tidak membedakan keduanya).
Gerakan akselerometer pada skenario berjalan bersama, menjauh, dan terpisah memakai rentang yang
sama agar intensitas berjalan saja tidak menjadi penentu label. Detector menandai prediksi
`MULAI MENJAUH`/`TERPISAH` sebagai guarded bila jarak atau trennya bertentangan dengan rules.
Model kemudian mengekspor
`models/herdsense_gbc.joblib`. File model contoh tersebut dibuat dari data sintetis agar demo bisa
langsung dijalankan; hasil sintetis **bukan bukti akurasi dunia nyata**.

Untuk evaluasi yang lebih kuat, isi kolom `label` di CSV dari satu atau lebih sesi nyata yang
ditinjau manual menggunakan empat label di atas, lalu gunakan file CSV itu sebagai input training.
Sisihkan beberapa `session_id` sebagai test yang tidak pernah dipakai untuk training. Jangan
mengklaim akurasi nyata dari data simulasi atau split acak per baris.

### Status

| Kondisi | Status |
|---|---|
| Tidak ada data selama `STALE_S`, atau akurasi GPS di atas `MIN_ACCURACY_M` | `LOST_SIGNAL` |
| Dalam jarak efektif dari setidaknya satu anggota dengan data layak | `TOGETHER` |
| Jauh, tetapi terdeteksi diam | `STRAGGLER_WAITING` |
| Jauh dan bergerak, atau diam-jauh lebih lama dari `GRACE_S` | `SEPARATED` |

Jika hanya ada satu anggota atau tidak ada anggota pembanding yang datanya layak, aturan saat ini
menganggapnya `TOGETHER`; hal ini tidak membuktikan bahwa anggota lain berada di dekatnya.
Pada rombongan dua orang yang terpisah, keduanya dapat ditandai sebagai jauh karena masing-masing
menjadi pembanding terdekat yang lain.

### Peringatan

| Status baru | Level | Pesan | Efek di ponsel |
|---|---|---|---|
| `SEPARATED` | `warn` | `<nama> is N m from the group` | Notifikasi dan getar 600 ms pada Termux |
| `STRAGGLER_WAITING` | `info` | `<nama> stopped N m away from the group` | Notifikasi |
| Kembali ke `TOGETHER` | `info` | `<nama> is back with the group` | Notifikasi |
| `LOST_SIGNAL` | `info` | `No signal from <nama>` | Notifikasi |

Semua ponsel yang subscribe menerima peringatan untuk anggota mana pun. Peringatan `warn` diulang
setiap `ALERT_COOLDOWN_S` selama anggota tetap terpisah.

## Parameter `.env`

Salin `.env.example` sebagai `.env`. Semua ponsel dan detector dalam grup harus menggunakan
`GROUP_ID` yang sama; tiap ponsel harus memiliki `MEMBER_NAME` berbeda. Environment variable
yang sudah diatur di terminal akan mengesampingkan `.env`.

| Variabel | Default | Arti |
|---|---:|---|
| `GROUP_ID` | Wajib diubah | Identifier unik rombongan di topik MQTT |
| `MEMBER_NAME` | `member1` | Nama unik anggota/perangkat |
| `MQTT_HOST` | `broker.hivemq.com` | Host broker MQTT |
| `MQTT_PORT` | `1883` | Port MQTT untuk klien Python; TLS broker umumnya memakai `8883` |
| `MQTT_TLS` | `false` | Aktifkan TLS pada koneksi Python |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | kosong | Kredensial broker bila diperlukan |
| `SEND_INTERVAL_S` | `3` | Interval pengiriman telemetri ponsel |
| `SEPARATION_M` | `100` | Ambang jarak normal |
| `MIN_SEPARATION_M` | `50` | Batas minimum jarak pemisah |
| `STALE_S` | `30` | Usia data maksimum sebelum `LOST_SIGNAL` |
| `MIN_ACCURACY_M` | `60` | Akurasi GPS terburuk yang masih diterima |
| `STILL_RMS` | `0.35` | Batas RMS untuk status diam |
| `GRACE_S` | `60` | Waktu diam-jauh sebelum naik menjadi `SEPARATED` |
| `SMOOTHING_SAMPLES` | `3` | Banyak sampel jarak untuk median smoothing |
| `DEBOUNCE_SAMPLES` | `3` | Sampel berturut-turut untuk konfirmasi transisi |
| `ALERT_COOLDOWN_S` | `30` | Jeda pengulangan peringatan terpisah |
| `FEATURE_WINDOW_S` | `30` | Jendela fitur sensor untuk logging/model |
| `DATA_LOG_PATH` | `data/detector_v2.csv` | Lokasi CSV log detector |
| `AI_MODEL_PATH` | `models/herdsense_gbc.joblib` | Model Gradient Boosting hasil training yang dimuat detector |
| `SIM_LAT` / `SIM_LON` | Jakarta pusat | Titik awal ponsel simulator; tidak digunakan ponsel asli |

## Persiapan dan Menjalankan

### Ponsel Android (Termux)

1. Pasang Termux dan Termux:API dari F-Droid.
2. Pasang alat:

   ```sh
   pkg install python git termux-api
   ```

3. Clone repositori dan masuk folder proyek. Ponsel hanya perlu dependensi MQTT:

   ```sh
   git clone <repo>
   cd herdsense
   pip install -r requirements.txt
   ```

4. Salin `.env.example` menjadi `.env`; isi `GROUP_ID` yang sama dengan grup dan `MEMBER_NAME`
   yang unik. Jangan membagikan `.env`.
5. Jalankan `python check_phone.py` sampai semua pemeriksaan menunjukkan `READY`.
6. Sebelum menjalankan `phone.py`, jalankan `termux-wake-lock` agar Android tidak menidurkan proses.
7. Pada perangkat yang menjalankan detector, pasang dependency AI. `requirements-ai.txt`
   menggunakan versi scikit-learn yang sama dengan model yang disediakan:

   ```sh
   pip install -r requirements-ai.txt
   ```

8. Jalankan detector di **satu perangkat saja**:

   ```sh
   python detector.py
   ```

9. Di setiap ponsel:

   ```sh
   python phone.py
   ```

### Menjalankan simulator di Windows PowerShell

Buka terminal terpisah untuk detector dan setiap anggota. Jalankan dari folder proyek. Jangan
menyalin nilai `GROUP_ID` ke perintah; simpan di `.env` lokal.

PowerShell 1 — detector:

```powershell
cd C:\kuliah\SMT3\iot\herdsense
$env:SEPARATION_M = "50"
$env:GRACE_S = "10"
python detector.py
```

PowerShell 2 — Bob:

```powershell
cd C:\kuliah\SMT3\iot\herdsense
$env:MEMBER_NAME = "Bob"
python phone.py --source simulator --scenario together
```

PowerShell 3 — Lorem:

```powershell
cd C:\kuliah\SMT3\iot\herdsense
$env:MEMBER_NAME = "Lorem"
python phone.py --source simulator --scenario together
```

PowerShell 4 — Sera berjalan menjauh:

```powershell
cd C:\kuliah\SMT3\iot\herdsense
$env:MEMBER_NAME = "Sera"
python phone.py --source simulator --scenario drift --speed 3 --drift-after 10
```

Tunggu sampai detector mencetak status anggota. Perubahan butuh beberapa siklus untuk melewati
smoothing, grace, dan debounce. Hentikan proses dengan `Ctrl+C`.

Untuk konfigurasi parameter yang bertahan, ubah `.env` lokal dan restart proses. Contoh yang sama
bisa dijalankan pada macOS/Linux, tetapi perintah set environment variable berbeda.

### Dashboard

Jalankan VS Code Live Server pada `dashboard/index.html`, atau buka file HTML di browser. Masukkan
nilai `GROUP_ID` yang sama dengan detector dan simulator lalu klik **Connect**. Dashboard memakai
MQTT melalui WebSocket ke `broker.hivemq.com:8884`; koneksi Python menggunakan MQTT TCP pada
`1883`. Keduanya harus menunjuk ke broker dan grup yang sama.

Halaman dashboard **tidak membaca `.env`** dan tidak menerima data langsung dari terminal. Indikator
`connected` hanya berarti dashboard berhasil terhubung ke broker/WebSocket; status anggota baru
muncul setelah detector menerbitkan pesan ke topik `status`.

Query string opsional untuk mengisi grup otomatis:

```text
dashboard/index.html?group=<GROUP_ID>
```

Untuk broker WebSocket lain, query dapat berisi `host`, `port`, `tls`, `user`, dan `pass`; jangan
memasukkan kredensial ke URL yang dapat dibagikan atau disimpan dalam riwayat browser.

## Troubleshooting

1. **Dashboard menunjukkan `Connected to MQTT, but no detector status arrived`:**
   pastikan `detector.py` masih berjalan, terminalnya menunjukkan `[detector] connected`, dan
   `GROUP_ID` yang diketik di dashboard sama dengan milik detector dan seluruh ponsel.
2. **Dashboard menunjukkan `disconnected`:** periksa koneksi internet, akses ke broker/WebSocket,
   dan apakah pustaka MQTT dari CDN berhasil dimuat. Coba refresh halaman lalu Connect lagi.
3. **Detector tidak menunjukkan anggota:** pastikan terminal simulator menampilkan `[nama] connected`
   dan baris `#...`; jalankan `python check_phone.py --skip-sensors` untuk menguji konfigurasi dan
   MQTT publish/subscribe.
4. **Ada data lama tetapi tidak ada pembaruan:** CSV adalah log historis; periksa waktu modifikasi
   file dan pastikan detector yang aktif masih berjalan. Dashboard menerima status aktif, bukan CSV.
5. Jika `GROUP_ID` diganti, hentikan dan mulai ulang detector serta semua simulator/ponsel. Masukkan
   nilai baru di dashboard juga.

Jangan kirim `GROUP_ID`, password broker, token, ataupun isi `.env` ke chat atau screenshot.
Broker publik tidak menyediakan privasi atau ACL hanya karena topiknya memakai nama grup.

## Training di Google Colab

1. Buat notebook Colab baru, lalu jalankan:

   ```python
   !git clone https://github.com/eugenehehehe/herdsense.git
   %cd /content/herdsense
   !pip install -r requirements.txt -r requirements-ai.txt
   ```

2. Buat perjalanan simulasi dengan empat label ground-truth dan GPS noisy:

   ```python
   !python generate_dataset.py --output data/synthetic_dataset.csv --sessions 120 --seed 42
   ```

3. Latih, evaluasi di sesi validation/test terpisah, dan bandingkan dengan baseline rules:

   ```python
   !python train_model.py --input data/synthetic_dataset.csv --output models/herdsense_gbc.joblib
   ```

   Script mencetak accuracy, macro-F1, laporan tiap kelas dan hasil rules pada baris test yang
   sama. Pastikan khususnya recall kelas `TERPISAH`; jangan memilih model hanya dari accuracy.
   Split dilakukan berdasarkan `session_id`, bukan baris/sampel.

4. Unduh model hasil training ke komputer:

   ```python
   from google.colab import files
   files.download("models/herdsense_gbc.joblib")
   ```

5. Ganti `models/herdsense_gbc.joblib` lokal dengan file unduhan. Simpan `.joblib` dari sumber
   tepercaya saja, karena file model serialisasi dapat menjalankan kode saat dimuat. Versi
   scikit-learn harus sesuai `requirements-ai.txt`.

Untuk training cepat tanpa Colab, jalankan dua command generator dan trainer yang sama di PowerShell
dari folder proyek:

```powershell
python generate_dataset.py --output data\synthetic_dataset.csv --sessions 120 --seed 42
python train_model.py --input data\synthetic_dataset.csv --output models\herdsense_gbc.joblib
```

`models/herdsense_gbc.joblib` yang disertakan di repository adalah model demo yang dibuat dari
data sintetis sehingga detector siap dijalankan; model tersebut tetap harus dianggap model
evaluasi awal, bukan model tervalidasi untuk pemakaian nyata.

## Log sesi nyata dan pelabelan

Detector menyimpan fitur 30 detik, status rules, prediksi AI, dan confidence ke
`data/detector.csv`. `session_id` dibuat setiap kali detector dimulai. Isi kolom `label` secara
manual setelah meninjau kondisi aktual pada setiap baris, menggunakan `AMAN`, `MULAI MENJAUH`,
`TERTINGGAL`, atau `TERPISAH`. Baris tanpa label diabaikan trainer. Sediakan setidaknya enam
session terlabel dan pastikan setiap kelas ada pada sesi training. Contoh training dari file anotasi:

```powershell
python train_model.py --input data\detector-labeled.csv --output models\herdsense_gbc.joblib
```

Jangan gabungkan sampel dari sesi test ke training. Untuk laporan yang mewakili penggunaan nyata,
gunakan sesi yang dianotasi manual dan bandingkan model/rules pada test set yang sama. Metrik
simulator hanya mengukur kemampuan model pada simulator, bukan pada kondisi lapangan.

## Pengujian

Tes unit menggunakan Python standar dan tidak memerlukan ponsel, broker, atau koneksi internet:

```sh
python -m unittest discover -s tests -v
```

Uji konektivitas broker dari folder proyek:

```sh
python check_phone.py --skip-sensors
```

## Catatan

- Broker default bersifat publik. Untuk privasi, gunakan broker dengan akun/ACL dan TLS
  (`MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TLS=true`, port MQTT TLS `8883`). Port WebSocket TLS
  dashboard harus sesuai konfigurasi broker.
- Akurasi GPS nyata bervariasi; gedung, cuaca, tas, dan posisi ponsel dapat menambah noise.
- Sensor akselerometer dipilih melalui nama sensor yang mengandung `acc` (misalnya `accelerometer`
  atau `lsm6dso_acc`).
- Struktur pembacaan sensor Termux dan format MQTT mengikuti contoh dari mata kuliah
  https://github.com/myudak/contoh-project-iot1; ide, aturan, dan dashboard proyek ini dikembangkan
  untuk HerdSense.
