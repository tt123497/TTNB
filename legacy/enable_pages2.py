import requests, re

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

# Login
r = s.get('https://gitee.com/login', timeout=15)
tok = re.search(r'name="authenticity_token" value="([^"]+)"', r.text).group(1)
s.post('https://gitee.com/login', data={
    'user[login]': '18896596212', 'user[password]': '123789asd!tt',
    'authenticity_token': tok, 'utf8': '%E2%9C%93',
}, timeout=15, allow_redirects=True)
print('Login OK')

# Get the settings page - find the Pages API endpoint from JS
r2 = s.get('https://gitee.com/tt123497/market-sentinel/settings', timeout=15)
print(f'Settings: {r2.status_code}')

# Try the API with session cookies
cookies_dict = s.cookies.get_dict()
cookie_str = '; '.join([f'{k}={v}' for k, v in cookies_dict.items()])
print(f'Cookies: {list(cookies_dict.keys())}')

# Try API with cookies
r3 = requests.get('https://gitee.com/api/v5/user',
    headers={'User-Agent': 'Mozilla/5.0', 'Cookie': cookie_str},
    timeout=15)
print(f'API with cookie: {r3.status_code}')
if r3.status_code == 200:
    user = r3.json().get('login')
    print(f'User: {user}')

    # Now try to enable pages
    r4 = requests.post(f'https://gitee.com/api/v5/repos/{user}/market-sentinel/pages',
        headers={'User-Agent': 'Mozilla/5.0', 'Cookie': cookie_str, 'Content-Type': 'application/json'},
        json={'branch': 'master', 'build_directory': '/'},
        timeout=15)
    print(f'Enable Pages: {r4.status_code}')
    print(f'Response: {r4.text[:300]}')
else:
    print(r3.text[:200])

# Also try direct HTML post to settings/pages endpoint
r5 = s.get('https://gitee.com/tt123497/market-sentinel/settings/pages', timeout=15)
print(f'Settings/pages: {r5.status_code}')
