"""Read-only physical memory and whole FoldGPT UID accounting over ADB."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    adb=['adb','-s',args.serial]
    def read(*parts,app=False):
        argv=['run-as','app.foldgpt',*parts] if app else list(parts)
        result=subprocess.run(adb+['exec-out',shlex.join(argv)],capture_output=True,timeout=15)
        return {'code':result.returncode,'text':result.stdout.decode(errors='replace'),
                'stderr':result.stderr.decode(errors='replace')}
    uid=int(read('id','-u',app=True)['text'])
    rows=read('ps','-A','-o','UID,PID,PPID,NAME')['text'].splitlines()[1:]
    processes=[]
    for line in rows:
        fields=line.split(None,3)
        if len(fields)!=4 or fields[0]!=str(uid):continue
        pid=int(fields[1]);record={'pid':pid,'parent':int(fields[2]),'name':fields[3]}
        for name in ('status','smaps_rollup','limits','cgroup'):
            record[name]=read('cat',f'/proc/{pid}/{name}',app=True)
        processes.append(record)
    pss=sum(int(match[1]) for record in processes
        if (match:=re.search(r'^Pss:\s+(\d+) kB$',record['smaps_rollup']['text'],re.M)))
    report={'observedAt':datetime.now(timezone.utc).isoformat(),'uid':uid,
        'meminfo':read('cat','/proc/meminfo'),'processes':processes,'summedPssKiB':pss,
        'pssObservedCount':sum(record['smaps_rollup']['code']==0 for record in processes),
        'scope':'Sequential live process snapshot; PSS excludes some graphics driver accounting'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key!='processes'},indent=2))
    for record in processes:
        values={key:int(value) for key,value in re.findall(r'^(Pss|Rss|SwapPss):\s+(\d+) kB$',record['smaps_rollup']['text'],re.M)}
        print(json.dumps({'pid':record['pid'],'name':record['name'].split()[0],**values}))


if __name__=='__main__':main()
