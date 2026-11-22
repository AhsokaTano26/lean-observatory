"""Rebind verified receipts for explicit reviewed Lean API and sandbox policy repairs.

No build command is run. The immutable write-ahead directory retains exact old
and proposed bytes, so interrupted replacements can only resume that transaction.
"""
import argparse
import ast
import contextlib
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .ns_worker import STAGES, file_hash, json_hash, validate_spec
from .store import QueueStore

MIGRATION_ID = 'audit-lean-loginfo-v1'
SCOPE = 'audit_script: qualify exactly two NS_ logInfo calls with Lean; preserve source/dependencies/compile execution'
NAMES = ('ns_worker.py', 'process.py', 'sandbox.py', 'child.py', 'build-tools.sh',
         'manifest.json', 'budget.py', 'admission.py', 'gates.py')
PRESERVED = STAGES[:3]
OLD = '\n    logInfo m!"NS_'
NEW = '\n    Lean.logInfo m!"NS_'
KERNEL_FIXES = (('import Export.Parse\n', 'import Comparator.Compare\n'),
                ('let some path := args[0]?', 'let some path := args.head?'),
                ('IO.FS.readFile path', 'IO.FS.readFile (System.FilePath.mk path)'),
                ('let stream ← IO.FS.Stream.ofBuffer ref', 'let stream := IO.FS.Stream.ofBuffer ref'))
REPAIRS = {'audit-namespace': (MIGRATION_ID, SCOPE, 'audit'),
           'kernel-api': ('kernel-lean-api-v1',
                          'REPLAY: four Lean API compatibility changes; preserve source/dependencies/compile/audit execution',
                          'kernel'),
           'independent-policy': ('independent-policy-v1',
                                  'independent policy only: measured layered guard and exact ABI4 warning; preserve five passed stages',
                                  'independent')}
APPROVED_POLICY_SHA256 = '88a28f32381b31e83a1ecbd553a446c0c59e8539eb5f3ede46e6d97c3ee3f878'
POLICY_IMPORT = 'from . import sandbox_policy\n'
POLICY_APPEND_OLD = "'gates.py']}"
POLICY_APPEND_NEW = "'gates.py', 'sandbox_policy.py']}"


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def _transaction_file(directory, migration_id, name):
    prefix = migration_id + '.' if migration_id != MIGRATION_ID else ''
    return directory / (prefix + name)


def _read(path):
    path = Path(path)
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file():
        raise ValueError('nonregular or symlink migration input: ' + str(path))
    return path.read_bytes()


def _sync(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def _write(path, content):
    with Path(path).open('xb') as stream:
        stream.write(content); stream.flush(); os.fchmod(stream.fileno(), 0o444); os.fsync(stream.fileno())


def _replace_receipt(path, content):
    # Existing checkpoint bytes are already backed up in the durable manifest.
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.migration-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content); stream.flush(); os.fchmod(stream.fileno(), 0o644); os.fsync(stream.fileno())
        os.replace(temporary, path); _sync(path.parent)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _state_check(state, receipt_hashes, preserved, phase):
    if not state or state.get('status') != 'PAUSED' or state.get('phase') != phase:
        raise ValueError('migration requires PAUSED state at ' + phase)
    validate_spec(state['spec'])
    for stage in preserved:
        rows = [row for row in state['stages'] if row['id'] == stage]
        if (len(rows) != 1 or rows[0].get('status') != 'PASSED' or
                type(rows[0].get('exitCode')) is not int or rows[0]['exitCode'] != 0 or
                rows[0].get('checkpointSha256') not in receipt_hashes[stage]):
            raise ValueError('queue successful checkpoint differs: ' + stage)
    if any(row.get('status') == 'PASSED' for row in state['stages'] if row['id'] in STAGES[len(preserved):]):
        raise ValueError('later stage already succeeded')
    if any(command.get('status') == 'RUNNING' for command in state.get('commands', [])):
        raise ValueError('queue still contains a running command')


