import os
import datetime
import jwt
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from contextlib import contextmanager, closing
from decimal import Decimal
import re
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error

# Load environment variables from .env file
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(env_path, override=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQL_PATH = os.path.join(BASE_DIR, "IMS.sql")
DIST_PATH = os.path.join(BASE_DIR, "dist")

# --- DB Config ---
DB_HOST = os.getenv("IMS_DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("IMS_DB_PORT", "3306"))
DB_USER = os.getenv("IMS_DB_USER", "ims_app")
DB_PASSWORD = os.getenv("IMS_DB_PASSWORD", "ims123")
DB_NAME = os.getenv("IMS_DB_NAME", "ims")
DB_TIMEOUT = int(os.getenv("IMS_DB_TIMEOUT", "5"))

# --- Admin Config ---
ADMIN_INVITE_CODE = os.getenv("ADMIN_INVITE_CODE", "ADMIN123")
SUPER_ADMIN_USERNAME = os.getenv("SUPER_ADMIN_USERNAME", "superadmin")
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "admin123")
SUPER_ADMIN_EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "superadmin@ims.com")

SECRET_KEY = os.getenv("JWT_SECRET", "ims-super-secret-key-at-least-32-bytes-long-2024")

app = Flask(__name__, static_folder=DIST_PATH, static_url_path='')
CORS(app, supports_credentials=True)

# --- Helpers ---
def send_email(to_email, subject, body):
    # Fetch fresh from env in case they changed
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    email_from = os.getenv("EMAIL_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        print(f"--- EMAIL CONFIG MISSING ---")
        print(f"SMTP_USER: '{smtp_user}', SMTP_PASS: '{'SET' if smtp_pass else 'NOT SET'}'")
        print(f"To: {to_email}\nSubject: {subject}")
        print(f"-----------------------------")
        return False

    server = None
    try:
        msg = MIMEMultipart()
        msg['From'] = email_from
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        print(f"Attempting to send email to {to_email} via {smtp_server}:{smtp_port}...")
        
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        print(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to send email to {to_email}: {type(e).__name__}: {e}")
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass

def decimal_to_float(value):
    if isinstance(value, Decimal):
        return float(value)
    return value

def format_row(row):
    if not row: return row
    new_row = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            new_row[k] = float(v)
        elif isinstance(v, (datetime.datetime, datetime.date)):
            new_row[k] = v.isoformat()
        else:
            new_row[k] = v
    return new_row

def normalize_admin_role(role):
    role_map = {
        "Super Admin": "SUPER_ADMIN",
        "Inventory Manager": "ADMIN",
        "Order Manager": "ORDER_MANAGER",
        "SUPER_ADMIN": "SUPER_ADMIN",
        "ADMIN": "ADMIN",
        "ORDER_MANAGER": "ORDER_MANAGER",
    }
    return role_map.get(role, role)

def display_admin_role(role):
    role_map = {
        "SUPER_ADMIN": "Super Admin",
        "ADMIN": "Inventory Manager",
        "ORDER_MANAGER": "Order Manager",
    }
    return role_map.get(role, role)

def map_admin_for_frontend(row):
    a = format_row(row)
    return {
        **a,
        "adminId": str(a["admin_id"]) if a.get("admin_id") is not None else "",
        "firstName": a.get("first_name", ""),
        "lastName": a.get("last_name", ""),
        "createdAt": a.get("created_at"),
        "isActive": bool(a.get("is_active", 0)),
        "role": display_admin_role(a.get("role")),
    }

def map_customer_for_frontend(row):
    c = format_row(row)
    return {
        **c,
        "customerId": str(c["customer_id"]) if c.get("customer_id") is not None else "",
        "firstName": c.get("first_name", ""),
        "lastName": c.get("last_name", ""),
        "createdAt": c.get("created_at"),
        "isActive": bool(c.get("is_active", 0)),
    }

def resolve_customer_username(cursor, customer_identifier):
    if customer_identifier is None:
        return None
    execute_query(
        cursor,
        "SELECT username FROM customer_accounts WHERE customer_id = %s OR username = %s LIMIT 1",
        (customer_identifier, customer_identifier),
    )
    row = fetch_one(cursor)
    return row.get("username") if row else None

def resolve_admin_username(cursor, admin_identifier):
    if admin_identifier is None:
        return None
    execute_query(
        cursor,
        "SELECT username FROM admin_accounts WHERE admin_id = %s OR username = %s LIMIT 1",
        (admin_identifier, admin_identifier),
    )
    row = fetch_one(cursor)
    return row.get("username") if row else None

def get_order_items_with_products(cursor, order_id):
    query = """
        SELECT
            oi.order_id,
            oi.product_id,
            oi.qty,
            p.name as product_name,
            p.price as unit_price,
            p.category_id,
            p.stock
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        WHERE oi.order_id = %s
    """
    execute_query(cursor, query, (order_id,))
    rows = [format_row(r) for r in fetch_all(cursor)]
    items = []
    for r in rows:
        items.append({
            "orderId": str(r["order_id"]),
            "productId": str(r["product_id"]),
            "quantity": int(r.get("qty", 0)),
            "product": {
                "productId": str(r["product_id"]),
                "name": r.get("product_name"),
                "price": float(r.get("unit_price") or 0),
                "stockQty": int(r.get("stock") or 0),
                "categoryId": str(r["category_id"]) if r.get("category_id") is not None else None,
            },
        })
    return items

def period_bucket_expr(period, column_name="o.datetime"):
    if DB_TYPE == "mysql":
        if period == "week":
            return f"DATE_FORMAT({column_name}, '%Y-%u')"
        if period == "month":
            return f"DATE_FORMAT({column_name}, '%Y-%m')"
        return f"DATE({column_name})"

    # sqlite
    if period == "week":
        return f"strftime('%Y-%W', {column_name})"
    if period == "month":
        return f"strftime('%Y-%m', {column_name})"
    return f"date({column_name})"

def normalize_order_status(status):
    allowed = {"pending", "processing", "shipped", "delivered", "cancelled"}
    normalized = str(status or "").strip().lower()
    return normalized if normalized in allowed else "pending"

def generate_username_by_formula(cursor, table, first_name, prefix):
    # Formula: PREFIX + first 3 letters of first name (upper) + current HHMMSS
    first_part = (first_name or "USR")[:3].upper()
    base_username = f"{prefix}-{first_part}{datetime.datetime.now().strftime('%H%M%S')}"
    username = base_username
    suffix = 1

    # Guard against same-second collisions
    while True:
        execute_query(cursor, f"SELECT 1 FROM {table} WHERE username = %s", (username,))
        if not fetch_one(cursor):
            return username
        username = f"{base_username}{suffix}"
        suffix += 1

def is_password_hash(value):
    value = str(value or "")
    return "$" in value and (value.startswith("pbkdf2:") or value.startswith("scrypt:") or value.startswith("argon2:"))

def hash_password(password):
    return generate_password_hash(password)

def verify_password(stored_password, candidate_password):
    if stored_password is None:
        return False
    stored_password = str(stored_password)
    candidate_password = str(candidate_password or "")
    if is_password_hash(stored_password):
        try:
            return check_password_hash(stored_password, candidate_password)
        except ValueError:
            return False
    return stored_password == candidate_password

def migrate_legacy_passwords(cursor, table_name, id_column):
    execute_query(cursor, f"SELECT {id_column} as id, password FROM {table_name}")
    rows = fetch_all(cursor)
    changed = 0
    for row in rows:
        stored_password = row.get("password")
        if not stored_password or is_password_hash(stored_password):
            continue
        execute_query(
            cursor,
            f"UPDATE {table_name} SET password = %s WHERE {id_column} = %s",
            (hash_password(stored_password), row["id"]),
        )
        changed += 1
    return changed

def ensure_password_column_width(cursor):
    if DB_TYPE != "mysql":
        return
    for table_name in ("admin_accounts", "customer_accounts"):
        try:
            execute_query(cursor, f"ALTER TABLE {table_name} MODIFY password VARCHAR(255) NOT NULL")
        except Exception as e:
            if "duplicate" not in str(e).lower() and "column" not in str(e).lower() and "exists" not in str(e).lower():
                print(f"Warning: Could not widen {table_name}.password: {e}")

import sqlite3

# --- DB Configuration ---
USE_SQLITE = os.getenv("USE_SQLITE", "false").lower() == "true"
SQLITE_PATH = os.path.join(BASE_DIR, "ims.db")

def get_db_type():
    if USE_SQLITE:
        return "sqlite"
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            connection_timeout=DB_TIMEOUT
        )
        conn.close()
        return "mysql"
    except:
        print("MySQL connection failed, falling back to SQLite.")
        return "sqlite"

DB_TYPE = get_db_type()

@contextmanager
def db_connection():
    if DB_TYPE == "sqlite":
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    else:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            connection_timeout=DB_TIMEOUT,
        )
        try:
            yield conn
        finally:
            conn.close()

