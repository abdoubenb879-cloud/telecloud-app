"""
TeleCloud - Cloud Database Layer
Uses Supabase (PostgreSQL) REST API directly for Python 3.14 compatibility.
"""
import os
import time
import random
import urllib.request
import urllib.parse
import json

class CloudDatabase:
    """Handles database operations in the cloud via Supabase REST API."""
    
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL", "")
        self.key = os.getenv("SUPABASE_KEY", "")
        if not self.url or not self.key:
            print("[DB] Warning: SUPABASE_URL or SUPABASE_KEY missing. Cloud DB won't work.")
            self.client = None
        else:
            self.client = True  # Just a flag to indicate we're ready
            print(f"[DB] Supabase REST API initialized")
    
    def _request(self, table, method="GET", data=None, params=None):
        """Make a request to Supabase REST API."""
        if not self.client:
            return None
            
        url = f"{self.url}/rest/v1/{table}"
        if params:
            url += "?" + urllib.parse.urlencode(params, safe=':,.')
        
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        body = json.dumps(data).encode('utf-8') if data else None
        
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = response.read().decode('utf-8')
                return json.loads(result) if result else []
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            print(f"[DB] HTTP Error {e.code}: {error_body}")
            raise
        except Exception as e:
            print(f"[DB] Request error: {e}")
            raise

    def add_user(self, telegram_id, session_string, api_id, api_hash):
        """Register or update a user's session in the cloud (legacy - for migration)."""
        data = {
            "telegram_id": str(telegram_id),
            "session_string": session_string,
            "api_id": api_id,
            "api_hash": api_hash
        }
        # Check if user exists first
        existing = self._request("users", params={"telegram_id": f"eq.{telegram_id}", "select": "*"})
        if existing:
            # Update
            return self._request("users", method="PATCH", data=data, params={"telegram_id": f"eq.{telegram_id}"})
        else:
            # Insert
            return self._request("users", method="POST", data=data)

    def get_user_by_username(self, username):
        """Get user by username for login."""
        result = self._request("users", params={"username": f"eq.{username}", "select": "*"})
        return result[0] if result else None
    
    def create_user(self, username, password_hash):
        """Create a new user with username/password."""
        # Generate a unique negative telegram_id for non-Telegram users
        unique_id = f"-{int(time.time())}{random.randint(1000, 9999)}"
        data = {
            "telegram_id": unique_id,
            "session_string": "bot_user",  # Placeholder - not used in Bot mode
            "api_id": 0,  # Placeholder - not used in Bot mode
            "api_hash": "bot_mode",  # Placeholder - not used in Bot mode
            "username": username,
            "password_hash": password_hash
        }
        result = self._request("users", method="POST", data=data)
        # Return the telegram_id as the user identifier (it's the primary key)
        if result and len(result) > 0:
            return result[0].get('id') or result[0].get('telegram_id') or unique_id
        return unique_id  # Fallback to the generated ID

    def get_user(self, telegram_id):
        """Retrieve user session data."""
        result = self._request("users", params={"telegram_id": f"eq.{telegram_id}", "select": "*"})
        return result[0] if result else None

    def add_file(self, user_id, filename, total_size, chunk_count, parent_id=None, thumbnail=None):
        """Tracks an uploaded file for a specific user."""
        data = {
            "user_id": str(user_id),
            "filename": filename,
            "total_size": total_size,
            "chunk_count": chunk_count,
            "parent_id": parent_id,
            "is_folder": False,
            "thumbnail": thumbnail
        }
        print(f"[DB DEBUG] Adding file with data: {data}")
        result = self._request("files", method="POST", data=data)
        return result[0]['id'] if result else None

    def create_folder(self, user_id, name, parent_id=None):
        """Creates a new folder for a user."""
        data = {
            "user_id": str(user_id),
            "filename": name,
            "total_size": 0,
            "chunk_count": 0,
            "parent_id": parent_id,
            "is_folder": True
        }
        result = self._request("files", method="POST", data=data)
        return result[0]['id'] if result else None

    def add_chunk(self, file_id, chunk_index, message_id, chunk_size):
        """Tracks individual chunks for a file."""
        data = {
            "file_id": file_id,
            "chunk_index": chunk_index,
            "message_id": message_id,
            "chunk_size": chunk_size
        }
        self._request("chunks", method="POST", data=data)

    def list_files(self, user_id, parent_id=None):
        """Lists files in a specific folder (or root), excluding deleted files."""
        # Base params - exclude deleted files (they go to trash)
        if parent_id is None:
            params = {
                "user_id": f"eq.{user_id}", 
                "parent_id": "is.null", 
                "or": "(is_deleted.is.null,is_deleted.eq.false)",
                "select": "*", 
                "order": "is_folder.desc,created_at.desc"
            }
        else:
            params = {
                "user_id": f"eq.{user_id}", 
                "parent_id": f"eq.{parent_id}", 
                "or": "(is_deleted.is.null,is_deleted.eq.false)",
                "select": "*", 
                "order": "is_folder.desc,created_at.desc"
            }
        
        result = self._request("files", params=params)
        return result if result else []

    def list_files_by_parent(self, parent_id):
        """Lists files by parent folder ID only (for shared folder downloads)."""
        params = {
            "parent_id": f"eq.{parent_id}", 
            "or": "(is_deleted.is.null,is_deleted.eq.false)",
            "select": "*", 
            "order": "is_folder.desc,created_at.desc"
        }
        result = self._request("files", params=params)
        return result if result else []

    def get_file(self, file_id):
        """Retrieves file metadata by ID."""
        result = self._request("files", params={"id": f"eq.{file_id}", "select": "*"})
        return result[0] if result else None

    def get_breadcrumbs(self, folder_id):
        """Returns list of {'id': id, 'name': name} for breadcrumb navigation."""
        breadcrumbs = []
        current_id = folder_id
        for _ in range(10): 
            if current_id is None: 
                break
            
            result = self._request("files", params={"id": f"eq.{current_id}", "select": "id,filename,parent_id"})
            if not result: 
                break
            
            folder = result[0]
            breadcrumbs.insert(0, {'id': folder['id'], 'name': folder['filename']})
            current_id = folder['parent_id']
            
        return breadcrumbs

    def get_file_by_token(self, token):
        """Retrieves file metadata by share token."""
        result = self._request("files", params={"share_token": f"eq.{token}", "select": "*"})
        return result[0] if result else None

    def set_share_token(self, file_id, token):
        """Updates the share token for a file."""
        self._request("files", method="PATCH", data={"share_token": token}, params={"id": f"eq.{file_id}"})

    def get_chunks(self, file_id):
        """Retrieves all chunks for a file."""
        result = self._request("chunks", params={"file_id": f"eq.{file_id}", "select": "*", "order": "chunk_index.asc"})
        return result if result else []


    def get_all_folders(self, user_id):
        """Get all folders for a user (for population of Move modal)."""
        result = self._request("files", params={
            "user_id": f"eq.{user_id}",
            "is_folder": "eq.true",
            "is_deleted": "neq.true",
            "select": "id,filename"
        })
        return result if result else []
    
    def move_file(self, file_id, user_id, new_parent_id):
        """Update a file's parent folder."""
        # Ensure new_parent_id is handled (None for root)
        data = {"parent_id": new_parent_id}
        self._request("files", method="PATCH", data=data, params={
            "id": f"eq.{file_id}",
            "user_id": f"eq.{user_id}"
        })

    def delete_file(self, file_id, user_id):
        """Deletes a file and its chunks (Supabase handles cascade if configured)."""
        # First delete chunks
        self._request("chunks", method="DELETE", params={"file_id": f"eq.{file_id}"})
        # Then delete file
        self._request("files", method="DELETE", params={"id": f"eq.{file_id}", "user_id": f"eq.{user_id}"})

    # ========== EMAIL AUTH METHODS ==========
    
    def get_user_by_email(self, email):
        """Get user by email for login."""
        result = self._request("users", params={"email": f"eq.{email}", "select": "*"})
        return result[0] if result else None
    
    def create_user_with_email(self, name, email, password_hash):
        """Create a new user with email/password."""
        import random
        import time
        # Generate a unique telegram_id-style ID for the new user (negative to distinguish from real Telegram IDs)
        user_id = -random.randint(1000000000, 9999999999)
        data = {
            "telegram_id": str(user_id),
            "username": name,
            "name": name,  # Also set name field for display
            "email": email,
            "password_hash": password_hash,
            "is_premium": False,
            # Required fields from old schema (NOT NULL constraints)
            "session_string": "email_user",  # Placeholder for email-based users
            "api_id": 0,  # Must be integer, not string
            "api_hash": "email_auth"
        }
        try:
            result = self._request("users", method="POST", data=data)
            if result and len(result) > 0:
                # Return the telegram_id from the created user
                return result[0].get('telegram_id', str(user_id))
            return str(user_id)
        except Exception as e:
            print(f"[DB] Error creating user: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def set_reset_token(self, user_id, token):
        """Set password reset token for user."""
        self._request("users", method="PATCH", 
                     data={"reset_token": token}, 
                     params={"telegram_id": f"eq.{user_id}"})
    
    def get_user_by_reset_token(self, token):
        """Get user by reset token."""
        result = self._request("users", params={"reset_token": f"eq.{token}", "select": "*"})
        return result[0] if result else None
    
    def update_password(self, user_id, password_hash):
        """Update user's password hash."""
        return self._request("users", method="PATCH", 
                     data={"password_hash": password_hash}, 
                     params={"telegram_id": f"eq.{user_id}"})

    def update_username(self, user_id, new_username):
        """Update user's username."""
        return self._request("users", method="PATCH", 
                     data={"username": new_username, "name": new_username}, 
                     params={"telegram_id": f"eq.{user_id}"})

    def update_email(self, user_id, new_email):
        """Update user's email."""
        return self._request("users", method="PATCH", 
                     data={"email": new_email}, 
                     params={"telegram_id": f"eq.{user_id}"})

    def clear_reset_token(self, user_id):
        """Clear the reset token after password reset."""
        self._request("users", method="PATCH", 
                     data={"reset_token": None}, 
                     params={"telegram_id": f"eq.{user_id}"})
    
    # ========== TRASH BIN METHODS ==========
    
    def soft_delete_file(self, file_id, user_id):
        """Soft delete a file (move to trash)."""
        import datetime
        self._request("files", method="PATCH", 
                     data={"is_deleted": True, "deleted_at": datetime.datetime.utcnow().isoformat()}, 
                     params={"id": f"eq.{file_id}", "user_id": f"eq.{user_id}"})
    
    def restore_file(self, file_id, user_id):
        """Restore a file from trash."""
        self._request("files", method="PATCH", 
                     data={"is_deleted": False, "deleted_at": None}, 
                     params={"id": f"eq.{file_id}", "user_id": f"eq.{user_id}"})
    
    def rename_file(self, file_id, user_id, new_name):
        """Rename a file."""
        self._request("files", method="PATCH", 
                     data={"filename": new_name}, 
                     params={"id": f"eq.{file_id}", "user_id": f"eq.{user_id}"})
    
    def get_trash(self, user_id):
        """Get all deleted files for a user."""
        result = self._request("files", params={
            "user_id": f"eq.{user_id}", 
            "is_deleted": "eq.true",
            "select": "*",
            "order": "deleted_at.desc"
        })
        return result if result else []
    
    def get_all_folders(self, user_id):
        """Get all folders for a user (for population of Move modal)."""
        result = self._request("files", params={
            "user_id": f"eq.{user_id}",
            "is_folder": "eq.true",
            "is_deleted": "neq.true",
            "select": "id,filename"
        })
        return result if result else []
    
    def move_file(self, file_id, user_id, new_parent_id):
        """Update a file's parent folder."""
        # Ensure new_parent_id is handled (None for root)
        data = {"parent_id": new_parent_id}
        self._request("files", method="PATCH", data=data, params={
            "id": f"eq.{file_id}",
            "user_id": f"eq.{user_id}"
        })
    
    def empty_trash(self, user_id):
        """Permanently delete all trashed files for a user."""
        # Get all trashed files first
        trashed = self.get_trash(user_id)
        for file in trashed:
            self._request("chunks", method="DELETE", params={"file_id": f"eq.{file['id']}"})
            self._request("files", method="DELETE", params={"id": f"eq.{file['id']}", "user_id": f"eq.{user_id}"})

    def get_trashed_files(self, user_id):
        """Alias for get_trash for compatibility."""
        return self.get_trash(user_id)
    
    def permanent_delete(self, file_id, user_id):
        """Permanently delete a single file from trash."""
        # Delete chunks first
        self._request("chunks", method="DELETE", params={"file_id": f"eq.{file_id}"})
        # Then delete file
        self._request("files", method="DELETE", params={"id": f"eq.{file_id}", "user_id": f"eq.{user_id}"})

    def delete_user(self, user_id):
        """Permanently delete a user and all their data."""
        # 1. Empty trash (removes all files and chunks)
        self.empty_trash(user_id)
        
        # 2. Delete all files that are NOT in trash but belong to the user
        # (empty_trash only handles is_deleted=true)
        files = self._request("files", params={"user_id": f"eq.{user_id}", "select": "id"})
        for f in files:
            self.permanent_delete(f['id'], user_id)
            
        # 3. Delete the user record
        self._request("users", method="DELETE", params={"telegram_id": f"eq.{user_id}"})
