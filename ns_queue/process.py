"""Argument-vector execution with complete logs and actual child termination evidence."""
from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    output: str
    log_path: str
    termination: str | None = None


def run_process(argv, *, cwd, log_path, on_line=None, heartbeat=None,
                heartbeat_interval=1., timeout=259200., stdout_path=None, env=None):
    """No shell; stdout exports stay separate from diagnostics. Never invent exit 0."""
    if not argv or not all(isinstance(x, str) and '\x00' not in x for x in argv):
        raise ValueError('invalid argument vector')
    log_path = Path(log_path); log_path.parent.mkdir(parents=True, exist_ok=True)
    actual = [sys.executable, str(Path(__file__).with_name('child.py')),
              '--guard', str(os.getpid()), *argv]
    started = time.monotonic(); beat_at = started - heartbeat_interval
    captured = bytearray(); buffers = {}; termination = None; process = None
    with log_path.open('wb') as log:
        exported = Path(stdout_path).open('wb') if stdout_path else None
        try:
            process = subprocess.Popen(actual, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            with selectors.DefaultSelector() as selector:
                for stream, label in [(process.stdout, 'stdout'), (process.stderr, 'stderr')]:
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, label); buffers[label] = b''
                while selector.get_map():
                    now = time.monotonic()
                    if now - beat_at >= heartbeat_interval:
                        if heartbeat: heartbeat()
                        beat_at = now
                    if now - started > timeout and termination is None:
                        termination = 'timeout'; os.killpg(process.pid, signal.SIGKILL)
                    for key, _ in selector.select(.05):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj); continue
                        label = key.data
                        if label == 'stdout' and exported:
                            exported.write(chunk); exported.flush()
                            continue
                        log.write(chunk); log.flush()
                        if len(captured) < 8 * 1024**2:
                            captured.extend(chunk[:8 * 1024**2 - len(captured)])
                        buffers[label] += chunk
                        while b'\n' in buffers[label]:
                            line, buffers[label] = buffers[label].split(b'\n', 1)
                            if on_line: on_line(line.decode(errors='replace').rstrip('\r'))
                        # Preserve arbitrarily long lines in the file without unbounded RAM.
                        if len(buffers[label]) > 1024**2:
                            if on_line: on_line(buffers[label][:16000].decode(errors='replace'))
                            buffers[label] = b''
                for pending in buffers.values():
                    if pending and on_line: on_line(pending.decode(errors='replace'))
            code = process.wait()
        except BaseException as error:
            if process and process.poll() is None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()
            if process is not None:
                error.child_exit_code = process.returncode
            raise
        finally:
            for stream in [process.stdout, process.stderr] if process else []:
                stream.close()
            if exported:
                exported.flush(); os.fsync(exported.fileno()); exported.close()
            log.flush(); os.fsync(log.fileno())
    return ProcessResult(code, captured.decode(errors='replace'), str(log_path), termination)
