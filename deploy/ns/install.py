#!/usr/bin/env python3
"""First-install plan for the independent NS add-on. Dry-run is the default.

This never configures certificates, the original RH stack, or the heavy worker.
An exact local acceptance receipt is required even to produce a reviewed plan.
"""
import argparse
import hashlib
import grp
import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path


INSTALL = Path('/opt/lean-observatory-ns')
DATA = Path('/var/lib/lean-observatory-queue')
PROFILE = 'lean-observatory-ns-worker'
UNITS = ('lean-observatory-ns-web.service', 'lean-observatory-ns-controller.service',
         'lean-observatory-ns-cert-reload.service', 'lean-observatory-ns-cert-reload.path')
CHECKS = ('unit', 'browser', 'compose', 'compile')


def source_files(root):
    root = Path(root)
    for directory in ('ns_queue', 'deploy/ns'):
        location = root / directory
        if not location.is_dir() or location.is_symlink():
            raise RuntimeError('Missing add-on source directory: ' + directory)
        for path in sorted(location.rglob('*')):
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            if path.is_symlink():
                raise RuntimeError('Symlink in add-on source: ' + str(path))
            if path.is_file():
                yield path
    for name in ('compose.ns.yaml', 'compose.ns-worker.yaml'):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('Missing or symlinked add-on Compose file: ' + name)
        yield path


