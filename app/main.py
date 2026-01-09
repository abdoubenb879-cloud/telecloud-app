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
)

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
        # Cache static files for 1 day
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
            
        return render_template('dashboard.html', 
                               files=files, 
                               storage_name=storage_name, 
                               multi_user=Config.MULTI_USER,
                               breadcrumbs=breadcrumbs,
                               current_folder_id=current_folder_id,
                               username=session.get('username', 'User'))
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

@app.route('/trash')
def trash_page():
    """Show deleted files."""
    if Config.MULTI_USER:
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user_id = session['user_id']
        files = db.get_trashed_files(user_id)
    else:
        files = []  # Local mode doesn't support trash

    return render_template('trash.html',
                           files=files,
                           username=session.get('username', 'User'))

@app.route('/restore/<int:file_id>', methods=['POST'])
@csrf.exempt
def restore_file(file_id):
    """Restore a file from trash."""
    if Config.MULTI_USER:
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        user_id = session['user_id']
        db.restore_file(file_id, user_id)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Not supported"}), 501

@app.route('/delete/permanent/<int:file_id>', methods=['POST'])
@csrf.exempt
def permanent_delete_file(file_id):
    """Permanently delete a file from trash."""
    if Config.MULTI_USER:
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        user_id = session['user_id']
        db.permanent_delete(file_id, user_id)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Not supported"}), 501

