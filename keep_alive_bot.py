import time
import requests
import sys

# Usage: python keep_alive.py https://your-app-name.onrender.com

def ping_server(url, interval=500):
    """Pings the server every interval seconds (default 500s, just under 10 minutes)."""
    print(f"Starting Keep-Alive Bot for: {url}")
    print(f"Ping interval: {interval} seconds")
    
    while True:
        try:
            # We hit /health to be lightweight
            target = f"{url.rstrip('/')}/health"
            response = requests.get(target, timeout=10)
            
            if response.status_code == 200:
                print(f"[OK] Ping successful at {time.strftime('%H:%M:%S')}")
            else:
                print(f"[WARN] Server returned {response.status_code}")
                
        except Exception as e:
            print(f"[ERR] Ping failed: {e}")
            
        time.sleep(interval)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python keep_alive.py <YOUR_RENDER_URL>")
        # Example for user to see
        print("Example: python keep_alive.py https://telecloud.onrender.com")
    else:
        ping_server(sys.argv[1])
