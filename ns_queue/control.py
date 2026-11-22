"""Host-only hour authorization; no public task-control API."""
import argparse
import datetime
import json
import math
import re
from pathlib import Path
from .store import QueueStore
from .budget import normalize, parse_start


def main(argv=None):
    parser=argparse.ArgumentParser(description='宿主机CLI：从服务器租用起点计算总小时额度')
    parser.add_argument('--root',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init');init.add_argument('--hours',type=float,default=0)
    init.add_argument('--rh-run',default='20565ace60c2')
    budget=commands.add_parser('set-budget');budget.add_argument('--hours',type=float,required=True)
    budget.add_argument('--mode',choices=['enforce','notify-only'],help='notify-only：计时和资源预检只告警，RH成功后自动启动NS')
    budget.add_argument('--started-at',help='服务器租用起点，带时区ISO时间；后续设置沿用同一起点')
    commands.add_parser('resume');commands.add_parser('status')
    schedule=commands.add_parser('set-scheduling')
    schedule.add_argument('--mode',choices=['serial','parallel-replay'],required=True)
    args=parser.parse_args(argv)
    try:
        amount=getattr(args,'hours',0)
        if not math.isfinite(amount) or amount<0:raise ValueError('时长必须为有限且非负的小时数')
        if args.command=='init':
            if not re.fullmatch(r'[a-f0-9]{12,64}',args.rh_run):raise ValueError('Invalid RH run ID')
            spec=json.loads(Path(__file__).with_name('manifest.json').read_text())
            store=QueueStore(args.root);existed=store.snapshot()
            if existed is None and amount!=0:raise ValueError('首次初始化额度为0；请用set-budget设置小时数及服务器租用起点')
            result=store.initialize(spec,args.rh_run,{'capHours':amount,'hourlyUsd':3.36,'minStartSeconds':300})
            if existed is None:
                store.log('scheduler','NS 已加入持久化队列；RH优先；时长额度0小时，等待服务器租用起点和总时限配置。')
                store.alert(result['id']+':queued','NS 已排队','NS 后续验证队列已部署，RH继续原任务。配置总运行时限前，NS不会启动。',
                            'info',{'project':'NS','RH':args.rh_run,'capHours':0})
        elif args.command=='status':
            result=QueueStore.readonly(args.root).snapshot()
            if result:result['budget']=normalize(result['budget'])
        else:
            store=QueueStore(args.root)
            if args.command=='set-scheduling':
                def scheduling(s):
                    if s.get('startedAt') is not None:raise ValueError('已启动任务的调度授权不能在运行中更改')
                    s.update(schedulingMode=args.mode.replace('-','_'),schedulingAuthorizedAt=__import__('time').time())
                result=store.mutate(scheduling,'scheduling_authorized')
                store.log('scheduler','管理员设置调度模式：'+args.mode+'；RH 成功状态仍须真实最终证据确认。')
            elif args.command=='set-budget':
                state=store.snapshot();existing=state['budget']
                requested_start=parse_start(args.started_at) if args.started_at else None
                def configure(s):
                    current=s['budget']
                    start=requested_start if requested_start is not None else current.get('rentalStartedAt')
                    if start is None:raise ValueError('首次设置总时限必须提供--started-at服务器租用起点')
                    if current.get('scope')=='server' and current.get('rentalStartedAt')!=start:
                        raise ValueError('服务器租用起点已锁定，不能通过调整时限重新计时')
                    s['budget']=normalize({**current,'scope':'server','capHours':amount,'rentalStartedAt':start,
                        'enforcement':('notify_only' if args.mode=='notify-only' else 'hard') if args.mode else current.get('enforcement','hard')})
                    if s.get('startedAt') is None:s['compile']['jobs']=60
                result=store.mutate(configure,'server_budget_changed')
                configured=result['budget'];start=configured['rentalStartedAt']
                if existing.get('scope')!='server' or existing.get('capHours')!=amount or existing.get('enforcement','hard')!=configured['enforcement']:
                    deadline=datetime.datetime.fromtimestamp(configured['deadlineAt'],datetime.timezone.utc).isoformat()
                    store.log('budget','服务器总时限设为 '+str(amount)+' 小时；RH与NS共用同一租用窗口；截止 '+deadline)
                    store.alert('server-budget:'+str(start)+':'+str(amount)+':'+configured['enforcement'],'服务器运行时限已更新',
                                'RH与NS从同一租用时刻累计 '+str(amount)+' 小时。'+('RH成功归档后NS自动启动，时限和资源预检只告警，到期继续运行，由管理员决定停止。' if configured['enforcement']=='notify_only' else '到期暂停NS并告警，RH由管理员决定。'),
                                'info',{'capHours':amount,'deadlineUTC':deadline,'hourlyUsd':configured['hourlyUsd']})
            else:
                def resume(state):
                    if state['status'] not in ('PAUSED','FAILED'):raise ValueError('仅允许显式恢复已暂停/失败的NS任务')
                    state.update(status='QUEUED',reason='waiting_rh',error=None,pausedAt=None)
                result=store.mutate(resume,'resumed')
                store.log('scheduler','管理员请求恢复；仍须通过RH和证据检查，并沿用既定时限策略；租用起点不变。')
    except (ValueError,OSError) as error:parser.error(str(error))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
