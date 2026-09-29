# Birthday Fullstack — Flask + SQLite/PostgreSQL

Project web ulang tahun dengan Flask, halaman publik, pesan, dan dashboard admin.

## Struktur
- `app.py` — backend Flask + API + database
- `templates/` — halaman web
- `static/` — foto dan lagu
- `requirements.txt` — dependency Python

## Jalankan lokal

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Buka `http://127.0.0.1:5000`.

Secara lokal, aplikasi otomatis memakai `birthday.db`.

## Login admin

Buka:

`http://127.0.0.1:5000/admin`

Password default:

```text
sayang123
```

Sebelum online, set:

```text
ADMIN_PASSWORD=buat-password-sendiri
SECRET_KEY=string-random-yang-panjang
```

## Deploy ke Vercel

Aplikasi mendukung dua database:

1. **SQLite lokal** — cocok untuk laptop.
2. **PostgreSQL** — gunakan `DATABASE_URL` untuk penyimpanan online yang persisten.

Environment variable yang disarankan untuk deployment:

```text
SECRET_KEY=...
ADMIN_PASSWORD=...
DATABASE_URL=...
COOKIE_SECURE=1
```

### Penting

Jika `DATABASE_URL` belum diisi saat berjalan di Vercel, aplikasi akan memakai SQLite di `/tmp` supaya fungsi Flask tetap bisa berjalan. Penyimpanan `/tmp` **tidak persisten**, sehingga pesan dapat hilang ketika instance/serverless function berganti.

Untuk web ulang tahun yang benar-benar online dan pesan harus tetap tersimpan, gunakan PostgreSQL dan isi `DATABASE_URL`.

File `birthday.db` dan `.secret_key` sengaja tidak disertakan dalam paket deployment ini.