def _verify_change(old, current_bytes, repair):
    if repair == 'audit-namespace':
        if old.count(OLD) != 2 or old.replace(OLD, NEW).encode() != current_bytes:
            raise ValueError('worker change is not exactly the reviewed two-call namespace fix')
        generator = old.split('\ndef audit_script(', 1)
        if len(generator) != 2 or generator[1].split('\n\nREPLAY =', 1)[0].count(OLD) != 2:
            raise ValueError('namespace fix is outside audit_script')
    elif repair == 'kernel-api':
        region = old.split("\n\nREPLAY = '''", 1)
        if len(region) != 2: raise ValueError('missing fixed REPLAY template')
        region = region[1].split("\n'''", 1)[0]
        transformed = old
        for before, after in KERNEL_FIXES:
            if old.count(before) != 1 or region.count(before) != 1:
                raise ValueError('kernel API repair is not exactly the four REPLAY replacements')
            transformed = transformed.replace(before, after)
        if transformed.encode() != current_bytes:
            raise ValueError('worker change exceeds the reviewed kernel API repair')
    else:
        current = current_bytes.decode()
        imports = [node for node in ast.parse(current).body if isinstance(node, ast.ImportFrom) and
                   node.level == 1 and node.module is None and len(node.names) == 1 and
                   node.names[0].name == 'sandbox_policy' and node.names[0].asname is None]
        if (old.count(POLICY_IMPORT) != 0 or current.count('\n' + POLICY_IMPORT) != 1 or len(imports) != 1 or
                old.count(POLICY_APPEND_OLD) != 1 or current.count(POLICY_APPEND_NEW) != 1 or
                current.count(POLICY_APPEND_OLD) != 0 or old.count(POLICY_APPEND_NEW) != 0):
            raise ValueError('independent repair requires exactly the policy import and implementation append')
        normalized = current.replace(POLICY_IMPORT, '').replace(POLICY_APPEND_NEW, POLICY_APPEND_OLD)
        if _without_policy_functions(old) != _without_policy_functions(normalized):
            raise ValueError('worker change exceeds the two independent policy functions')



def _without_policy_functions(source):
    tree = ast.parse(source); spans = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'validate_independent_output':
            spans.append(node)
        if isinstance(node, ast.ClassDef) and node.name == 'NSWorker':
            spans.extend(method for method in node.body if isinstance(method, ast.FunctionDef) and method.name == '_independent')
    if (len(spans) != 2 or {node.name for node in spans} != {'validate_independent_output', '_independent'} or
            any(node.decorator_list for node in spans)):
        raise ValueError('independent policy function boundaries differ')
    lines = source.splitlines(keepends=True)
    for node in sorted(spans, key=lambda node: node.lineno, reverse=True):
        lines[node.lineno - 1:node.end_lineno] = ['# APPROVED_POLICY_FUNCTION:' + node.name + '\n']
    return ''.join(lines)


