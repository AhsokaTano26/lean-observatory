#!/usr/bin/env bash
# First installation only. The assistant invokes this; dry-run is the default.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
INSTALL_DIR=/opt/lean-observatory
DOMAIN=lean.tano.asia
EXECUTE=0
EMAIL=''
while (($#)); do
  case "$1" in
    --dry-run) EXECUTE=0 ;;
    --execute) EXECUTE=1 ;;
    --email) shift; EMAIL="${1:?--email needs an address}" ;;
    --help|-h) printf '%s\n' 'Usage: bash scripts/bootstrap_server.sh [--dry-run|--execute] [--email address]'; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done
# The exact unpacked source must have passed the local gate, before any host write.
SOURCE_SHA256="$(python3 - "$ROOT_DIR" <<'PY'
import sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'scripts'))
from gates import require_local_gate
try:print(require_local_gate(root)['sourceSha256'])
except (OSError,ValueError,RuntimeError) as error:raise SystemExit('本地门禁拒绝初装: '+str(error))
PY
)"
if (( ! EXECUTE )); then
  cat <<PLAN
DRY RUN — no host changes, no network requests, no proof tasks.
Source: $SOURCE_SHA256
Install only in $INSTALL_DIR as root on Ubuntu 24.04 x86_64.
Require >=64 CPUs, >=240 GiB memory, >=500 GiB free disk and unused 80/443.
Reject existing .env, project containers/data volumes; never stop unrelated services.
Require AppArmor enabled; install apparmor/parser and load the exact enforcing worker profile.
Reuse Docker Engine/Compose >=2.24.4; if absent install from official Docker apt repository.
Create lean-metrics system user and host metrics service; /var/lib/lean-observatory-metrics.
Write root-owned .env (0600): ENABLE_REAL=0, SOURCE_SHA256=$SOURCE_SHA256,
METRICS_DIR=/var/lib/lean-observatory-metrics, WORKER_CPUSET=8-55, WORKER_CPUS=48, WORKER_MEMORY=208g,
APPARMOR_PROFILE=lean-observatory-worker.
Start api/worker/nginx only for project lean-observatory; no mock profile and no task creation.
Use certbot webroot at $INSTALL_DIR/acme for $DOMAIN, then switch this project's nginx to TLS.
Install certbot renewal deploy-hook and enable certbot.timer; test renewal with certbot renew --dry-run.
Run tiny-only production worker-fixture under the enforcing profile and save source/script/profile hashes.
Run trusted HTTPS online_acceptance.py separately before any later real-task authorization.
PLAN
  exit 0
fi
if [[ "$ROOT_DIR" != "$INSTALL_DIR" ]]; then
  printf 'Execute requires unpacked, verified source at %s\n' "$INSTALL_DIR" >&2; exit 1
