"""Read source bytes without changing files; zstd support is optional and ordered."""
import importlib,importlib.util,shutil,subprocess
from pathlib import Path

DECODER_HINT='读取 .jsonl.zst 需要解压器：使用 Python 3.14+，或运行 python -m pip install zstandard，或安装 zstd 命令；来源文件未改动'

def zstd_decoder():
    """Name of the first available zstd decoder, or None. Imports nothing permanently and runs nothing."""
    for name in ('compression.zstd','zstandard'):
        if importlib.util.find_spec(name.split('.')[0]) is None:continue
        try:importlib.import_module(name);return name
        except ImportError:continue
    return 'zstd' if shutil.which('zstd') else None

def is_compressed(path):
    """True when the rollout is (or has been compressed on disk to) .jsonl.zst."""
    path=str(path)
    return path.endswith('.zst') or (not Path(path).exists() and Path(path+'.zst').exists())

def source_bytes(path):
    data=Path(path).read_bytes()
    if not str(path).endswith('.zst'):return data
    for name in ('compression.zstd','zstandard'):
        try:module=importlib.import_module(name)
        except ImportError:continue
        try:
            if name=='compression.zstd':return module.decompress(data)
            # Streaming accepts frames without a declared decompressed size.
            import io
            with module.ZstdDecompressor().stream_reader(io.BytesIO(data)) as reader:return reader.read()
        except Exception as error:raise ValueError('zstd 解压失败：'+str(error)) from error
    command=shutil.which('zstd')
    if command:
        result=subprocess.run([command,'-d','-c'],input=data,capture_output=True)
        if result.returncode:raise ValueError('zstd 解压失败：'+result.stderr.decode('utf-8',errors='replace'))
        return result.stdout
    raise ValueError(DECODER_HINT)
