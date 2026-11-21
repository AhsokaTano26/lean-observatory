"""Local acceptance receipts bind deployment authorization to exact source bytes."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={'node_modules','.git','.data','dist','__pycache__','reports','docs','artifacts','test-results'}
REQUIRED_CHECKS=('backend','charts','build','browser','compose','http','worker_smoke','amd64_worker_smoke','lake_pipeline','apparmor_profile')


def fingerprint(root=ROOT):
    h=hashlib.sha256()
    for p in sorted(root.rglob('*')):
        rel=p.relative_to(root)
        if not p.is_file() or any(x in EXCLUDED for x in rel.parts) or rel.name.startswith('.env') and rel.name!='.env.example': continue
        h.update(str(rel).encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def require_local_gate(root=ROOT):
    path=root/'reports/local-acceptance.json'
    if not path.exists(): raise RuntimeError('本地验收报告不存在：禁止连接目标服务器')
    report=json.loads(path.read_text())
    if report.get('sourceSha256')!=fingerprint(root): raise RuntimeError('源码已改变：本地门禁失效，必须重新验收')
    if any(report.get('checks',{}).get(k,{}).get('exitCode')!=0 for k in REQUIRED_CHECKS):
        raise RuntimeError('本地检查尚未全部通过：禁止连接目标服务器')
    return report