def _verify_prior_migration(root, state, originals, implementation, seed, allowed_roots, profile):
    """Verify every ancestor manifest and original/proposed receipt against its ledger."""
    migration_id, scope, phase = REPAIRS[profile]; preserved = STAGES[:STAGES.index(phase)]
    directory = root / 'worker/checkpoints/migrations' / migration_id
    ledgers = [entry for entry in state.get('checkpointMigrations', []) if entry.get('id') == migration_id]
    if len(ledgers) != 1: raise ValueError('missing committed prior migration: ' + migration_id)
    ledger = ledgers[0]
    expected_path = str(_transaction_file(directory, migration_id, 'manifest.json').relative_to(root))
    if ledger.get('manifestPath') != expected_path: raise ValueError('prior migration manifest path differs')
    content = _read(root / ledger['manifestPath']); manifest = json.loads(content)
    if (ledger.get('scope') != scope or ledger.get('manifestSha256') != _sha(content) or
            manifest.get('id') != migration_id or manifest.get('scope') != scope or
            manifest.get('allowedRoots') != list(map(str, allowed_roots)) or
            manifest.get('newImplementation') != implementation or manifest.get('newSeedSha256') != seed or
            ledger.get('receipts') != manifest.get('receipts') or set(manifest.get('receipts', {})) != set(preserved)):
        raise ValueError('prior migration manifest/ledger differs: ' + migration_id)
    old_implementation = manifest.get('oldImplementation', {})
    if (set(old_implementation) != set(NAMES) or set(implementation) != set(NAMES) or
            any(old_implementation[name] != implementation[name] for name in NAMES if name != 'ns_worker.py')):
        raise ValueError('prior migration implementation differs')
    previous = json_hash({'spec': state['spec'], 'implementation': old_implementation})
    if previous != manifest.get('oldSeedSha256'): raise ValueError('prior migration seed differs')
    saved = {stage: _read(_transaction_file(directory, migration_id, stage + '.original.json')) for stage in preserved}
    if profile == 'kernel-api':
        ancestor = _verify_prior_migration(root, state, saved, old_implementation, previous, allowed_roots, 'audit-namespace')
        if manifest.get('priorMigrationManifestSha256') != ancestor: raise ValueError('ancestor manifest hash differs')
    last_proposed = seed
    for stage in preserved:
        original = saved[stage]
        proposed = _read(_transaction_file(directory, migration_id, stage + '.proposed.json'))
        entry = manifest['receipts'][stage]; receipt = json.loads(original)
        if (entry != {'originalSha256': _sha(original), 'proposedSha256': _sha(proposed)} or
                originals[stage] != proposed or receipt.get('stage') != stage or receipt.get('status') != 'PASSED' or
                type(receipt.get('exitCode')) is not int or receipt['exitCode'] != 0 or
                receipt.get('inputSha256') != previous or not receipt.get('outputs') or
                (profile == 'audit-namespace' and 'checkpointMigration' in receipt)):
            raise ValueError('prior receipt lineage differs: ' + stage)
        updated = copy.deepcopy(receipt); updated['inputSha256'] = last_proposed
        updated['checkpointMigration'] = {'id': migration_id, 'scope': scope,
            'originalSha256': _sha(original), 'originalInputSha256': previous,
            'oldWorkerSha256': old_implementation['ns_worker.py'], 'newWorkerSha256': implementation['ns_worker.py']}
        if 'checkpointMigration' in receipt:
            updated['checkpointMigration']['previous'] = copy.deepcopy(receipt['checkpointMigration'])
        if _json(updated) != proposed: raise ValueError('prior proposed receipt differs: ' + stage)
        previous = _sha(original); last_proposed = _sha(proposed)
    if 'checkpointMigration' in json.loads(originals[phase]): raise ValueError('unexpected earlier phase receipt migration')
    return _sha(content)


