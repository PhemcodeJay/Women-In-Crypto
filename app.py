# app.py
# Women in Crypto Alliance – Registration & Admin Portal
# Requirements: pip install flask flask-mail werkzeug python-dotenv

import os
import uuid
import secrets
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, send_from_directory, session, abort
)
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ─── Configuration from .env ─────────────────────────────────────────
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)

# Email settings
app.config["MAIL_SERVER"]          = os.getenv("MAIL_SERVER")
app.config["MAIL_PORT"]            = int(os.getenv("MAIL_PORT", "587"))
app.config["MAIL_USERNAME"]        = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"]        = os.getenv("MAIL_PASSWORD")
app.config["MAIL_USE_TLS"]         = os.getenv("MAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
app.config["MAIL_USE_SSL"]         = os.getenv("MAIL_USE_SSL", "False").lower() in ("true", "1", "yes")
app.config["MAIL_DEFAULT_SENDER"]  = os.getenv("MAIL_DEFAULT_SENDER") or app.config["MAIL_USERNAME"]

# Paths
BASE_DIR = Path(__file__).resolve().parent

DB_FILENAME   = os.getenv("DB_FILENAME", "cryptowomen.db")
DB_PATH       = Path(os.getenv("DB_PATH", str(BASE_DIR / DB_FILENAME))).resolve()

UPLOAD_SUBDIR = os.getenv("UPLOAD_SUBDIR", "uploads")
UPLOAD_FOLDER = Path(os.getenv("UPLOAD_PATH", str(BASE_DIR / UPLOAD_SUBDIR))).resolve()

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}

# Admin defaults – MUST override in production via .env
ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL",    "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")   # ← Change this!

mail = Mail(app)

# ─── Directory setup ─────────────────────────────────────────────────
def ensure_directory(path: Path, label: str = "directory"):
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"CRITICAL: Cannot create {label} → {path}\nError: {e}")
        raise

ensure_directory(DB_PATH.parent,   "database directory")
ensure_directory(UPLOAD_FOLDER,    "upload directory")

app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

# ─── Database helpers ────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    print(f"Database → {DB_PATH}")
    print(f"  Exists: {DB_PATH.is_file()}  Size: {DB_PATH.stat().st_size if DB_PATH.is_file() else 0:,} bytes")

    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                email               TEXT UNIQUE NOT NULL,
                password_hash       TEXT NOT NULL,
                confirmed           INTEGER DEFAULT 0,
                confirmation_token  TEXT,
                reset_token         TEXT,
                created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                name        TEXT NOT NULL,
                phone       TEXT,
                age         INTEGER,
                category    TEXT NOT NULL,
                reason      TEXT,
                id_proof    TEXT,
                timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Default admin
        row = db.execute(
            "SELECT 1 FROM users WHERE email = ?",
            (ADMIN_EMAIL,)
        ).fetchone()

        if not row:
            print(f"Creating default admin: {ADMIN_EMAIL}")
            hashed = generate_password_hash(ADMIN_PASSWORD)
            db.execute(
                "INSERT INTO users (email, password_hash, confirmed) VALUES (?, ?, 1)",
                (ADMIN_EMAIL, hashed)
            )
            db.commit()
            print("Admin account created.")
        else:
            print("Admin account already exists.")

        print("Database ready.\n")


# Initialize on startup
try:
    init_db()
except Exception as e:
    print("\n" + "═"*70)
    print(" DATABASE INIT FAILED ".center(70))
    print(str(e))
    print("Check write permissions or set DB_PATH= in .env")
    print("═"*70 + "\n")
    raise


# ─── Helpers ─────────────────────────────────────────────────────────
def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


# ─── Routes ──────────────────────────────────────────────────────────

@app.route('/')
def home():
    return render_template('home.html')


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/faq')
def faq():
    return render_template('faq.html')


@app.route('/donate')
def donate():
    return render_template('donate.html')


@app.route('/schedule')
def schedule():
    return render_template('schedule.html')


@app.route('/speakers')
def speakers():
    return render_template('speakers.html')


