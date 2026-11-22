"""Pure, fail-closed gates for the fixed RH dependency and NS start budget.

RH input is the public ``{'run': snapshot}`` payload. Heartbeat freshness is
deliberately not a success/failure signal. Only explicit worker-process evidence
(``workerRunning=False`` or ``workerStopped=True``) establishes a stopped worker.
"""
import math
import re
from decimal import Decimal


RH_STAGES = {'download', 'integrity', 'dependencies', 'compile', 'audit', 'replay'}
RH_THEOREMS = {
    'riemannHypothesis': 'RiemannHypothesis',
    'riemannZeta_eq_zero_re': 'RiemannZetaZerosOnLine',
    'LFunction_ne_zero_of_half_lt_re': 'DirichletLNonvanishingRightOfHalf',
    'LFunction_eq_zero_re': 'DirichletLZerosOnLine',
    'LFunction_eq_zero_re_of_isPrimitive': 'PrimitiveDirichletLZerosOnLine',
}
RH_ARCHIVE_SHA256 = '9631b4f020199e580ba86178cb56c6e9b09f690c2369a80dc4334aa93f49c7fc'
RH_ARCHIVE_BYTES = 239275554
RH_MATHLIB = '0df444a360eaa60ab8c11dca51a86af692955474'
STANDARD_AXIOMS = {'propext', 'Classical.choice', 'Quot.sound'}
ACTIVE = {'queued', 'running', 'paused'}
FAILURES = {'failed', 'interrupted', 'cancelled', 'resource_exhausted'}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _finished(value):
    return _number(value) and value > 0


def _validate_run(run, run_id, *, replay_pending=False):
    _require(isinstance(run, dict), 'rh_missing')
    _require(run.get('id') == run_id and isinstance(run_id, str) and bool(run_id), 'rh_run_mismatch')
    _require(run.get('mode') == 'real', 'rh_mode')
    if replay_pending:
        _require(run.get('status') == 'running' and run.get('phase') == 'replay' and
                 run.get('finishedAt') is None and not run.get('error'), 'rh_not_replaying')
    else:
        _require(run.get('status') == 'checks_completed', 'rh_not_completed')
        _require(_finished(run.get('finishedAt')), 'rh_finished_at')

    stages = run.get('stages')
    _require(isinstance(stages, list) and len(stages) == 6 and
             all(isinstance(stage, dict) for stage in stages), 'rh_stages')
    _require({stage.get('id') for stage in stages} == RH_STAGES, 'rh_stages')
    for stage in stages:
        if replay_pending and stage['id'] == 'replay':
            _require(stage.get('status') == 'running' and stage.get('exitCode') is None and
                     stage.get('finishedAt') is None, 'rh_replay_pending')
        else:
            _require(stage.get('status') == 'passed' and type(stage.get('exitCode')) is int and
                     stage['exitCode'] == 0, 'rh_stage_evidence')

    compiled = run.get('compile')
    _require(isinstance(compiled, dict), 'rh_compile')
    for key, expected in (('total', 175187), ('succeeded', 175187), ('failed', 0)):
        _require(type(compiled.get(key)) is int and compiled[key] == expected, 'rh_compile')

    audits = run.get('audits')
    _require(isinstance(audits, list) and len(audits) == 5 and
             all(isinstance(audit, dict) for audit in audits), 'rh_audits')
    _require({audit.get('name') for audit in audits} == set(RH_THEOREMS), 'rh_audits')
    for audit in audits:
        _require(audit.get('expectedType') == RH_THEOREMS[audit['name']], 'rh_audit_type')
        _require(all(audit.get(check) == 'passed' for check in ('type', 'axioms')), 'rh_audit_evidence')
        _require(audit.get('replay') == ('pending' if replay_pending else 'passed'), 'rh_audit_replay')
        dependencies = audit.get('dependencies')
        _require(isinstance(dependencies, list) and all(isinstance(item, str) for item in dependencies), 'rh_axioms')
        _require(set(dependencies) <= STANDARD_AXIOMS, 'rh_axioms')

    provenance = run.get('provenance')
    _require(isinstance(provenance, dict), 'rh_archive')
    _require(provenance.get('sha256') == RH_ARCHIVE_SHA256 and
             provenance.get('expectedSha256') == RH_ARCHIVE_SHA256 and
             provenance.get('integrity') == 'passed', 'rh_archive')
    for key in ('bytes', 'expectedBytes'):
        _require(type(provenance.get(key)) is int and provenance[key] == RH_ARCHIVE_BYTES, 'rh_archive')

    environment = run.get('environment')
    _require(isinstance(environment, dict), 'rh_environment')
    _require(environment.get('lean') == 'v4.33.1' and environment.get('mathlib') == RH_MATHLIB and
             environment.get('actualMathlib') == RH_MATHLIB, 'rh_pins')
    actual_lean = environment.get('actualLean')
    _require(isinstance(actual_lean, str) and bool(re.search(r'\bversion\s+4\.33\.1(?:,|\))', actual_lean)), 'rh_lean')

    commands = run.get('commands')
    _require(isinstance(commands, list) and bool(commands), 'rh_commands')
    active = 0
    for command in commands:
        if replay_pending and isinstance(command, dict) and command.get('status') == 'running':
            _require(command.get('stage') == 'replay' and command.get('exitCode') is None and
                     command.get('finishedAt') is None and
                     command.get('argv') == ['lake', '-f', 'lakefile.toml', 'env', 'leanchecker', '--fresh', 'Main'],
                     'rh_active_command')
            active += 1
            continue
        _require(isinstance(command, dict) and type(command.get('exitCode')) is int and
                 _finished(command.get('finishedAt')) and
                 command.get('status') in (FAILURES | {'passed'}) and
                 (command['exitCode'] == 0 if command['status'] == 'passed' else True),
                 'rh_active_command')
    if replay_pending: _require(active == 1, 'rh_replay_command')


