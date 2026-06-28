import requests, re, json

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0'})

# Login
r = s.get('https://gitee.com/login', timeout=15)
tok = re.search(r'name="authenticity_token" value="([^"]+)"', r.text).group(1)
s.post('https://gitee.com/login', data={
    'user[login]': '18896596212', 'user[password]': '123789asd!tt',
    'authenticity_token': tok, 'utf8': '%E2%9C%93',
}, timeout=15, allow_redirects=True)
print('Login OK')

# Get cookies for API
cookies = s.cookies.get_dict()
print(f'Cookies: {list(cookies.keys())}')

# Try API auth with session cookie
gitee_session = cookies.get('gitee-session-n', '')

# Gitee API uses OAuth or Basic Auth for most endpoints
# The Pages API might need the session cookie
headers = {
    'User-Agent': 'Mozilla/5.0',
    'Cookie': '; '.join([f'{k}={v}' for k, v in cookies.items()]),
    'X-CSRF-Token': tok,
    'Content-Type': 'application/json',
}

# Try the enterprise API path
urls = [
    'https://gitee.com/api/v5/repos/tt123497/market-sentinel/pages',
    'https://gitee.com/tt123497/market-sentinel/pages/deploy',
    'https://gitee.com/api/v5/repos/tt123497/market-sentinel/pages/builds',
]

for url in urls:
    # Try POST to enable
    r = requests.post(url, json={'branch': 'master'}, headers=headers, timeout=15)
    print(f'POST {url}: {r.status_code} {r.text[:200]}')

    # Try PUT
    r2 = requests.put(url, json={'branch': 'master'}, headers=headers, timeout=15)
    print(f'PUT  {url}: {r2.status_code} {r2.text[:200]}')

# Try the Gitee Pages API that the web UI might call
# The web UI typically calls an internal API
internal_urls = [
    'https://gitee.com/tt123497/market-sentinel/-/pages',
    'https://gitee.com/api/v5/repos/tt123497/market-sentinel/pages',
]

# Try getting current pages status
r3 = requests.get('https://gitee.com/tt123497/market-sentinel/pages', headers=headers, timeout=15)
print(f'GET pages: {r3.status_code} {r3.text[:100]}')
