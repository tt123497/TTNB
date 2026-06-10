"""Create GitHub repo and push site via API"""
import requests, json, base64, os, sys

GITHUB_USER = "tt123497"
GITHUB_PASS = "123789asd!tt"
GITHUB_EMAIL = "571335112@qq.com"
REPO_NAME = "market-sentinel"
DIR = r"D:\projects\market-dashboard"

def basic_auth():
    """Create basic auth header"""
    raw = f"{GITHUB_USER}:{GITHUB_PASS}"
    encoded = base64.b64encode(raw.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Accept": "application/vnd.github+json"}

def check_2fa():
    """Test if 2FA is needed"""
    r = requests.get("https://api.github.com/user", headers=basic_auth())
    if r.status_code == 200:
        print(f"Auth OK, user: {r.json().get('login')}")
        return False, None
    elif r.status_code == 401:
        otp_header = r.headers.get("X-GitHub-OTP", "")
        if "required" in otp_header:
            print("2FA is ENABLED - need different approach")
            return True, otp_header
        else:
            print(f"Auth failed: {r.status_code} {r.text[:200]}")
            return True, None
    else:
        print(f"Unexpected: {r.status_code} {r.text[:200]}")
        return True, None

def create_repo(headers):
    """Create the repo"""
    data = {
        "name": REPO_NAME,
        "description": "Stock market sentinel dashboard - 30+ sector realtime monitoring",
        "homepage": f"https://{GITHUB_USER}.github.io/{REPO_NAME}",
        "private": False,
        "has_issues": True,
        "has_projects": False,
        "has_wiki": False,
    }
    r = requests.post("https://api.github.com/user/repos", headers=headers, json=data)
    if r.status_code == 201:
        print(f"Repo created: {r.json().get('html_url')}")
        return True
    elif r.status_code == 422:  # Already exists
        print("Repo already exists")
        return True
    else:
        print(f"Create failed: {r.status_code} {r.text[:300]}")
        return False

def push_via_api(headers):
    """Push files directly via GitHub Contents API"""
    files = {}
    for root, dirs, filenames in os.walk(DIR):
        for fn in filenames:
            if fn.endswith(('.html', '.json', '.py', '.bat', '.ps1', '.md', '.css', '.js')):
                fpath = os.path.join(root, fn)
                relpath = os.path.relpath(fpath, DIR).replace('\\', '/')
                with open(fpath, 'rb') as f:
                    content = base64.b64encode(f.read()).decode()
                files[relpath] = content
    print(f"Files to push: {len(files)}")

    pushed = 0
    for fpath, content in files.items():
        api_url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/contents/{fpath}"
        data = {
            "message": f"Auto deploy: {fpath}",
            "content": content,
            "branch": "main",
        }
        r = requests.put(api_url, headers=headers, json=data)
        if r.status_code in [201, 200]:
            pushed += 1
        elif r.status_code == 422:  # File exists, try update
            # Get SHA first
            r2 = requests.get(api_url, headers=headers)
            if r2.status_code == 200:
                sha = r2.json().get("sha")
                data["sha"] = sha
                r3 = requests.put(api_url, headers=headers, json=data)
                if r3.status_code in [200, 201]:
                    pushed += 1
                else:
                    print(f"  Update failed {fpath}: {r3.status_code} {r3.text[:100]}")
            else:
                print(f"  Get SHA failed {fpath}: {r2.status_code}")
        else:
            print(f"  Push failed {fpath}: {r.status_code} {r.text[:100]}")

    print(f"Pushed: {pushed}/{len(files)}")
    return pushed > 0

def enable_pages(headers):
    """Enable GitHub Pages"""
    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/pages",
        headers=headers,
        json={"source": {"branch": "main", "path": "/"}}
    )
    if r.status_code in [201, 204, 200]:
        print("Pages enabled!")
        return True
    else:
        print(f"Pages: {r.status_code} {r.text[:200]}")
        return False

# Main
print("=== GitHub Deploy ===")
print(f"User: {GITHUB_USER}")

# Step 1: Check auth
needs_2fa, _ = check_2fa()

if needs_2fa:
    print("\n2FA is on. Trying device flow...")
    # Try gh CLI with token
    os.system(f'set GH_TOKEN=&& gh auth login --hostname github.com --git-protocol https --web')
else:
    print("\nNo 2FA - pushing via API...")
    headers = basic_auth()
    if create_repo(headers):
        if push_via_api(headers):
            print(f"\nDONE: https://{GITHUB_USER}.github.io/{REPO_NAME}")
            print("(may take 1-2 min for Pages to activate)")
            enable_pages(headers)
