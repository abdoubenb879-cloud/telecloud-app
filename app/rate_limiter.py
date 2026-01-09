"""
Rate Limiter Module with Exponential Backoff for Telegram API
CloudVault V2 - Handles API rate limits gracefully
"""

import time
import threading
from collections import defaultdict
from functools import wraps

class RateLimiter:
    """
    Rate limiter with exponential backoff for Telegram API calls.
    Tracks requests per endpoint and backs off when limits are hit.
    """
    
    def __init__(self):
        # Track request timestamps per endpoint
        self.requests = defaultdict(list)
        # Track backoff state per endpoint
        self.backoff_until = defaultdict(float)
        # Lock for thread safety
        self.lock = threading.Lock()
        
        # Rate limit settings
        self.MAX_REQUESTS_PER_SECOND = 30  # Telegram's default
        self.WINDOW_SECONDS = 1
        self.MAX_BACKOFF = 300  # 5 minutes max backoff
    
    def _cleanup_old_requests(self, endpoint):
        """Remove requests outside the window."""
        cutoff = time.time() - self.WINDOW_SECONDS
        self.requests[endpoint] = [t for t in self.requests[endpoint] if t > cutoff]
    
    def can_proceed(self, endpoint="default"):
        """Check if we can make a request to this endpoint."""
        with self.lock:
            now = time.time()
            
            # Check if we're in backoff
            if now < self.backoff_until[endpoint]:
                wait_time = self.backoff_until[endpoint] - now
                return False, wait_time
            
            # Cleanup old requests
            self._cleanup_old_requests(endpoint)
            
            # Check if under limit
            if len(self.requests[endpoint]) >= self.MAX_REQUESTS_PER_SECOND:
                return False, 1.0  # Wait 1 second
            
            return True, 0
    
    def record_request(self, endpoint="default"):
        """Record a successful request."""
        with self.lock:
            self.requests[endpoint].append(time.time())
    
    def record_rate_limit(self, endpoint="default", retry_after=None):
        """Record that we hit a rate limit, trigger backoff."""
        with self.lock:
            if retry_after:
                wait_time = min(retry_after, self.MAX_BACKOFF)
            else:
                # Exponential backoff
                current_backoff = self.backoff_until[endpoint] - time.time()
                if current_backoff <= 0:
                    wait_time = 1
                else:
                    wait_time = min(current_backoff * 2, self.MAX_BACKOFF)
            
            self.backoff_until[endpoint] = time.time() + wait_time
            print(f"[RATE LIMIT] Backing off endpoint '{endpoint}' for {wait_time:.1f}s")
            return wait_time
    
    def wait_if_needed(self, endpoint="default"):
        """Wait if rate limited. Returns True if we can proceed."""
        can_go, wait_time = self.can_proceed(endpoint)
        if not can_go:
            print(f"[RATE LIMIT] Waiting {wait_time:.1f}s for endpoint '{endpoint}'")
            time.sleep(wait_time)
            return self.can_proceed(endpoint)[0]
        return True


class RetryQueue:
    """
    Queue for retrying failed uploads with exponential backoff.
    """
    
    def __init__(self, max_retries=5):
        self.queue = []
        self.max_retries = max_retries
        self.lock = threading.Lock()
    
    def add(self, task_id, task_func, *args, **kwargs):
        """Add a task to the retry queue."""
        with self.lock:
            self.queue.append({
                'id': task_id,
                'func': task_func,
                'args': args,
                'kwargs': kwargs,
                'retries': 0,
                'next_retry': time.time()
            })
    
    def process(self, rate_limiter):
        """Process pending retries. Call this periodically."""
        with self.lock:
            now = time.time()
            ready_tasks = [t for t in self.queue if t['next_retry'] <= now]
            
            for task in ready_tasks:
                if task['retries'] >= self.max_retries:
                    print(f"[RETRY] Task {task['id']} failed after {self.max_retries} retries")
                    self.queue.remove(task)
                    continue
                
                # Check rate limit
                if not rate_limiter.wait_if_needed():
                    continue
                
                try:
                    task['func'](*task['args'], **task['kwargs'])
                    rate_limiter.record_request()
                    self.queue.remove(task)
                    print(f"[RETRY] Task {task['id']} succeeded on retry {task['retries']}")
                except Exception as e:
                    task['retries'] += 1
                    # Exponential backoff: 1s, 2s, 4s, 8s, 16s...
                    wait_time = min(2 ** task['retries'], 60)
                    task['next_retry'] = now + wait_time
                    print(f"[RETRY] Task {task['id']} failed, retry {task['retries']} in {wait_time}s: {e}")
    
    def get_queue_length(self):
        """Get number of pending tasks."""
        with self.lock:
            return len(self.queue)


# Global instances
rate_limiter = RateLimiter()
retry_queue = RetryQueue()


def with_retry(endpoint="default"):
    """Decorator to automatically retry failed API calls with rate limiting."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Wait if rate limited
            rate_limiter.wait_if_needed(endpoint)
            
            try:
                result = func(*args, **kwargs)
                rate_limiter.record_request(endpoint)
                return result
            except Exception as e:
                error_str = str(e).lower()
                
                # Check if it's a rate limit error
                if 'flood' in error_str or 'too many requests' in error_str or '420' in error_str:
                    # Extract retry_after if available
                    retry_after = None
                    if 'retry after' in error_str:
                        try:
                            retry_after = int(''.join(filter(str.isdigit, error_str.split('retry after')[1][:10])))
                        except:
                            pass
                    
                    wait_time = rate_limiter.record_rate_limit(endpoint, retry_after)
                    time.sleep(wait_time)
                    
                    # Retry once after waiting
                    return func(*args, **kwargs)
                
                raise
        return wrapper
    return decorator