def generate_token(user_id, role, username):
    # Map roles to match frontend's AppRole ('admin' | 'customer') for routing
    # The frontend uses this field in ProtectedRoute to allow/deny access.
    app_role = 'admin' if role in ['SUPER_ADMIN', 'ADMIN', 'ORDER_MANAGER', 'Super Admin', 'Inventory Manager', 'Order Manager'] else 'customer'
    
    # Keep the raw backend role in the token for permission checks.
    db_role = role
    
    print(f"DEBUG TOKEN: input_role='{role}', mapped_role='{app_role}', db_role='{db_role}'")

    payload = {
        "sub": str(user_id),
        "username": username,
        "role": app_role,
        "db_role": db_role,
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def get_auth_payload():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split(' ', 1)[1]
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None


def log_admin_action(admin_username, product_id, action):
    """Silently log an admin action with Pakistan timezone (UTC+5)."""
    if not admin_username:
        return
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            # Get current time in Pakistan timezone (UTC+5)
            pk_tz = datetime.timezone(datetime.timedelta(hours=5))
            pk_time = datetime.datetime.now(pk_tz).strftime('%Y-%m-%d %H:%M:%S')
            # Insert with Pakistan timezone timestamp
            query = "INSERT INTO admin_products (admin_username, product_id, action, action_datetime) VALUES (%s, %s, %s, %s)"
            execute_query(cursor, query, (admin_username, product_id, action, pk_time))
            conn.commit()
    except Exception as e:
        print(f"[AUDIT LOG] Error: {e}")
        pass  # Silently fail - never disrupt the main operation


def execute_query(cursor, query, args=None):
    if DB_TYPE == "sqlite":
        # Convert %s to ? for SQLite
        query = query.replace("%s", "?")
    cursor.execute(query, args or [])

def fetch_one(cursor):
    row = cursor.fetchone()
    if not row: return None
    if DB_TYPE == "sqlite":
        return dict(row)
    return row

def fetch_all(cursor):
    rows = cursor.fetchall()
    if DB_TYPE == "sqlite":
        return [dict(r) for r in rows]
    return rows

# Update helpers to use normalized functions
def paginate(query, params, query_args=None):
    page = int(params.get('page', 1))
    limit = int(params.get('limit', 10))
    offset = (page - 1) * limit
    
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql":
            cursor = conn.cursor(dictionary=True)
        
        # Get total count
        count_query = f"SELECT COUNT(*) as total FROM ({query}) as t"
        execute_query(cursor, count_query, query_args)
        res = fetch_one(cursor)
        total = res['total'] if res else 0
        
        # Get paginated data
        paginated_query = f"{query} LIMIT %s OFFSET %s"
        args = list(query_args or []) + [limit, offset]
        execute_query(cursor, paginated_query, args)
        rows = fetch_all(cursor)
        
        return {
            "data": [format_row(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
            "totalPages": (total + limit - 1) // limit if limit > 0 else 1
        }

# --- Auth Routes ---
@app.post("/api/auth/login")
def api_login():
    data = request.get_json(silent=True) or {}
    role = data.get("role") # 'admin' or 'customer'
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if role not in {"admin", "customer"}:
        return jsonify({"error": "Invalid role"}), 400
    
    table = "admin_accounts" if role == "admin" else "customer_accounts"
    id_col = "admin_id" if role == "admin" else "customer_id"

    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        
        execute_query(cursor, f"SELECT * FROM {table} WHERE username = %s", (username,))
        user = fetch_one(cursor)
        if not user:
            return jsonify({"error": "Username not found"}), 404

        if not bool(user.get('is_active') or 0):
            return jsonify({"error": "Your account is deactivated."}), 403

        query = f"SELECT * FROM {table} WHERE username = %s"
        execute_query(cursor, query, (username,))
        user = fetch_one(cursor)
        
        if not user:
            return jsonify({"error": "Invalid password"}), 401

        if not verify_password(user.get('password'), password):
            return jsonify({"error": "Invalid password"}), 401
        
        user_id = user[id_col]
        user_role = user.get('role', 'CUSTOMER') if role == 'admin' else 'CUSTOMER'
        
        print(f"DEBUG LOGIN: user_id={user_id}, role={role}, db_role={user_role}, username={username}")
        
        token = generate_token(user_id, user_role, username)
        
        return jsonify({
            "token": token,
            "refreshToken": "dummy-refresh-token",
            "role": role,
            "user": {
                "id": str(user_id),
                "firstName": user['first_name'],
                "lastName": user['last_name'],
                "email": user['email'],
                "username": user['username']
            }
        })

@app.post("/api/auth/register")
def api_register():
    data = request.get_json(silent=True) or {}
    role = data.get("role", "customer") # 'admin' or 'customer'
    first_name = data.get("firstName")
    last_name = data.get("lastName")
    email = data.get("email")
    phone = data.get("phone")
    password = data.get("password")
    address = data.get("address") # Only for customers
    
    if not all([first_name, last_name, email, password]):
        return jsonify({"error": "Missing fields"}), 400

    if role == "admin":
        return jsonify({"error": "Admin registration is restricted to super admins"}), 403

    table = "customer_accounts"
    id_col = "customer_id"
    prefix = "CUS"

    with db_connection() as conn:
        cursor = conn.cursor()
        
        # Check if email exists
        execute_query(cursor, f"SELECT 1 FROM {table} WHERE email = %s", (email,))
        if fetch_one(cursor):
            return jsonify({"error": "Email already exists"}), 400

        username = generate_username_by_formula(cursor, table, first_name, prefix)
        password_hash = hash_password(password)
        
        execute_query(cursor, 
            "INSERT INTO customer_accounts (username, password, first_name, last_name, email, phone, address) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (username, password_hash, first_name, last_name, email, phone, address)
        )
        
        conn.commit()
        user_id = cursor.lastrowid
        
        # Fetch the email and first name from the database to be absolutely sure we have the correct target
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        execute_query(cursor, f"SELECT * FROM {table} WHERE {id_col} = %s", (user_id,))
        db_user = fetch_one(cursor)
        
        if db_user:
            target_email = db_user['email']
            target_first_name = db_user['first_name']
            target_role = db_user.get('role', 'CUSTOMER')
            
            # Send real email with username
            subject = "Your IIMS Username"
            body = f"Hello {target_first_name},\n\nYour account has been created successfully.\nYour unique username for logging in is: {username}\n\nWelcome aboard!\nIIMS Team"
            email_sent = send_email(target_email, subject, body)
        else:
            target_role = 'CUSTOMER'
            email_sent = False

        token = generate_token(user_id, target_role, username)
        
        response = {
            "token": token,
            "refreshToken": "dummy-refresh-token",
            "role": role,
            "user": {
                "id": str(user_id),
                "firstName": first_name,
                "lastName": last_name,
                "email": email,
                "username": username
            }
        }

        if not email_sent:
            response["warning"] = "Account created, but the confirmation email could not be sent. Check SMTP settings."

        return jsonify(response)

@app.post("/api/auth/logout")
def api_logout():
    return jsonify({"ok": True})

# --- Product Routes ---
@app.get("/api/products")
def get_products():
    query = "SELECT p.*, c.name as categoryName FROM products p LEFT JOIN categories c ON p.category_id = c.category_id WHERE 1=1"
    args = []
    
    search = request.args.get('search')
    if search:
        query += " AND (p.name LIKE %s OR c.name LIKE %s)"
        args.extend([f"%{search}%", f"%{search}%"])
        
    category_id = request.args.get('categoryId')
    if category_id:
        query += " AND p.category_id = %s"
        args.append(category_id)

    sort_by = request.args.get('sortBy')
    sort_order = (request.args.get('order') or 'asc').lower()
    sort_map = {
        'name': 'p.name',
        'price': 'p.price',
        'stockQty': 'p.stock',
    }
    if sort_by in sort_map:
        direction = 'DESC' if sort_order == 'desc' else 'ASC'
        query += f" ORDER BY {sort_map[sort_by]} {direction}"

    # Normalize fields for frontend (productId, stockQty)
    res = paginate(query, request.args, args)
    for p in res['data']:
        p['productId'] = str(p['product_id'])
        p['stockQty'] = p['stock']
        p['categoryId'] = str(p.get('category_id')) if p.get('category_id') else None
        if p.get('categoryName'):
            p['category'] = {
                "categoryId": str(p['category_id']),
                "categoryName": p['categoryName'],
                "description": ""
            }
    return jsonify(res)

@app.get("/api/products/<id>")
def get_product(id):
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        query = "SELECT p.*, c.name as categoryName FROM products p LEFT JOIN categories c ON p.category_id = c.category_id WHERE p.product_id = %s"
        execute_query(cursor, query, (id,))
        p = fetch_one(cursor)
        if not p: return jsonify({"error": "Not found"}), 404
        p = format_row(p)
        p['productId'] = str(p['product_id'])
        p['stockQty'] = p['stock']
        return jsonify(p)

@app.post("/api/products")
def create_product():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    price = data.get('price')
    stockQty = data.get('stockQty')
    category_id = data.get('categoryId')

    if not name or price is None or stockQty is None or category_id is None or str(category_id).strip() == '':
        return jsonify({"error": "Missing required product fields"}), 400

    try:
        price = float(price)
        stockQty = int(stockQty)
    except Exception:
        return jsonify({"error": "Invalid price or stockQty"}), 400

    if price <= 0 or stockQty < 0:
        return jsonify({"error": "Invalid price or stockQty"}), 400

    with db_connection() as conn:
        cursor = conn.cursor()
        query = "INSERT INTO products (name, price, stock, category_id) VALUES (%s, %s, %s, %s)"
        execute_query(cursor, query, (name, price, stockQty, category_id))
        conn.commit()
        product_id = cursor.lastrowid
        # Log audit (always log, with or without auth)
        auth = get_auth_payload()
        admin_username = auth.get('username') if auth else 'system_admin'
        print(f"[AUDIT] Logging action 'created' for product {product_id} by {admin_username}")
        log_admin_action(admin_username, product_id, 'created')
        return jsonify({"ok": True, "id": product_id})

@app.put("/api/products/<id>")
def update_product(id):
    data = request.get_json()
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        
        # Build dynamic update query for partial updates
        updates = []
        args = []
        
        if 'name' in data:
            name = (data.get('name') or '').strip()
            if not name:
                return jsonify({"error": "Product name cannot be empty"}), 400
            updates.append("name=%s")
            args.append(name)
        if 'price' in data:
            try:
                price = float(data['price'])
            except Exception:
                return jsonify({"error": "Invalid price"}), 400
            if price <= 0:
                return jsonify({"error": "Price must be greater than zero"}), 400
            updates.append("price=%s")
            args.append(price)
        if 'stockQty' in data:
            try:
                stockQty = int(data['stockQty'])
            except Exception:
                return jsonify({"error": "Invalid stock quantity"}), 400
            if stockQty < 0:
                return jsonify({"error": "Stock quantity cannot be negative"}), 400
            updates.append("stock=%s")
            args.append(stockQty)
        if 'categoryId' in data:
            category_id = data.get('categoryId')
            if category_id == '':
                category_id = None
            updates.append("category_id=%s")
            args.append(category_id)
        
        if not updates:
            return jsonify({"error": "No fields to update"}), 400
        
        args.append(id)
        query = f"UPDATE products SET {', '.join(updates)} WHERE product_id=%s"
        execute_query(cursor, query, args)
        conn.commit()
        
        # Log audit (always log, with or without auth)
        auth = get_auth_payload()
        admin_username = auth.get('username') if auth else 'system_admin'
        is_restock = len(data) == 1 and 'stockQty' in data
        action = 'restocked' if is_restock else 'updated'
        print(f"[AUDIT] Logging action '{action}' for product {id} by {admin_username}")
        log_admin_action(admin_username, int(id), action)
        
        # Fetch and return updated product
        query_fetch = "SELECT p.*, c.name as categoryName FROM products p LEFT JOIN categories c ON p.category_id = c.category_id WHERE p.product_id = %s"
        execute_query(cursor, query_fetch, (id,))
        p = fetch_one(cursor)
        if p:
            p = format_row(p)
            p['productId'] = str(p['product_id'])
            p['stockQty'] = p['stock']
            if p.get('categoryName'):
                p['category'] = {
                    "categoryId": str(p['category_id']),
                    "categoryName": p['categoryName'],
                    "description": ""
                }
            return jsonify(p)
        return jsonify({"ok": True})

@app.delete("/api/products/<id>")
def delete_product(id):
    with db_connection() as conn:
        cursor = conn.cursor()
        query = "DELETE FROM products WHERE product_id = %s"
        execute_query(cursor, query, (id,))
        conn.commit()
        # Log audit (always log, with or without auth)
        auth = get_auth_payload()
        admin_username = auth.get('username') if auth else 'system_admin'
        print(f"[AUDIT] Logging action 'deleted' for product {id} by {admin_username}")
        log_admin_action(admin_username, int(id), 'deleted')
        return jsonify({"ok": True})

# --- Category Routes ---
@app.get("/api/categories")
def get_categories():
    query = "SELECT category_id as categoryId, name as categoryName, description FROM categories"
    return jsonify(paginate(query, request.args))

# --- Order Routes ---
@app.get("/api/orders")
def get_orders():
    customer_id = request.args.get('customerId')
    search = request.args.get('search')
    query = """
        SELECT
            o.*,
            COALESCE(SUM(oi.qty), 0) AS item_count,
            COALESCE(SUM(oi.qty * p.price), 0) AS total_amount
        FROM orders o
        LEFT JOIN order_items oi ON oi.order_id = o.order_id
        LEFT JOIN products p ON p.product_id = oi.product_id
        WHERE 1=1
    """
    args = []
    
    if customer_id:
        with db_connection() as conn:
            customer_cursor = conn.cursor()
            if DB_TYPE == "mysql": customer_cursor = conn.cursor(dictionary=True)
            customer_username = resolve_customer_username(customer_cursor, customer_id)
        query += " AND (o.customer_name = %s"
        args.append(customer_id)
        if customer_username and customer_username != customer_id:
            query += " OR o.customer_name = %s"
            args.append(customer_username)
        query += ")"
        
    status = request.args.get('status')
    if status:
        query += " AND LOWER(o.status) = %s"
        args.append(normalize_order_status(status))

    if search:
        query += " AND (CAST(o.order_id AS CHAR) LIKE %s OR o.customer_name LIKE %s)"
        args.extend([f"%{search}%", f"%{search}%"])

    query += " GROUP BY o.order_id ORDER BY o.datetime DESC"
    res = paginate(query, request.args, args)
    for o in res['data']:
        o['orderId'] = str(o['order_id'])
        o['customerId'] = o['customer_name']
        o['status'] = normalize_order_status(o.get('status'))
        o['itemCount'] = int(o.get('item_count') or 0)
        o['totalAmount'] = float(o.get('total_amount') or 0)
    return jsonify(res)

@app.post("/api/orders")
def create_order():
    data = request.get_json()
    customer_id = data.get('customerId')
    items = data.get('items', [])
    
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        
        # Validate that all items have sufficient stock before creating order
        for item in items:
            query_check = "SELECT stock FROM products WHERE product_id = %s"
            execute_query(cursor, query_check, (item['productId'],))
            result = fetch_one(cursor)
            
            if not result:
                return jsonify({"error": f"Product {item['productId']} not found"}), 404
            
            available_stock = result['stock'] if isinstance(result, dict) else result[0]
            if item['quantity'] > available_stock:
                return jsonify({
                    "error": f"Insufficient stock for product {item['productId']}",
                    "available": available_stock,
                    "requested": item['quantity']
                }), 400
        
        customer_username = resolve_customer_username(cursor, customer_id)
        order_customer_name = customer_username or customer_id

        # Create order
        query_order = "INSERT INTO orders (customer_name, status) VALUES (%s, %s)"
        execute_query(cursor, query_order, (order_customer_name, normalize_order_status('pending')))
        order_id = cursor.lastrowid
        
        # Add items
        for item in items:
            query_item = "INSERT INTO order_items (order_id, product_id, qty) VALUES (%s, %s, %s)"
            execute_query(cursor, query_item, (order_id, item['productId'], item['quantity']))
            
            # Update stock
            query_stock = "UPDATE products SET stock = stock - %s WHERE product_id = %s"
            execute_query(cursor, query_stock, (item['quantity'], item['productId']))
            
        conn.commit()
        return jsonify({"ok": True, "orderId": str(order_id)})

# --- Admin/Customer Management ---
@app.get("/api/customers")
def get_customers():
    query = "SELECT * FROM customer_accounts"
    res = paginate(query, request.args)
    res['data'] = [map_customer_for_frontend(c) for c in res['data']]
    return jsonify(res)

@app.get("/api/admins")
def get_admins():
    query = "SELECT * FROM admin_accounts"
    res = paginate(query, request.args)
    res['data'] = [map_admin_for_frontend(a) for a in res['data']]
    return jsonify(res)

# --- Audit Log ---
@app.get("/api/admin-products/audit")
def get_audit_log():
    query = """
        SELECT ap.*, a.first_name || ' ' || a.last_name as adminName, p.name as productName 
        FROM admin_products ap
        LEFT JOIN admin_accounts a ON ap.admin_username = a.username
        LEFT JOIN products p ON ap.product_id = p.product_id
        WHERE 1=1
    """
    if DB_TYPE == "mysql":
        query = """
            SELECT ap.*, CONCAT(a.first_name, ' ', a.last_name) as adminName, p.name as productName 
            FROM admin_products ap
            LEFT JOIN admin_accounts a ON ap.admin_username = a.username
            LEFT JOIN products p ON ap.product_id = p.product_id
            WHERE 1=1
        """
    
    args = []
    search = request.args.get('search')
    if search:
        query += " AND (a.first_name LIKE %s OR a.last_name LIKE %s OR p.name LIKE %s)"
        args.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    
    action = request.args.get('action')
    if action:
        query += " AND ap.action = %s"
        args.append(action)
        
    res = paginate(query, request.args, args)
    # Map fields for frontend (actionDatetime)
    for r in res['data']:
        r['actionDatetime'] = r['action_datetime']
        r['adminId'] = r['admin_username']
        r['productId'] = str(r['product_id'])
    return jsonify(res)

# --- Analytics ---
@app.get("/api/analytics/sales")
def get_sales_analytics():
    period = request.args.get("period", "day")
    bucket = period_bucket_expr(period, "o.datetime")
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        query = f"""
            SELECT {bucket} as date, COALESCE(SUM(oi.qty * p.price), 0) as revenue, COUNT(DISTINCT o.order_id) as orders
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN products p ON p.product_id = oi.product_id
            WHERE o.status <> 'cancelled'
            GROUP BY {bucket}
            ORDER BY date DESC
            LIMIT 30
        """
        execute_query(cursor, query)
        rows = fetch_all(cursor)
        return jsonify([format_row(r) for r in rows] if rows else [
            {"date": "2024-01-01", "revenue": 1000, "orders": 5},
            {"date": "2024-01-02", "revenue": 1500, "orders": 8}
        ])

@app.get("/api/analytics/top-products")
def get_top_products():
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        query = """
            SELECT p.product_id as productId, p.name, SUM(oi.qty) as quantity, COALESCE(SUM(oi.qty * p.price), 0) as revenue 
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            GROUP BY p.product_id, p.name
            ORDER BY revenue DESC
            LIMIT 5
        """
        execute_query(cursor, query)
        rows = fetch_all(cursor)
        return jsonify([format_row(r) for r in rows] if rows else [
            {"name": "Keyboard", "value": 150},
            {"name": "Mouse", "value": 120}
        ])

@app.get("/api/analytics/category-performance")
def get_category_performance():
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        query = """
            SELECT c.category_id as categoryId, c.name as categoryName, COALESCE(SUM(oi.qty * p.price), 0) as revenue, SUM(oi.qty) as units 
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            JOIN categories c ON p.category_id = c.category_id
            GROUP BY c.category_id, c.name
        """
        execute_query(cursor, query)
        rows = fetch_all(cursor)
        return jsonify([format_row(r) for r in rows] if rows else [
            {"category": "Electronics", "sales": 4500, "orders": 25}
        ])

@app.get("/api/analytics/low-stock")
def get_low_stock():
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        query = "SELECT product_id FROM products WHERE stock < 10"
        execute_query(cursor, query)
        rows = fetch_all(cursor)
        return jsonify([str(r['product_id']) for r in rows])

@app.get("/api/analytics/demand-forecast")
def get_demand_forecast():
    period = request.args.get("period", "day")
    product_id = request.args.get("productId")
    if not product_id:
        return jsonify([])

    window_days = 30 if period == "day" else (84 if period == "week" else 180)
    horizon = 30 if period == "day" else 16
    step_days = 1 if period == "day" else 7

    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)

        execute_query(
            cursor,
            """
                SELECT COALESCE(SUM(oi.qty), 0) AS qty
                FROM order_items oi
                JOIN orders o ON o.order_id = oi.order_id
                WHERE oi.product_id = %s
                  AND o.status <> 'cancelled'
                  AND o.datetime >= datetime('now', ?)
            """ if DB_TYPE == "sqlite" else
            """
                SELECT COALESCE(SUM(oi.qty), 0) AS qty
                FROM order_items oi
                JOIN orders o ON o.order_id = oi.order_id
                WHERE oi.product_id = %s
                  AND o.status <> 'cancelled'
                  AND o.datetime >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """,
            (product_id, f"-{window_days} day") if DB_TYPE == "sqlite" else (product_id, window_days),
        )
        qty_row = fetch_one(cursor) or {"qty": 0}

    avg_daily = float(qty_row.get("qty") or 0) / max(window_days, 1)
    if avg_daily <= 0:
        avg_daily = 1.0

    points = []
    start = datetime.date.today()
    for i in range(horizon):
        point_date = start + datetime.timedelta(days=i * step_days)
        trend_factor = 1 + (i / max(horizon, 1)) * 0.08
        demand = round(avg_daily * step_days * trend_factor, 2)
        points.append({
            "date": point_date.isoformat(),
            "demand": demand,
            "lower": round(demand * 0.85, 2),
            "upper": round(demand * 1.20, 2),
        })
    return jsonify(points)

@app.get("/api/analytics/recommendations")
def get_recommendations_v1():
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)

        execute_query(cursor, "SELECT COUNT(DISTINCT order_id) AS total_orders FROM order_items")
        total_orders_row = fetch_one(cursor) or {"total_orders": 0}
        total_orders = int(total_orders_row.get("total_orders") or 0)
        if total_orders == 0:
            return jsonify([])

        execute_query(
            cursor,
            """
                SELECT product_id, COUNT(DISTINCT order_id) AS orders_count
                FROM order_items
                GROUP BY product_id
            """
        )
        by_product = {str(r["product_id"]): int(r["orders_count"]) for r in fetch_all(cursor)}

        execute_query(
            cursor,
            """
                SELECT
                    a.product_id AS productAId,
                    pa.name AS productAName,
                    b.product_id AS productBId,
                    pb.name AS productBName,
                    COUNT(DISTINCT a.order_id) AS pairOrders
                FROM order_items a
                JOIN order_items b ON a.order_id = b.order_id AND a.product_id < b.product_id
                JOIN products pa ON pa.product_id = a.product_id
                JOIN products pb ON pb.product_id = b.product_id
                GROUP BY a.product_id, pa.name, b.product_id, pb.name
                ORDER BY pairOrders DESC
                LIMIT 25
            """
        )
        pairs = fetch_all(cursor)

    result = []
    for p in pairs:
        pair_orders = int(p.get("pairOrders") or 0)
        a_id = str(p["productAId"])
        support = round((pair_orders / total_orders) * 100, 2)
        confidence = round((pair_orders / max(by_product.get(a_id, 1), 1)) * 100, 2)
        result.append({
            "productAId": a_id,
            "productAName": p.get("productAName"),
            "productBId": str(p["productBId"]),
            "productBName": p.get("productBName"),
            "supportPct": support,
            "confidencePct": confidence,
        })

    return jsonify(result[:10])

@app.get("/api/analytics/recommendations-ids")
def get_recommendations_ids():
    customer_id = request.args.get("customerId")
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)

        recommendations = []
        if customer_id:
            customer_username = resolve_customer_username(cursor, customer_id)
            execute_query(
                cursor,
                """
                    SELECT DISTINCT oi.product_id
                    FROM orders o
                    JOIN order_items oi ON oi.order_id = o.order_id
                    WHERE o.customer_name = %s OR o.customer_name = %s
                """,
                (customer_id, customer_username or customer_id),
            )
            purchased = [str(r["product_id"]) for r in fetch_all(cursor)]

            if purchased:
                placeholders = ", ".join(["%s"] * len(purchased))
                query = f"""
                    SELECT oi2.product_id, COUNT(*) AS score
                    FROM orders o
                    JOIN order_items oi1 ON oi1.order_id = o.order_id
                    JOIN order_items oi2 ON oi2.order_id = o.order_id AND oi2.product_id <> oi1.product_id
                    WHERE (o.customer_name = %s OR o.customer_name = %s)
                      AND oi1.product_id IN ({placeholders})
                    GROUP BY oi2.product_id
                    ORDER BY score DESC
                    LIMIT 10
                """
                execute_query(cursor, query, (customer_id, customer_username or customer_id, *purchased))
                recommendations = [str(r["product_id"]) for r in fetch_all(cursor) if str(r["product_id"]) not in purchased]

        if not recommendations:
            execute_query(
                cursor,
                """
                    SELECT oi.product_id, SUM(oi.qty) AS sold
                    FROM order_items oi
                    GROUP BY oi.product_id
                    ORDER BY sold DESC
                    LIMIT 10
                """
            )
            recommendations = [str(r["product_id"]) for r in fetch_all(cursor)]

        return jsonify({"customerId": customer_id, "productIds": recommendations[:10]})

