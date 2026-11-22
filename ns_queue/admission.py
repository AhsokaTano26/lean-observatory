"""Explicit authorization for overlap; never an RH completion certificate."""
import hashlib
import json
import re
from pathlib import Path
from .gates import _validate_run, rh_gate, ACTIVE, FAILURES


def validate_admission(document, run_id):
    try:
        payload=document['payload']; ledger=document['ledger']
        if payload.get('workerRunning') is not True:raise ValueError('rh_worker_unconfirmed')
        _validate_run(payload['run'],run_id,replay_pending=True)
        if not isinstance(ledger,list):raise ValueError('rh_ledger_unknown')
        for row in ledger:
            if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or
                row.get('status') not in ACTIVE | FAILURES | {'checks_completed'}):
                raise ValueError('rh_ledger_unknown')
            if row['id']!=run_id and row['status'] in ACTIVE:raise ValueError('rh_other_active_run')
    except (KeyError,TypeError,AttributeError) as error:
        raise ValueError('rh_malformed_admission') from error


def dependency_gate(payload, ledger, state):
    final=rh_gate(payload,ledger,state['rhRunId'])
    if final['decision'] in ('READY','PAUSE') or state.get('schedulingMode')!='parallel_replay':return final
    try:validate_admission({'payload':payload,'ledger':ledger},state['rhRunId'])
    except ValueError as error:return {'decision':'WAIT','reason':str(error)}
    return {'decision':'READY','reason':'rh_replay_overlap'}


def has_parallel(state):
    evidence=state.get('parallelAdmission') or {}
    return (state.get('schedulingMode')=='parallel_replay' and evidence.get('kind')=='rh_replay' and
            evidence.get('runId')==state.get('rhRunId') and bool(evidence.get('runId')) and
            evidence.get('finalSuccess') is False)


def verify_parallel(root, state):
    if not has_parallel(state):raise ValueError('parallel_admission_not_authorized')
    evidence=state['parallelAdmission'];root=Path(root).resolve()
    try:
        relative=evidence['snapshotPath'];expected=evidence['snapshotSha256'];size=evidence['snapshotBytes']
        if not isinstance(relative,str) or Path(relative).is_absolute():raise ValueError('parallel_admission_path')
        path=root/relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('parallel_admission_path')
        if (type(size) is not int or not 0<size<=64*1024**2 or path.stat().st_size!=size or
            not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected)):
            raise ValueError('parallel_admission_size')
        blob=path.read_bytes()
        if hashlib.sha256(blob).hexdigest()!=expected:raise ValueError('parallel_admission_hash')
        validate_admission(json.loads(blob),state['rhRunId'])
    except (KeyError,TypeError,OSError) as error:raise ValueError('parallel_admission_invalid') from error
