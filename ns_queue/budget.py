"""Hour-based authorization; the shared server window never restarts with a job."""
import datetime
from decimal import Decimal
import math
import time


def number(value, name):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise ValueError('invalid budget: '+name)
    return float(value)


def normalize(budget, now=None):
    if not isinstance(budget,dict):raise ValueError('invalid budget')
    now=time.time() if now is None else number(now,'now')
    rate=number(budget.get('hourlyUsd',3.36),'hourlyUsd')
    if rate<=0:raise ValueError('invalid budget: hourlyUsd')
    cap=number(budget['capHours'],'capHours') if 'capHours' in budget else number(budget.get('capUsd',0),'capUsd')/rate
    minimum=number(budget.get('minStartSeconds',300),'minStartSeconds')
    scope=budget.get('scope','ns')
    mode=budget.get('enforcement','hard')
    if mode not in ('hard','notify_only') or mode=='notify_only' and scope!='server':raise ValueError('invalid budget enforcement')
    if scope=='server':
        start=number(budget.get('rentalStartedAt'),'rentalStartedAt')
        if start>now:raise ValueError('rental start is in the future')
        deadline=start+cap*3600
        used=(now-start)/3600
    elif scope=='ns':
        start=deadline=None
        used=number(budget['usedHours'],'usedHours') if 'usedHours' in budget else number(budget.get('estimatedUsd',0),'estimatedUsd')/rate
    else:raise ValueError('invalid budget scope')
    result={**budget,'unit':'hours','scope':scope,'capHours':cap,'usedHours':used,
            'remainingHours':max(0,cap-used),'enforcement':mode,'hourlyUsd':rate,'minStartSeconds':minimum,
            'rentalStartedAt':start,'deadlineAt':deadline,'capUsd':cap*rate,'estimatedUsd':used*rate}
    for key in ['capUsd','estimatedUsd','usedHours','remainingHours']:
        number(result[key],key)
    if deadline is not None:number(deadline,'deadlineAt')
    return result


def available_seconds(budget, now=None):
    normalized=normalize(budget,now)
    return normalized['remainingHours']*3600


def can_start(budget, now=None):
    try:
        b=normalize(budget,now)
        if b['enforcement']=='notify_only':return True
        # Microsecond resolution avoids rejecting exactly five minutes expressed
        # as a fractional JSON hour; prices never participate in this comparison.
        remaining=(Decimal(str(b['capHours']))-Decimal(str(b['usedHours'])))*3600
        return b['capHours']>0 and remaining.quantize(Decimal('0.000001'))>=max(300,b['minStartSeconds'])
    except (ValueError,TypeError,OverflowError,ArithmeticError):return False


def runtime_usage(budget, hours, now=None):
    if budget.get('scope')=='server':return normalize(budget,now)
    return normalize({**budget,'usedHours':number(hours,'usedHours')},now)


def parse_start(text, now=None):
    try:date=datetime.datetime.fromisoformat(text.replace('Z','+00:00'))
    except (ValueError,AttributeError) as error:raise ValueError('租用起点必须是带时区的ISO时间') from error
    if date.tzinfo is None or date.utcoffset() is None:raise ValueError('租用起点必须包含时区')
    stamp=date.timestamp()
    if stamp>(time.time() if now is None else now):raise ValueError('租用起点不能在未来')
    return number(stamp,'rentalStartedAt')
