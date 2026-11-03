"""Native metadata relocation keeps directory suffixes and outside values private."""
import argparse,json,sys,tempfile,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import claude_native as n,project_rehome as p

def encoded(values):
    return b'\xef\xbb\xbf'+''.join(' { "cwd" : '+json.dumps(value,ensure_ascii=False)+', "message":{"cwd":"nested stays","content":"historical body"} }\r\n' for value in values).encode('utf-8')

def values(data):return [json.loads(line)['cwd'] for line in data.decode('utf-8-sig').split('\n') if line.strip()]

old='F:\\proj';original=[old,old+'\\抖音美学号',old+'\\抖音美学号\\ep01', 'f:/PROJ/抖音美学号/ep01',old+'2', 'G:\\outside',old+'\\..\\outside','']
data=encoded(original);stats={}
mapped=n.rewrite_cwd(data,old,'/目标',stats=stats)
assert values(mapped)==['/目标','/目标/抖音美学号','/目标/抖音美学号/ep01','/目标/抖音美学号/ep01',old+'2','G:\\outside',old+'\\..\\outside','']
assert stats['outside_rows']==3 and len(stats['outside_values'])==3
assert mapped.startswith(b'\xef\xbb\xbf') and mapped.count(b'\r\n')==len(original)
assert b'"message":{"cwd":"nested stays","content":"historical body"}' in mapped
assert values(n.rewrite_cwd(data,old,'D:\\target'))[:4]==['D:\\target','D:\\target\\抖音美学号','D:\\target\\抖音美学号\\ep01','D:\\target\\抖音美学号\\ep01']
assert values(n.rewrite_cwd(encoded(['/src','/src/中文/ep01','/src2','/SRC/child']),'/src','D:\\target'))==['D:\\target','D:\\target\\中文\\ep01','/src2','/SRC/child']
assert values(n.rewrite_cwd(encoded(['/src/中文/ep01']),'/src','/dest'))==['/dest/中文/ep01']
assert values(n.rewrite_cwd(encoded(['F:\\child']), 'F:\\','/'))==['/child']
assert values(n.rewrite_cwd(encoded(['/outside']),'.','/dest'))==['/outside']
assert values(n.rewrite_cwd(encoded(['\\\\server\\share\\proj\\中文']), '\\\\server\\share\\proj','/dest'))==['/dest/中文']
assert values(n.rewrite_cwd(encoded(['\\\\?\\F:\\proj\\中文']),old,'/dest'))==['/dest/中文']
# Unmatched records are byte-preserved, including cwd's original JSON escape spelling.
outside=b'{"cwd":"G:\\\\outside", "message":{"content":"F:\\\\proj"}}\r\n'
assert n.rewrite_cwd(outside,old,'/dest')==outside

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);home=root/'source-home';folder=home/'projects/fixture';folder.mkdir(parents=True)
    sid=str(uuid.uuid4());source=folder/(sid+'.jsonl');sub=folder/sid/'subagents';sub.mkdir(parents=True)
    rows=[{'type':'custom-title','customTitle':'directory fixture'},
        {'type':'user','sessionId':sid,'cwd':old,'version':'0.0.0-test','timestamp':'2026-11-01T00:00:00Z','message':{'content':'synthetic request'}},
        {'type':'assistant','cwd':old+'\\中文\\ep01','message':{'content':[{'type':'text','text':'historical output'}]}},
        {'type':'system','cwd':'G:\\outside'},{'type':'system','cwd':'G:\\outside'},{'type':'system','cwd':old+'2'}]
    raw=b'\xef\xbb\xbf'+('\r\n'.join(json.dumps(row,ensure_ascii=False) for row in rows)+'\r\n').encode('utf-8');source.write_bytes(raw)
    sub_raw=encoded([old+'\\中文\\ep01\\assets','G:\\outside']);(sub/'agent.jsonl').write_bytes(sub_raw)
    memory=folder/'memory';memory.mkdir();unchanged=b'{"cwd":"F:\\\\proj\\\\memory"}\r\n';(memory/'notes.jsonl').write_bytes(unchanged)
    history=home/'file-history'/sid;history.mkdir(parents=True);(history/'old.jsonl').write_bytes(unchanged)
    snap=n.snapshot(source,home,include_memory=True,include_checkpoints=True)
    assert snap['source']['cwd']==old
    package=root/'native';manifest=n.pack(snap,package);assert manifest['source']['cwd']==old
    loaded=n.load(package);target=root/'target';target.mkdir();target_home=root/'target-home'
    args=argparse.Namespace(cwd=str(target),target_home=str(target_home),to='claude',dry_run=True,no_desktop=True,desktop_registry=None)
    preview=n.restore(loaded,args);assert not target_home.exists()
    assert preview['outside_cwd_rows']==4 and preview['outside_cwd_values']==2
    warning=next(w for w in preview['warnings'] if 'out-of-project cwd' in w)
    assert '4' in warning and '2' in warning and 'G:' not in warning and old not in warning
    args.dry_run=False;result=n.restore(loaded,args)
    assert (result['outside_cwd_rows'],result['outside_cwd_values'])==(4,2)
    restored=next(target_home.glob('projects/*/'+sid+'.jsonl'));actual=[json.loads(line) for line in restored.read_text(encoding='utf-8-sig').split('\n') if line.strip()]
    assert actual[1]['cwd']==str(target.resolve()) and actual[2]['cwd']==str(target.resolve()/'中文/ep01')
    assert actual[3]['cwd']==actual[4]['cwd']=='G:\\outside' and actual[5]['cwd']==old+'2'
    assert restored.read_bytes()==n.rewrite_cwd(raw,old,str(target.resolve()))
    assert (restored.with_suffix('')/'subagents/agent.jsonl').read_bytes()==n.rewrite_cwd(sub_raw,old,str(target.resolve()))
    assert (restored.parent/'memory/notes.jsonl').read_bytes()==unchanged
    assert (target_home/'file-history'/sid/'old.jsonl').read_bytes()==unchanged
    # Project inventory root overrides a session whose first cwd already starts in a child.
    project=root/'project';project.mkdir();(project/'file.txt').write_text('fixture',encoding='utf-8')
    project_rows=[dict(rows[1],cwd=str(project/'中文')),dict(rows[2],cwd=str(project/'中文/ep01'))]
    project_raw=''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in project_rows).encode('utf-8');source.write_bytes(project_raw)
    (sub/'agent.jsonl').write_bytes(encoded([str(project/'中文/ep01/assets')]))
    assert n.snapshot(source,home)['source']['cwd']==str(project/'中文')
    packed=root/'project-package';p.pack('claude',project,packed,home,[{'snapshot':str(source),'title':'project root'}],native=True)
    native_manifest=json.loads((packed/'sessions'/sid/'raw-native/manifest.json').read_text(encoding='utf-8'))
    assert native_manifest['source']['cwd']==str(project.resolve())
    project_target=root/'project-target';project_home=root/'project-home';p.restore(packed,project_target,'claude',project_home,True)
    restored_project=next(project_home.glob('projects/*/'+sid+'.jsonl'))
    assert values(restored_project.read_bytes())==[str(project_target.resolve()/'中文'),str(project_target.resolve()/'中文/ep01')]
    assert values((restored_project.with_suffix('')/'subagents/agent.jsonl').read_bytes())==[str(project_target.resolve()/'中文/ep01/assets')]
print('PASS: prefix relocation, Chinese child paths, cross-platform separators/case/boundaries, outside counts/privacy, lexical preservation, manifest roots and native project restore')
