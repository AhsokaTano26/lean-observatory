"""Load an explicitly synthetic, slow-running demo with backend-generated history."""
import argparse
import copy
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.store import Store
from backend.mock import tick,metrics,compiled_count


def seed(data, history_seconds=180, slowdown=20, tick_seconds=1):
    store=Store(Path(data));previous=store.raw()
    if previous and previous['mode']!='mock': raise RuntimeError('Refusing to replace real verification data')
    for active in store.active_runs():
        if active['mode']!='mock': raise RuntimeError('Real task present; Mock demo refused')
        store.control(active['id'],'cancel')
    s=store.create('mock','success');now=time.time();step=1/slowdown
    s.update(status='running',startedAt=now-30*slowdown*tick_seconds,mockTicks=round(30-step,10),mockStepTicks=slowdown)
    s['compile'].update(total=175187,succeeded=compiled_count(30-step))
    tick(s,tick_seconds)
    s.update(elapsedSeconds=30*slowdown*tick_seconds,activeSeconds=30*slowdown*tick_seconds)
    for i,stage in enumerate(s['stages']):
        if i<=3:
            stage['startedAt']=s['startedAt']+i*5*slowdown*tick_seconds
            if i<3:stage['finishedAt']=s['startedAt']+(i+1)*5*slowdown*tick_seconds
    store.mutate(s['id'],lambda current:current.update(s),'mock_demo_loaded')
    for offset in range(history_seconds,-1,-1):
        stamp=now-offset;n=max(0,30-offset/(slowdown*tick_seconds));past=copy.deepcopy(s)
        past['mockTicks']=n;past['phase']='compile' if n>=15 else 'dependencies'
        rate=max(0,compiled_count(n)-compiled_count(n-step))/tick_seconds if n>=15 else 0
        sample=metrics(past,now=stamp)
        sample.update(runId=s['id'],mode='mock',rate=round(rate,1),completed=compiled_count(n),observedAt=stamp)
        store.sample(sample)
    store.log(s['id'],'info',f'[MOCK] 已载入 {history_seconds} 秒合成历史；慢速模拟任务，不代表真实验证。','compile')
    return {'id':s['id'],'mode':'mock','historySeconds':history_seconds,'slowdown':slowdown}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data',default='.data');parser.add_argument('--seconds',type=int,default=180);parser.add_argument('--slowdown',type=int,default=20);parser.add_argument('--tick-seconds',type=float,default=1)
    args=parser.parse_args();print(json.dumps(seed(args.data,args.seconds,args.slowdown,args.tick_seconds)))