@app.get("/api/analytics/low-stock-forecast")
def get_low_stock_forecast():
    period = request.args.get("period", "day")
    window_days = 30 if period == "day" else (84 if period == "week" else 180)

    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        query = """
            SELECT
                p.product_id as productId,
                p.name,
                p.stock as stockQty,
                COALESCE(SUM(CASE WHEN o.order_id IS NOT NULL THEN oi.qty ELSE 0 END), 0) as soldQty
            FROM products p
            LEFT JOIN order_items oi ON oi.product_id = p.product_id
            LEFT JOIN orders o ON o.order_id = oi.order_id
              AND o.status <> 'cancelled'
              AND o.datetime >= datetime('now', ?)
            WHERE p.stock < 20
            GROUP BY p.product_id, p.name, p.stock
        """ if DB_TYPE == "sqlite" else """
            SELECT
                p.product_id as productId,
                p.name,
                p.stock as stockQty,
                COALESCE(SUM(CASE WHEN o.status <> 'cancelled' AND o.datetime >= DATE_SUB(NOW(), INTERVAL %s DAY) THEN oi.qty ELSE 0 END), 0) as soldQty
            FROM products p
            LEFT JOIN order_items oi ON oi.product_id = p.product_id
            LEFT JOIN orders o ON o.order_id = oi.order_id
            WHERE p.stock < 20
            GROUP BY p.product_id, p.name, p.stock
        """
        execute_query(cursor, query, (f"-{window_days} day",) if DB_TYPE == "sqlite" else (window_days,))
        rows = fetch_all(cursor)
        data = []
        for r in rows:
            stock_qty = float(r.get('stockQty') or 0)
            sold_qty = float(r.get('soldQty') or 0)
            avg_daily = round(sold_qty / max(window_days, 1), 2)
            if avg_daily <= 0:
                avg_daily = 0.1
            r['avgDailySales'] = avg_daily
            r['daysRemaining'] = round(stock_qty / avg_daily, 1)
            data.append(format_row(r))
        data.sort(key=lambda x: x.get('daysRemaining', 9999))
        return jsonify(data)