@app.route('/trash/empty', methods=['POST'])
@csrf.exempt
def empty_trash():
    """Empty the trash (permanently delete all trashed files)."""
    if Config.MULTI_USER:
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        user_id = session['user_id']
        db.empty_trash(user_id)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Not supported"}), 501

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
    """Receives a slice of a file and appends it."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    upload_id = request.form.get('upload_id')
    # Accept either 'chunk' or 'file' field name for flexibility
    chunk = request.files.get('chunk') or request.files.get('file')
    
    if not chunk:
        return jsonify({"error": "No chunk data received"}), 400
    
    # Temp file is named after the upload_id
    temp_path = os.path.join(Config.UPLOAD_DIR, upload_id)
    
    # Append mode 'ab'
    with open(temp_path, 'ab') as f:
        f.write(chunk.read())
        
    return jsonify({"status": "ok"})

@app.route('/upload_finish', methods=['POST'])
@csrf.exempt
def upload_finish():
    """Finalizes the chunked upload and starts background processing."""
    if Config.MULTI_USER and 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    upload_id = request.form.get('upload_id')
    filename = request.form.get('filename')
    parent_id = request.form.get('parent_id')
    parent_id = int(parent_id) if parent_id and parent_id != 'None' else None
    
    user_id = session.get('user_id', 'local')
    
    temp_path = os.path.join(Config.UPLOAD_DIR, upload_id)
    
    if not os.path.exists(temp_path):
        return jsonify({"error": "Upload failed (temp file missing)"}), 400
    
    # Get file size from disk and mime type
    file_size = os.path.getsize(temp_path)
    
    # MAX CONTENT LENGTH: 2GB (Telegram Bot API limit)
    max_size = 2000 * 1024 * 1024 
    
    if file_size > max_size:
        os.remove(temp_path)
        return jsonify({"error": "File too large. Maximum limit is 2GB."}), 413
        
    mime_type = request.form.get('mime_type', 'application/octet-stream')
    
    # Start Background Thread with correct arguments
    thread = threading.Thread(
        target=process_background_upload,
        args=(temp_path, filename, user_id, mime_type, file_size, parent_id),
        daemon=True 
    )
    thread.start()


    return jsonify({"message": "Upload complete! Processing in background."})

@app.route('/thumbnail/<int:file_id>')
def get_thumbnail(file_id):
    """Serve a thumbnail for the given file, or a placeholder if not available."""
    thumb_path = os.path.join(app.static_folder, 'thumbnails', f"{file_id}.jpg")
    
    if os.path.exists(thumb_path):
        return send_file(thumb_path, mimetype='image/jpeg')
    else:
        # Return a 1x1 transparent pixel as fallback (or 404)
        return '', 404

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
            for chunk in chunks:
                msg_id = chunk['message_id'] if Config.MULTI_USER else chunk[3]
                try:
                    chunk_path = bot.download_media(msg_id)
                    if chunk_path:
                        downloaded_chunks.append(chunk_path)
                    else:
                        raise Exception(f"Empty chunk {msg_id}")
                except Exception as e:
                    print(f"Error downloading chunk {msg_id}: {e}")
                    # Cleanup what we have
                    for p in downloaded_chunks:
                        if os.path.exists(p): os.remove(p)
                    raise e
        except Exception as e:
            print(f"[BOT] Download error: {e}")
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
        
        # Split file into chunks
        print(f"[BG] Splitting file {filepath} (Size: {file_size})...")
        chunk_paths = Chunker.split_file(filepath, Config.CHUNK_SIZE, Config.UPLOAD_DIR)
        print(f"[BG] Split into {len(chunk_paths)} chunks")
        
        uploaded_chunks = []
        try:
            bot.connect()
            for idx, cp in enumerate(chunk_paths):
                print(f"[BG] Uploading chunk {idx+1}/{len(chunk_paths)}: {cp}")
                
                # Upload with basic progress logging
                msg = bot.upload_file(cp, progress_callback=lambda c, t: None) 
                
                if not msg:
                    raise Exception(f"Chunk {idx} upload failed (None returned)")
                    
                print(f"[BG] Chunk {idx+1} uploaded. Msg ID: {msg.id}")
                uploaded_chunks.append({'index': idx, 'msg_id': msg.id, 'size': os.path.getsize(cp)})
                
                # Clean chunk immediately to save space
                if os.path.exists(cp): os.remove(cp)
        except Exception as e:
            print(f"[BOT] Upload error: {e}")
            raise e

        # Database Insertion
        chunk_count = len(uploaded_chunks)
        print(f"[BG] All chunks uploaded. Saving to DB...")
        
        if Config.MULTI_USER:
             f_id = db.add_file(user_id, original_filename, file_size, chunk_count, parent_id=parent_id)
             for c in uploaded_chunks:
                 db.add_chunk(f_id, c['index'], c['msg_id'], c['size'])
        else:
             f_id = db.add_file(original_filename, file_size, chunk_count, parent_id=parent_id)
             for c in uploaded_chunks:
                 db.add_chunk(f_id, c['index'], c['msg_id'], c['size'])
                 
        print(f"[BG] Database Inserted. File ID: {f_id}")

        # Cleanup original temp file
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"[BG] Cleaned up temp file {filepath}")

    except Exception as e:
        print(f"[BG] Background Task Failed: {e}")
        traceback.print_exc()
        # Ensure cleanup on failure
        if os.path.exists(filepath):
            os.remove(filepath)

@app.route('/delete/<int:file_id>', methods=['POST'])
@csrf.exempt
def delete_file_route(file_id):
    """Soft deletes a file (moves to trash)."""
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
    
    return render_template('trash.html', 
                          files=trashed_files, 
                          is_premium=is_premium,
                          username=session.get('username'))

@app.route('/restore/<int:file_id>', methods=['POST'])
@csrf.exempt
def restore_file_route(file_id):
    """Restore a file from trash."""
    try:
        user_id = session.get('user_id', 'local')
        db.restore_file(file_id, user_id)
        return jsonify({"message": "File restored successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/trash/empty', methods=['POST'])
@csrf.exempt
def empty_trash_route():
    """Permanently delete all files in trash."""
    try:
        user_id = session.get('user_id', 'local')
        
        # Get chunks to delete from Telegram first
        trashed_files = db.get_trash(user_id)
        bot = get_bot_client()
        bot.connect()
        
        for file in trashed_files:
            chunks = db.get_chunks(file['id'])
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
        return jsonify({"error": str(e)}), 500

@app.route('/delete/permanent/<int:file_id>', methods=['POST'])
@csrf.exempt
def permanent_delete_route(file_id):
    """Permanently delete a single file from trash."""
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
        
        filename = file_info['filename'] if isinstance(file_info, dict) else file_info[1]
        file_id = file_info['id'] if isinstance(file_info, dict) else file_info[0]
        file_size = file_info.get('total_size', 0) if isinstance(file_info, dict) else 0
        
        return render_template('share.html', 
                             filename=filename, 
                             file_id=file_id, 
                             token=token,
                             file_size=file_size)
    except Exception as e:
        return render_template('error.html', message=str(e), error_code="500"), 500

@app.route('/download_shared/<token>')
def download_shared(token):
    """Download a file via share token."""
    try:
        file_info = db.get_file_by_token(token)
        if not file_info:
            return "Invalid or expired share link", 404
        
        file_id = file_info['id'] if isinstance(file_info, dict) else file_info[0]
        filename = file_info['filename'] if isinstance(file_info, dict) else file_info[1]
        
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
                msg_id = chunk['message_id'] if isinstance(chunk, dict) else chunk[3]
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
