# HerdSense - Group Travel Tracker

Ponsel mengirim data GPS + akselerometer lewat MQTT. Sebuah detector memutuskan siapa yang
menjauh dari rombongan, lalu mengirim peringatan ke semua ponsel (getar + notifikasi). Dashboard
web menampilkan status secara langsung.

**Presented by Group 8 - IoT Kelas A Informatika UNDIP**

## Anggota Kelompok

| Nama | NIM |
|---|---|
| Fathin Arva A. | 24060125130056 |
| Nabil Al Gazaska | 24060125130096 |
| Adelia Rafalina | 24060125140236 |
| Eugene N. Serafhina | 24060125140242 |

```
ponsel (Termux)  <--MQTT-->  broker  <--MQTT-->  detector.py
                               |
                               +--MQTT(WebSocket)--> dashboard/index.html
```

| Bagian | File |
|---|---|
| Edge: sensor, pemrosesan, publish, menerima peringatan | `phone.py` |
| Aturan (fusi jarak + gerakan), murni dan teruji | `rules.py`, `tests/` |
| Detector + peringatan | `detector.py` |
| Dashboard | `dashboard/index.html` |
| Pengecekan kesiapan per ponsel | `check_phone.py` |
| Konfigurasi bersama, nama topik, koneksi MQTT | `common.py` |

## Infrastruktur

Semua bagian berkomunikasi lewat satu **broker MQTT** dan tidak saling mengenal secara langsung.
Yang mereka bagikan hanya alamat broker dan `GROUP_ID`.

| Komponen | Peran | Berjalan di |
|---|---|---|
| Broker MQTT | Perantara pesan (publish/subscribe), tidak mengambil keputusan. Bawaan: `broker.hivemq.com` (publik) | Server internet |
| `phone.py` (edge) | Membaca GPS + akselerometer tiap `SEND_INTERVAL_S` detik, mem-publish telemetri, menampilkan peringatan | Setiap ponsel (Termux) |
| `detector.py` | Mengumpulkan telemetri semua anggota, menjalankan aturan, mem-publish status dan peringatan | **Satu** perangkat mana saja yang punya internet (laptop, ponsel, server) |
| `dashboard/index.html` | Hanya menampilkan status dan peringatan, tidak menghitung apa pun | Browser (file statis, tanpa server, via WebSocket) |

Karena semuanya hanya bergantung pada broker dan `GROUP_ID`, detector bisa dijalankan di mana saja,
anggota baru bisa ditambah tanpa mengubah apa pun, dan ponsel simulasi bekerja persis seperti
ponsel asli (mengirim JSON yang sama).

**Fungsi `GROUP_ID`:** menjadi bagian dari setiap nama topik (`trip/<GROUP_ID>/...`), sehingga
berfungsi sebagai kanal privat satu rombongan di broker publik. Hanya perangkat dengan `GROUP_ID`
yang sama yang saling melihat. Broker publik tidak punya akun, jadi `GROUP_ID` yang panjang dan acak
adalah satu-satunya pengaman.

### Topik MQTT
```
trip/<GROUP_ID>/edge/<member>/telemetry   ponsel -> broker    {device_id, sequence, lat, lon, accuracy_m, motion_rms, sent_at_ms}
trip/<GROUP_ID>/alerts                    detector -> ponsel  {level, member, message, ts}
trip/<GROUP_ID>/status                    detector -> dashboard (retained)
```

| Perangkat | Publish | Subscribe |
|---|---|---|
| Ponsel | `.../edge/<member>/telemetry` | `.../alerts` |
| Detector | `.../status` (retained), `.../alerts` | `.../edge/+/telemetry` |
| Dashboard | - | `.../status`, `.../alerts` |

`+` adalah wildcard MQTT untuk satu level, sehingga detector menerima telemetri semua anggota
dengan satu subscription. Anggota baru muncul otomatis saat pertama kali mengirim telemetri;
`MEMBER_NAME` harus unik.

## Logika

Alur detector (`detector.py`, tiap 1 detik):

1. **Terima:** validasi tiap pesan telemetri (buang yang rusak atau duplikat), simpan data terakhir
   tiap anggota beserta waktu **penerimaan** (agar tidak terpengaruh perbedaan jam ponsel).
2. **Putuskan:** `rules.evaluate()` menghitung status tiap anggota (lihat di bawah).
3. **Publikasi:** kirim status lengkap ke `status` (retained, sehingga dashboard yang baru
   terhubung langsung melihat kondisi terkini) dan kirim peringatan ke `alerts` saat status berubah.

Dua pemrosesan digabung (fusi sensor berbasis aturan):
- **A, jarak:** jarak haversine ke **anggota terdekat** (bukan rata-rata rombongan, yang akan
  tertarik oleh satu orang yang jauh).
- **B, gerakan:** deviasi standar besar percepatan dari akselerometer (`motion_rms`).
  Di bawah 0,35 dianggap diam. Data gerakan kosong dianggap bergerak.