# --- Admin/Customer/Category Management ---
@app.post("/api/categories")
def create_category():
    data = request.get_json()
    with db_connection() as conn:
        cursor = conn.cursor()
        query = "INSERT INTO categories (name, description) VALUES (%s, %s)"
        execute_query(cursor, query, (data['categoryName'], data['description']))
        conn.commit()
        return jsonify({"ok": True, "id": cursor.lastrowid})

@app.put("/api/categories/<id>")
def update_category(id):
    data = request.get_json()
    with db_connection() as conn:
        cursor = conn.cursor()
        query = "UPDATE categories SET name=%s, description=%s WHERE category_id=%s"
        execute_query(cursor, query, (data['categoryName'], data['description'], id))
        conn.commit()
        return jsonify({"ok": True})

@app.delete("/api/categories/<id>")
def delete_category(id):
    with db_connection() as conn:
        cursor = conn.cursor()
        execute_query(cursor, "DELETE FROM categories WHERE category_id = %s", (id,))
        conn.commit()
        return jsonify({"ok": True})

@app.get("/api/admins/<id>")
def get_admin_detail(id):
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        query = "SELECT * FROM admin_accounts WHERE admin_id = %s OR username = %s"
        execute_query(cursor, query, (id, id))
        a = fetch_one(cursor)
        if not a: return jsonify({"error": "Not found"}), 404
        return jsonify(map_admin_for_frontend(a))

