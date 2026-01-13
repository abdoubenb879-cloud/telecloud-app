"""
In-memory upload queue for managing concurrent uploads.
Works on Render free tier (no Redis required).
"""
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from enum import Enum


class UploadStatus(Enum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class UploadJob:
    job_id: str
    user_id: str
    filename: str
    file_size: int
    status: UploadStatus = UploadStatus.QUEUED
    queue_position: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    error: Optional[str] = None


class UploadQueue:
    """
    Thread-safe upload queue with per-user and global limits.
    
    Configuration:
    - MAX_FILE_SIZE: Maximum file size allowed (bytes)
    - MAX_CONCURRENT_PER_USER: Max simultaneous uploads per user
    - MAX_GLOBAL_CONCURRENT: Max simultaneous uploads globally
    """
    
    def __init__(
        self,
        max_file_size: int = 500 * 1024 * 1024,  # 500MB default
        max_concurrent_per_user: int = 2,
        max_global_concurrent: int = 5
    ):
        self.max_file_size = max_file_size
        self.max_concurrent_per_user = max_concurrent_per_user
        self.max_global_concurrent = max_global_concurrent
        
        self._lock = threading.RLock()
        self._jobs: Dict[str, UploadJob] = {}
        self._active_by_user: Dict[str, int] = defaultdict(int)
        self._global_active: int = 0
        self._queue_order: list = []  # job_ids in queue order
        
    def validate_upload(self, file_size: int, user_id: str) -> Tuple[bool, str]:
        """
        Validate if an upload can be started.
        Returns (is_valid, error_message).
        """
        if file_size > self.max_file_size:
            max_mb = self.max_file_size // (1024 * 1024)
            file_mb = file_size // (1024 * 1024)
            return False, f"File too large ({file_mb}MB). Maximum is {max_mb}MB."
        
        return True, ""
    
    def can_start_now(self, user_id: str) -> Tuple[bool, int]:
        """
        Check if upload can start immediately or needs to queue.
        Returns (can_start, queue_position).
        """
        with self._lock:
            # Check user limit
            if self._active_by_user[user_id] >= self.max_concurrent_per_user:
                # Count how many are ahead in queue for this user
                queue_pos = len([j for j in self._queue_order 
                               if self._jobs[j].user_id == user_id])
                return False, queue_pos + 1
            
            # Check global limit
            if self._global_active >= self.max_global_concurrent:
                return False, len(self._queue_order) + 1
            
            return True, 0
    
    def register_upload(self, job_id: str, user_id: str, filename: str, file_size: int) -> UploadJob:
        """Register a new upload and return its job info."""
        with self._lock:
            can_start, queue_pos = self.can_start_now(user_id)
            
            job = UploadJob(
                job_id=job_id,
                user_id=user_id,
                filename=filename,
                file_size=file_size,
                status=UploadStatus.UPLOADING if can_start else UploadStatus.QUEUED,
                queue_position=queue_pos
            )
            
            self._jobs[job_id] = job
            
            if can_start:
                self._start_upload(job_id)
            else:
                self._queue_order.append(job_id)
                print(f"[QUEUE] Upload {job_id} queued at position {queue_pos}")
            
            return job
    
    def _start_upload(self, job_id: str):
        """Internal: Mark upload as started."""
        job = self._jobs.get(job_id)
        if job:
            job.status = UploadStatus.UPLOADING
            job.started_at = time.time()
            self._active_by_user[job.user_id] += 1
            self._global_active += 1
            print(f"[QUEUE] Upload {job_id} started (global: {self._global_active}/{self.max_global_concurrent})")
    
    def complete_upload(self, job_id: str, success: bool = True, error: str = None):
        """Mark upload as complete and process queue."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            
            if job.status == UploadStatus.UPLOADING:
                self._active_by_user[job.user_id] = max(0, self._active_by_user[job.user_id] - 1)
                self._global_active = max(0, self._global_active - 1)
            
            job.status = UploadStatus.COMPLETED if success else UploadStatus.FAILED
            job.error = error
            
            print(f"[QUEUE] Upload {job_id} {'completed' if success else 'failed'} (global: {self._global_active}/{self.max_global_concurrent})")
            
            # Process next in queue
            self._process_queue()
    
    def _process_queue(self):
        """Check if any queued uploads can start."""
        while self._queue_order and self._global_active < self.max_global_concurrent:
            job_id = self._queue_order[0]
            job = self._jobs.get(job_id)
            
            if not job:
                self._queue_order.pop(0)
                continue
            
            # Check user limit
            if self._active_by_user[job.user_id] < self.max_concurrent_per_user:
                self._queue_order.pop(0)
                self._start_upload(job_id)
            else:
                # User at limit, try next in queue
                break
        
        # Update queue positions
        for i, job_id in enumerate(self._queue_order):
            job = self._jobs.get(job_id)
            if job:
                job.queue_position = i + 1
    
    def get_job(self, job_id: str) -> Optional[UploadJob]:
        """Get job status."""
        return self._jobs.get(job_id)
    
    def get_user_active_count(self, user_id: str) -> int:
        """Get number of active uploads for a user."""
        with self._lock:
            return self._active_by_user.get(user_id, 0)
    
    def cleanup_old_jobs(self, max_age_seconds: int = 3600):
        """Remove completed/failed jobs older than max_age."""
        with self._lock:
            cutoff = time.time() - max_age_seconds
            to_remove = [
                jid for jid, job in self._jobs.items()
                if job.status in (UploadStatus.COMPLETED, UploadStatus.FAILED)
                and job.created_at < cutoff
            ]
            for jid in to_remove:
                del self._jobs[jid]
            
            if to_remove:
                print(f"[QUEUE] Cleaned up {len(to_remove)} old jobs")
    
    @property
    def stats(self) -> dict:
        """Get queue statistics."""
        with self._lock:
            return {
                "active": self._global_active,
                "queued": len(self._queue_order),
                "max_concurrent": self.max_global_concurrent,
                "max_file_size_mb": self.max_file_size // (1024 * 1024)
            }


# Global queue instance
_upload_queue: Optional[UploadQueue] = None


def get_upload_queue() -> UploadQueue:
    """Get or create the global upload queue."""
    global _upload_queue
    if _upload_queue is None:
        _upload_queue = UploadQueue()
    return _upload_queue
