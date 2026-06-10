import subprocess, json, os

# Use the cookies from gitee_cookies.pkl + direct API call with session token
import pickle, requests

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0'})

# Load saved cookies from earlier login
pkl_path = r'D:\projects\market-dashboard\gitee_cookies.pkl'
if os.path.exists(pkl_path):
    with open(pkl_path, 'rb') as f:
        s.cookies = pickle.load(f)
    print("Loaded cookies from cache")

    # Test if still valid
    r = s.get('https://gitee.com/api/v5/user', timeout=15)
    if r.status_code == 200:
        user = r.json().get('login')
        print(f"Session alive! User: {user}")

        # Now enable Pages
        r2 = s.post(f'https://gitee.com/api/v5/repos/{user}/market-sentinel/pages',
            json={'branch': 'master', 'build_directory': '/'},
            timeout=15)
        print(f"Enable: {r2.status_code}")
        print(r2.text[:300])

        if r2.status_code == 201:
            print("PAGES ENABLED!")
            print("URL: https://tt123497.gitee.io/market-sentinel")
    else:
        print(f"Session expired: {r.status_code}")
        print(r.text[:200])
else:
    print("No cookie file found. Need fresh login.")

    # Do a fresh login
    import re
    r = s.get('https://gitee.com/login', timeout=15)
    tok = re.search(r'name="authenticity_token" value="([^"]+)"', r.text).group(1)
    r2 = s.post('https://gitee.com/login', data={
        'user[login]': '18896596212',
        'user[password]': '123789asd!tt',
        'authenticity_token': tok,
        'utf8': '%E2%9C%93',
    }, timeout=15, allow_redirects=True)
    print(f"Login: {r2.status_code} url={r2.url[:60]}")

    # Save cookies
    with open(pkl_path, 'wb') as f:
        pickle.dump(s.cookies, f)
    print("Saved cookies")

    # Try to enable pages
    r3 = s.post('https://gitee.com/api/v5/repos/tt123497/market-sentinel/pages',
        json={'branch': 'master', 'build_directory': '/'},
        timeout=15)
    print(f"Enable: {r3.status_code} {r3.text[:300]}")
