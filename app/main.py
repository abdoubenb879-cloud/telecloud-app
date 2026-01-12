import sys
import os
import asyncio
import threading
import time
import re
import uuid
import traceback
from datetime import timedelta
from functools import wraps
from collections import defaultdict
from io import BytesIO

# Image processing for thumbnails
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[WARN] Pillow not installed. Thumbnails will be disabled.")

# Fix for Python 3.10+ where get_event_loop() fails if not started
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory, session, redirect, url_for, g
from flask_compress import Compress
from app.config import Config
from app.chunker import Chunker
from app.telegram_client import TelegramCloud, get_bot_client
import hashlib

# Pluggable Database Logic
if Config.MULTI_USER:
    from app.database_cloud import CloudDatabase
    db = CloudDatabase()
    print("[INIT] Multi-User Mode: Cloud Database (Supabase) active.")
else:
    from app.database import Database
    db = Database()
    print("[INIT] Single-User Mode: Local Database active.")

app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')
app.secret_key = Config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=30)

# Auto-generate secret key if not set or default
if not app.secret_key or app.secret_key == 'your-secret-key-here':
    import secrets
    app.secret_key = secrets.token_hex(32)
    print(f"[SECURITY] Generated new secure secret key for this session.")

# ========== SECURITY CONFIGURATION ==========

# Secure session cookies
app.config.update(
    SESSION_COOKIE_SECURE=True,       # Only send cookie over HTTPS
    SESSION_COOKIE_HTTPONLY=True,     # Prevent JavaScript access to cookie
    SESSION_COOKIE_SAMESITE='Lax',    # Protect against CSRF
    WTF_CSRF_ENABLED=True,            # Enable CSRF protection
    WTF_CSRF_TIME_LIMIT=3600,         # CSRF token valid for 1 hour
    MAX_CONTENT_LENGTH=500 * 1024 * 1024,  # 500MB max upload
    COMPRESS_MIMETYPES=['text/html', 'text/css', 'text/javascript', 'application/javascript', 'application/json'],
    COMPRESS_LEVEL=6,                 # Good balance of speed vs compression
    COMPRESS_MIN_SIZE=500,            # Only compress if > 500 bytes
)

# Enable Gzip Compression for ~70% smaller responses
Compress(app)

# CSRF Protection
from flask_wtf.csrf import CSRFProtect, generate_csrf
csrf = CSRFProtect(app)

# Exempt API endpoints from CSRF (they use session auth)
CSRF_EXEMPT_ENDPOINTS = [
    'upload', 'upload_chunk', 'upload_finish', 'delete_file', 
    'generate_share', 'health_check'
]

# Allowed file extensions (security)
ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico',
    'mp3', 'wav', 'ogg', 'm4a', 'flac',
    'mp4', 'mkv', 'avi', 'mov', 'webm', 'wmv',
    'zip', 'rar', '7z', 'tar', 'gz',
    'py', 'js', 'html', 'css', 'json', 'xml', 'csv', 'md'
}

def allowed_file(filename):
    """Check if file extension is allowed."""
    if '.' not in filename:
        return True  # Allow files without extension
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS or len(ALLOWED_EXTENSIONS) == 0

# Input sanitization
try:
    import bleach
    def sanitize_input(text):
        """Sanitize user input to prevent XSS."""
        if text is None:
            return None
        return bleach.clean(str(text), tags=[], strip=True)
except ImportError:
    def sanitize_input(text):
        return text

# Security headers middleware
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Enable XSS filter
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Referrer policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Content Security Policy (permissive for ads)
    response.headers['Content-Security-Policy'] = (
        "default-src 'self' https:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
        "script-src-elem 'self' 'unsafe-inline' https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "font-src 'self' https: data:; "
        "img-src 'self' data: blob: https:; "
        "frame-src 'self' https:; "
        "connect-src 'self' https:; "
        "media-src 'self' blob: https:;"
    )
    return response

# Request logging for security audit
@app.before_request
def log_request():
    """Log requests for security auditing."""
    if request.endpoint not in ['static', 'health_check']:
        ip = get_client_ip()
        print(f"[AUDIT] {request.method} {request.path} - IP: {ip} - User: {session.get('user_id', 'anonymous')}")

# ========== END SECURITY CONFIG ==========

# Enable gzip compression for all responses
Compress(app)

# Rate limiting configuration
RATE_LIMIT = 30  # requests per minute
RATE_WINDOW = 60  # seconds
rate_limit_data = defaultdict(list)

def get_client_ip():
    """Get client IP address, handling proxies."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'

def rate_limit(f):
    """Decorator to rate limit requests per IP."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ip = get_client_ip()
        now = time.time()
        
        # Clean old entries
        rate_limit_data[ip] = [t for t in rate_limit_data[ip] if now - t < RATE_WINDOW]
        
        if len(rate_limit_data[ip]) >= RATE_LIMIT:
            return jsonify({"error": "Rate limit exceeded. Please wait a moment."}), 429
        
        rate_limit_data[ip].append(now)
        return f(*args, **kwargs)
    return decorated_function

@app.after_request
def add_cache_headers(response):
    """Add caching headers for static files."""
    if request.path.startswith('/static/'):
        # Cache static files for 7 days (immutable for versioned assets)
        response.headers['Cache-Control'] = 'public, max-age=604800, immutable'
    elif request.path.startswith('/thumbnail/'):
        # Cache thumbnails for 1 day
        response.headers['Cache-Control'] = 'public, max-age=86400'
    else:
        # Don't cache dynamic content
        response.headers['Cache-Control'] = 'no-store'
    return response

# User-friendly error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', 
                           message="The page you're looking for doesn't exist.",
                           error_code="404"), 404

@app.errorhandler(500)
def internal_error(error):
    print(f"[500 ERROR] {error}")
    # Return 500 explicitly for the error page
    return render_template('error.html', 
                           message="Something went wrong on our end.",
                           error_code="500"), 500

# Health check endpoint for Render
@app.route('/health')
def health_check():
    """Health check endpoint for deployment monitoring."""
    return jsonify({"status": "healthy", "service": "cloudvault"}), 200

@app.route('/debug-user-v3')
def debug_user_lookup():
    """Temporary debug route to check user lookup."""
    u = request.args.get('u', '')
    list_all = request.args.get('all', '0') == '1'
    
    if list_all:
        users = db._request("users", params={"select": "telegram_id,username,name,email", "limit": "10"})
        files = db._request("files", params={"select": "id,filename,user_id", "limit": "10"})
        return jsonify({"users": users, "files": files})

    # Try multiple lookups to see where it might be
    by_email = db._request("users", params={"email": f"eq.{u}", "select": "*"})
    by_username = db._request("users", params={"username": f"eq.{u}", "select": "*"})
    by_name = db._request("users", params={"name": f"eq.{u}", "select": "*"})
    by_telegram_id = db._request("users", params={"telegram_id": f"eq.{u}", "select": "*"})
    
    return jsonify({
        "lookup_value": u,
        "results": {
            "by_email": by_email,
            "by_username": by_username,
            "by_name": by_name,
            "by_telegram_id": by_telegram_id
        }
    })

