from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from contextlib import contextmanager
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import wraps
import hmac
import os
import secrets
import sqlite3
import time

# Optional PostgreSQL support for production hosting.
try:
    import psycopg2
except ImportError:
    psycopg2 = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Local: birthday.db
# Vercel without DATABASE_URL: /tmp is writable, but data is temporary.
if DATABASE_URL:
    DB_TYPE = "postgres"
    DB_PATH = None
elif os.environ.get("VERCEL") == "1":
    DB_TYPE = "sqlite"
    DB_PATH = os.environ.get("DB_PATH", "/tmp/birthday.db")
else:
    DB_TYPE = "sqlite"
    DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "birthday.db"))

SECRET_FILE = os.path.join(BASE_DIR, ".secret_key")
DEFAULT_PASSWORD = "sayang123"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", DEFAULT_PASSWORD)

BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
         "Agustus", "September", "Oktober", "November", "Desember"]
WIB = timezone(timedelta(hours=7))


def load_secret_key():
    """Ambil SECRET_KEY dari environment.
    Jika lokal dan file tersedia, pakai file. Di hosting read-only, buat key sementara."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    try:
        if os.path.exists(SECRET_FILE):
            with open(SECRET_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key

        key = secrets.token_hex(32)
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(key)
        return key
    except OSError:
        return secrets.token_hex(32)


app = Flask(__name__)
app.secret_key = load_secret_key()
app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    JSON_AS_ASCII=False,
)

if os.environ.get("TRUST_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# ---------- Database ----------

@contextmanager
def get_db():
    """Buka koneksi SQLite lokal atau PostgreSQL production."""
    if DB_TYPE == "postgres":
        if psycopg2 is None:
            raise RuntimeError("psycopg2-binary belum terpasang.")
        conn = psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10)

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(conn, query, params=()):
    """Jalankan query dengan placeholder yang sesuai database."""
    if DB_TYPE == "postgres":
        query = query.replace("?", "%s")
        cur = conn.cursor()
        cur.execute(query, params)
        return cur
    return conn.execute(query, params)


def rows_as_dicts(cursor):
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def init_db():
    with get_db() as conn:
        if DB_TYPE == "sqlite":
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass

            execute(conn, """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
        else:
            execute(conn, """
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)


# Jalankan saat import agar tabel tersedia sebelum request pertama.
init_db()


def now_wib():
    n = datetime.now(WIB)
    return f"{n.day:02d} {BULAN[n.month - 1]} {n.year}, {n:%H:%M}"


# ---------- Rate limit sederhana (in-memory, per IP) ----------

_hits = defaultdict(deque)


def rate_limited(bucket, limit, window):
    key = (bucket, request.remote_addr or "?")
    now = time.monotonic()
    q = _hits[key]

    while q and now - q[0] > window:
        q.popleft()

    if len(q) >= limit:
        return True

    q.append(now)
    return False


# ---------- Auth ----------

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper


def password_ok(candidate):
    return hmac.compare_digest(
        candidate.encode("utf-8"),
        ADMIN_PASSWORD.encode("utf-8"),
    )


# ---------- Routes ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/messages")
def messages():
    with get_db() as conn:
        cur = execute(
            conn,
            "SELECT name, text, created_at FROM messages "
            "ORDER BY id DESC LIMIT 30"
        )
        rows = rows_as_dicts(cur)

    resp = jsonify(rows)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/messages")
def create_message():
    if rate_limited("post_message", limit=5, window=60):
        return jsonify(error="Terlalu cepat, coba lagi sebentar ya."), 429

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Format data tidak valid."), 400

    name, text = data.get("name"), data.get("text")

    if not isinstance(name, str) or not isinstance(text, str):
        return jsonify(error="Nama dan pesan wajib diisi."), 400

    name, text = name.strip(), text.strip()

    if not name or not text:
        return jsonify(error="Nama dan pesan wajib diisi."), 400
    if len(name) > 80:
        return jsonify(error="Nama terlalu panjang (maks. 80 karakter)."), 400
    if len(text) > 1000:
        return jsonify(error="Pesan terlalu panjang (maks. 1000 karakter)."), 400

    with get_db() as conn:
        execute(
            conn,
            "INSERT INTO messages(name, text, created_at) VALUES (?, ?, ?)",
            (name, text, now_wib()),
        )

    return jsonify(ok=True), 201


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if session.get("admin"):
        return redirect(url_for("admin_dashboard"))

    error = None

    if request.method == "POST":
        if rate_limited("login", limit=5, window=300):
            error = "Terlalu banyak percobaan. Coba lagi beberapa menit lagi."
        elif password_ok(request.form.get("password", "")):
            session.clear()
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Password salah."

    return render_template("admin_login.html", error=error)


@app.get("/admin/dashboard")
@admin_required
def admin_dashboard():
    with get_db() as conn:
        cur = execute(
            conn,
            "SELECT id, name, text, created_at FROM messages ORDER BY id DESC"
        )
        rows = rows_as_dicts(cur)

    return render_template("admin.html", messages=rows)


@app.post("/admin/delete/<int:message_id>")
@admin_required
def delete_message(message_id):
    with get_db() as conn:
        execute(conn, "DELETE FROM messages WHERE id = ?", (message_id,))
    return redirect(url_for("admin_dashboard"))


@app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# ---------- Error handlers ----------

def api_error(message, code):
    if request.path.startswith("/api/"):
        return jsonify(error=message), code
    return message, code


@app.errorhandler(404)
def not_found(_e):
    return api_error("Halaman tidak ditemukan.", 404)


@app.errorhandler(405)
def method_not_allowed(_e):
    return api_error("Method tidak diizinkan.", 405)


@app.errorhandler(413)
def too_large(_e):
    return api_error("Data terlalu besar.", 413)


@app.errorhandler(500)
def server_error(_e):
    return api_error("Terjadi kesalahan di server.", 500)


if __name__ == "__main__":
    if ADMIN_PASSWORD == DEFAULT_PASSWORD:
        print("[!] ADMIN_PASSWORD masih default. Sebaiknya ganti sebelum online.")

    app.run(
        debug=os.environ.get("FLASK_DEBUG") == "1",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
    )