fi
if [[ "$(id -u)" != 0 ]]; then printf '%s\n' 'Execute requires root' >&2; exit 1; fi
# Read-only host preconditions all run before apt, directories or configuration changes.
python3 - "$INSTALL_DIR" <<'PY'
import os,platform,shutil,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1])
if Path('/sys/module/apparmor/parameters/enabled').read_text().strip()!='Y':raise SystemExit('AppArmor must be enabled; unconfined production fallback is forbidden')
osinfo=dict(line.split('=',1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
if osinfo.get('ID','').strip('"')!='ubuntu' or osinfo.get('VERSION_ID','').strip('"')!='24.04' or platform.machine()!='x86_64':raise SystemExit('Ubuntu 24.04 x86_64 required')
mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()}
if (os.cpu_count() or 0)<64 or mem['MemTotal']<240*1024**3:raise SystemExit('64 CPUs and 240 GiB memory required')
if any(shutil.disk_usage(path).free<500*1024**3 for path in [root,'/var/lib']):raise SystemExit('500 GiB free required for install and Docker data')
if (root/'.env').exists() or (root/'.env').is_symlink():raise SystemExit('Existing .env: first-install script refuses to overwrite deployment')
for path in [root/'.data',Path('/etc/systemd/system/lean-observatory-metrics.service'),Path('/etc/letsencrypt/renewal-hooks/deploy/lean-observatory-reload'),Path('/etc/letsencrypt/live/lean.tano.asia'),Path('/etc/letsencrypt/renewal/lean.tano.asia.conf'),Path('/etc/apparmor.d/lean-observatory-worker')]:
    if path.exists() or path.is_symlink():raise SystemExit('Existing deployment state: first-install refuses overwrite: '+str(path))
if root.stat().st_uid!=0 or root.stat().st_mode & 0o022:raise SystemExit('Install directory must be root-owned and not group/world writable')
for path in root.rglob('*'):
    if any(part in {'.data','node_modules','.git','artifacts','reports','docs','__pycache__'} for part in path.relative_to(root).parts):continue
    if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode & 0o022:raise SystemExit('Deploy source must be root-owned and not writable by other users: '+str(path))
ports=subprocess.run(['ss','-H','-ltn'],capture_output=True,text=True,check=True,timeout=15)
for line in ports.stdout.splitlines():
    if len(line.split())>3 and line.split()[3].rsplit(':',1)[-1] in ('80','443'):raise SystemExit('80/443 occupied; refusing to stop existing services')
if shutil.which('docker'):
    subprocess.run(['docker','info'],capture_output=True,check=True,timeout=30)
    version=subprocess.run(['docker','compose','version','--short'],capture_output=True,text=True,check=True,timeout=15).stdout.strip().lstrip('v').split('-')[0]
    if tuple(map(int,version.split('.'))) < (2,24,4):raise SystemExit('Existing Docker requires Compose >=2.24.4; no automatic replacement')
    result=subprocess.run(['docker','ps','-a','-q','--filter','label=com.docker.compose.project=lean-observatory'],capture_output=True,text=True,check=True,timeout=15)
    if result.stdout.strip():raise SystemExit('Existing project containers: first-install script refuses changes')
    result=subprocess.run(['docker','volume','ls','-q','--filter','name=lean-observatory_'],capture_output=True,text=True,check=True,timeout=15)
    if result.stdout.strip():raise SystemExit('Existing project volumes: preserve data and use reviewed update procedure')
PY
cd -- "$INSTALL_DIR"
if ! command -v docker >/dev/null 2>&1; then
  # https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository
  # Conflicting packages are never uninstalled automatically.
  for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'ok installed'; then
      printf 'Conflicting package %s installed; refusing automatic uninstall\n' "$package" >&2; exit 1
    fi
  done
  apt-get update
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  if [[ -e /etc/apt/keyrings/docker.asc || -e /etc/apt/sources.list.d/docker.sources || -e /etc/apt/sources.list.d/docker.list ]]; then
    printf '%s\n' 'Existing Docker apt configuration; refusing overwrite' >&2; exit 1
  fi
  curl --fail --show-error --silent --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  cat > /etc/apt/sources.list.d/docker.sources <<'APT'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
APT
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
docker info >/dev/null
apt-get update
apt-get install -y certbot apparmor
install -o root -g root -m 0644 deploy/lean-observatory-worker.apparmor /etc/apparmor.d/lean-observatory-worker
apparmor_parser -r /etc/apparmor.d/lean-observatory-worker
systemctl enable --now apparmor.service
python3 - <<'PY'
from pathlib import Path
if 'lean-observatory-worker (enforce)' not in Path('/sys/kernel/security/apparmor/profiles').read_text().splitlines():raise SystemExit('Worker AppArmor profile is not enforcing')
PY
if ! getent passwd lean-metrics >/dev/null; then
  useradd --system --user-group --no-create-home --shell /usr/sbin/nologin lean-metrics
fi
python3 - <<'PY'
import pwd
user=pwd.getpwnam('lean-metrics')
if user.pw_shell not in ('/usr/sbin/nologin','/bin/false') or user.pw_uid==0:raise SystemExit('Existing metrics account is not an unprivileged service account')
PY
install -d -o lean-metrics -g lean-metrics -m 0755 /var/lib/lean-observatory-metrics
install -d -o root -g root -m 0755 "$INSTALL_DIR/acme" "$INSTALL_DIR/.data" "$INSTALL_DIR/.data/approval"
# No shell evaluation of .env. The source fingerprint is provided by the gate.
umask 077
cat > .env <<ENV
ENABLE_REAL=0
SOURCE_SHA256=$SOURCE_SHA256
HTTP_PORT=8789
METRICS_DIR=/var/lib/lean-observatory-metrics
ACME_WEBROOT=$INSTALL_DIR/acme
WORKER_CPUS=48
WORKER_CPUSET=8-55
WORKER_MEMORY=208g
APPARMOR_PROFILE=lean-observatory-worker
ENV
chmod 0600 .env
if [[ -e /etc/systemd/system/lean-observatory-metrics.service ]]; then
  printf '%s\n' 'Existing metrics service: refusing overwrite' >&2; exit 1
fi
install -o root -g root -m 0644 deploy/lean-observatory-metrics.service /etc/systemd/system/lean-observatory-metrics.service
systemctl daemon-reload
systemctl enable --now lean-observatory-metrics.service
COMPOSE=(docker compose -p lean-observatory -f compose.yaml)
"${COMPOSE[@]}" -f compose.acme.yaml --profile verification up -d --build --wait
CERTBOT=(certbot certonly --non-interactive --agree-tos --webroot -w "$INSTALL_DIR/acme" -d "$DOMAIN")
if [[ -n "$EMAIL" ]]; then CERTBOT+=(--email "$EMAIL"); else CERTBOT+=(--register-unsafely-without-email); fi
"${CERTBOT[@]}"
"${COMPOSE[@]}" -f compose.tls.yaml --profile verification up -d --wait
"${COMPOSE[@]}" -f compose.tls.yaml exec -T nginx nginx -t
install -d -o root -g root -m 0755 /etc/letsencrypt/renewal-hooks/deploy
if [[ -e /etc/letsencrypt/renewal-hooks/deploy/lean-observatory-reload ]]; then
  printf '%s\n' 'Existing renewal hook: refusing overwrite' >&2; exit 1
fi
cat > /etc/letsencrypt/renewal-hooks/deploy/lean-observatory-reload <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
case " ${RENEWED_DOMAINS:-} " in
  *' lean.tano.asia '*)
    cd /opt/lean-observatory
    docker compose -p lean-observatory -f compose.yaml -f compose.tls.yaml exec -T nginx nginx -t
    docker compose -p lean-observatory -f compose.yaml -f compose.tls.yaml exec -T nginx nginx -s reload
    ;;
esac
HOOK
chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/lean-observatory-reload
systemctl enable --now certbot.timer
certbot renew --cert-name "$DOMAIN" --dry-run
python3 scripts/online_acceptance.py --worker-fixture-only
printf '%s\n' 'Installed with ENABLE_REAL=0. Assistant must run scripts/online_acceptance.py and review its receipt before separately authorizing proof work.'
