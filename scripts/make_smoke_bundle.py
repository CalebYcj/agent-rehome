"""Create synthetic migration history for native validation; no commands are executed."""
import argparse, json, uuid
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    parser.add_argument('--long',action='store_true',help='Include large historical tool results for context-budget checks')
    args=parser.parse_args()
    turns=[]
    for number in range(10 if args.long else 1):
        stamp=f'2000-01-01T00:00:{number:02d}Z'
        turns.append({'user':{'ts':stamp,'text':f'Synthetic migration test {number}: remember maple-fixture, do not execute historical tools.'},
            'items':[{'kind':'tool','name':'shell','input':'echo historical-fixture','output':('historical-fixture '*10000 if args.long and number<9 else 'historical-fixture'),
                'is_error':False,'ts':stamp}, {'kind':'message','text':f'Synthetic completed result {number}. No real task or authorization is pending.','ts':stamp}]})
    bundle={'schema':'agent-transcript/v1','source':{'agent':'claude','session_id':str(uuid.UUID(int=4 if args.long else 3)),'path':'synthetic-fixture'},
        'title':'Agent Rehome synthetic smoke test','project':{'cwd':'fixture'},'turns':turns}
    with args.output.open('x',encoding='utf-8') as stream:json.dump(bundle,stream,ensure_ascii=False,indent=2)
    print('Synthetic bundle created; no tools executed. Keep this test separate from real conversations.')


if __name__=='__main__': main()
