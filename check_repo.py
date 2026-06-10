import requests, re

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0'})

# Login
r = s.get('https://gitee.com/login', timeout=15)
tok = re.search(r'name="authenticity_token" value="([^"]+)"', r.text).group(1)
s.post('https://gitee.com/login', data={
    'user[login]': '18896596212', 'user[password]': '123789asd!tt',
    'authenticity_token': tok, 'utf8': '%E2%9C%93',
}, timeout=15, allow_redirects=True)
print('1. Login OK')

# Check repo files via API
r2 = s.get('https://gitee.com/api/v5/repos/tt123497/market-sentinel/contents/', timeout=15)
if r2.status_code == 200:
    files = [f['name'] for f in r2.json()]
    print(f'2. Files: {files}')
else:
    print(f'2. API: {r2.status_code} {r2.text[:200]}')

# Check if index.html exists at root
r3 = s.get('https://gitee.com/api/v5/repos/tt123497/market-sentinel/contents/index.html', timeout=15)
print(f'3. index.html: {r3.status_code}')

# Try to get pages status
r4 = s.get('https://gitee.com/api/v5/repos/tt123497/market-sentinel/pages', timeout=15)
print(f'4. Pages status: {r4.status_code} {r4.text[:300]}')

# Try to enable pages
r5 = s.post('https://gitee.com/api/v5/repos/tt123497/market-sentinel/pages',
    json={'branch': 'master', 'build_directory': '/'}, timeout=15)
print(f'5. Enable Pages: {r5.status_code} {r5.text[:300]}')

print()
print('URL: https://tt123497.gitee.io/market-sentinel')
