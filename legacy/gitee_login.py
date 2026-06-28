import requests, re, os, sys, time

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36'})

# Step 1: Get login page CSRF
r = s.get('https://gitee.com/login', timeout=15)
print(f"Login page: {r.status_code}")

tok = re.search(r'name="authenticity_token" value="([^"]+)"', r.text)
if not tok:
    print("No auth token")
    sys.exit(1)

# Step 2: Login with phone
r2 = s.post('https://gitee.com/login', data={
    'user[login]': '18896596212',
    'user[password]': '123789asd!tt',
    'authenticity_token': tok.group(1),
    'utf8': '%E2%9C%93',
}, timeout=15, allow_redirects=True)

print(f"Login response: {r2.status_code} -> {r2.url[:80]}")

# Check if login succeeded
if 'tt123497' in r2.text or '/dashboard' in r2.url or 'passport' not in r2.url:
    print("Login SUCCESS!")
else:
    print("Login failed, checking...")
    # Try to find error
    err = re.search(r'<div[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</div>', r2.text, re.DOTALL)
    if err:
        print(f"Error: {err.group(1).strip()[:200]}")
    # Check if redirected to login
    if '/login' in r2.url:
        print("Still on login page - credentials may be wrong or blocked")
    sys.exit(1)

# Step 3: Create repo
r3 = s.get('https://gitee.com/projects/new', timeout=15)
tok2 = re.search(r'name="authenticity_token" value="([^"]+)"', r3.text)
if not tok2:
    print(f"No token on new page (status: {r3.status_code})")
    print(r3.text[:500])
    sys.exit(1)

r4 = s.post('https://gitee.com/projects', data={
    'project[name]': 'market-sentinel',
    'project[description]': 'sentinel',
    'project[private]': '0',
    'project[auto_init]': '0',
    'authenticity_token': tok2.group(1),
    'utf8': '%E2%9C%93',
}, timeout=15, allow_redirects=True)

print(f"Create repo: {r4.status_code} -> {r4.url[:80]}")

if 'market-sentinel' in r4.url:
    print("REPO CREATED!")
elif r4.status_code == 200 and ('已存在' in r4.text or 'exist' in r4.text.lower()):
    print("REPO EXISTS")
else:
    # Check error
    err = re.search(r'<div[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</div>', r4.text, re.DOTALL)
    if err:
        print(f"Error: {err.group(1).strip()[:200]}")
    else:
        print("Unknown result, trying to push anyway")

# Save cookies for reuse
import pickle
with open(os.path.join(r'D:\projects\market-dashboard', 'gitee_cookies.pkl'), 'wb') as f:
    pickle.dump(s.cookies, f)

# Get user info
r5 = s.get('https://gitee.com/api/v5/user', timeout=15)
print(f"API user: {r5.status_code}")
if r5.status_code == 200:
    u = r5.json()
    print(f"User: {u.get('login')} / {u.get('name')}")
    # Get token
    r6 = s.post('https://gitee.com/oauth/token', data={
        'grant_type': 'password',
        'username': '18896596212',
        'password': '123789asd!tt',
        'client_id': 'd9c1661dbc470d6c9fc90a0d96a3539cac14043c28c73d61e3fd63a561990e00',
        'client_secret': 'fe4b6e9e8c7c5d3a2b1f0e9d8c7b6a5f4e3d2c1b0a9',
        'scope': 'user_info projects'
    })
    print(f"Token: {r6.status_code}")
    if r6.status_code == 200:
        print(f"TOKEN: {r6.json().get('access_token','')[:20]}...")
