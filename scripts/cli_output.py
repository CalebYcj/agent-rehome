"""UTF-8 CLI output; a completed write must not fail on console encoding."""
import builtins, sys

def configure():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            try: stream.reconfigure(encoding='utf-8',errors='backslashreplace')
            except (ValueError,OSError): pass

def print(*args,**kwargs):
    stream=kwargs.get('file') or sys.stdout
    try:
        builtins.print(*args,**kwargs)
    except UnicodeEncodeError:
        encoding=getattr(stream,'encoding',None) or 'utf-8'
        text=kwargs.get('sep',' ').join(str(value) for value in args)+kwargs.get('end','\n')
        stream.write(text.encode(encoding,errors='backslashreplace').decode(encoding))
        if kwargs.get('flush'): stream.flush()
    except BrokenPipeError:
        # No data mutation or retry: the caller still receives the function's result/status.
        pass