@app.route('/favicon.ico')
def favicon():
    """Serve favicon to prevent 404 errors."""
    return send_from_directory(app.static_folder, 'logo.png', mimetype='image/png')

@app.errorhandler(Exception)
def handle_exception(error):
    print(f"[UNHANDLED ERROR] {error}")
    return render_template('error.html', 
                           message="An unexpected error occurred. Please try again.",
                           error_code="ERR"), 500

# Storage for pending login clients (Dictionary: {phone: client_object})
pending_logins = {}



@app.route('/')
def index():
    """Main dashboard or login redirect."""
    try:
        if Config.MULTI_USER:
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user_id = session['user_id']
            
            # Multi-User Folders Logic
            folder_id = request.args.get('folder_id')
            current_folder_id = int(folder_id) if folder_id and folder_id != 'None' else None
            
            files = db.list_files(user_id=user_id, parent_id=current_folder_id)
            breadcrumbs = db.get_breadcrumbs(current_folder_id)
            
            storage_name = session.get('storage_name', 'My Cloud Storage')
        else:
            # Single User Logic
            folder_id = request.args.get('folder_id')
            current_folder_id = int(folder_id) if folder_id else None
            
            files = db.list_files(parent_id=current_folder_id)
            breadcrumbs = db.get_breadcrumbs(current_folder_id)
            storage_name = "My Cloud Storage"
            
        render_params = {
            "files": files,
            "storage_name": storage_name,
            "multi_user": Config.MULTI_USER,
            "breadcrumbs": breadcrumbs,
            "current_folder_id": current_folder_id,
            "username": session.get('username', 'User')
        }

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax') == 'true':
            return render_template('dashboard.html', is_ajax=True, **render_params)

        return render_template('dashboard.html', **render_params)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Debug Error: {str(e)}", 500

@app.route('/create_folder', methods=['POST'])
def create_folder():
    name = request.form.get('name')
    parent_id = request.form.get('parent_id')
    parent_id = int(parent_id) if parent_id and parent_id != 'None' else None
    
    if name:
        if Config.MULTI_USER:
            if 'user_id' in session:
                db.create_folder(session['user_id'], name, parent_id)
        else:
            db.create_folder(name, parent_id)
        
    return redirect(url_for('index', folder_id=parent_id if parent_id else None))

@app.route('/create_folder_ajax', methods=['POST'])
@csrf.exempt
def create_folder_ajax():
    """Create folder and return its ID (for folder upload)."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    name = request.form.get('name')
    parent_id = request.form.get('parent_id')
    parent_id = int(parent_id) if parent_id and parent_id != 'None' else None
    
    if not name:
        return jsonify({"error": "Folder name required"}), 400
    
    try:
        user_id = session.get('user_id') if Config.MULTI_USER else 'default_user'
        folder_id = db.get_or_create_folder(user_id, name, parent_id)
        
        return jsonify({"status": "ok", "folder_id": folder_id})
    except Exception as e:
        print(f"[FOLDER] Error creating folder: {e}")
        return jsonify({"error": str(e)}), 500



@app.route('/login', methods=['GET', 'POST'])
@rate_limit
def login():
    """Email/password login with backwards compatibility for username-based accounts."""
    if request.method == 'POST':
        email_or_username = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'
        
        if not email_or_username or not password:
            return render_template('login.html', error="Please enter both email and password.")
        
        # Hash the password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # Try to find user by email first, then by username (backwards compatibility)
        user = db.get_user_by_email(email_or_username)
        if not user:
            # Fallback: check if it's a username from the old system
            user = db.get_user_by_username(email_or_username)
        
        if not user:
            return render_template('login.html', error="No account found. Please sign up.")
        
        # Verify password
        if user.get('password_hash') != password_hash:
            return render_template('login.html', error="Incorrect password.")
        
        user_id = user.get('id', user.get('telegram_id'))
        
        # Set session - use name, username, email prefix, or the raw input as fallback
        display_name = user.get('name') or user.get('username') or email_or_username
        if '@' in display_name:
            display_name = display_name.split('@')[0]  # Use email prefix if it's an email
        
        session['user_id'] = str(user_id)
        session['username'] = display_name
        session['email'] = user.get('email', '')
        
        if remember:
            session.permanent = True
        
        return redirect(url_for('index'))
            
    return render_template('login.html')

@app.route('/register', methods=['POST'])
@rate_limit
def register():
    """Create new user account with email/password."""
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    
    # Validation
    if not name or not email or not password:
        return render_template('login.html', error="Please fill in all fields.")
    
    if password != confirm_password:
        return render_template('login.html', error="Passwords do not match.")
    
    if len(password) < 8:
        return render_template('login.html', error="Password must be at least 8 characters.")
    
    # Check if email already exists
    existing_user = db.get_user_by_email(email)
    if existing_user:
        return render_template('login.html', error="An account with this email already exists.")
    
    # Hash password and create user
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    user_id = db.create_user_with_email(name, email, password_hash)
    
    if not user_id:
        return render_template('login.html', error="Failed to create account. Please try again.")
    
    # Auto-login after registration
    session['user_id'] = str(user_id)
    session['username'] = name
    session['email'] = email
    
    return redirect(url_for('index'))

@app.route('/forgot-password', methods=['GET', 'POST'])
@rate_limit
def forgot_password():
    """Request password reset via email."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        
        if not email:
            return render_template('forgot_password.html', error="Please enter your email.")
        
        user = db.get_user_by_email(email)
        
        if user:
            # Generate reset token
            reset_token = str(uuid.uuid4())
            db.set_reset_token(user.get('id', user.get('telegram_id')), reset_token)
            
            # Send email with reset link
            reset_link = f"{request.host_url}reset-password/{reset_token}"
            
            # Import and use email service
            from app.email_service import email_service
            email_service.send_password_reset(email, reset_link)
        
        # Always show success to prevent email enumeration
        return render_template('forgot_password.html', 
                             success="If an account exists with that email, a reset link has been sent.")
    
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
@rate_limit
def reset_password(token):
    """Reset password using token."""
    # Verify token exists
    user = db.get_user_by_reset_token(token)
    
    if not user:
        return render_template('reset_password.html', token=token, 
                             error="Invalid or expired reset link. Please request a new one.")
    
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if password != confirm_password:
            return render_template('reset_password.html', token=token, error="Passwords do not match.")
        
        if len(password) < 8:
            return render_template('reset_password.html', token=token, 
                                 error="Password must be at least 8 characters.")
        
        # Update password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        user_id = user.get('id', user.get('telegram_id'))
        db.update_password(user_id, password_hash)
        db.clear_reset_token(user_id)
        
        return redirect(url_for('login'))
    
    return render_template('reset_password.html', token=token)

