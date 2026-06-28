import requests, os

user = 'tt123497'
pw = '123789asd!tt'
print(f'User: {user}')

# Auth check
r = requests.get('https://api.github.com/user', auth=(user, pw), timeout=15)
print(f'Auth: {r.status_code}')

if r.status_code == 200:
    data = r.json()
    login_name = data.get('login')
    print(f'Login: {login_name}')

    # Create repo
    r2 = requests.post('https://api.github.com/user/repos', auth=(user, pw),
        json={'name': 'market-sentinel', 'description': 'sentinel', 'private': False, 'auto_init': False},
        timeout=15)
    print(f'Repo create: {r2.status_code}')
    if r2.status_code not in [201, 422]:
        print(r2.text[:300])
    else:
        print('Repo ready')

    # Add SSH key
    pubkey_path = os.path.expanduser(r'~\.ssh\id_ed25519.pub')
    with open(pubkey_path) as f:
        pubkey = f.read().strip()
    print(f'SSH key length: {len(pubkey)}')

    r3 = requests.post('https://api.github.com/user/keys', auth=(user, pw),
        json={'title': 'home-pc-sentinel', 'key': pubkey}, timeout=15)
    print(f'SSH add: {r3.status_code}')
    if r3.status_code == 201:
        print('SSH KEY ADDED!')
    elif r3.status_code == 422:
        print('SSH key already exists (OK)')
    else:
        print(r3.text[:200])

    # Build git remote and push
    print()
    print('Repo: git@github.com:{}/market-sentinel.git'.format(login_name))
    print('Pages: https://{}.github.io/market-sentinel'.format(login_name))
elif r.status_code == 401:
    print('Bad credentials - might need OTP/2FA')
else:
    print('Network error or blocked')
    print(r.text[:200] if r.text else 'no body')
