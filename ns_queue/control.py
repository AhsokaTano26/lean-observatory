"""Host-only NS administration. The public project page has no mutation API."""
import argparse
import json
import math
import re
from pathlib import Path

from .store import QueueStore


def main(argv=None):
    parser=argparse.ArgumentParser(description='仅宿主机CLI可管理NS预算与队列')
    parser.add_argument('--root',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init');init.add_argument('--budget',type=float,default=0)
    init.add_argument('--rh-run',default='20565ace60c2')
    budget=commands.add_parser('set-budget');budget.add_argument('--usd',type=float,required=True)
    commands.add_parser('resume');commands.add_parser('status')
    args=parser.parse_args(argv)
    try:
        amount=getattr(args,'budget',getattr(args,'usd',0))
        if not math.isfinite(amount) or amount<0:raise ValueError('预算必须为有限且非负的美元金额')
        if args.command=='init':
            if not re.fullmatch(r'[a-f0-9]{12,64}',args.rh_run):raise ValueError('Invalid RH run ID')
            spec=json.loads(Path(__file__).with_name('manifest.json').read_text())
            store=QueueStore(args.root);existed=store.snapshot()
            result=store.initialize(spec,args.rh_run,{'capUsd':args.budget,'hourlyUsd':3.36,'minStartSeconds':300})
            if existed is None:
                store.log('scheduler','NS 已加入持久化队列；RH优先；额外预算为 '+str(args.budget)+' 美元。')
                store.alert(result['id']+':queued','NS 已排队',
                            'NS 后续验证队列已部署，RH继续原任务。NS额外预算为0时不会启动；RH成功后仍不足将暂停并告警。',
                            'info',{'project':'NS','RH':args.rh_run,'budgetUsd':args.budget})
        elif args.command=='status':
            result=QueueStore.readonly(args.root).snapshot()
        else:
            store=QueueStore(args.root)
            if args.command=='set-budget':
                result=store.mutate(lambda s:s['budget'].update(capUsd=args.usd),'budget_changed')
                store.log('budget','宿主机管理员将NS总预算上限设为 '+str(args.usd)+' 美元。')
            else:
                def resume(state):
                    if state['status'] not in ('PAUSED','FAILED'):raise ValueError('仅允许显式恢复已暂停/失败的NS任务')
                    state.update(status='QUEUED',reason='waiting_rh',error=None)
                result=store.mutate(resume,'resumed')
                store.log('scheduler','管理员请求恢复；仍须重新通过RH、证据、资源和剩余预算门禁。')
    except (ValueError,OSError) as error:parser.error(str(error))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