@app.route('/logout')
def logout():
    """Clear session and redirect to login."""
    session.clear()
    return redirect(url_for('login'))

@app.route('/rename', methods=['POST'])
@csrf.exempt
@rate_limit
def rename_file():
    """Rename a file."""
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session['user_id']
    
    # Accept both JSON and form data
    if request.is_json:
        data = request.get_json()
        file_id = data.get('file_id')
        new_name = data.get('new_name', '').strip()
    else:
        file_id = request.form.get('file_id')
        new_name = request.form.get('new_name', '').strip()
    
    if not file_id or not new_name:
        return jsonify({"error": "File ID and new name required"}), 400
    
    try:
        db.rename_file(int(file_id), user_id, new_name)
        return jsonify({"status": "ok", "message": "File renamed successfully"})
    except Exception as e:
        print(f"[RENAME] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/download/bulk', methods=['POST'])
@csrf.exempt
@rate_limit
def download_bulk():
    """Download multiple files as a ZIP archive."""
    import zipfile
    from io import BytesIO
    
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session['user_id']
    data = request.get_json()
    file_ids = data.get('file_ids', [])
    
    if not file_ids:
        return jsonify({"error": "No files specified"}), 400
    
    try:
        # Create in-memory ZIP
        zip_buffer = BytesIO()
        bot = get_bot_client()
        bot.connect()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_id in file_ids:
                try:
                    file_info = db.get_file(file_id)
                    if not file_info or str(file_info['user_id']) != str(user_id):
                        continue
                    
                    filename = file_info['filename']
                    chunks = db.get_chunks(file_id)
                    
                    if not chunks:
                        continue
                    
                    # Download and merge chunks
                    file_data = BytesIO()
                    for chunk in chunks:
                        msg_id = chunk['message_id'] if isinstance(chunk, dict) else chunk[3]
                        chunk_path = bot.download_media(msg_id)
                        if chunk_path and os.path.exists(chunk_path):
                            with open(chunk_path, 'rb') as f:
                                file_data.write(f.read())
                            os.remove(chunk_path)
                    
                    # Add to ZIP
                    file_data.seek(0)
                    zip_file.writestr(filename, file_data.read())
                    print(f"[BULK] Added {filename} to ZIP")
                    
                except Exception as e:
                    print(f"[BULK] Error adding file {file_id}: {e}")
                    continue
        
        zip_buffer.seek(0)
        
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name='CloudVault-Download.zip'
        )
        
    except Exception as e:
        print(f"[BULK] Error: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to create download"}), 500

@app.route('/download/folder/<int:folder_id>')
@rate_limit
def download_folder(folder_id):
    """Download entire folder as ZIP archive."""
    import zipfile
    from io import BytesIO
    
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session['user_id']
    
    try:
        # Get folder info
        folder = db.get_file(folder_id)
        if not folder or str(folder.get('user_id')) != str(user_id):
            return jsonify({"error": "Folder not found"}), 404
        
        folder_name = folder.get('filename', 'Folder')
        
        # Recursively get all files in folder
        def get_files_recursive(parent_id, path=""):
            files_list = []
            items = db.list_files(user_id, parent_id)
            
            for item in items:
                # Support both dict and sqlite3.Row via key access
                item_id = item['id']
                item_name = item['filename']
                is_folder_item = item['is_folder']
                
                if is_folder_item:
                    # Recurse into subfolder
                    subpath = f"{path}/{item_name}" if path else item_name
                    files_list.extend(get_files_recursive(item_id, subpath))
                else:
                    files_list.append({
                        'id': item_id,
                        'name': item_name,
                        'path': f"{path}/{item_name}" if path else item_name
                    })
            
            return files_list
        
        files = get_files_recursive(folder_id)
        
        if not files:
            return jsonify({"error": "Folder is empty"}), 400
        
        # Create ZIP
        zip_buffer = BytesIO()
        bot = get_bot_client()
        bot.connect()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_info in files:
                try:
                    chunks = db.get_chunks(file_info['id'])
                    if not chunks:
                        continue
                    
                    # Download and merge chunks
                    file_data = BytesIO()
                    for chunk in chunks:
                        msg_id = chunk['message_id'] if isinstance(chunk, dict) else chunk[3]
                        chunk_path = bot.download_media(msg_id)
                        if chunk_path and os.path.exists(chunk_path):
                            with open(chunk_path, 'rb') as f:
                                file_data.write(f.read())
                            os.remove(chunk_path)
                    
                    # Add to ZIP with folder path
                    file_data.seek(0)
                    zip_file.writestr(file_info['path'], file_data.read())
                    print(f"[FOLDER DL] Added {file_info['path']} to ZIP")
                    
                except Exception as e:
                    print(f"[FOLDER DL] Error adding file {file_info['id']}: {e}")
                    continue
        
        zip_buffer.seek(0)
        
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'{folder_name}.zip'
        )
        
    except Exception as e:
        print(f"[FOLDER DL] Error: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to create folder download"}), 500

