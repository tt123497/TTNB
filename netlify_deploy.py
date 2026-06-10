"""Deploy to Netlify - no account required, free, China-accessible"""
import requests, os, io, zipfile

DIR = r'D:\projects\market-dashboard'

# Create zip
zip_buf = io.BytesIO()
with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, fnames in os.walk(DIR):
        for fn in fnames:
            if fn.endswith(('.html', '.css', '.js', '.json')):
                fpath = os.path.join(root, fn)
                rel = os.path.relpath(fpath, DIR)
                zf.write(fpath, rel)

zip_data = zip_buf.getvalue()
print(f"Zip: {len(zip_data)} bytes, {len([n for n in os.listdir(DIR) if n.endswith('.html')])} HTML files")

# Create site
r = requests.post('https://api.netlify.com/api/v1/sites', json={}, timeout=15)
if r.status_code != 201:
    print(f"Create site failed: {r.status_code} {r.text[:200]}")
    exit()

site = r.json()
site_id = site['id']
site_url = site.get('ssl_url') or site.get('url', '')
print(f"Site: {site_url}")

# Deploy
r2 = requests.post(
    f'https://api.netlify.com/api/v1/sites/{site_id}/deploys',
    data=zip_data,
    headers={'Content-Type': 'application/zip'},
    timeout=30
)
if r2.status_code == 200:
    deploy = r2.json()
    url = deploy.get('ssl_url') or deploy.get('url', site_url)
    print(f"Deployed: {url}")
    with open(os.path.join(DIR, 'public-url.txt'), 'w') as f:
        f.write(url)
else:
    print(f"Deploy failed: {r2.status_code}")
    print(r2.text[:300])