def _migrate(root, old_code, implementation_dir, allowed_roots, execute, repair):
    migration_id, scope, phase = REPAIRS[repair]; preserved = STAGES[:STAGES.index(phase)]
    if any(path != path.resolve() for path in allowed_roots):
        raise ValueError('allowed output roots must be canonical nonsymlink paths')
    checkpoints = root / 'worker/checkpoints'
    transaction = checkpoints / 'migrations' / migration_id
    for path in (checkpoints, transaction.parent, transaction):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError('invalid checkpoint/migration directory')
    old_bytes = _read(old_code); old = old_bytes.decode()
    current_bytes = _read(implementation_dir / 'ns_worker.py')
    _verify_change(old, current_bytes, repair)
    names = (*NAMES, 'sandbox_policy.py') if repair == 'independent-policy' else NAMES
    implementation = {name: _sha(_read(implementation_dir / name)) for name in names}
    if repair == 'independent-policy' and implementation['sandbox_policy.py'] != APPROVED_POLICY_SHA256:
        raise ValueError('sandbox policy module differs from the reviewed SHA256')
    old_implementation = {name: implementation[name] for name in NAMES}
    old_implementation['ns_worker.py'] = _sha(old_bytes)
    store = QueueStore.readonly(root); state = store.snapshot()
    validate_spec(state['spec'])
    old_seed = json_hash({'spec': state['spec'], 'implementation': old_implementation})
    new_seed = json_hash({'spec': state['spec'], 'implementation': implementation})
    originals = {stage: _read(_transaction_file(transaction, migration_id, stage + '.original.json') if transaction.exists()
                              else checkpoints / (stage + '.json')) for stage in preserved}
    prior_profile = {'kernel-api': 'audit-namespace', 'independent-policy': 'kernel-api'}.get(repair)
    prior_manifest = (_verify_prior_migration(root, state, originals, old_implementation, old_seed, allowed_roots, prior_profile)
                      if prior_profile else None)
    proposed = {}; entries = {}; previous_old = old_seed; previous_new = new_seed
    for stage in preserved:
        content = originals[stage]; receipt = json.loads(content)
        if (receipt.get('stage') != stage or receipt.get('status') != 'PASSED' or
                type(receipt.get('exitCode')) is not int or receipt['exitCode'] != 0 or
                receipt.get('inputSha256') != previous_old or not receipt.get('outputs') or
                (repair == 'audit-namespace' and 'checkpointMigration' in receipt)):
            raise ValueError('invalid original receipt or parent chain: ' + stage)
        for output in receipt['outputs']:
            path = Path(output['path'])
            if (not path.is_absolute() or path != path.resolve() or
                    not any(path.is_relative_to(base) for base in allowed_roots) or
                    type(output.get('bytes')) is not int or path.stat().st_size != output['bytes'] or
                    file_hash(path) != output['sha256']):
                raise ValueError('checkpoint output escaped scope or changed: ' + str(path))
            # Inspect every ancestor too; a parent symlink must not authorize reuse.
            if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file():
                raise ValueError('checkpoint output is not a regular nonsymlink file')
        updated = copy.deepcopy(receipt); updated['inputSha256'] = previous_new
        updated['checkpointMigration'] = {'id': migration_id, 'scope': scope,
            'originalSha256': _sha(content), 'originalInputSha256': previous_old,
            'oldWorkerSha256': old_implementation['ns_worker.py'],
            'newWorkerSha256': implementation['ns_worker.py']}
        if 'checkpointMigration' in receipt:
            updated['checkpointMigration']['previous'] = copy.deepcopy(receipt['checkpointMigration'])
        proposed[stage] = _json(updated)
        entries[stage] = {'originalSha256': _sha(content), 'proposedSha256': _sha(proposed[stage])}
        previous_old = _sha(content); previous_new = _sha(proposed[stage])
    manifest = {'id': migration_id, 'scope': scope, 'allowedRoots': list(map(str, allowed_roots)),
                'oldSeedSha256': old_seed, 'newSeedSha256': new_seed,
                'oldImplementation': old_implementation, 'newImplementation': implementation, 'receipts': entries}
    if prior_manifest: manifest['priorMigrationManifestSha256'] = prior_manifest
    manifest_bytes = _json(manifest)
    if transaction.exists():
        if _read(_transaction_file(transaction, migration_id, 'manifest.json')) != manifest_bytes:
            raise ValueError('migration manifest was altered or implementation changed')
        for stage in preserved:
            if _read(_transaction_file(transaction, migration_id, stage + '.proposed.json')) != proposed[stage]:
                raise ValueError('proposed receipt was altered: ' + stage)
    for stage in STAGES[len(preserved):]:
        path = checkpoints / (stage + '.json')
        if (path.exists() or path.is_symlink()) and json.loads(_read(path)).get('status') == 'PASSED':
            raise ValueError('later successful receipt exists: ' + stage)
    acceptable = {stage: {entry['originalSha256'], entry['proposedSha256']} for stage, entry in entries.items()}
    for stage in preserved:
        current = _read(checkpoints / (stage + '.json'))
        if current not in (originals[stage], proposed[stage]):
            raise ValueError('current receipt changed outside this migration: ' + stage)
    _state_check(state, acceptable, preserved, phase)
    ledger = {'id': migration_id, 'scope': scope, 'manifestPath': str(_transaction_file(transaction, migration_id, 'manifest.json').relative_to(root)),
              'manifestSha256': _sha(manifest_bytes), 'receipts': entries}
    recorded = [entry for entry in state.get('checkpointMigrations', []) if entry.get('id') == migration_id]
    if recorded and (recorded != [ledger] or any(_read(checkpoints / (s + '.json')) != proposed[s] for s in preserved)):
        raise ValueError('queue migration ledger or committed receipts changed')
    if not execute or recorded:
        return {'migration': migration_id, 'status': 'already_migrated' if recorded else 'validated_dry_run',
                'manifestSha256': ledger['manifestSha256'], 'receipts': entries}
    if not transaction.exists():
        transaction.parent.mkdir(parents=True, exist_ok=True); _sync(checkpoints)
        staging = Path(tempfile.mkdtemp(prefix='.' + migration_id + '-', dir=transaction.parent))
        for stage in preserved:
            _write(_transaction_file(staging, migration_id, stage + '.original.json'), originals[stage])
            _write(_transaction_file(staging, migration_id, stage + '.proposed.json'), proposed[stage])
        _write(_transaction_file(staging, migration_id, 'manifest.json'), manifest_bytes); staging.chmod(0o755); _sync(staging)
        os.rename(staging, transaction); _sync(transaction.parent)
    # All original/proposed files and every output have passed validation first.
    for stage in preserved:
        path = checkpoints / (stage + '.json')
        if _read(path) != proposed[stage]: _replace_receipt(path, proposed[stage])
    def commit(current):
        _state_check(current, acceptable, preserved, phase)
        if any(entry.get('id') == migration_id for entry in current.get('checkpointMigrations', [])):
            raise ValueError('migration ledger changed concurrently')
        for row in current['stages']:
            if row['id'] in preserved: row['checkpointSha256'] = entries[row['id']]['proposedSha256']
        for artifact in current.get('artifacts', []):
            for stage in preserved:
                if artifact.get('path') == 'worker/checkpoints/' + stage + '.json':
                    artifact.update(sha256=entries[stage]['proposedSha256'], bytes=len(proposed[stage]))
        current.setdefault('checkpointMigrations', []).append(ledger)
    QueueStore(root).mutate(commit, repair.replace('-', '_') + '_checkpoint_migrated')
    return {'migration': migration_id, 'status': 'migrated', 'manifestSha256': ledger['manifestSha256'], 'receipts': entries}