@app.route('/sponsors')
def sponsors():
    return render_template('sponsors.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        name     = request.form.get('name', '').strip()
        phone    = request.form.get('phone', '').strip()
        age_str  = request.form.get('age', '').strip()
        category = request.form.get('category', '').strip()
        reason   = request.form.get('reason', '').strip()

        if not all([email, password, name, category]):
            flash("Required fields missing", "danger")
            return redirect(request.url)

        age = None
        if age_str:
            try:
                age = int(age_str)
            except ValueError:
                flash("Age must be a number", "danger")
                return redirect(request.url)

        file = request.files.get('id_proof')
        if not file or not file.filename or not allowed_file(file.filename):
            flash("Valid ID proof required (png/jpg/jpeg/pdf)", "danger")
            return redirect(request.url)

        filename = f"{uuid.uuid4().hex[:12]}_{secure_filename(file.filename)}"
        file_path = UPLOAD_FOLDER / filename

        try:
            file.save(file_path)

            token = secrets.token_urlsafe(40)
            pw_hash = generate_password_hash(password)

            with get_db() as db:
                db.execute(
                    "INSERT INTO users (email, password_hash, confirmation_token) VALUES (?, ?, ?)",
                    (email, pw_hash, token)
                )
                user_id = db.lastrowid

                db.execute(
                    """
                    INSERT INTO participants
                    (user_id, name, phone, age, category, reason, id_proof)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, name, phone or None, age, category, reason or None, filename)
                )
                db.commit()

            if app.config["MAIL_SERVER"] and app.config["MAIL_USERNAME"]:
                confirm_url = url_for("confirm_email", token=token, _external=True)
                msg = Message(
                    "Confirm Your Email – Women in Crypto Alliance",
                    sender=app.config["MAIL_DEFAULT_SENDER"],
                    recipients=[email]
                )
                msg.body = f"""Thank you for registering!

Confirm your email: {confirm_url}

If this wasn't you, please ignore this message.

Women in Crypto Alliance Team"""
                try:
                    mail.send(msg)
                    flash("Registered! Please check your email to confirm.", "success")
                except Exception as e:
                    print(f"Email failed: {e}")
                    flash("Registered, but confirmation email could not be sent.", "warning")
            else:
                flash("Registered (email confirmation not configured).", "success")

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            if file_path.exists():
                file_path.unlink(missing_ok=True)
            flash("This email is already registered.", "danger")
        except Exception as e:
            if file_path.exists():
                file_path.unlink(missing_ok=True)
            flash(f"Error during registration: {str(e)}", "danger")

    return render_template("register.html")


@app.route('/confirm/<token>')
def confirm_email(token):
    with get_db() as db:
        user = db.execute(
            "SELECT id FROM users WHERE confirmation_token = ?",
            (token,)
        ).fetchone()

        if user:
            db.execute(
                "UPDATE users SET confirmed = 1, confirmation_token = NULL WHERE id = ?",
                (user["id"],)
            )
            db.commit()
            flash("Email confirmed! You can now log in.", "success")
        else:
            flash("Invalid or expired confirmation link.", "danger")

    return redirect(url_for("login"))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        with get_db() as db:
            user = db.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            ).fetchone()

            if user and check_password_hash(user["password_hash"], password):
                if user["confirmed"]:
                    session["user_id"] = user["id"]
                    session["email"] = user["email"]
                    flash("Logged in successfully", "success")
                    return redirect(url_for("dashboard"))
                else:
                    flash("Please confirm your email first.", "warning")
            else:
                flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get("email", "").strip()

        with get_db() as db:
            user = db.execute(
                "SELECT id FROM users WHERE email = ?",
                (email,)
            ).fetchone()

            if user:
                token = secrets.token_urlsafe(40)
                db.execute(
                    "UPDATE users SET reset_token = ? WHERE id = ?",
                    (token, user["id"])
                )
                db.commit()

                if app.config["MAIL_SERVER"] and app.config["MAIL_USERNAME"]:
                    reset_url = url_for("reset_password", token=token, _external=True)
                    msg = Message(
                        "Password Reset – Women in Crypto Alliance",
                        sender=app.config["MAIL_DEFAULT_SENDER"],
                        recipients=[email]
                    )
                    msg.body = f"""Click to reset password: {reset_url}

If you did not request this, ignore this email."""
                    try:
                        mail.send(msg)
                        flash("Password reset link sent (check spam).", "info")
                    except Exception as e:
                        print(f"Reset email failed: {e}")
                        flash("Could not send reset email – contact support.", "danger")
                else:
                    flash("Password reset link generated (email sending disabled).", "warning")
            else:
                # Security: don't confirm whether email exists
                flash("If the email is registered, you will receive reset instructions.", "info")

    return render_template("forgot_password.html")


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if request.method == 'POST':
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")

        if not password or password != confirm:
            flash("Passwords do not match or are empty.", "danger")
            return redirect(request.url)

        with get_db() as db:
            user = db.execute(
                "SELECT id FROM users WHERE reset_token = ?",
                (token,)
            ).fetchone()

            if user:
                hashed = generate_password_hash(password)
                db.execute(
                    "UPDATE users SET password_hash = ?, reset_token = NULL WHERE id = ?",
                    (hashed, user["id"])
                )
                db.commit()
                flash("Password reset successful! Please log in.", "success")
                return redirect(url_for("login"))
            else:
                flash("Invalid or expired reset link.", "danger")

    return render_template("reset_password.html", token=token)


@app.route('/dashboard')
def dashboard():
    if "user_id" not in session:
        flash("Please log in to access your dashboard.", "warning")
        return redirect(url_for("login"))

    with get_db() as db:
        user = db.execute(
            """
            SELECT u.email, u.confirmed, p.*
            FROM users u
            LEFT JOIN participants p ON u.id = p.user_id
            WHERE u.id = ?
            """,
            (session["user_id"],)
        ).fetchone()

    return render_template("dashboard.html", user=user)


@app.route('/participants')
def participants():
    if "user_id" not in session or session.get("email") != ADMIN_EMAIL:
        flash("Admin access only.", "danger")
        return redirect(url_for("dashboard"))

    with get_db() as db:
        rows = db.execute(
            """
            SELECT p.*, u.email, u.confirmed
            FROM participants p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.timestamp DESC
            """
        ).fetchall()

    return render_template("participants.html", participants=rows)


@app.route('/admin')
def admin():
    if "user_id" not in session or session.get("email") != ADMIN_EMAIL:
        flash("Admin access only.", "danger")
        return redirect(url_for("home"))

    with get_db() as db:
        stats = {
            "total_users": db.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"],
            "confirmed_users": db.execute("SELECT COUNT(*) AS cnt FROM users WHERE confirmed = 1").fetchone()["cnt"],
            "total_participants": db.execute("SELECT COUNT(*) AS cnt FROM participants").fetchone()["cnt"],
            "recent": db.execute(
                """
                SELECT p.*, u.email, u.confirmed
                FROM participants p
                JOIN users u ON p.user_id = u.id
                ORDER BY p.timestamp DESC LIMIT 10
                """
            ).fetchall()
        }

    return render_template("admin.html", stats=stats)


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    if session.get("email") != ADMIN_EMAIL:
        # Optional: restrict file access to admin only
        abort(403)
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ─── Error handlers ──────────────────────────────────────────────────

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template("500.html"), 500


# ─── Startup banner ──────────────────────────────────────────────────

if __name__ == '__main__':
    print("═" * 60)
    print("  Women in Crypto Alliance – Registration Portal")
    print("═" * 60)
    print(f"  Database → {DB_PATH}")
    print(f"  Uploads  → {UPLOAD_FOLDER}")
    print(f"  Admin    → {ADMIN_EMAIL}  (set ADMIN_PASSWORD in .env!)")
    print("═" * 60)
    print("  http://127.0.0.1:5000")
    print("═" * 60 + "\n")

    app.run(debug=True, host="0.0.0.0", port=5000)