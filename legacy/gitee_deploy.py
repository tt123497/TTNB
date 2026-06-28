"""Deploy to Gitee Pages - using token-based auth"""
import requests, json, time, os, base64

EMAIL = "571335112@qq.com"
PASSWORD = "123789asd!tt!"
DIR = r"D:\projects\market-dashboard"

def req(method, url, **kw):
    h = {"Accept": "application/json", "Content-Type": "application/json;charset=UTF-8"}
    if 'headers' in kw: h.update(kw.pop('headers'))
    for i in range(3):
        try:
            r = requests.request(method, url, headers=h, timeout=20, **kw)
            return r
        except Exception as e:
            if i < 2: time.sleep(3)
    return None

# Try to create Gitee account
print("=== Creating Gitee Account ===")
r = req("POST", "https://gitee.com/api/v5/users", json={
    "email": EMAIL, "password": PASSWORD,
    "login": "tt123497", "name": "tt123497"
})
if r:
    print(f"Response: {r.status_code}")
    print(r.text[:300])
else:
    print("Network unreachable for account creation")

# Try OAuth with form data instead of JSON
print("\n=== Try OAuth ===")
r = req("POST", "https://gitee.com/oauth/token", data={
    "grant_type": "password",
    "username": EMAIL,
    "password": PASSWORD,
    "client_id": "1b0d6c7a8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b",
    "client_secret": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    "scope": "user_info projects"
})
if r:
    print(f"OAuth: {r.status_code}")
    if r.status_code == 200:
        print(f"Token: {r.json().get('access_token','?')[:20]}...")
    else:
        print(r.text[:300])
else:
    print("OAuth endpoint unreachable")