@app.post("/api/admins")
def create_admin():
    payload = get_auth_payload()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    current_db_role = str(payload.get('db_role') or '')
    if current_db_role != 'SUPER_ADMIN':
        return jsonify({"error": "Only Super Admin can create admin accounts"}), 403

    data = request.get_json() or {}
    first_name = data.get('firstName')
    last_name = data.get('lastName')
    email = data.get('email')
    password = data.get('password')
    role = data.get('role')
    phone = data.get('phone')

    if not all([first_name, last_name, email, password, role]):
        return jsonify({"error": "Missing fields"}), 400

    with db_connection() as conn:
        cursor = conn.cursor()
        username = generate_username_by_formula(cursor, "admin_accounts", first_name, "ADM")
        normalized_role = normalize_admin_role(role)
        password_hash = hash_password(password)
        query = "INSERT INTO admin_accounts (username, password, first_name, last_name, email, phone, role) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        execute_query(
            cursor,
            query,
            (
                username,
                password_hash,
                first_name,
                last_name,
                email,
                phone,
                normalized_role,
            )
        )
        conn.commit()
        admin_id = cursor.lastrowid

        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        execute_query(cursor, "SELECT * FROM admin_accounts WHERE admin_id = %s", (admin_id,))
        created = fetch_one(cursor)

        if created:
            target_email = created['email']
            target_first_name = created['first_name']
            subject = "Your IIMS Admin Username"
            body = f"Hello {target_first_name},\n\nYour admin account has been created successfully.\nYour unique username for logging in is: {username}\n\nPlease keep this email safe.\nIIMS Team"
            email_sent = send_email(target_email, subject, body)
        else:
            email_sent = False

        response = map_admin_for_frontend(created)
        if not email_sent:
            response["warning"] = "Admin created, but the notification email could not be sent. Check SMTP settings."

        return jsonify(response)

