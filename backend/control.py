"""Host-side task administration. Never exposed by the HTTP service."""
import argparse
import json
import os
from pathlib import Path
from .store import Store


def main(argv=None):
    parser=argparse.ArgumentParser(description='通过宿主机命令行管理验证任务；Web 仅提供展示')
    parser.add_argument('--data',default='.data')
    commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('create')
    create.add_argument('--mode',choices=['mock','real'],default='mock')
    create.add_argument('--scenario',choices=['success','failure','interruption','resource'],default='success')
    create.add_argument('--jobs',type=int,default=48)
    commands.add_parser('list')
    for name in ['pause','resume','cancel']:
        commands.add_parser(name).add_argument('run')
    args=parser.parse_args(argv)
    if args.command=='create' and args.mode=='real' and os.environ.get('ENABLE_REAL')!='1':
        parser.error('真实任务尚未通过部署验收门禁；ENABLE_REAL 必须保持 0 直到线上验收通过')
    store=Store(Path(args.data))
    try:
        if args.command=='create': result=store.create(args.mode,args.scenario,args.jobs)
        elif args.command=='list': result=store.runs()
        else: result=store.control(args.run,args.command)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
