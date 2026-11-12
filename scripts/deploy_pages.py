"""Publish dist/ to the gh-pages branch of this repo's origin.

    python scripts/preflight.py && python scripts/deploy_pages.py

A throwaway repo holds only dist/ plus .nojekyll, commits it as "Deploy <sha>" and
force-pushes gh-pages, so the branch carries no source history. Nothing here checks the
build; run the preflight first.

Account safety: `gh` may hold several accounts and git's credential helper follows the
*active* one. The push authenticates as the owner of origin, with a token requested for
that account and set for this process only (GH_TOKEN); the global gh login is never
switched, and the push is refused if the token belongs to anyone else.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
BRANCH = 'gh-pages'


def run(*args, cwd=ROOT, env=None):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


def main():
    if not (DIST / 'index.html').exists():
        sys.exit('dist/index.html is missing: build the site first')
    if run('git', 'status', '--porcelain', '--', '.'):
        print('note: the working tree has uncommitted changes; the deploy is labelled with HEAD')

    remote = run('git', 'remote', 'get-url', 'origin')
    m = re.search(r'github\.com[:/]([^/]+)/', remote)
    if not m:
        sys.exit(f'origin is not a GitHub remote: {remote}')
    owner = m.group(1)

    token = run('gh', 'auth', 'token', '--hostname', 'github.com', '--user', owner)
    env = {**os.environ, 'GH_TOKEN': token}
    login = json.loads(run('gh', 'api', 'user', env=env))['login']
    if login.lower() != owner.lower():
        sys.exit(f'token belongs to {login}, not {owner}; refusing to push')

    name, email = run('git', 'config', 'user.name'), run('git', 'config', 'user.email')
    sha = run('git', 'rev-parse', '--short', 'HEAD')

    staging = Path(tempfile.mkdtemp(prefix='meta-analyzer-pages-'))
    try:
        shutil.copytree(DIST, staging, dirs_exist_ok=True)
        (staging / '.nojekyll').write_text('')   # Jekyll would drop _-prefixed files
        git = lambda *a: run('git', *a, cwd=staging, env=env)
        git('init', '-q', '-b', BRANCH)
        git('config', 'core.autocrlf', 'false')   # ship the exact bytes preflight checked
        git('config', 'user.name', name)
        git('config', 'user.email', email)
        git('config', 'credential.https://github.com.helper', '')
        git('config', '--add', 'credential.https://github.com.helper', '!gh auth git-credential')
        git('add', '-A')
        git('commit', '-q', '-m', f'Deploy {sha}')
        print(f'deploy: pushing {BRANCH} to {remote} as {login}')
        subprocess.run(['git', 'push', '--force', remote, f'{BRANCH}:{BRANCH}'], cwd=staging, env=env, check=True)
        print(f'deploy: published build of {sha}')
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == '__main__':
    main()