@app.put("/api/admins/<id>")
def update_admin(id):
    data = request.get_json() or {}
    payload = get_auth_payload()
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    current_db_role = str(payload.get('db_role') or '')
    is_super_admin = current_db_role == 'SUPER_ADMIN' or current_db_role.lower() in ['super admin', 'super_admin']

    if 'isActive' in data and not is_super_admin:
        return jsonify({"error": "Only Super Admin can deactivate or activate admin accounts"}), 403

    if 'role' in data and normalize_admin_role(data['role']) == 'SUPER_ADMIN' and not is_super_admin:
        return jsonify({"error": "Only Super Admin can promote another admin to Super Admin"}), 403

    field_map = {
        "firstName": "first_name",
        "lastName": "last_name",
        "email": "email",
        "role": "role",
        "isActive": "is_active",
        "phone": "phone",
    }

    updates = []
    values = []
    for key, column in field_map.items():
        if key not in data:
            continue
        value = data[key]
        if key == "role":
            value = normalize_admin_role(value)
        if key == "isActive":
            value = 1 if value else 0
        updates.append(f"{column}=%s")
        values.append(value)

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    with db_connection() as conn:
        cursor = conn.cursor()
        # Fetch old data before update
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        execute_query(cursor, "SELECT * FROM admin_accounts WHERE admin_id = %s", (id,))
        old_admin = fetch_one(cursor)
        if not old_admin:
            return jsonify({"error": "Admin not found"}), 404

        query = f"UPDATE admin_accounts SET {', '.join(updates)} WHERE admin_id=%s"
        execute_query(cursor, query, (*values, id))
        conn.commit()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        execute_query(cursor, "SELECT * FROM admin_accounts WHERE admin_id = %s", (id,))
        updated = fetch_one(cursor)

        # Check if role changed
        old_role = old_admin.get('role')
        new_role = updated.get('role')
        if old_role != new_role and 'role' in data:
            target_email = updated['email']
            target_first_name = updated['first_name']
            subject = "Your Admin Role Has Been Updated"
            body = f"Hello {target_first_name},\n\nYour admin role has been changed to: {display_admin_role(new_role)}\n\nIf you have any questions, please contact the Super Admin.\n\nIIMS Team"
            email_sent = send_email(target_email, subject, body)
            if not email_sent:
                print(f"Warning: Failed to send role change email to {target_email}")

        # Check if status changed
        if 'isActive' in data:
            old_active = bool(old_admin.get('is_active') or 0)
            new_active = bool(updated.get('is_active') or 0)
            if old_active != new_active:
                target_email = updated['email']
                target_first_name = updated['first_name']
                status_text = 'activated' if new_active else 'deactivated'
                subject = "Your Admin Account Status Has Changed"
                body = f"Hello {target_first_name},\n\nYour admin account has been {status_text}.\n\nIf you have any questions, please contact the Super Admin.\n\nIIMS Team"
                email_sent = send_email(target_email, subject, body)
                if not email_sent:
                    print(f"Warning: Failed to send status email to {target_email}")

        return jsonify(map_admin_for_frontend(updated))

