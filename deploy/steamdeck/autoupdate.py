#!/usr/bin/env python3
"""Poll the public master branch; test, deploy, and roll back failed starts."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(os.environ.get('BOT_DEPLOY_ROOT', str(Path.home() / 'server/discord-quote-bot')))
REPOSITORY = 'https://github.com/Imdad3456/discord-quote-bot.git'
BRANCH = 'master'
IMAGES = {'bot': 'localhost/discord-quote-bot', 'lavalink': 'localhost/discord-lavalink'}
SERVICES = ['discord-lavalink.service', 'discord-quote-bot.service']


def run(*args, capture=False, timeout=600):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE if capture else None,
                          timeout=timeout).stdout


def save(state):
    path = ROOT / 'deploy-state.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(path)


def healthy():
    # Check Discord guild availability and the authenticated Lavalink connection path.
    code = '''import json,os,urllib.request
url="http://127.0.0.1:8080/api/"+os.environ["DASHBOARD_TOKEN"]+"/state"
assert json.load(urllib.request.urlopen(url, timeout=5))["players"]
request=urllib.request.Request(os.environ["LAVALINK_URI"]+"/v4/info",headers={"Authorization":os.environ["LAVALINK_PASSWORD"]})
assert json.load(urllib.request.urlopen(request, timeout=5))["version"]
'''
    for _ in range(60):
        try:
            subprocess.run(['podman', 'exec', 'discord-quote-bot', 'python', '-c', code],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            return True
        except (subprocess.SubprocessError, OSError):
            time.sleep(3)
    return False


def switch(candidate, previous):
    """Only called after build/tests pass. Restore both images if activation fails."""
    try:
        run('systemctl', '--user', 'stop', 'discord-quote-bot.service', timeout=70)
        run('python3', str(ROOT / 'backup-data.py'), timeout=60)
        run('systemctl', '--user', 'stop', 'discord-lavalink.service', timeout=70)
        for name, image in candidate.items():
            run('podman', 'tag', image, IMAGES[name] + ':current')
        run('systemctl', '--user', 'start', *SERVICES, timeout=90)
        if not healthy():
            raise RuntimeError('New deployment failed the Discord/dashboard/Lavalink health check')
    except Exception:
        print('Activation failed; restoring previous images', flush=True)
        run('systemctl', '--user', 'stop', 'discord-quote-bot.service', 'discord-lavalink.service', timeout=100)
        for name, image in previous.items():
            run('podman', 'tag', image, IMAGES[name] + ':current')
        run('systemctl', '--user', 'start', *SERVICES, timeout=90)
        if not healthy():
            raise RuntimeError('Rollback also failed health checks; inspect the user service journal')
        raise


def deploy(retry=False):
    repo = ROOT / 'repository'
    if not (repo / '.git').exists():
        run('git', 'clone', '--single-branch', '--branch', BRANCH, REPOSITORY, str(repo))
    run('git', '-C', str(repo), 'fetch', '--prune', 'origin', BRANCH, timeout=90)
    sha = run('git', '-C', str(repo), 'rev-parse', 'origin/' + BRANCH, capture=True).strip()
    state = json.loads((ROOT / 'deploy-state.json').read_text())
    if sha == state.get('deployed'):
        print('Already deployed ' + sha, flush=True)
        return
    if sha == state.get('failed') and not retry:
        print('Previously failed ' + sha + '; push a fix or run update.sh --retry', flush=True)
        return
    previous = {name: run('podman', 'image', 'inspect', '--format', '{{.Id}}', image + ':current',
                          capture=True).strip() for name, image in IMAGES.items()}
    candidate = {name: image + ':' + sha for name, image in IMAGES.items()}
    try:
        with tempfile.TemporaryDirectory(prefix='build-', dir=ROOT) as directory:
            archive = ROOT / 'source.tar'
            run('git', '-C', str(repo), 'archive', '--format=tar', '-o', str(archive), sha)
            run('tar', '-xf', str(archive), '-C', directory)
            archive.unlink()
            run('podman', 'build', '--label', 'org.opencontainers.image.revision=' + sha,
                '-t', candidate['bot'], '-f', directory + '/deploy/steamdeck/Containerfile', directory)
            run('podman', 'run', '--rm', '--network', 'none', candidate['bot'],
                'python', '-m', 'unittest', 'discover', '-s', 'tests', '-v', timeout=120)
            run('podman', 'build', '--label', 'org.opencontainers.image.revision=' + sha,
                '-t', candidate['lavalink'], directory + '/deploy/lavalink')
        switch(candidate, previous)
    except Exception as error:
        state.update(failed=sha, error=str(error), failed_at=int(time.time()))
        save(state)
        raise
    for name, image in previous.items():
        run('podman', 'tag', image, IMAGES[name] + ':previous')
    state.update(deployed=sha, previous=state.get('deployed'), images=candidate,
                 deployed_at=int(time.time()))
    for key in ('failed', 'error', 'failed_at'):
        state.pop(key, None)
    save(state)
    print('Successfully deployed ' + sha, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retry', action='store_true', help='Retry a revision that failed earlier')
    args = parser.parse_args()
    os.umask(0o077)
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'deploy.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another deployment is in progress', flush=True)
            return
        deploy(args.retry)


if __name__ == '__main__':
    main()
