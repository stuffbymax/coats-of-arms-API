from flask import Flask, render_template, request, jsonify, redirect, url_for, session, g
import sqlite3
import json
import os
import click
import secrets
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-super-secret-key")
DB_PATH = "coats_of_arms.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS coats_of_arms")
    c.execute("DROP TABLE IF EXISTS users")

    c.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            api_key TEXT UNIQUE NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE coats_of_arms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            motto_latin TEXT,
            motto_english TEXT,
            motto_other TEXT,
            colors TEXT,
            symbols TEXT,
            shield_shape TEXT,
            created_at TEXT,
            designer TEXT,
            image TEXT,
            description TEXT,
            usage_official_documents INTEGER DEFAULT 0,
            usage_flags INTEGER DEFAULT 0,
            usage_seal INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

def seed_db(json_data):
    conn = get_db()
    c = conn.cursor()
    for item in json_data.get("coats_of_arms", []):
        c.execute("""
            INSERT INTO coats_of_arms
            (id, name, motto_latin, motto_english, motto_other, colors, symbols,
             shield_shape, created_at, designer, image, description,
             usage_official_documents, usage_flags, usage_seal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.get("id"),
            item.get("name", ""),
            item.get("motto_latin", ""),
            item.get("motto_english", ""),
            json.dumps(item.get("motto_other")) if item.get("motto_other") else None,
            json.dumps(item.get("colors", [])),
            json.dumps(item.get("symbols", [])),
            item.get("shield_shape", ""),
            item.get("created_at", ""),
            item.get("designer", ""),
            item.get("image", ""),
            item.get("description", ""),
            item.get("usage_official_documents", 0),
            item.get("usage_flags", 0),
            item.get("usage_seal", 0),
        ))
    conn.commit()
    conn.close()


@app.cli.command("init-db")
def init_db_command():
    """Clear the existing data and create new tables, then seed with data.json."""
    init_db()
    click.echo("Initialized the database.")
    json_file = "data.json"
    if os.path.exists(json_file):
        with open(json_file) as f:
            seed_db(json.load(f))
            click.echo("Seeded the database from data.json.")
    else:
        click.echo("data.json not found. Database seeded empty.")


@app.cli.command("make-admin")
@click.argument("username")
def make_admin(username):
    """Grant admin privileges to a user by username."""
    conn = get_db()
    user = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        click.echo(f"User '{username}' not found.")
        conn.close()
        return
    conn.execute("UPDATE users SET is_admin = 1 WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    click.echo(f"'{username}' is now an admin.")


@app.cli.command("revoke-admin")
@click.argument("username")
def revoke_admin(username):
    """Revoke admin privileges from a user by username."""
    conn = get_db()
    conn.execute("UPDATE users SET is_admin = 0 WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    click.echo(f"Admin privileges revoked from '{username}'.")

# ── Authentication & Helpers ────────────────────────────────────────────

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        conn = get_db()
        g.user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('login'))
        if not g.user["is_admin"]:
            return render_template("403.html"), 403
        return f(*args, **kwargs)
    return decorated_function

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key:
            return jsonify({"error": "API key is missing. Provide it in the X-API-Key header."}), 401

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE api_key = ?", (api_key,)).fetchone()
        conn.close()

        if not user:
            return jsonify({"error": "Invalid API key."}), 401

        request.api_user_id = user["id"]
        request.api_user_is_admin = bool(user["is_admin"])
        return f(*args, **kwargs)
    return decorated_function

# ── Web Auth Routes ─────────────────────────────────────────────────────

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db()
        if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            return render_template("signup.html", error="Username already taken.")

        password_hash = generate_password_hash(password)
        api_key = secrets.token_hex(32)

        conn.execute("INSERT INTO users (username, password_hash, api_key) VALUES (?, ?, ?)",
                     (username, password_hash, api_key))
        conn.commit()
        conn.close()

        return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            if user["is_admin"]:
                return redirect(url_for("admin_panel"))
            return redirect(url_for("profile"))

        return render_template("login.html", error="Invalid username or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", user=g.user)

# ── Admin Routes ────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_panel():
    conn = get_db()
    users = conn.execute("SELECT id, username, is_admin, api_key FROM users ORDER BY id").fetchall()
    items = conn.execute("""
        SELECT c.*, u.username as owner_name
        FROM coats_of_arms c
        LEFT JOIN users u ON c.user_id = u.id
        ORDER BY c.id DESC
    """).fetchall()
    stats = {
        "total_users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "total_items": conn.execute("SELECT COUNT(*) FROM coats_of_arms").fetchone()[0],
        "admin_count": conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0],
    }
    conn.close()
    return render_template("admin.html", users=users, items=items, stats=stats)


@app.route("/admin/items/add", methods=["GET", "POST"])
@admin_required
def admin_add_item():
    conn = get_db()
    users = conn.execute("SELECT id, username FROM users ORDER BY username").fetchall()
    if request.method == "POST":
        d = request.form
        conn.execute("""
            INSERT INTO coats_of_arms
            (user_id, name, motto_latin, motto_english, colors, symbols, shield_shape,
             created_at, designer, image, description,
             usage_official_documents, usage_flags, usage_seal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            d.get("user_id") or None,
            d.get("name", ""),
            d.get("motto_latin", ""),
            d.get("motto_english", ""),
            json.dumps([c.strip() for c in d.get("colors", "").split(",") if c.strip()]),
            "[]",
            d.get("shield_shape", ""),
            d.get("created_at", ""),
            d.get("designer", ""),
            d.get("image", ""),
            d.get("description", ""),
            1 if d.get("usage_official_documents") else 0,
            1 if d.get("usage_flags") else 0,
            1 if d.get("usage_seal") else 0,
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("admin_panel"))
    conn.close()
    return render_template("admin_item_form.html", item=None, users=users, action="Add")


@app.route("/admin/items/edit/<int:item_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_item(item_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM coats_of_arms WHERE id = ?", (item_id,)).fetchone()
    users = conn.execute("SELECT id, username FROM users ORDER BY username").fetchall()
    if not row:
        conn.close()
        return redirect(url_for("admin_panel"))

    if request.method == "POST":
        d = request.form
        conn.execute("""
            UPDATE coats_of_arms SET
            user_id=?, name=?, motto_latin=?, motto_english=?, colors=?, shield_shape=?,
            created_at=?, designer=?, image=?, description=?,
            usage_official_documents=?, usage_flags=?, usage_seal=?
            WHERE id=?
        """, (
            d.get("user_id") or None,
            d.get("name", ""),
            d.get("motto_latin", ""),
            d.get("motto_english", ""),
            json.dumps([c.strip() for c in d.get("colors", "").split(",") if c.strip()]),
            d.get("shield_shape", ""),
            d.get("created_at", ""),
            d.get("designer", ""),
            d.get("image", ""),
            d.get("description", ""),
            1 if d.get("usage_official_documents") else 0,
            1 if d.get("usage_flags") else 0,
            1 if d.get("usage_seal") else 0,
            item_id,
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("admin_panel"))

    try:
        colors = json.loads(row["colors"]) if row["colors"] else []
    except:
        colors = []
    conn.close()
    return render_template("admin_item_form.html", item=row, colors=colors, users=users, action="Edit")


@app.route("/admin/items/delete/<int:item_id>", methods=["POST"])
@admin_required
def admin_delete_item(item_id):
    conn = get_db()
    conn.execute("DELETE FROM coats_of_arms WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))


@app.route("/admin/users/toggle-admin/<int:user_id>", methods=["POST"])
@admin_required
def admin_toggle_admin(user_id):
    # Prevent self-demotion
    if user_id == g.user["id"]:
        return redirect(url_for("admin_panel"))
    conn = get_db()
    user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if user:
        new_val = 0 if user["is_admin"] else 1
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_val, user_id))
        conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))