@app.get("/api/customers/<id>")
def get_customer_detail(id):
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        query = "SELECT * FROM customer_accounts WHERE customer_id = %s OR username = %s"
        execute_query(cursor, query, (id, id))
        c = fetch_one(cursor)
        if not c: return jsonify({"error": "Not found"}), 404
        return jsonify(map_customer_for_frontend(c))

@app.put("/api/customers/<id>")
def update_customer(id):
    data = request.get_json()
    with db_connection() as conn:
        cursor = conn.cursor()
        query = "UPDATE customer_accounts SET first_name=%s, last_name=%s, email=%s WHERE customer_id=%s"
        execute_query(cursor, query, (data['firstName'], data['lastName'], data['email'], id))
        conn.commit()
        return jsonify({"ok": True})

@app.patch("/api/customers/<id>/status")
def patch_customer_status(id):
    data = request.get_json()
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        execute_query(cursor, "SELECT * FROM customer_accounts WHERE customer_id = %s", (id,))
        old_customer = fetch_one(cursor)
        if not old_customer:
            return jsonify({"error": "Customer not found"}), 404

        old_active = bool(old_customer.get('is_active') or 0)
        new_active = bool(data.get('isActive'))

        query = "UPDATE customer_accounts SET is_active=%s WHERE customer_id=%s"
        execute_query(cursor, query, (1 if new_active else 0, id))
        conn.commit()

        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        execute_query(cursor, "SELECT * FROM customer_accounts WHERE customer_id = %s", (id,))
        updated = fetch_one(cursor)

        if old_active != new_active:
            target_email = updated['email']
            target_first_name = updated['first_name']
            status_text = 'activated' if new_active else 'deactivated'
            subject = "Your Customer Account Status Has Changed"
            body = f"Hello {target_first_name},\n\nYour customer account has been {status_text}.\n\nIf you have any questions, please contact support.\n\nIIMS Team"
            email_sent = send_email(target_email, subject, body)
            if not email_sent:
                print(f"Warning: Failed to send customer status email to {target_email}")

        return jsonify({"ok": True})

@app.get("/api/orders/<id>")
def get_order_detail(id):
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        query = """
            SELECT
                o.*,
                COALESCE(SUM(oi.qty), 0) AS item_count,
                COALESCE(SUM(oi.qty * p.price), 0) AS total_amount
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN products p ON p.product_id = oi.product_id
            WHERE o.order_id = %s
            GROUP BY o.order_id
        """
        execute_query(cursor, query, (id,))
        o = fetch_one(cursor)
        if not o: return jsonify({"error": "Not found"}), 404
        o = format_row(o)
        o['orderId'] = str(o['order_id'])
        o['customerId'] = o['customer_name']
        o['status'] = normalize_order_status(o.get('status'))
        o['itemCount'] = int(o.get('item_count') or 0)
        o['totalAmount'] = float(o.get('total_amount') or 0)
        o['items'] = get_order_items_with_products(cursor, id)
        return jsonify(o)

@app.put("/api/orders/<id>")
def update_order(id):
    data = request.get_json() or {}
    auth = get_auth_payload()
    current_admin_username = auth.get('username') if auth else None
    updates = []
    values = []

    if 'status' in data:
        normalized_status = normalize_order_status(data['status'])
        updates.append("status=%s")
        values.append(normalized_status)
        if normalized_status == 'pending':
            updates.append("processed_by=%s")
            values.append(None)
        elif 'processedBy' not in data and current_admin_username:
            updates.append("processed_by=%s")
            values.append(current_admin_username)
    if 'processedBy' in data:
        with db_connection() as conn:
            admin_cursor = conn.cursor()
            if DB_TYPE == "mysql": admin_cursor = conn.cursor(dictionary=True)
            admin_username = resolve_admin_username(admin_cursor, data['processedBy'])
        updates.append("processed_by=%s")
        values.append(admin_username or data['processedBy'])

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    with db_connection() as conn:
        cursor = conn.cursor()
        query = f"UPDATE orders SET {', '.join(updates)} WHERE order_id=%s"
        execute_query(cursor, query, (*values, id))
        conn.commit()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        execute_query(
            cursor,
            """
                SELECT
                    o.*,
                    COALESCE(SUM(oi.qty), 0) AS item_count,
                    COALESCE(SUM(oi.qty * p.price), 0) AS total_amount
                FROM orders o
                LEFT JOIN order_items oi ON oi.order_id = o.order_id
                LEFT JOIN products p ON p.product_id = oi.product_id
                WHERE o.order_id = %s
                GROUP BY o.order_id
            """,
            (id,),
        )
        updated = fetch_one(cursor)
        if not updated:
            return jsonify({"error": "Not found"}), 404
        updated = format_row(updated)
        updated["orderId"] = str(updated["order_id"])
        updated["customerId"] = updated["customer_name"]
        updated["status"] = normalize_order_status(updated.get("status"))
        updated["itemCount"] = int(updated.get("item_count") or 0)
        updated["totalAmount"] = float(updated.get("total_amount") or 0)
        return jsonify(updated)

@app.patch("/api/orders/<id>/status")
def patch_order_status(id):
    data = request.get_json()
    auth = get_auth_payload()
    current_admin_username = auth.get('username') if auth else None
    normalized_status = normalize_order_status(data.get('status'))
    with db_connection() as conn:
        cursor = conn.cursor()
        if normalized_status == 'pending':
            query = "UPDATE orders SET status=%s, processed_by=NULL WHERE order_id=%s"
            execute_query(cursor, query, (normalized_status, id))
        elif current_admin_username:
            query = "UPDATE orders SET status=%s, processed_by=%s WHERE order_id=%s"
            execute_query(cursor, query, (normalized_status, current_admin_username, id))
        else:
            query = "UPDATE orders SET status=%s WHERE order_id=%s"
            execute_query(cursor, query, (normalized_status, id))
        conn.commit()
        return jsonify({"ok": True})

@app.get("/api/orders/<id>/items")
def get_order_items(id):
    with db_connection() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)
        return jsonify(get_order_items_with_products(cursor, id))

# --- Static Files & SPA Routing ---
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(app.static_folder, 'index.html')

# --- DB Init ---
def parse_sql_script(script_text):
    statements = []
    delimiter = ";"
    buffer = []
    for raw_line in script_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("--"): continue
        if stripped.upper().startswith("DELIMITER"):
            parts = stripped.split(None, 1)
            delimiter = parts[1] if len(parts) > 1 else ";"
            continue
        buffer.append(raw_line)
        if raw_line.rstrip().endswith(delimiter):
            statement = "\n".join(buffer)
            statement = statement[: statement.rfind(delimiter)].strip()
            if statement: statements.append(statement)
            buffer = []
    return statements