@app.route('/settings')
@rate_limit
def settings_page():
    """Renders the account settings page."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    user = db.get_user(user_id)
    if not user:
        return redirect(url_for('login'))
        
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax') == 'true':
        return render_template('settings.html', 
                             is_ajax=True,
                             user=user,
                             username=session.get('username'), 
                             email=session.get('email'))
                             
    return render_template('settings.html', 
                         user=user,
                         username=session.get('username'), 
                         email=session.get('email'))

@app.route('/settings/update', methods=['POST'])
@rate_limit
def update_settings():
    """Handle account updates from settings page."""
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    user_id = session['user_id']
    field = request.form.get('field')
    value = request.form.get('value', '').strip()
    old_password = request.form.get('old_password', '').strip()
    
    if not field or not value:
        return jsonify({"error": "Missing data"}), 400
        
    try:
        if field == 'username':
            db.update_username(user_id, value)
            session['username'] = value
            return jsonify({"status": "ok", "message": "Username updated"})
            
        elif field == 'email':
            # Check if email taken
            existing = db.get_user_by_email(value)
            if existing and str(existing.get('id', existing.get('telegram_id'))) != str(user_id):
                return jsonify({"error": "Email already in use"}), 400
            
            # For now, allow direct email change (verification can be added later)
            db.update_email(user_id, value)
            session['email'] = value
            return jsonify({"status": "ok", "message": "Email updated"})
            
        elif field == 'password':
            # Require old password
            if not old_password:
                return jsonify({"error": "Current password required"}), 400
            
            # Verify old password
            user = db.get_user(user_id)
            if not user:
                return jsonify({"error": "User not found"}), 404
            
            old_hash = hashlib.sha256(old_password.encode()).hexdigest()
            if user.get('password_hash') != old_hash:
                return jsonify({"error": "Current password is incorrect"}), 400
            
            # Validate new password
            if len(value) < 8:
                return jsonify({"error": "Password must be at least 8 characters"}), 400
            
            password_hash = hashlib.sha256(value.encode()).hexdigest()
            db.update_password(user_id, password_hash)
            return jsonify({"status": "ok", "message": "Password updated"})
            
        return jsonify({"error": "Invalid field"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/settings/delete_account', methods=['POST'])
@rate_limit
def delete_account():
    """Permanently delete the user account."""
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    user_id = session['user_id']
    try:
        db.delete_user(user_id)
        session.clear()
        return jsonify({"status": "ok", "message": "Account deleted successfully"})
    except Exception as e:
        print(f"[ERROR] Account deletion failed: {e}")
        return jsonify({"error": "Failed to delete account"}), 500

@app.route('/api/files')
def api_list_files():
    """API endpoint to get file list for AJAX refresh."""
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    user_id = session['user_id']
    folder_id = request.args.get('folder_id')
    folder_id = int(folder_id) if folder_id and folder_id != 'None' else None
    
    files = db.list_files(user_id, parent_id=folder_id)
    return jsonify({"files": files})

@app.route('/api/folders')
@rate_limit
def api_get_folders():
    """API endpoint to get list of all folders for the Move modal."""
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session['user_id']
    if Config.MULTI_USER:
        folders = db.get_all_folders(user_id)
    else:
        folders = db.get_all_folders()
        # Convert tuple list to dict list for local mode consistency
        folders = [{"id": f[0], "filename": f[1]} for f in folders]
        
    return jsonify({"folders": folders})

@app.route('/api/move/bulk', methods=['POST'])
@csrf.exempt
@rate_limit
def api_bulk_move():
    """Move multiple files and folders to a target directory."""
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        data = request.get_json()
        file_ids = data.get('file_ids', [])
        target_id = data.get('target_folder_id') # Can be None for root
        
        if target_id == 'root':
            target_id = None
        elif target_id:
            target_id = int(target_id)
            
        user_id = session['user_id']
        
        for file_id in file_ids:
            # Basic validation: don't move a folder into itself
            if int(file_id) == target_id:
                continue
                
            if Config.MULTI_USER:
                db.move_file(int(file_id), user_id, target_id)
            else:
                db.move_file(int(file_id), target_id)
                
        return jsonify({"message": f"Successfully moved {len(file_ids)} items"})
    except Exception as e:
        print(f"[MOVE] Error: {e}")
        return jsonify({"error": str(e)}), 500


def get_session_data():
    """Get session data, falling back to Config for single-user mode."""
    if Config.MULTI_USER:
        return {
            'session_string': session.get('session_string'),
            'api_id': session.get('api_id'),
            'api_hash': session.get('api_hash')
        }
    else:
        # Single-user mode: use .env credentials and local session file
        return {
            'session_string': None,  # Will use local session file
            'api_id': Config.API_ID,
            'api_hash': Config.API_HASH
        }


@app.route('/upload', methods=['POST'])
@csrf.exempt
@rate_limit
def upload_file():
    """Fire-and-forget upload wrapper."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session.get('user_id', 'local')
    file = request.files['file']
    
    # Save safely to unique temp path to avoid collisions
    safe_filename = f"{int(time.time())}_{file.filename}"
    temp_path = os.path.join(Config.UPLOAD_DIR, safe_filename)
    file.save(temp_path)
    
    # Get actual file size from disk (content_length can be None)
    file_size = os.path.getsize(temp_path)
    mime_type = request.form.get('mime_type', 'application/octet-stream')
    
    # Start background upload
    thread = threading.Thread(target=process_background_upload, 
                            args=(temp_path, file.filename, user_id, mime_type, file_size, None))
    thread.start()
    
    return jsonify({"message": f"started! {file.filename} is uploading in the background..."})

@app.route('/upload_chunk', methods=['POST'])
@csrf.exempt
@rate_limit
def upload_chunk():
    """Receives a slice of a file and saves it as a part file."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    upload_id = request.form.get('upload_id')
    chunk_index = request.form.get('chunk_index')
    # Accept either 'chunk' or 'file' field name for flexibility
    chunk = request.files.get('chunk') or request.files.get('file')
    
    if not chunk or upload_id is None or chunk_index is None:
        return jsonify({"error": "Missing upload parameters"}), 400
    
    # Save as a part file
    part_filename = f"{upload_id}.part{chunk_index}"
    temp_path = os.path.join(Config.UPLOAD_DIR, part_filename)
    
    chunk.save(temp_path)
    return jsonify({"status": "ok", "index": chunk_index})

@app.route('/upload_finish', methods=['POST'])
@csrf.exempt
def upload_finish():
    """Finalizes the parallel chunked upload by merging parts."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    upload_id = request.form.get('upload_id')
    filename = request.form.get('filename')
    total_chunks = request.form.get('total_chunks')
    parent_id = request.form.get('parent_id')
    
    if not upload_id or not total_chunks:
        return jsonify({"error": "Missing completion parameters"}), 400
        
    total_chunks = int(total_chunks)
    parent_id = int(parent_id) if parent_id and parent_id != 'None' else None
    user_id = session.get('user_id', 'local')
    
    final_temp_path = os.path.join(Config.UPLOAD_DIR, upload_id)
    
    try:
        # Merge parts in order
        with open(final_temp_path, 'wb') as outfile:
            for i in range(total_chunks):
                part_path = os.path.join(Config.UPLOAD_DIR, f"{upload_id}.part{i}")
                if not os.path.exists(part_path):
                    # If any part is missing, we can't finalize
                    return jsonify({"error": f"Part {i} missing"}), 400
                
                with open(part_path, 'rb') as infile:
                    outfile.write(infile.read())
                
                # Cleanup part file immediately
                os.remove(part_path)
        
        file_size = os.path.getsize(final_temp_path)
        max_size = 2000 * 1024 * 1024 # 2GB
        
        if file_size > max_size:
            os.remove(final_temp_path)
            return jsonify({"error": "File too large. Maximum limit is 2GB."}), 413
            
        mime_type = request.form.get('mime_type', 'application/octet-stream')
        
        # Process in background
        thread = threading.Thread(
            target=process_background_upload,
            args=(final_temp_path, filename, user_id, mime_type, file_size, parent_id),
            daemon=True 
        )
        thread.start()
        
        return jsonify({"message": "Upload complete and verification passed!"})
        
    except Exception as e:
        print(f"[FINISH ERROR] {e}")
        if os.path.exists(final_temp_path):
            os.remove(final_temp_path)
        return jsonify({"error": "Internal server error during merge"}), 500

