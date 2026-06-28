"""GitHub deploy via OAuth device flow (China-friendly)"""
import requests, json, time, os, base64

DIR = r"D:\projects\market-dashboard"
CLIENT_ID = "178c6fc778ccc68e1d6a"  # GitHub CLI client ID
GITHUB_USER = "tt123497"
GITHUB_EMAIL = "571335112@qq.com"
REPO = "market-sentinel"

def api_post(url, data, timeout=15):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            r = requests.post(url, json=data, headers=headers, timeout=timeout)
            return r
        except Exception as e:
            print(f"  Attempt {attempt+1}: {e}")
            time.sleep(3)
    return None

def api_get(url, headers, timeout=15):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            return r
        except:
            time.sleep(3)
    return None

def api_put(url, headers, data, timeout=15):
    for attempt in range(3):
        try:
            r = requests.put(url, json=data, headers=headers, timeout=timeout)
            return r
        except:
            time.sleep(3)
    return None

# Step 1: Device flow
print("=== GitHub Device Auth ===")
r = api_post("https://github.com/login/device/code", {
    "client_id": CLIENT_ID,
    "scope": "repo,workflow"
})
if not r or r.status_code != 200:
    print(f"Failed: {r.status_code if r else 'no response'}")
    print("Trying browser-based approach...")
    os.system(f'start https://github.com/login/device')
    exit()

data = r.json()
device_code = data["device_code"]
user_code = data["user_code"]
verify_url = data["verification_uri"]
interval = data.get("interval", 5)

print(f"\n{'='*50}")
print(f"  VERIFICATION CODE: {user_code}")
print(f"  OPEN: {verify_url}")
print(f"  Enter the code above, then wait...")
print(f"{'='*50}\n")

# Open browser
os.system(f'start {verify_url}')

# Step 2: Poll for token
token = None
for i in range(40):  # Try for ~200 seconds
    print(f"  Waiting... ({i*interval}s)", end='\r')
    r = api_post("https://github.com/login/oauth/access_token", {
        "client_id": CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
    })
    if r and r.status_code == 200:
        d = r.json()
        if "access_token" in d:
            token = d["access_token"]
            print(f"\n  Token obtained!")
            break
        elif d.get("error") == "authorization_pending":
            pass  # Keep waiting
        elif d.get("error") == "slow_down":
            interval += 5
        else:
            print(f"\n  Error: {d.get('error')}")
    time.sleep(interval)

if not token:
    print("\nTimeout - user didn't approve. Run again later.")
    exit()

# Step 3: Configure git and push
print("\n=== Pushing to GitHub ===")
gh_headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
}

# Create repo
r = api_post("https://api.github.com/user/repos", {
    "name": REPO,
    "description": "Stock market sentinel - 30+ sectors realtime monitoring",
    "private": False,
    "has_pages": True,
}, timeout=20)
if r:
    if r.status_code == 201:
        print("Repo created")
    elif r.status_code == 422:
        print("Repo exists")
    else:
        print(f"Repo: {r.status_code}")

# Push files via Contents API
print("Pushing files...")
files_pushed = 0
for root, dirs, fnames in os.walk(DIR):
    for fn in fnames:
        if fn in ('.git', '.ghtoken', '.surge_token', 'update.log', 'tunnel-err.txt', 'public-url.txt'):
            continue
        if fn.endswith(('.html', '.json', '.py', '.bat', '.ps1', '.md', '.css', '.js', '.txt')):
            fpath = os.path.join(root, fn)
            rel = os.path.relpath(fpath, DIR).replace('\\', '/')

            with open(fpath, 'rb') as f:
                content = base64.b64encode(f.read()).decode()

            # Check if file exists
            url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO}/contents/{rel}"
            data = {"message": f"Deploy {rel}", "content": content}

            r_check = api_get(url, gh_headers)
            if r_check and r_check.status_code == 200:
                data["sha"] = r_check.json()["sha"]

            r_put = api_put(url, gh_headers, data)
            if r_put and r_put.status_code in [200, 201]:
                files_pushed += 1
                if files_pushed % 10 == 0:
                    print(f"  {files_pushed} files...", end='\r')

print(f"\n  Pushed {files_pushed} files!")

# Enable Pages
print("Enabling GitHub Pages...")
r = api_post(f"https://api.github.com/repos/{GITHUB_USER}/{REPO}/pages",
    {"source": {"branch": "main", "path": "/"}}, timeout=20)
if r:
    print(f"  Pages: {r.status_code}")

print(f"\n{'='*50}")
print(f"  DONE! Your site:")
print(f"  https://{GITHUB_USER}.github.io/{REPO}")
print(f"  (may take 30-60 seconds to go live)")
print(f"{'='*50}")

# Save token for later
with open(os.path.join(DIR, '.ghtoken'), 'w') as f:
    f.write(token)
print("Token saved for future updates")
