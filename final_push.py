"""One-shot: push everything to GitHub with PAT token"""
import subprocess, sys, os

GIT = r'D:\Tools\Git\bin\git.exe'
DIR = r'D:\projects\market-dashboard'

def run(cmd):
    return subprocess.run(cmd, cwd=DIR, capture_output=True, text=True, timeout=60)

if len(sys.argv) < 2:
    print("Usage: python final_push.py <github_token>")
    print("Get token at: https://github.com/settings/tokens/new")
    print("Scopes needed: repo, workflow, admin:public_key")
    sys.exit(1)

token = sys.argv[1]
print(f"Token: {token[:10]}...")

# Set remote
run([GIT, 'remote', 'remove', 'origin'])
run([GIT, 'remote', 'add', 'origin', f'https://oauth2:{token}@github.com/tt123497/market-sentinel.git'])

# Restore .github files
run([GIT, 'add', '.github/'])
run([GIT, 'add', '-A'])

# Commit
result = run([GIT, 'commit', '--allow-empty', '-m', 'final deploy: live update system + workflows'])
print(result.stdout[-200:] if result.stdout else 'no changes')

# Push
print("Pushing...")
result = run([GIT, 'push', 'origin', 'main', '--force'])
if result.returncode == 0:
    print("SUCCESS!")
    print("Site: https://tt123497.github.io/market-sentinel/")
    print("Workflows will run every 15 min during trading hours")
else:
    print(f"FAILED: {result.stderr[-300:]}")