Jarak saja tidak bisa membedakan orang yang tersesat dari orang yang berhenti di toko; menambahkan
gerakan menyelesaikannya.

### Status (`rules.py`)

| Kondisi | Status |
|---|---|
| tidak ada data selama `STALE_S` atau akurasi GPS lebih buruk dari `MIN_ACCURACY_M` | LOST_SIGNAL |
| dalam jarak `SEPARATION_M` dari seorang anggota | TOGETHER |
| jauh tetapi diam | STRAGGLER_WAITING |
| jauh dan bergerak, atau diam-dan-jauh lebih lama dari `GRACE_S` | SEPARATED |

Kembali ke TOGETHER membutuhkan jarak di bawah 80% batas (histeresis), agar noise GPS tidak
membuat status berkedip. Keterbatasan: pada rombongan 2 orang, keduanya ditandai saat berjauhan.

### Peringatan

| Status baru | Level | Pesan | Efek di ponsel |
|---|---|---|---|
| SEPARATED | `warn` | `<nama> is N m from the group` | notifikasi + getar 600 ms |
| STRAGGLER_WAITING | `info` | `<nama> stopped N m away from the group` | notifikasi |
| kembali ke TOGETHER | `info` | `<nama> is back with the group` | notifikasi |
| LOST_SIGNAL | `info` | `No signal from <nama>` | notifikasi |

Setiap ponsel menerima setiap peringatan, termasuk tentang anggota lain. Peringatan `warn`
diulang tiap `ALERT_COOLDOWN_S` selama anggota tetap terpisah.

### Parameter (`.env`)

| Variabel | Bawaan | Arti |
|---|---|---|
| `SEPARATION_M` | 100 | jarak yang dianggap "jauh" |
| `GRACE_S` | 60 | diam-dan-jauh selama ini naik menjadi SEPARATED |
| `STALE_S` | 30 | tanpa data selama ini menjadi LOST_SIGNAL |
| `MIN_ACCURACY_M` | 60 | GPS lebih buruk dari ini dianggap tanpa sinyal |
| `ALERT_COOLDOWN_S` | 30 | jeda pengulangan peringatan saat tetap terpisah |
| `SEND_INTERVAL_S` | 3 | interval kirim telemetri |
| `SIM_LAT`, `SIM_LON` | Jakarta pusat | titik awal ponsel simulasi (diabaikan ponsel asli) |

## Persiapan (setiap perangkat)
1. Termux + Termux:API dari F-Droid, lalu `pkg install python git termux-api`
2. `git clone <repo> && cd <repo> && pip install -r requirements.txt`
3. `cp .env.example .env` lalu ubah: `GROUP_ID` bersama (panjang, acak, bagikan secara privat),
   `MEMBER_NAME` unik
4. `python check_phone.py` sampai muncul READY

## Menjalankan
- **Detector (satu perangkat):** `python detector.py`
- **Setiap ponsel:** `python phone.py` (jalankan `termux-wake-lock` dulu agar Android tidak mematikannya)
- **Dashboard:** buka `dashboard/index.html` di browser, masukkan `GROUP_ID`, Connect
  (atau `index.html?group=GROUP_ID_ANDA`; tambahkan `&host=...&port=...&user=...&pass=...` untuk broker lain)

## Demo tanpa berkumpul (simulator, PC mana saja)
Turunkan batas di `.env` (`SEPARATION_M=30`, `GRACE_S=10`), lalu:
- **Seseorang menjauh:** dua ponsel `python phone.py --source simulator`, satu dengan `--scenario drift --speed 3`
- **Seseorang tertinggal diam:** dua ponsel `--scenario drift --speed 3`, satu `--scenario still`

Tiap ponsel simulasi butuh `MEMBER_NAME` sendiri (`MEMBER_NAME=ayu python phone.py ...`).
Atur `SIM_LAT` dan `SIM_LON` ke lokasi Anda agar ponsel simulasi mulai di dekat ponsel asli.

## Pengujian

Tes unit untuk aturan (tanpa ponsel, broker, atau internet):

```
python -m unittest tests.test_rules -v
```


## Catatan
- Broker bawaan bersifat publik: pakai `GROUP_ID` yang panjang dan acak, dan gunakan jalur simulasi
  untuk demo. Untuk privasi gunakan broker dengan login (atur `MQTT_USERNAME`/`MQTT_PASSWORD`,
  `MQTT_TLS=true`, port 8883).
- GPS hanya akurat sekitar 5-20 m. Pada penggunaan nyata, jaga `SEPARATION_M` minimal 50 m.
- Sensor akselerometer dikenali dari nama yang mengandung `acc` (mis. `accelerometer`, `lsm6dso_acc`).
- Struktur kode (pembacaan sensor Termux, struktur MQTT) mengikuti contoh dari mata kuliah
  https://github.com/myudak/contoh-project-iot1; ide, aturan, dan dashboard adalah karya sendiri.