@app.route('/thumbnail/<int:file_id>')
def get_thumbnail(file_id):
    """Serve a thumbnail for the given file, or a placeholder if not available."""
    # First check if file has thumbnail in database
    file_info = db.get_file(file_id)
    # Use .get() to safely handle databases without the thumbnail column
    thumbnail = file_info.get('thumbnail') if file_info else None
    if thumbnail:
        thumb_path = os.path.join(Config.UPLOAD_DIR, thumbnail)
        if os.path.exists(thumb_path):
            return send_file(thumb_path, mimetype='image/jpeg')
    
    # Legacy: check static thumbnails folder
    thumb_path = os.path.join(app.static_folder, 'thumbnails', f"{file_id}.jpg")
    if os.path.exists(thumb_path):
        return send_file(thumb_path, mimetype='image/jpeg')
    
    # Return 1x1 transparent PNG (prevents 404 console spam)
    transparent_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    return Response(transparent_png, mimetype='image/png', status=200)

import mimetypes
from flask import Response, stream_with_context

@app.route('/preview/<int:file_id>')
@rate_limit
def preview_file(file_id):
    """Stream file content for preview (images, videos, etc.) from Telegram."""
    try:
        user_id = session.get('user_id', 'local')
        
        # Get file info
        if Config.MULTI_USER:
            info = db.get_file(file_id)
            chunks = db.get_chunks(file_id)
        else:
            return "Not supported in local mode", 501
             
        if not info: return "File not found", 404
        
        # Security check
        if str(info['user_id']) != str(user_id):
            return "Unauthorized", 403

        # Get file details
        filename = info['filename']
        total_size = info['total_size'] or 0
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type: mime_type = 'application/octet-stream'
        
        if not chunks: return "File content not found", 404
        
        # Build a unique cache path for this file
        cache_filename = f"preview_{file_id}_{filename}"
        output_path = os.path.join(Config.DOWNLOAD_DIR, cache_filename)
        
        # Check if already cached
        if not os.path.exists(output_path):
            print(f"[PREVIEW] Downloading file {file_id} ({filename}) - {len(chunks)} chunks")
            # Download all chunks and merge them
            bot = get_bot_client()
            downloaded_chunks = []
            bot.connect()
            try:
                for i, chunk in enumerate(chunks):
                    msg_id = chunk['message_id'] if isinstance(chunk, dict) else chunk[3]
                    print(f"[PREVIEW] Downloading chunk {i+1}/{len(chunks)}, message_id: {msg_id}")
                    chunk_path = bot.download_media(msg_id)
                    if chunk_path:
                        print(f"[PREVIEW] Chunk downloaded to: {chunk_path}")
                        downloaded_chunks.append(chunk_path)
                    else:
                        print(f"[PREVIEW] WARNING: Chunk {i+1} returned None!")
            except Exception as e:
                print(f"[PREVIEW] Download error: {e}")
                traceback.print_exc()
                for p in downloaded_chunks:
                    if os.path.exists(p): os.remove(p)
                return f"Preview failed - download error: {str(e)}", 500
            
            # Check if we got any chunks
            if not downloaded_chunks:
                print(f"[PREVIEW] ERROR: No chunks were downloaded!")
                return "Preview failed - no chunks downloaded", 500
            
            # Merge chunks into output path
            print(f"[PREVIEW] Merging {len(downloaded_chunks)} chunks to {output_path}")
            with open(output_path, 'wb') as outfile:
                for chunk_path in downloaded_chunks:
                    with open(chunk_path, 'rb') as infile:
                        outfile.write(infile.read())
                    os.remove(chunk_path)
            
            # Update total_size if it was wrong
            total_size = os.path.getsize(output_path)
            print(f"[PREVIEW] File cached successfully, size: {total_size} bytes")
            
            # Schedule cleanup after 10 minutes
            def cleanup():
                time.sleep(600)
                if os.path.exists(output_path):
                    os.remove(output_path)
                    print(f"[CLEANUP] Removed preview cache: {output_path}")
            threading.Thread(target=cleanup, daemon=True).start()
        else:
            # Use cached file
            total_size = os.path.getsize(output_path)
        
        # Handle Range requests for video seeking
        range_header = request.headers.get('Range', None)
        
        if range_header:
            # Parse Range header
            byte1, byte2 = 0, total_size - 1
            match = re.search(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                byte1 = int(match.group(1))
                if match.group(2):
                    byte2 = int(match.group(2))
            
            length = byte2 - byte1 + 1
            
            # Read the specific range
            with open(output_path, 'rb') as f:
                f.seek(byte1)
                data = f.read(length)
            
            response = Response(data, status=206, mimetype=mime_type, direct_passthrough=True)
            response.headers.add('Content-Range', f'bytes {byte1}-{byte2}/{total_size}')
            response.headers.add('Accept-Ranges', 'bytes')
            response.headers.add('Content-Length', str(length))
            return response
        else:
            # Full file request
            response = send_file(output_path, mimetype=mime_type)
            response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
            return response

    except Exception as e:
        print(f"Preview Error: {e}")
        traceback.print_exc()
        return "Preview failed", 500

@app.route('/download_batch', methods=['POST'])
@csrf.exempt
def download_batch():
    """Download multiple files as a single ZIP archive using parallel fetching."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        data = request.get_json()
        file_ids = data.get('file_ids', [])
        if not file_ids:
            return jsonify({"error": "No files selected"}), 400
            
        user_id = session.get('user_id', 'local')
        files_to_zip = []
        
        # 1. Fetch metadata for all files
        for fid in file_ids:
            if Config.MULTI_USER:
                # Optimized: get chunks and metadata in one go if possible
                file_info = db.get_file(fid) 
                if file_info and (file_info.get('user_id') == user_id or not Config.MULTI_USER):
                    chunks = db.get_chunks(fid)
                    files_to_zip.append({"info": file_info, "chunks": chunks})
            else:
                file_info = db.get_file(fid)
                if file_info:
                    chunks = db.get_chunks(fid)
                    files_to_zip.append({"info": {"id": file_info[0], "filename": file_info[1]}, "chunks": chunks})

        if not files_to_zip:
            return jsonify({"error": "No valid files found"}), 404

        # 2. Collect all chunk message IDs for parallel download
        all_msg_ids = []
        chunk_map = {} # Maps msg_id -> (file_index, chunk_index)
        
        for f_idx, f_data in enumerate(files_to_zip):
            for c_idx, chunk in enumerate(f_data['chunks']):
                msg_id = chunk['message_id'] if Config.MULTI_USER else chunk[3]
                all_msg_ids.append(msg_id)
                chunk_map[msg_id] = (f_idx, c_idx)

        print(f"[BATCH] Downloading {len(all_msg_ids)} chunks for {len(files_to_zip)} files")
        
        bot = get_bot_client()
        bot.connect()
        
        # Increase concurrency for batch downloads (6-8 is usually safe)
        downloaded_paths = bot.download_chunks_parallel(all_msg_ids, max_concurrent=5)
        
        # 3. Create ZIP
        zip_filename = f"batch_{int(time.time())}.zip"
        zip_path = os.path.join(Config.DOWNLOAD_DIR, zip_filename)
        
        # Map message IDs to temporary disk paths
        msg_to_path = dict(zip(all_msg_ids, downloaded_paths))
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f_data in files_to_zip:
                filename = f_data['info']['filename']
                chunks = f_data['chunks']
                
                # Reassemble file in memory if small, or temp if large
                file_bytes = b""
                for chunk in chunks:
                    mid = chunk['message_id'] if Config.MULTI_USER else chunk[3]
                    cp = msg_to_path.get(mid)
                    if cp and os.path.exists(cp):
                        with open(cp, 'rb') as cf:
                            file_bytes += cf.read()
                
                zf.writestr(filename, file_bytes)

        # 4. Cleanup individual chunk files
        for p in downloaded_paths:
            if p and os.path.exists(p):
                os.remove(p)

        # Schedule ZIP cleanup
        def cleanup_zip():
            time.sleep(600) # 10 minutes
            if os.path.exists(zip_path): os.remove(zip_path)
            
        threading.Thread(target=cleanup_zip, daemon=True).start()

        return send_file(zip_path, as_attachment=True, download_name="TeleCloud_Batch.zip")

    except Exception as e:
        print(f"[BATCH ERROR] {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/download/<int:file_id>')
@app.route('/download_shared/<token>')
@rate_limit
def download_file(file_id=None, token=None):
    """Downloads a file from Telegram. Supports both private (ID) and public (Token) access."""
    try:
        user_id = session.get('user_id', 'local')
        session_data = get_session_data()
        
        if token:
            info = db.get_file_by_token(token)
            if not info: return "Link expired or invalid", 404
            
            # Standardize info structure based on DB type
            if Config.MULTI_USER:
                file_id = info['id']
                filename = info['filename']
                is_folder = info.get('is_folder', False)
                
                # Handle folder downloads - create ZIP
                if is_folder:
                    import zipfile
                    print(f"[SHARE] Folder download requested: {filename} (ID: {file_id})")
                    
                    def get_files_recursive(parent_id, path=""):
                        files_list = []
                        items = db.list_files_by_parent(parent_id)
                        for item in items:
                            i_id = item['id']
                            i_name = item['filename']
                            i_folder = item['is_folder']
                            if i_folder:
                                subpath = f"{path}/{i_name}" if path else i_name
                                files_list.extend(get_files_recursive(i_id, subpath))
                            else:
                                files_list.append({
                                    'id': i_id,
                                    'name': i_name,
                                    'path': f"{path}/{i_name}" if path else i_name
                                })
                        return files_list
                    
                    files = get_files_recursive(file_id)
                    print(f"[SHARE] Found {len(files)} files in folder")
                    if not files:
                        return "Folder is empty", 400
                    
                    zip_buffer = BytesIO()
                    bot = get_bot_client()
                    bot.connect()
                    
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_STORED) as zip_file:
                        for f_info in files:
                            try:
                                chunks = db.get_chunks(f_info['id'])
                                if not chunks: continue
                                cdat = BytesIO()
                                for chunk in chunks:
                                    mid = chunk['message_id']
                                    cp = bot.download_media(mid)
                                    if cp and os.path.exists(cp):
                                        with open(cp, 'rb') as f:
                                            cdat.write(f.read())
                                        os.remove(cp)
                                cdat.seek(0)
                                zip_file.writestr(f_info['path'], cdat.read())
                                print(f"[SHARE] Added to ZIP: {f_info['path']}")
                            except Exception as e:
                                print(f"[SHARE] Error adding {f_info['name']}: {e}")
                                continue
                    
                    zip_buffer.seek(0)
                    print(f"[SHARE] ZIP size: {zip_buffer.getbuffer().nbytes} bytes")
                    return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name=f"{filename}.zip")
                
                chunks = db.get_chunks(file_id)
            else:
                file_id = info[0]
                filename = info[1]
                chunks = db.get_chunks(file_id)
        else:
            if not file_id: return "File ID required", 400
            
            if Config.MULTI_USER:
                files = db.list_files(user_id)
                info = next((f for f in files if f['id'] == file_id), None)
                if not info: return "File not found in DB list", 404
                filename = info['filename']
                chunks = db.get_chunks(file_id)
            else:
                info = db.get_file(file_id)
                if not info: return "File not found locally", 404
                filename = info[1]
                chunks = db.get_chunks(file_id)

        # Use centralized Bot client for downloads
        bot = get_bot_client()
        
        # Create a unique temp folder/file to avoid conflicts
        safe_filename = f"{int(time.time())}_{filename}"
        output_path = os.path.join(Config.DOWNLOAD_DIR, safe_filename)
        
        downloaded_chunks = []
        
        bot.connect()
        try:
            # Use parallel download for multi-chunk files (3x faster)
            if len(chunks) > 1:
                msg_ids = [chunk['message_id'] if Config.MULTI_USER else chunk[3] for chunk in chunks]
                print(f"[DOWNLOAD] Parallel download of {len(msg_ids)} chunks")
                downloaded_chunks = bot.download_chunks_parallel(msg_ids, max_concurrent=3)
                # Filter out any None values
                downloaded_chunks = [p for p in downloaded_chunks if p]
                if len(downloaded_chunks) != len(chunks):
                    raise Exception(f"Only {len(downloaded_chunks)} of {len(chunks)} chunks downloaded")
            else:
                # Single chunk - use regular download
                for chunk in chunks:
                    msg_id = chunk['message_id'] if Config.MULTI_USER else chunk[3]
                    chunk_path = bot.download_media(msg_id)
                    if chunk_path:
                        downloaded_chunks.append(chunk_path)
                    else:
                        raise Exception(f"Empty chunk {msg_id}")
        except Exception as e:
            print(f"[BOT] Download error: {e}")
            # Cleanup what we have
            for p in downloaded_chunks:
                if p and os.path.exists(p): os.remove(p)
            raise
            
        # Merge chunks
        with open(output_path, 'wb') as outfile:
            for chunk_path in downloaded_chunks:
                with open(chunk_path, 'rb') as infile:
                    outfile.write(infile.read())
                os.remove(chunk_path)
        
        # Schedule cleanup after file is sent (5 min delay to ensure download completes)
        def cleanup_download():
            time.sleep(300)  # 5 minutes
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                    print(f"[CLEANUP] Removed: {output_path}")
                except Exception as e:
                    print(f"[CLEANUP] Failed to remove {output_path}: {e}")
        
        threading.Thread(target=cleanup_download, daemon=True).start()
        
        return send_file(output_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        print(traceback.format_exc())
        return str(e), 500

def process_background_upload(filepath, original_filename, user_id, mime_type, file_size, parent_id=None):
    """Background task to upload to Telegram and save to DB."""
    try:
        print(f"[BG] Starting background upload for {original_filename} (User: {user_id})")
        
        # Use the centralized Bot client
        print(f"[BG] Initializing BotClient...")
        bot = get_bot_client()
        
        # Generate Thumbnail for images
        thumbnail_filename = None
        if mime_type.startswith('image/'):
            try:
                thumb_id = str(uuid.uuid4())[:8]
                thumbnail_filename = f"thumb_{thumb_id}.jpg"
                thumb_path = os.path.join(Config.UPLOAD_DIR, thumbnail_filename)
                with Image.open(filepath) as img:
                    img.thumbnail((200, 200))
                    if img.mode != 'RGB': img = img.convert('RGB')
                    img.save(thumb_path, "JPEG", quality=85)
                print(f"[BG] Generated thumbnail: {thumbnail_filename}")
            except Exception as te:
                print(f"[BG] Thumbnail failed: {te}")

        # Split file into chunks
        print(f"[BG] Splitting file {filepath} (Size: {file_size}, ChunkSize: {Config.CHUNK_SIZE})...")
        chunk_paths = Chunker.split_file(filepath, Config.CHUNK_SIZE, Config.UPLOAD_DIR)
        print(f"[BG] Split into {len(chunk_paths)} chunks")
        
        # Add file entry to DB first to get file_id
        chunk_count = len(chunk_paths)
        if Config.MULTI_USER:
             file_id = db.add_file(user_id, original_filename, file_size, chunk_count, parent_id=parent_id, thumbnail=thumbnail_filename)
        else:
             file_id = db.add_file('local', original_filename, file_size, chunk_count, parent_id=parent_id, thumbnail=thumbnail_filename)

        try:
            bot.connect()
            # NEW: Upload chunks in parallel to Telegram (3x speedup)
            uploaded_messages = bot.upload_chunks_parallel(chunk_paths, max_concurrent=3)
            
            # Filter and store in DB
            for idx, msg in enumerate(uploaded_messages):
                if not msg:
                    raise Exception(f"Failed to upload chunk {idx}")
                
                mid = msg.id if hasattr(msg, 'id') else msg.message_id
                # Correct arguments: file_id, chunk_index, message_id, chunk_size
                db.add_chunk(file_id, idx, mid, os.path.getsize(chunk_paths[idx]))
                print(f"[BG] Chunk {idx+1}/{len(chunk_paths)} registered: {mid}")

            # Update final file status
            db.update_file_status(file_id, "ready")
            print(f"[BG] SUCCESS: {original_filename} is ready.")

        except Exception as ue:
            print(f"[BG] Upload error: {ue}")
            db.update_file_status(file_id, "error")
            raise
        finally:
            # Cleanup all local chunks
            for cp in chunk_paths:
                if os.path.exists(cp): os.remove(cp)
            
            # Cleanup the merged temp file
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    print(f"[BG] Cleaned up final temp file {filepath}")
                except Exception as e:
                    print(f"[BG] Failed to remove final temp file: {e}")

    except Exception as e:
        print(f"[BG] Background Task Failed: {e}")
        traceback.print_exc()
        # Ensure cleanup on failure
        if os.path.exists(filepath):
            os.remove(filepath)

@app.route('/move_files', methods=['POST'])
@csrf.exempt
def move_files():
    """Batch move files to a target folder."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        file_ids = data.get('file_ids', [])
        # Important: target_folder_id is explicitly allowed to be None (root)
        target_folder_id = data.get('target_folder_id')
        user_id = session.get('user_id', 'local')
        
        if not file_ids:
            return jsonify({"error": "No files selected"}), 400
            
        db.move_files_bulk(file_ids, user_id, target_folder_id)
        
        return jsonify({"message": f"Successfully moved {len(file_ids)} files"})
        
    except Exception as e:
        print(f"[MOVE ERROR] {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete/<int:file_id>', methods=['POST'])
@csrf.exempt
def delete_file_route(file_id):
    """Soft deletes a file (moves to trash)."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        user_id = session.get('user_id', 'local')
        
        if Config.MULTI_USER:
            # Soft delete - move to trash
            db.soft_delete_file(file_id, user_id)
        else:
            # For local mode, still do hard delete
            db.delete_file(file_id)
        
        return jsonify({"message": "File moved to trash"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/trash')
def trash():
    """View deleted files."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    trashed_files = db.get_trash(user_id)
    is_premium = session.get('is_premium', False)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax') == 'true':
        return render_template('trash.html', 
                             is_ajax=True,
                             files=trashed_files, 
                             is_premium=is_premium,
                             username=session.get('username'))
                             
    return render_template('trash.html', 
                         files=trashed_files, 
                         is_premium=is_premium,
                         username=session.get('username'))

@app.route('/restore/<int:file_id>', methods=['POST'])
@csrf.exempt
def restore_file_route(file_id):
    """Restore a file from trash."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        user_id = session.get('user_id', 'local')
        db.restore_file(file_id, user_id)
        return jsonify({"message": "File restored successfully"})
    except Exception as e:
        print(f"[RESTORE] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/trash/empty', methods=['POST'])
@csrf.exempt
def empty_trash_route():
    """Permanently delete all files in trash."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        user_id = session.get('user_id', 'local')
        
        # Get chunks to delete from Telegram first
        trashed_files = db.get_trash(user_id)
        bot = get_bot_client()
        bot.connect()
        
        for file in trashed_files:
            file_id = file['id'] if isinstance(file, dict) else file[0]
            chunks = db.get_chunks(file_id)
            for chunk in chunks:
                msg_id = chunk['message_id'] if Config.MULTI_USER else chunk[3]
                try:
                    bot.delete_message(msg_id)
                except Exception as e:
                    print(f"[DELETE] Could not delete message {msg_id}: {e}")
        
        # Permanently delete from database
        db.empty_trash(user_id)
        
        return jsonify({"message": "Trash emptied successfully"})
    except Exception as e:
        print(f"[EMPTY TRASH] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete/permanent/<int:file_id>', methods=['POST'])
@csrf.exempt
def permanent_delete_route(file_id):
    """Permanently delete a single file from trash."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        user_id = session.get('user_id', 'local')
        
        # Delete from Telegram
        chunks = db.get_chunks(file_id)
        bot = get_bot_client()
        bot.connect()
        
        for chunk in chunks:
            msg_id = chunk['message_id'] if Config.MULTI_USER else chunk[3]
            try:
                bot.delete_message(msg_id)
            except Exception as e:
                print(f"[DELETE] Could not delete message {msg_id}: {e}")
        
        # Permanently delete from database
        db.delete_file(file_id, user_id)
        
        return jsonify({"message": "File permanently deleted"})
    except Exception as e:
        print(f"[PERM DELETE] Error: {e}")
        return jsonify({"error": str(e)}), 500



@app.route('/generate_share', methods=['POST'])
@csrf.exempt
@rate_limit
def generate_share():
    """Generate a public share link for a file."""
    try:
        user_id = session.get('user_id', 'local')
        
        # Accept both JSON and form data
        if request.is_json:
            data = request.get_json()
            file_id = data.get('file_id')
        else:
            file_id = request.form.get('file_id')
        
        if not file_id:
            return jsonify({"error": "File ID required"}), 400
        
        # Generate a unique token
        import secrets
        token = secrets.token_urlsafe(16)
        
        # Save to database
        if Config.MULTI_USER:
            db.set_share_token(int(file_id), token)
        else:
            db.set_share_token(int(file_id), token)
        
        # Build the share URL
        share_url = request.host_url.rstrip('/') + f"/s/{token}"
        
        return jsonify({"share_url": share_url})
    except Exception as e:
        print(f"[SHARE] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/s/<token>')
def shared_file_page(token):
    """Display a shared file download page."""
    try:
        file_info = db.get_file_by_token(token)
        if not file_info:
            return render_template('error.html', message="This share link is invalid or has expired.", error_code="404"), 404
        
        filename = file_info['filename']
        file_id = file_info['id']
        file_size = file_info['total_size']
        is_folder = file_info['is_folder']
        
        return render_template('share.html', 
                             filename=filename, 
                             file_id=file_id, 
                             token=token,
                             file_size=file_size,
                             is_folder=is_folder)
    except Exception as e:
        return render_template('error.html', message=str(e), error_code="500"), 500

@app.route('/download_shared/<token>')
def download_shared(token):
    """Download a file via share token."""
    try:
        print(f"[SHARE] Download request for token: {token}")
        file_info = db.get_file_by_token(token)
        if not file_info:
            print(f"[SHARE] Token not found: {token}")
            return "Invalid or expired share link", 404
        
        print(f"[SHARE] File info: id={file_info['id']}, name={file_info['filename']}, is_folder={file_info['is_folder']}")
        
        file_id = file_info['id']
        filename = file_info['filename']
        is_folder = file_info['is_folder']
        # user_id is only in cloud DB, local uses 'local'
        user_id = file_info['user_id'] if 'user_id' in file_info.keys() else 'local'
        print(f"[SHARE] User ID: {user_id}")
        
        if is_folder:
            # Handle Folder Download (ZIP)
            import zipfile
            from io import BytesIO
            
            print(f"[SHARE] Starting folder download for folder ID: {file_id}")
            
            def get_files_recursive(parent_id, path=""):
                files_list = []
                print(f"[SHARE] Listing files in folder {parent_id}")
                # Use list_files_by_parent which doesn't require user_id
                items = db.list_files_by_parent(parent_id)
                print(f"[SHARE] Found {len(items) if items else 0} items in folder {parent_id}")
                for item in items:
                    i_id = item['id']
                    i_name = item['filename']
                    i_folder = item['is_folder']
                    
                    if i_folder:
                        subpath = f"{path}/{i_name}" if path else i_name
                        files_list.extend(get_files_recursive(i_id, subpath))
                    else:
                        files_list.append({
                            'id': i_id,
                            'name': i_name,
                            'path': f"{path}/{i_name}" if path else i_name
                        })
                return files_list

            files = get_files_recursive(file_id)
            print(f"[SHARE] Total files to zip: {len(files)}")
            if not files: 
                print(f"[SHARE] Folder is empty, returning 400")
                return "Folder is empty", 400
            
            zip_buffer = BytesIO()
            bot = get_bot_client()
            bot.connect()
            
            print(f"[SHARE] Creating ZIP for folder...")
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_STORED) as zip_file:
                for f_info in files:
                    try:
                        print(f"[SHARE] Adding file to zip: {f_info['name']} (ID: {f_info['id']})")
                        chunks = db.get_chunks(f_info['id'])
                        if not chunks: 
                            print(f"[SHARE] WARNING: No chunks for file {f_info['id']}")
                            continue
                        
                        cdat = BytesIO()
                        for chunk in chunks:
                            mid = chunk['message_id']
                            cp = bot.download_media(mid)
                            if cp and os.path.exists(cp):
                                with open(cp, 'rb') as f: 
                                    cdat.write(f.read())
                                os.remove(cp)
                            else:
                                print(f"[SHARE] ERROR: Chunk download failed for msg {mid}")

                        cdat.seek(0)
                        zip_file.writestr(f_info['path'], cdat.read())
                    except Exception as e:
                        print(f"[SHARE] Zip add error for {f_info['name']}: {e}")
                        continue
            
            zip_buffer.seek(0)
            print(f"[SHARE] ZIP creation complete. Size: {zip_buffer.getbuffer().nbytes} bytes. Sending to user.")
            return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name=f"{filename}.zip")

        # Handle Single File Download
        # Get chunks
        chunks = db.get_chunks(file_id)
        if not chunks:
            return "File content not found", 404
        
        # Download from Telegram
        bot = get_bot_client()
        safe_filename = f"{int(time.time())}_{filename}"
        output_path = os.path.join(Config.DOWNLOAD_DIR, safe_filename)
        
        downloaded_chunks = []
        bot.connect()
        try:
            for chunk in chunks:
                msg_id = chunk['message_id']
                chunk_path = bot.download_media(msg_id)
                if chunk_path:
                    downloaded_chunks.append(chunk_path)
        except Exception as e:
            print(f"[SHARE] Download error: {e}")
            for p in downloaded_chunks:
                if os.path.exists(p): os.remove(p)
            return "Download failed", 500
        
        # Merge chunks
        with open(output_path, 'wb') as outfile:
            for chunk_path in downloaded_chunks:
                with open(chunk_path, 'rb') as infile:
                    outfile.write(infile.read())
                os.remove(chunk_path)
        
        # Cleanup later
        def cleanup():
            time.sleep(300)
            if os.path.exists(output_path):
                os.remove(output_path)
        threading.Thread(target=cleanup, daemon=True).start()
        
        return send_file(output_path, as_attachment=True, download_name=filename)
    except Exception as e:
        return str(e), 500


# Ensure directories exist at startup
os.makedirs(Config.UPLOAD_DIR, exist_ok=True)
os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