def source_fingerprint(root):
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(source_files(root)):
        digest.update(str(path.relative_to(root)).encode() + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return digest.hexdigest()


def require_receipt(root):
    try:
        report = json.loads((root / 'reports/ns-local-acceptance.json').read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError('NS local acceptance receipt is missing or invalid') from error
    if report.get('sourceSha256') != source_fingerprint(root):
        raise RuntimeError('NS source changed after local acceptance')
    checks = report.get('checks', {})
    if not isinstance(checks, dict) or any(type(checks.get(name, {}).get('exitCode')) is not int or
                                          checks[name]['exitCode'] != 0 for name in CHECKS):
        raise RuntimeError('NS local acceptance checks have not all passed')
    return report


def installation_plan(source_sha, execute=False):
    compose = ['docker', 'compose', '-p', 'lean-observatory-ns', '-f', str(INSTALL / 'compose.ns.yaml')]
    return {'dryRun': not execute, 'sourceSha256': source_sha, 'installRoot': str(INSTALL),
            'dataRoot': str(DATA), 'budgetCapUsd': 0,
            'commands': [
                ['groupadd', '--system', '--gid', '10001', 'lean-observatory-ns'],
                ['apparmor_parser', '-r', '/etc/apparmor.d/' + PROFILE],
                ['python3', '-m', 'ns_queue.control', '--root', str(DATA), 'init', '--hours', '0', '--rh-run', '20565ace60c2'],
                [*compose, 'up', '-d', '--build', '--wait', 'api', 'nginx'],
                ['systemctl', 'daemon-reload'],
                ['systemctl', 'enable', '--now', 'lean-observatory-ns-web.service',
                 'lean-observatory-ns-controller.service', 'lean-observatory-ns-cert-reload.path']]}


def preflight(root):
    if root != INSTALL:
        raise RuntimeError('Execute requires verified source at /opt/lean-observatory-ns')
    if os.geteuid() != 0 or platform.system() != 'Linux':
        raise RuntimeError('Execute requires root on Linux')
    if root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o022:
        raise RuntimeError('Deployment root must be root-owned and not writable by others')
    for path in source_files(root):
        if path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise RuntimeError('Untrusted deployment source ownership: ' + str(path))
    directories = [root / 'ns_queue', root / 'deploy', root / 'deploy/ns', root / 'reports']
    directories += [p for base in ('ns_queue', 'deploy/ns') for p in (root / base).rglob('*') if p.is_dir()]
    if any(p.is_symlink() or p.stat().st_uid != 0 or p.stat().st_mode & 0o022 for p in directories):
        raise RuntimeError('Untrusted deployment directory ownership')
    destinations = [DATA, root / '.env', Path('/etc/apparmor.d') / PROFILE,
                    *(Path('/etc/systemd/system') / unit for unit in UNITS)]
    if any(path.exists() or path.is_symlink() for path in destinations):
        raise RuntimeError('Existing NS installation state: refusing first-install overwrite')
    if Path('/sys/module/apparmor/parameters/enabled').read_text().strip() != 'Y':
        raise RuntimeError('AppArmor must already be enabled')
    for binary in ('docker', 'apparmor_parser', 'systemctl', 'python3', 'groupadd'):
        if shutil.which(binary) is None:
            raise RuntimeError('Missing prerequisite: ' + binary)
    for name in ('fullchain.pem', 'privkey.pem'):
        if not (Path('/etc/letsencrypt/live/lean.tano.asia') / name).is_file():
            raise RuntimeError('Existing TLS certificate required; this installer never modifies certificates')
    subprocess.run(['docker', 'info'], check=True, capture_output=True, timeout=30)
    subprocess.run(['docker', 'compose', 'version'], check=True, capture_output=True, timeout=15)
    existing = subprocess.run(['docker', 'ps', '-a', '-q', '--filter',
                               'label=com.docker.compose.project=lean-observatory-ns'],
                              check=True, capture_output=True, text=True, timeout=15)
    if existing.stdout.strip():
        raise RuntimeError('Existing add-on project containers; refusing first install')
    with socket.socket() as probe:
        probe.bind(('0.0.0.0', 9443))


def install(root, execute=False):
    root = Path(root).absolute()
    receipt = require_receipt(root)
    plan = installation_plan(receipt['sourceSha256'], execute)
    if not execute:
        return plan
    preflight(root)
    # Every write below has a fresh, add-on-specific destination. Parent RH
    # configuration, volumes, containers, certificates and DNS are untouched.
    DATA.mkdir(mode=0o750)
    os.chown(DATA, 0, 10001)
    os.chmod(DATA, 0o2750)
    with (root / '.env').open('x') as config:
        config.write('NS_DATA_ROOT=' + str(DATA) + '\nNS_SOURCE_SHA256=' + receipt['sourceSha256'] + '\n')
    os.chmod(root / '.env', 0o600)
    profile = Path('/etc/apparmor.d') / PROFILE
    shutil.copyfile(root / 'deploy/ns/ns-worker.apparmor', profile)
    os.chmod(profile, 0o644)
    for unit in UNITS:
        target = Path('/etc/systemd/system') / unit
        shutil.copyfile(root / 'deploy/ns' / unit, target)
        os.chmod(target, 0o644)
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'NS_SOURCE_SHA256': receipt['sourceSha256'],
           'NS_DATA_ROOT': str(DATA)}
    for command in plan['commands']:
        if command[0] == 'groupadd':
            try:
                grp.getgrgid(10001)
                continue
            except KeyError:
                pass
        subprocess.run(command, cwd=root, env=env, check=True,
                       timeout=900 if command[:2] == ['docker', 'compose'] else 60)
        if command[0] == 'apparmor_parser':
            profiles = Path('/sys/kernel/security/apparmor/profiles').read_text().splitlines()
            if PROFILE + ' (enforce)' not in profiles:
                raise RuntimeError('New NS AppArmor profile is not enforcing')
        if command[:4] == ['python3', '-m', 'ns_queue.control', '--root']:
            # CLI runs as root; allow the read-only UI UID to traverse and read
            # its SQLite/lock files without giving it write permission.
            for path in DATA.iterdir():
                if path.is_file() and not path.is_symlink():
                    os.chown(path, 0, 10001)
                    os.chmod(path, 0o640)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.execute and args.dry_run:
        parser.error('choose --dry-run or --execute')
    try:
        print(json.dumps(install(args.root, args.execute), indent=2))
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        raise SystemExit('NS installation refused: ' + str(error)) from error


if __name__ == '__main__':
    main()
