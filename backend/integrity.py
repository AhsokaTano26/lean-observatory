import hashlib
import tarfile
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_archive(path, expected_hash, expected_size):
    path = Path(path)
    if path.stat().st_size != expected_size:
        raise ValueError(f'归档大小不匹配: {path.stat().st_size} != {expected_size}')
    with path.open('rb') as f:
        if f.read(2) != b'\x1f\x8b':
            raise ValueError('归档不是 gzip，可能是 HTTP 200 错误页面')
    digest = sha256(path)
    if digest != expected_hash:
        raise ValueError('SHA-256 不匹配')
    return digest


def safe_extract(path, destination, max_bytes=8*1024**3, max_members=400000):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    with tarfile.open(path, 'r:gz') as archive:
        for i, member in enumerate(archive):
            target = (destination / member.name).resolve()
            total += member.size
            if (i >= max_members or total > max_bytes or member.name.startswith('/')
                    or not target.is_relative_to(destination) or not (member.isfile() or member.isdir())):
                raise ValueError('拒绝不安全或超限的归档成员: ' + member.name)
            archive.extract(member, destination, filter='data')
