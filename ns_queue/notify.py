"""Bounded, durable-outbox delivery to the administrator's authorized webhook."""
import datetime
import ipaddress
import json
import math
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_WEBHOOK = 'https://uptimepulse.tano.asia/webhook/general'


def build_payload(alert):
    level = alert.get('level', 'info')
    if level not in {'info', 'success', 'warning', 'error'}:
        raise ValueError('Invalid notification level')
    fields = {}
    for key, value in (alert.get('fields') or {}).items():
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Webhook fields must be flat finite scalar values')
        if len(fields) >= 6:
            break
        fields[str(key)[:40]] = value[:120] if isinstance(value, str) else value
    body = dict(title=str(alert.get('title', 'Lean Observatory'))[:80],
                message=str(alert.get('message') or '验证状态更新')[:900],
                source='Lean Observatory / NS queue', level=level,
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                fields=fields, url='https://lean.tano.asia/ns/')
    # Stay below the receiver's 1900-character composed-input limit even for CJK.
    while len(json.dumps(body, ensure_ascii=False).encode()) > 1500:
        if len(body['message']) > 40:
            body['message'] = body['message'][:max(40, len(body['message']) - 40)]
        elif body['fields']:
            body['fields'].pop(next(reversed(body['fields'])))
        else:
            body['title'] = body['title'][:20]
            break
    return body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def deliver(url, alert, *, allow_local_http=False, timeout=10):
    parsed = urllib.parse.urlsplit(url)
    local = False
    try:
        local = ipaddress.ip_address(parsed.hostname or '').is_loopback
    except ValueError:
        pass
    if parsed.username or parsed.password or not parsed.hostname or parsed.fragment:
        raise ValueError('Invalid webhook destination')
    if parsed.scheme != 'https' and not (allow_local_http and local and parsed.scheme == 'http'):
        raise ValueError('Webhook requires verified HTTPS')
    payload = json.dumps(build_payload(alert), ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json', 'User-Agent': 'LeanObservatory/1.0'}, method='POST')
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            code = response.status
            response.read(1024)
        if code == 200:
            return {'status': 'sent', 'httpStatus': code, 'error': None}
        if code == 202:
            return {'status': 'accepted', 'httpStatus': code, 'error': None}
        return {'status': 'retry', 'httpStatus': code, 'error': 'Unexpected webhook acknowledgement'}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        result = {'status': 'retry', 'httpStatus': getattr(error, 'code', None), 'error': str(error)[:400]}
        if isinstance(error, urllib.error.HTTPError): error.close()
        return result
