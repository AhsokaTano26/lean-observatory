"""Host metrics. Linux uses /proc; unsupported measurements stay null."""
import argparse
import json
import os
import platform
import shutil
import time
from pathlib import Path

_previous = None


def collect(disk_path, proc=Path('/proc')):
    global _previous
    now = time.time()
    disk = shutil.disk_usage(disk_path)
    m = dict(sampledAt=now, source='local_host', hostname=platform.node(),
             platform=platform.platform(), cpuCount=os.cpu_count(), cpuPercent=None,
             memoryTotalBytes=None, memoryUsedBytes=None, memoryPercent=None,
             diskTotalBytes=disk.total, diskUsedBytes=disk.used,
             diskPercent=round(disk.used/disk.total*100, 2),
             networkRxBytesPerSec=None, networkTxBytesPerSec=None,
             load=list(os.getloadavg()), limitations=[])
    if not (proc/'stat').exists():
        m['limitations'] = ['当前系统不提供 Linux /proc；CPU、内存及网络采样不可用']
        return m
    cpu = list(map(int, (proc/'stat').read_text().splitlines()[0].split()[1:9]))
    memory = {line.split(':')[0]: int(line.split()[1])*1024 for line in (proc/'meminfo').read_text().splitlines()}
    m['memoryTotalBytes'] = memory['MemTotal']
    m['memoryUsedBytes'] = memory['MemTotal'] - memory['MemAvailable']
    m['memoryPercent'] = round(m['memoryUsedBytes']/m['memoryTotalBytes']*100, 2)
    rx = tx = 0
    for line in (proc/'net/dev').read_text().splitlines()[2:]:
        interface, values = line.split(':')
        if interface.strip() != 'lo':
            values = values.split(); rx += int(values[0]); tx += int(values[8])
    if _previous:
        old_time, old_cpu, old_rx, old_tx = _previous
        delta = sum(cpu)-sum(old_cpu)
        idle = cpu[3]+cpu[4]-old_cpu[3]-old_cpu[4]
        m['cpuPercent'] = round(max(0, min(100, (1-idle/delta)*100)), 2) if delta else 0
        dt = max(.001, now-old_time)
        m['networkRxBytesPerSec'] = max(0, (rx-old_rx)/dt)
        m['networkTxBytesPerSec'] = max(0, (tx-old_tx)/dt)
    _previous = (now, cpu, rx, tx)
    return m


def read_host_file(path, max_age=20):
    try:
        m = json.loads(Path(path).read_text())
        m['stale'] = time.time()-m['sampledAt'] > max_age
        return m
    except (OSError, ValueError, KeyError):
        return dict(source='host_agent', stale=True, sampledAt=None,
                    limitations=['宿主机采集器未连接，不能用容器指标替代宿主机指标'])


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output', required=True); p.add_argument('--disk', default='/')
    a=p.parse_args(); out=Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    while True:
        m=collect(a.disk); m['source']='host_agent'
        tmp=out.with_suffix('.tmp'); tmp.write_text(json.dumps(m)); tmp.replace(out)
        time.sleep(5)


if __name__ == '__main__':
    main()