def migrate(root, old_code, implementation_dir=None, allowed_roots=None, execute=False, repair='audit-namespace'):
    if repair not in REPAIRS: raise ValueError('unknown reviewed repair profile')
    root = Path(root).resolve(); implementation_dir = Path(implementation_dir or Path(__file__).parent).resolve()
    allowed_roots = tuple(Path(path).absolute() for path in (allowed_roots or (root / 'worker', '/sandbox/work/ns')))
    lock_path = root / 'ns-worker.lock'
    if lock_path.is_symlink(): raise ValueError('worker lock is a symlink')
    with (lock_path.open('a' if execute else 'rb') if execute or lock_path.exists() else contextlib.nullcontext()) as lock:
        if lock: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _migrate(root, Path(old_code).absolute(), implementation_dir, allowed_roots, execute, repair)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/data')
    parser.add_argument('--repair', choices=tuple(REPAIRS), default='audit-namespace')
    parser.add_argument('--old-code', help='old supervisor backup; defaults to the selected repair phase')
    parser.add_argument('--execute', action='store_true', help='commit after complete validation; default is dry run')
    args = parser.parse_args()
    old_code = args.old_code or '/data/backups/ns-worker-before-' + REPAIRS[args.repair][2] + '.py'
    print(json.dumps(migrate(args.root, old_code, execute=args.execute, repair=args.repair), sort_keys=True))


if __name__ == '__main__': main()
