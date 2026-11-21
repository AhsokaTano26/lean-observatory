#!/usr/bin/env python3
import hashlib,json,tarfile
from pathlib import Path
from gates import ROOT,EXCLUDED,require_local_gate
receipt=require_local_gate()
archive=Path('/tmp')/('lean-observatory-'+receipt['sourceSha256'][:12]+'.tar.gz')
with tarfile.open(archive,'w:gz') as out:
    for p in sorted(ROOT.rglob('*')):
        rel=p.relative_to(ROOT)
        if not p.is_file() or any(x in EXCLUDED-{'reports','docs'} for x in rel.parts):continue
        if rel.name.startswith('.env') and rel.name!='.env.example':continue
        out.add(p,arcname=rel,recursive=False)
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix(archive.suffix+'.sha256').write_text(f'{digest}  {archive.name}\n')
print(json.dumps({'archive':str(archive),'sha256':digest,'bytes':archive.stat().st_size}))