def validate_result(result, run_id):
    """Validate the downloaded RH result; a report cannot contain its own hash.

    The live API must advertise that report with a hash before download. Its
    embedded snapshot is captured immediately before its registration, so that
    self-referential artifact requirement belongs only to ``rh_gate``.
    """
    _require(isinstance(result, dict), 'rh_result')
    try:
        _validate_run(result.get('run'), run_id)
    except (TypeError, KeyError, OverflowError) as error:
        raise ValueError('rh_malformed_evidence') from error


def rh_gate(payload, ledger, expected_run):
    def decision(action, reason):
        return {'decision': action, 'reason': reason}

    if not isinstance(payload, dict) or not isinstance(payload.get('run'), dict):
        return decision('WAIT', 'rh_missing')
    run = payload['run']
    if run.get('id') != expected_run:
        return decision('WAIT', 'rh_run_mismatch')
    if run.get('mode') != 'real':
        return decision('PAUSE', 'rh_mode')
    if not isinstance(run.get('status'), str):
        return decision('WAIT', 'rh_status_unknown')
    if run['status'] in FAILURES:
        return decision('PAUSE', 'rh_' + run['status'])
    if payload.get('workerRunning') is False or payload.get('workerStopped') is True:
        return decision('PAUSE', 'rh_worker_stopped')
    if run.get('status') != 'checks_completed':
        return decision('WAIT', 'waiting_rh')
    try:
        _validate_run(run, expected_run)
    except (ValueError, TypeError, KeyError) as error:
        return decision('WAIT', str(error))
    artifacts = run.get('artifacts')
    if not isinstance(artifacts, list):
        return decision('WAIT', 'rh_result_artifact')
    reports = [entry for entry in artifacts if isinstance(entry, dict) and entry.get('name') == 'verification-result.json']
    if len(reports) != 1:
        return decision('WAIT', 'rh_result_artifact')
    report = reports[0]
    if not (isinstance(report.get('sha256'), str) and re.fullmatch(r'[0-9a-fA-F]{64}', report['sha256']) and
            type(report.get('bytes')) is int and report['bytes'] > 0):
        return decision('WAIT', 'rh_result_artifact')
    if not isinstance(ledger, list) or any(not isinstance(row, dict) for row in ledger):
        return decision('WAIT', 'rh_ledger_unknown')
    for row in ledger:
        if (not isinstance(row.get('id'), str) or not isinstance(row.get('status'), str) or
                row['status'] not in (ACTIVE | FAILURES | {'checks_completed'})):
            return decision('WAIT', 'rh_ledger_unknown')
        if row.get('id') != expected_run and row.get('status') in ACTIVE:
            return decision('WAIT', 'rh_other_active_run')
    return decision('READY', 'rh_checks_completed')


def start_gate(state, resources, now=None):
    """Require durable RH, 300 seconds of remaining budget, and host resources."""
    def blocked(reason):
        return {'allowed': False, 'reason': reason}

    from .admission import has_parallel
    overlap = isinstance(state, dict) and has_parallel(state)
    if not isinstance(state, dict) or not (isinstance(state.get('rhEvidence'), dict) and state['rhEvidence'].get('persisted') is True or overlap):
        return blocked('rh_evidence')
    from .budget import can_start, normalize
    if not can_start(state.get('budget'), now):
        return blocked('budget')
    if not isinstance(resources, dict):
        return blocked('resources_unknown')
    if resources.get('rhActive') is not False and not overlap:
        return blocked('rh_active')
    if normalize(state['budget'],now)['enforcement']=='notify_only':
        return {'allowed':True,'reason':'ready_advisory'}
    for key, threshold, reason in (('cpuCount', 64, 'cpu'),
                                   ('memoryAvailableBytes', 224 * 1024**3, 'memory'),
                                   ('diskFreeBytes', 100 * 1024**3, 'disk')):
        if not _number(resources.get(key)) or resources[key] < threshold:
            return blocked(reason)
    return {'allowed': True, 'reason': 'ready'}