def init_db():
    try:
        if DB_TYPE == "mysql":
            try:
                # Try to create database using a generic connection first
                conn = mysql.connector.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    user=DB_USER,
                    password=DB_PASSWORD,
                    connection_timeout=DB_TIMEOUT
                )
                cursor = conn.cursor()
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Warning: Could not create database via MySQL: {e}")

        if os.path.exists(SQL_PATH):
            with open(SQL_PATH, "r", encoding="utf-8") as f:
                statements = parse_sql_script(f.read())
            
            with db_connection() as conn:
                cursor = conn.cursor()
                for s in statements:
                    try:
                        # Skip MySQL specific administrative commands
                        s_upper = s.upper().strip()
                        if any(x in s_upper for x in ["CREATE USER", "GRANT ALL", "FLUSH PRIVILEGES", "USE ", "DELIMITER"]):
                            continue
                        
                        # Handle SQLite specific adjustments
                        if DB_TYPE == "sqlite":
                            # Skip database creation
                            if "CREATE DATABASE" in s_upper: continue
                            
                            # SQLite requires INTEGER PRIMARY KEY AUTOINCREMENT for auto-inc
                            s = s.replace("INT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                            s = s.replace("INT AUTO_INCREMENT", "INTEGER PRIMARY KEY AUTOINCREMENT")
                            s = s.replace("INTEGER AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                            s = s.replace("AUTO_INCREMENT", "AUTOINCREMENT")
                            
                            s = s.replace("INT ", "INTEGER ")
                            s = s.replace("TINYINT(1)", "INTEGER")
                            s = s.replace("DECIMAL(10, 2)", "REAL")
                            s = s.replace("DATETIME DEFAULT CURRENT_TIMESTAMP", "DATETIME DEFAULT (datetime('now','localtime'))")
                            s = s.replace(" UNSIGNED", "")
                            s = s.replace("INSERT IGNORE", "INSERT OR IGNORE")
                            
                            # SQLite doesn't like some MySQL syntax in CREATE TABLE
                            if "ENGINE=" in s.upper():
                                s = s[:s.upper().find("ENGINE=")]
                            
                            # SQLite doesn't like ALTER TABLE AUTOINCREMENT
                            if "ALTER TABLE" in s.upper() and ("AUTOINCREMENT" in s.upper() or "AUTO_INCREMENT" in s.upper()):
                                continue
                        
                        # Fix for MySQL connector and triggers
                        if "CREATE TRIGGER" in s_upper: continue
                        
                        cursor.execute(s)
                    except Exception as e:
                        if "already exists" not in str(e).lower():
                            print(f"Error executing statement: {e}")
                conn.commit()
                
                # Seed categories if empty
                cursor = conn.cursor()
                execute_query(cursor, "SELECT COUNT(*) as count FROM categories")
                count = fetch_one(cursor)
                if count and count['count'] == 0:
                    print("Seeding initial categories...")
                    categories_data = [
                        ('Electronics', 'Electronic devices and accessories'),
                        ('Peripherals', 'Computer peripherals and input devices'),
                        ('Storage', 'Storage devices and drives'),
                        ('Networking', 'Network devices and accessories'),
                        ('Office', 'Office supplies and equipment')
                    ]
                    for name, desc in categories_data:
                        execute_query(cursor, "INSERT INTO categories (name, description) VALUES (%s, %s)", (name, desc))
                    conn.commit()

                # Make sure password columns can safely store hashed passwords.
                ensure_password_column_width(cursor)
                conn.commit()
                
                # Seed super admin if not exists
                execute_query(cursor, "SELECT COUNT(*) as count FROM admin_accounts WHERE email = %s", ("superadmin@ims.com",))
                count = fetch_one(cursor)
                if count and count['count'] == 0:
                    print("Seeding super admin...")
                    seed_password = hash_password("admin123")
                    execute_query(cursor, "INSERT INTO admin_accounts (username, password, first_name, last_name, email, role) VALUES (%s, %s, %s, %s, %s, %s)", 
                                  ("superadmin", seed_password, "Super", "Admin", "superadmin@ims.com", "SUPER_ADMIN"))
                    conn.commit()
                
                # Seed products if empty
                execute_query(cursor, "SELECT COUNT(*) as count FROM products")
                count = fetch_one(cursor)
                if count and count['count'] == 0:
                    print("Seeding initial products...")
                    products_data = [
                        (101, 'Keyboard', 1500, 20, 2),
                        (102, 'Mouse', 800, 35, 2),
                        (103, 'Monitor', 22000, 12, 1),
                        (104, 'USBDrive', 1200, 50, 3),
                        (105, 'Router', 5500, 8, 4),
                        (106, 'Webcam', 3200, 15, 1),
                        (107, 'Headset', 2800, 18, 1),
                        (108, 'Desk Lamp', 950, 30, 5)
                    ]
                    for pid, name, price, stock, cat_id in products_data:
                        execute_query(cursor, "INSERT INTO products (product_id, name, price, stock, category_id) VALUES (%s, %s, %s, %s, %s)", (pid, name, price, stock, cat_id))
                    conn.commit()
                
                # Normalize super-admin seed and avoid dummy admin@example.com rows.
                cursor = conn.cursor()
                if DB_TYPE == "mysql": cursor = conn.cursor(dictionary=True)

                # Remove legacy dummy admin seeded by older logic.
                execute_query(
                    cursor,
                    "DELETE FROM admin_accounts WHERE email = %s AND first_name = %s AND last_name = %s",
                    ("admin@example.com", "System", "Administrator")
                )

                # Ensure superadmin@ims.com has a username for login.
                execute_query(
                    cursor,
                    "SELECT admin_id FROM admin_accounts WHERE role = %s AND email = %s AND (username IS NULL OR username = '') LIMIT 1",
                    ("SUPER_ADMIN", SUPER_ADMIN_EMAIL)
                )
                broken_super = fetch_one(cursor)
                if broken_super:
                    execute_query(
                        cursor,
                        "UPDATE admin_accounts SET username = %s WHERE admin_id = %s",
                        (SUPER_ADMIN_USERNAME, broken_super["admin_id"])
                    )

                # Ensure at least one valid super admin exists.
                execute_query(
                    cursor,
                    "SELECT admin_id FROM admin_accounts WHERE role = %s AND username IS NOT NULL AND username <> '' LIMIT 1",
                    ("SUPER_ADMIN",)
                )
                valid_super = fetch_one(cursor)
                if not valid_super:
                    print("Seeding canonical super admin account...")
                    seed_password = hash_password(SUPER_ADMIN_PASSWORD)
                    execute_query(
                        cursor,
                        "INSERT INTO admin_accounts (username, password, first_name, last_name, email, role) VALUES (%s, %s, %s, %s, %s, %s)",
                        (SUPER_ADMIN_USERNAME, seed_password, "Super", "Admin", SUPER_ADMIN_EMAIL, "SUPER_ADMIN")
                    )

                # Migrate any legacy plaintext passwords that already exist in the tables.
                admin_migrated = migrate_legacy_passwords(cursor, "admin_accounts", "admin_id")
                customer_migrated = migrate_legacy_passwords(cursor, "customer_accounts", "customer_id")
                if admin_migrated or customer_migrated:
                    print(f"Migrated plaintext passwords: admin_accounts={admin_migrated}, customer_accounts={customer_migrated}")

                conn.commit()

        print(f"Database ({DB_TYPE}) initialized successfully.")
    except Exception as e:
        print(f"Database initialization failed: {e}")

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
