"""Sync data.json to Gitee - keep the site updated"""
import os, subprocess, time

DIR = r'D:\projects\market-dashboard'
GIT = r'D:\Tools\Git\bin\git.exe'

def sync():
    try:
        subprocess.run([GIT, '-C', DIR, 'add', 'data.json'], capture_output=True, timeout=10)
        result = subprocess.run([GIT, '-C', DIR, 'commit', '-m', f'auto update {time.strftime("%H:%M")}'],
                               capture_output=True, timeout=10, text=True)
        if 'nothing to commit' not in result.stdout + result.stderr:
            push = subprocess.run([GIT, '-C', DIR, 'push', 'origin', 'master'],
                                 capture_output=True, timeout=30, text=True)
            print(f"[{time.strftime('%H:%M:%S')}] Synced to Gitee")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] No changes")
    except Exception as e:
        print(f"Sync error: {e}")

if __name__ == '__main__':
    print(f"Syncing every 30 min...")
    while True:
        sync()
        time.sleep(1800)
