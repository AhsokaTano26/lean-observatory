"""Deployment acceptance required before a real task can be queued or claimed."""
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

ONLINE_CHECKS=('tls','source','resources','metrics','clean','readOnly','methods','sse')

def validate_online_receipt(receipt, source_sha, now=None):
    now=time.time() if now is None else now
    if not re.fullmatch(r'[0-9a-f]{64}',source_sha or ''): raise ValueError('缺少已部署源码指纹')
    if receipt.get('passed') is not True or receipt.get('productionEligible') is not True: raise ValueError('线上验收未通过或只是本地演练')
    if receipt.get('sourceSha256')!=source_sha: raise ValueError('线上验收对应其他源码版本')
    stamp=receipt.get('checkedAt')
    if not isinstance(stamp,(int,float)) or not -60<=now-stamp<=86400: raise ValueError('线上验收已过期，请重新检查')
    url=urlparse(receipt.get('url',''))
    if url.scheme!='https' or url.hostname!='lean.tano.asia' or url.port not in (None,443): raise ValueError('线上验收不是目标域名的 HTTPS 页面')
    if any(receipt.get('checks',{}).get(name) is not True for name in ONLINE_CHECKS): raise ValueError('线上验收存在未通过项')
    return receipt

def require_online_gate(run=None):
    file=Path(os.environ.get('ONLINE_RECEIPT','/approval/online.json'))
    try: receipt=json.loads(file.read_text())
    except (OSError,ValueError) as error: raise ValueError('缺少有效线上验收记录，不能启动真实验证') from error
    validated=validate_online_receipt(receipt,os.environ.get('SOURCE_SHA256',''))
    if receipt.get('resumeRun') is not None and receipt['resumeRun']!=run:
        raise ValueError('恢复验收只允许指定任务，不能创建或领取其他任务')
    return validated
