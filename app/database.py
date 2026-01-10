import sqlite3
from .config import Config

class Database:
    """Handles all database operations for file and chunk tracking."""
    
    def __init__(self):
        # Increased timeout to handle potential concurrency
        self.conn = sqlite3.connect(
            Config.DATABASE_PATH, 
            check_same_thread=False,
            timeout=30
        )
        self.conn.row_factory = sqlite3.Row
        self.create_tables()


    def create_tables(self):
        """Creates the necessary tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Files table: stores overall metadata
        # Added: parent_id, share_token, is_folder
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                total_size INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                checksum TEXT,
                parent_id INTEGER DEFAULT NULL,
                share_token TEXT UNIQUE DEFAULT NULL,
                is_folder BOOLEAN DEFAULT 0,
                thumbnail TEXT
            )
        ''')
        
        # Chunks table: stores info about each piece on Telegram
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                chunk_size INTEGER NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
            )
        ''')
        
        self.conn.commit()

    def add_file(self, user_id, filename, total_size, chunk_count, checksum=None, parent_id=None, thumbnail=None):
        """Adds a new file record and returns its ID. user_id is ignored in local mode."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO files (filename, total_size, chunk_count, checksum, parent_id, is_folder, thumbnail) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (filename, total_size, chunk_count, checksum, parent_id, thumbnail)
        )
        self.conn.commit()
        return cursor.lastrowid

    def create_folder(self, name, parent_id=None):
        """Creates a new folder."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO files (filename, total_size, chunk_count, parent_id, is_folder) VALUES (?, 0, 0, ?, 1)",
            (name, parent_id)
        )
        self.conn.commit()
        return cursor.lastrowid

    def add_chunk(self, file_id, chunk_index, message_id, chunk_size):
        """Adds a chunk record linked to a file."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO chunks (file_id, chunk_index, message_id, chunk_size) VALUES (?, ?, ?, ?)",
            (file_id, chunk_index, message_id, chunk_size)
        )
        self.conn.commit()

    def get_file(self, file_id):
        """Retrieves file metadata by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
        return cursor.fetchone()

    def get_file_by_token(self, token):
        """Retrieves file metadata by share token."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM files WHERE share_token = ?", (token,))
        return cursor.fetchone()

    def set_share_token(self, file_id, token):
        """Updates the share token for a file."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE files SET share_token = ? WHERE id = ?", (token, file_id))
        self.conn.commit()

    def get_chunks(self, file_id):
        """Retrieves all chunks for a specific file, ordered by index."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM chunks WHERE file_id = ? ORDER BY chunk_index ASC", (file_id,))
        return cursor.fetchall()

    def list_files(self, user_id=None, parent_id=None):
        """Lists files in a specific folder (or root). user_id is ignored in local mode."""
        cursor = self.conn.cursor()
        if parent_id is None:
            cursor.execute("SELECT id, filename, total_size, upload_date, is_folder, share_token FROM files WHERE parent_id IS NULL ORDER BY is_folder DESC, upload_date DESC")
        else:
            cursor.execute("SELECT id, filename, total_size, upload_date, is_folder, share_token FROM files WHERE parent_id = ? ORDER BY is_folder DESC, upload_date DESC", (parent_id,))
        return cursor.fetchall()

    def get_breadcrumbs(self, folder_id):
        """Returns list of (id, name) tuples for breadcrumb navigation."""
        breadcrumbs = []
        current_id = folder_id
        while current_id is not None:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, filename, parent_id FROM files WHERE id = ?", (current_id,))
            folder = cursor.fetchone()
            if not folder: break
            breadcrumbs.insert(0, {'id': folder[0], 'name': folder[1]})
            current_id = folder[2]
        return breadcrumbs

        self.conn.commit()

    def get_all_folders(self):
        """Get all folders (local mode)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, filename FROM files WHERE is_folder = 1")
        return cursor.fetchall()
        
    def move_file(self, file_id, new_parent_id):
        """Update a file's parent folder (local mode)."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE files SET parent_id = ? WHERE id = ?", (new_parent_id, file_id))
        self.conn.commit()

    def delete_file(self, file_id):
        """Deletes a file (or folder) and its content."""
        # Note: Basic deletion. If folder, won't recursively delete children in this snippet (for safety).
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
        self.conn.commit()

    def close(self):
        """Closes the database connection."""
        self.conn.close()
