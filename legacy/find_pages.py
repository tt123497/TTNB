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

# Check settings page for all internal links
r2 = s.get('https://gitee.com/tt123497/market-sentinel/settings', timeout=15)
print(f'Settings page: {r2.status_code} ({len(r2.text)} bytes)')

# Find all internal hrefs in settings page
hrefs = re.findall(r'href="(/tt123497/market-sentinel/[^"]+)"', r2.text)
hrefs = sorted(set(hrefs))
print(f'\nRepo links found ({len(hrefs)}):')
for h in hrefs:
    print(f'  {h}')

# Also find all sidebar menu links
menu_links = re.findall(r'href="(/[^"]+)"[^>]*>\s*<span[^>]*>([^<]+)</span>', r2.text)
print(f'\nMenu links ({len(menu_links)}):')
for url, text in menu_links:
    print(f'  {url} -> {text.strip()}')

# Check repo main page for service menu
r3 = s.get('https://gitee.com/tt123497/market-sentinel', timeout=15)
print(f'\nRepo main: {r3.status_code}')

# Find tabs/buttons on the repo page
tabs = re.findall(r'<a[^>]*class="[^"]*tab[^"]*"[^>]*>(.*?)</a>', r3.text, re.DOTALL)
print(f'Tabs: {[re.sub(r"<[^>]+>","",t).strip() for t in tabs]}')

# Find all nav items
nav_items = re.findall(r'<a[^>]*class="[^"]*(?:nav|menu|tab|item)[^"]*"[^>]*>(.*?)</a>', r3.text, re.DOTALL)
nav_texts = [re.sub(r'<[^>]+>', '', n).strip()[:30] for n in nav_items if re.sub(r'<[^>]+>', '', n).strip()]
print(f'Nav items: {nav_texts[:20]}')

# Search for "pages" or "服务" in main repo page
for word in ['pages', 'Pages', 'PAGES', '服务', 'service', 'gitee.io', 'static', '静态']:
    cnt = r3.text.count(word)
    if cnt > 0:
        idx = r3.text.find(word)
        print(f'  "{word}" found {cnt}x, first at pos {idx}: ...{r3.text[max(0,idx-30):idx+50]}...')
