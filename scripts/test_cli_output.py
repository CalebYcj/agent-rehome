"""CLI output survives legacy Windows encodings, including post-write output."""
import io,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import project_rehome as p
from cli_output import print as output_print

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();project=root/'project';project.mkdir();(project/'private-\ue11f.md').write_text('fixture',encoding='utf-8')
    inventory=root/'empty.json';inventory.write_text('[]',encoding='utf-8');package=root/'package-\ue11f'
    output=io.BytesIO();stream=io.TextIOWrapper(output,encoding='cp936')
    with patch.object(sys,'stdout',stream),patch.object(sys,'argv',['project_rehome','pack','--from','claude','--project',str(project),'--sessions-json',str(inventory),'--out',str(package)]):
        p.main();stream.flush()
    assert (package/'manifest.json').is_file()
    assert output.getvalue().decode('utf-8').strip()
    legacy_bytes=io.BytesIO();legacy=io.TextIOWrapper(legacy_bytes,encoding='cp936')
    output_print(json.dumps({'name':'\ue11f'},ensure_ascii=False),file=legacy,flush=True)
    assert json.loads(legacy_bytes.getvalue().decode('cp936'))['name']=='\ue11f'
print('PASS: cp936 stdout with private-use filenames, successful write and readable UTF-8 result')

# Both documentation headers must identify the version shipped in this tree.
root = Path(__file__).resolve().parents[1]
version = (root/'VERSION').read_text(encoding='utf-8').strip()
for filename, prefix in (('README.md','版本'), ('README.en.md','Version')):
    header = (root/filename).read_text(encoding='utf-8').splitlines()[:6]
    line, = (line for line in header if line.startswith(prefix+' **'))
    assert line.split('**')[1] == version, filename
