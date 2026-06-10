import requests, re, os

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0'})

# Login
r = s.get('https://gitee.com/login', timeout=15)
tok = re.search(r'name="authenticity_token" value="([^"]+)"', r.text).group(1)
s.post('https://gitee.com/login', data={
    'user[login]': '18896596212', 'user[password]': '123789asd!tt',
    'authenticity_token': tok, 'utf8': '%E2%9C%93',
}, timeout=15, allow_redirects=True)
print("Login OK")

# Get create page, examine the form
r3 = s.get('https://gitee.com/tt123497/projects/new', timeout=15)

# Find ALL form actions
forms = re.findall(r'<form[^>]*action="([^"]*)"[^>]*>', r3.text)
print(f"Forms: {forms}")

# Find ALL input names in the main form
# Get the form area
form_match = re.search(r'(<form[^>]*id="new_project"[^>]*>.*?</form>)', r3.text, re.DOTALL)
if form_match:
    form_html = form_match.group(1)
    inputs = re.findall(r'name="([^"]+)"', form_html)
    print(f"Form inputs: {inputs}")
    # Check if repo name has sub-fields
    if 'project[namespace_id]' in form_html or 'project[path]' in form_html:
        print("Has namespace/path fields")
else:
    # Just search for the form differently
    form2 = re.search(r'(<form[^>]*accept-charset[^>]*>.*?</form>)', r3.text, re.DOTALL)
    if form2:
        inputs = re.findall(r'name="([^"]+)"', form2.group(1))
        print(f"Form2 inputs: {inputs}")

# Get CSRF
csrf_meta = re.search(r'<meta[^>]*name="csrf-token"[^>]*content="([^"]+)"', r3.text)
csrf_token = csrf_meta.group(1) if csrf_meta else None

# Try POST to /tt123497/projects (the URL we're already on)
if csrf_token:
    # Try with proper headers mimicking browser
    headers = {
        'X-CSRF-Token': csrf_token,
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': 'https://gitee.com',
        'Referer': 'https://gitee.com/tt123497/projects/new',
    }
    r4 = s.post('https://gitee.com/tt123497/projects',
        data={
            'project[name]': 'market-sentinel',
            'project[path]': 'market-sentinel',
            'project[description]': 'sentinel',
            'project[private]': '0',
            'project[auto_init]': '0',
            'authenticity_token': csrf_token,
            'utf8': '%E2%9C%93',
        },
        headers=headers,
        timeout=15, allow_redirects=True)

    print(f"\nPOST result: {r4.status_code} -> {r4.url[:100]}")

    # Check for error message
    err = re.search(r'<div[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</div>', r4.text, re.DOTALL)
    if err:
        err_text = re.sub(r'<[^>]+>', '', err.group(1)).strip()
        print(f"Error: {err_text[:300]}")
    else:
        # Check page title or flash message
        flash = re.search(r'<div[^>]*class="[^"]*flash[^"]*"[^>]*>(.*?)</div>', r4.text, re.DOTALL)
        if flash:
            print(f"Flash: {re.sub(r'<[^>]+>','',flash.group(1)).strip()[:200]}")

    # Check if redirected to repo page
    if 'market-sentinel' in r4.url:
        print("SUCCESS! Repo created!")
    else:
        # Print form errors
        field_errors = re.findall(r'<span[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</span>', r4.text)
        if field_errors:
            for e in field_errors[:3]:
                print(f"Field error: {re.sub(r'<[^>]+>','',e).strip()[:100]}")
