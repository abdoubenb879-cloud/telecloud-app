import requests
import re
import os

BASE_URL = "https://my-telecloud.onrender.com"
EMAIL = "abdoubenb879@gmail.com"
PASSWORD = "Abdounouar22"

session = requests.Session()
session.headers.update({"User-Agent": "Debug-Script/1.0"})

def get_csrf(url):
    print(f"Fetching {url}...")
    r = session.get(url)
    # Regex to find CSRF token value
    match = re.search(r'name=["\']csrf_token["\'].*?value=["\']([^"\']+)["\']', r.text, re.DOTALL)
    if not match:
        # Try finding value first
        match = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']csrf_token["\']', r.text, re.DOTALL)
        
    if match:
        print(f"Got CSRF: {match.group(1)[:10]}...")
        return match.group(1)
    
    print("❌ Could not find CSRF token!")
    # print(r.text[:1000]) # Debug
    return None

def login():
    csrf = get_csrf(f"{BASE_URL}/login")
    if not csrf: return False
    
    data = {
        "email": EMAIL,
        "password": PASSWORD,
        "csrf_token": csrf
    }
    
    print("Logging in...")
    r = session.post(f"{BASE_URL}/login", data=data)
    
    if r.url.strip('/').endswith("/login") or "error" in r.text.lower():
        print("❌ Login Failed!")
        # Debug the page text to find the error
        if "Incorrect password" in r.text:
            print("REASON: Incorrect Password")
        elif "No account found" in r.text:
            print("REASON: No Account Found")
        elif "csrf" in r.text.lower() and "missing" in r.text.lower():
            print("REASON: CSRF Issue")
        else:
            print(f"DEBUG HTML: {r.text[:500]} ...")
        
        # Check for specific error message class
        err_match = re.search(r'class="alert alert-danger"[^>]*>([^<]+)', r.text)
        if err_match:
            print(f"Server Message: {err_match.group(1).strip()}")
        return False
        
    print(f"✅ Login Success! Redirected to: {r.url}")
    return True

def upload():
    filename = "telecloud_debug_test.txt"
    with open(filename, "w") as f:
        f.write("This is a debug upload to test the bot connection.")
        
    print(f"Uploading {filename}...")
    try:
        with open(filename, "rb") as f:
            # Note: The real upload endpoint is /upload (AJAX) or via form?
            # From source code, it's /upload
            r = session.post(f"{BASE_URL}/upload", files={"file": f}, timeout=120)
            
        print(f"Upload Status: {r.status_code}")
        print(f"Response: {r.text}")
        
    except Exception as e:
        print(f"❌ Upload Error: {e}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)

if __name__ == "__main__":
    if login():
        upload()