@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    # Prevent self-deletion
    if user_id == g.user["id"]:
        return redirect(url_for("admin_panel"))
    conn = get_db()
    conn.execute("DELETE FROM coats_of_arms WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))


@app.route("/admin/users/reset-key/<int:user_id>", methods=["POST"])
@admin_required
def admin_reset_api_key(user_id):
    new_key = secrets.token_hex(32)
    conn = get_db()
    conn.execute("UPDATE users SET api_key = ? WHERE id = ?", (new_key, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))

# ── Web UI Routes ───────────────────────────────────────────────────────

@app.route("/")
def index():
    conn = get_db()
    search = request.args.get("q", "").strip()
    if search:
        rows = conn.execute(
            "SELECT * FROM coats_of_arms WHERE name LIKE ? ORDER BY name",
            (f"%{search}%",)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM coats_of_arms ORDER BY name").fetchall()
    conn.close()
    return render_template("index.html", items=rows, search=search)

@app.route("/item/<int:item_id>")
def detail(item_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM coats_of_arms WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if not row:
        return redirect(url_for("index"))

    try: colors = json.loads(row["colors"]) if row["colors"] else []
    except: colors = []
    try: symbols = json.loads(row["symbols"]) if row["symbols"] else []
    except: symbols = []

    return render_template("detail.html", item=row, colors=colors, symbols=symbols)

@app.route("/add", methods=["GET", "POST"])
@login_required
def add():
    if request.method == "POST":
        d = request.form
        conn = get_db()
        conn.execute("""
            INSERT INTO coats_of_arms
            (user_id, name, motto_latin, motto_english, colors, symbols, shield_shape,
             created_at, designer, image, description,
             usage_official_documents, usage_flags, usage_seal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            g.user["id"],
            d.get("name", ""),
            d.get("motto_latin", ""),
            d.get("motto_english", ""),
            json.dumps([c.strip() for c in d.get("colors", "").split(",") if c.strip()]),
            "[]",
            d.get("shield_shape", ""),
            d.get("created_at", ""),
            d.get("designer", ""),
            d.get("image", ""),
            d.get("description", ""),
            1 if d.get("usage_official_documents") else 0,
            1 if d.get("usage_flags") else 0,
            1 if d.get("usage_seal") else 0,
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))
    return render_template("add.html")

@app.route("/edit/<int:item_id>", methods=["GET", "POST"])
@login_required
def edit(item_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM coats_of_arms WHERE id = ?", (item_id,)).fetchone()
    if not row:
        conn.close()
        return redirect(url_for("index"))

    # Admins can edit any item; regular users only their own
    if not g.user["is_admin"] and row["user_id"] != g.user["id"]:
        conn.close()
        return "Forbidden: You did not create this item.", 403

    if request.method == "POST":
        d = request.form
        conn.execute("""
            UPDATE coats_of_arms SET
            name=?, motto_latin=?, motto_english=?, colors=?, shield_shape=?,
            created_at=?, designer=?, image=?, description=?,
            usage_official_documents=?, usage_flags=?, usage_seal=?
            WHERE id=?
        """, (
            d.get("name", ""),
            d.get("motto_latin", ""),
            d.get("motto_english", ""),
            json.dumps([c.strip() for c in d.get("colors", "").split(",") if c.strip()]),
            d.get("shield_shape", ""),
            d.get("created_at", ""),
            d.get("designer", ""),
            d.get("image", ""),
            d.get("description", ""),
            1 if d.get("usage_official_documents") else 0,
            1 if d.get("usage_flags") else 0,
            1 if d.get("usage_seal") else 0,
            item_id,
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("detail", item_id=item_id))

    conn.close()
    try: colors = json.loads(row["colors"]) if row["colors"] else []
    except: colors = []

    return render_template("edit.html", item=row, colors=colors)

@app.route("/delete/<int:item_id>", methods=["POST"])
@login_required
def delete(item_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM coats_of_arms WHERE id = ?", (item_id,)).fetchone()

    # Admins can delete any item; regular users only their own
    if row and (g.user["is_admin"] or row["user_id"] == g.user["id"]):
        conn.execute("DELETE FROM coats_of_arms WHERE id = ?", (item_id,))
        conn.commit()

    conn.close()
    return redirect(url_for("index"))

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/docs")
def docs():
    return render_template("docs.html")

@app.route("/fun-facts")
def fun_facts():
    return render_template("fun-facts.html")

# ── API endpoints ────────────────────────────────────────────────────────

@app.route("/api/items", methods=["GET"])
def api_items():
    conn = get_db()
    rows = conn.execute("SELECT * FROM coats_of_arms ORDER BY name").fetchall()
    conn.close()
    result = []
    for r in rows:
        item = dict(r)
        try: item["colors"] = json.loads(item["colors"]) if item["colors"] else []
        except: item["colors"] = []
        try: item["symbols"] = json.loads(item["symbols"]) if item["symbols"] else []
        except: item["symbols"] = []
        try: item["motto_other"] = json.loads(item["motto_other"]) if item["motto_other"] else {}
        except: item["motto_other"] = {}
        result.append(item)
    return jsonify(result)

@app.route("/api/items/<int:item_id>", methods=["GET"])
def api_item(item_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM coats_of_arms WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404

    item = dict(row)
    try: item["colors"] = json.loads(item["colors"]) if item["colors"] else []
    except: item["colors"] = []
    try: item["symbols"] = json.loads(item["symbols"]) if item["symbols"] else []
    except: item["symbols"] = []

    return jsonify(item)

@app.route("/api/items", methods=["POST"])
@require_api_key
def api_create_item():
    data = request.json
    if not data or not data.get("name"):
        return jsonify({"error": "Name is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO coats_of_arms (
            user_id, name, motto_latin, motto_english, motto_other, colors, symbols,
            shield_shape, created_at, designer, image, description,
            usage_official_documents, usage_flags, usage_seal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request.api_user_id,
        data.get("name"),
        data.get("motto_latin"),
        data.get("motto_english"),
        json.dumps(data.get("motto_other", {})),
        json.dumps(data.get("colors", [])),
        json.dumps(data.get("symbols", [])),
        data.get("shield_shape"),
        data.get("created_at"),
        data.get("designer"),
        data.get("image"),
        data.get("description"),
        data.get("usage_official_documents", 0),
        data.get("usage_flags", 0),
        data.get("usage_seal", 0),
    ))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    return jsonify({"id": new_id, "message": "Item created successfully"}), 201

@app.route("/api/items/<int:item_id>", methods=["PUT"])
@require_api_key
def api_update_item(item_id):
    data = request.json
    if not data:
        return jsonify({"error": "Invalid payload"}), 400

    conn = get_db()
    item = conn.execute("SELECT id, user_id FROM coats_of_arms WHERE id = ?", (item_id,)).fetchone()

    if not item:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    # Admins can update any item; regular API users only their own
    if not request.api_user_is_admin and item["user_id"] != request.api_user_id:
        conn.close()
        return jsonify({"error": "Forbidden: You can only edit items you created."}), 403

    conn.execute("""
        UPDATE coats_of_arms SET
        name=?, motto_latin=?, motto_english=?, colors=?, shield_shape=?,
        created_at=?, designer=?, image=?, description=?,
        usage_official_documents=?, usage_flags=?, usage_seal=?
        WHERE id=?
    """, (
        data.get("name"),
        data.get("motto_latin"),
        data.get("motto_english"),
        json.dumps(data.get("colors", [])),
        data.get("shield_shape"),
        data.get("created_at"),
        data.get("designer"),
        data.get("image"),
        data.get("description"),
        data.get("usage_official_documents", 0),
        data.get("usage_flags", 0),
        data.get("usage_seal", 0),
        item_id,
    ))
    conn.commit()
    conn.close()

    return jsonify({"status": "updated", "id": item_id})

@app.route("/api/items/<int:item_id>", methods=["DELETE"])
@require_api_key
def api_delete_item(item_id):
    conn = get_db()
    item = conn.execute("SELECT id, user_id FROM coats_of_arms WHERE id = ?", (item_id,)).fetchone()

    if not item:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    # Admins can delete any item; regular API users only their own
    if not request.api_user_is_admin and item["user_id"] != request.api_user_id:
        conn.close()
        return jsonify({"error": "Forbidden: You can only delete items you created."}), 403

    conn.execute("DELETE FROM coats_of_arms WHERE id=?", (item_id,))
    conn.commit()
    conn.close()

    return jsonify({"status": "deleted"})

# ── Admin API endpoints (web UI AJAX) ────────────────────────────────────

@app.route("/api/admin/stats")
@admin_required
def api_admin_stats():
    conn = get_db()
    stats = {
        "total_users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "total_items": conn.execute("SELECT COUNT(*) FROM coats_of_arms").fetchone()[0],
        "admin_count": conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0],
    }
    conn.close()
    return jsonify(stats)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
