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
print('Login OK')

# Go to Pages settings
r2 = s.get('https://gitee.com/tt123497/market-sentinel/pages', timeout=15)
print(f'Pages page: {r2.status_code}')

# Check if already active
if '已开启' in r2.text or 'deploying' in r2.text.lower() or 'active' in r2.text.lower():
    print('Pages may already be active or deploying')

# Find CSRF
csrf_meta = re.search(r'<meta[^>]*name="csrf-token"[^>]*content="([^"]+)"', r2.text)
if not csrf_meta:
    # try hidden input
    csrf_input = re.search(r'name="authenticity_token"\s+value="([^"]+)"', r2.text)
    if csrf_input:
        ct = csrf_input.group(1)
        cn = 'authenticity_token'
    else:
        print('No CSRF found')
        print(r2.text[:500])
        exit()
else:
    ct = csrf_meta.group(1)
    cn = 'authenticity_token'
    csrf_pn = re.search(r'<meta[^>]*name="csrf-param"[^>]*content="([^"]+)"', r2.text)
    if csrf_pn:
        cn = csrf_pn.group(1)

print(f'CSRF: {cn}={ct[:20]}...')

# Try to enable Pages
r3 = s.post('https://gitee.com/tt123497/market-sentinel/pages',
    data={'branch': 'master', 'directory': '/', cn: ct, 'utf8': '%E2%9C%93'},
    headers={'X-CSRF-Token': ct, 'X-Requested-With': 'XMLHttpRequest'},
    timeout=15, allow_redirects=True)
print(f'Enable: {r3.status_code} url={r3.url[:80]}')

# Check result
if '已开启' in r3.text or '正在部署' in r3.text:
    print('Pages ENABLED!')
elif r3.status_code in [200, 302] and 'pages' in r3.url:
    print('Pages enabled (via redirect)')
else:
    # Check if there's an error
    err = re.search(r'<div[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</div>', r3.text, re.DOTALL)
    if err:
        print(f'Error: {re.sub("<[^>]+>","",err.group(1)).strip()[:200]}')

print()
print('Site URL: https://tt123497.gitee.io/market-sentinel')
print('Repo URL: https://gitee.com/tt123497/market-sentinel')
