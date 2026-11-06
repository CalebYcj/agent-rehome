"""Internal Codex writer; caller supplies validated history, backups and overwrite guards."""
from contextlib import closing
from pathlib import Path
from platform_paths import storage_path,path_key
import datetime as dt
import json,os,sqlite3,uuid

NS = uuid.UUID("6f1c2a9e-4b7d-4c1e-9a3f-c1a0dec0de01")


def indexed_title(home,thread_id):
    """Read the last matching sidebar title; callers retain their own fallbacks."""
    path=Path(home)/'session_index.jsonl';title=None
    if not path.exists():return None
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip():continue
            record=json.loads(line)
            if record.get('id')==thread_id:
                value=record.get('thread_name')
                title=value if isinstance(value,str) and value.strip() else None
    return title


def iso(ts):
    return ts if ts else dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def to_ms(ts):
    return int(dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


def clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"\n…[已截断，原长 {len(text)} 字符]"


class Rollout:
    def __init__(self, thread_id):
        self.thread_id = thread_id
        self.lines = []

    def add(self, ts, typ, payload, **extra):
        rec = {"timestamp": iso(ts), "ordinal": len(self.lines), "type": typ, "payload": payload}
        rec.update(extra)
        self.lines.append(rec)


def long_path(p):
    return storage_path(p)


def ensure_project(db, cwd, name):
    for pid, path in db.execute("select project_id, path from project_roots"):
        if path_key(path) == path_key(cwd):
            return pid
    pid = str(uuid.uuid5(NS, "project/" + path_key(cwd)))
    now = int(dt.datetime.now().timestamp() * 1000)
    pos = (db.execute("select coalesce(max(position), -1) from projects").fetchone()[0]) + 1
    db.execute("insert into projects(id,name,metadata,position,created_at_ms,updated_at_ms) values(?,?,?,?,?,?)",
               (pid, name, "{}", pos, now, now))
    db.execute("insert into project_roots(project_id,position,path) values(?,?,?)", (pid, 0, cwd))
    return pid


def write_codex_thread(home,thread_id,ro,cwd,title,model,*,first_ts,last_ts,first_user_message):
    """Persist a prepared rollout/index/thread/project; no CLI or module-state overrides."""
    title = title or first_user_message.strip().splitlines()[0][:60]
    stamp = dt.datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
    rel = os.path.join("sessions", stamp.strftime("%Y"), stamp.strftime("%m"), stamp.strftime("%d"),
                       f"rollout-{stamp.strftime('%Y-%m-%dT%H-%M-%S')}-{thread_id}.jsonl")
    rollout_path = os.path.normpath(os.path.join(home, rel))
    os.makedirs(os.path.dirname(rollout_path), exist_ok=True)
    with open(rollout_path, "w", encoding="utf-8", newline="\n") as f:
        for rec in ro.lines:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    idx = os.path.join(home, "session_index.jsonl")
    kept = [l for l in open(idx, encoding="utf-8")] if os.path.exists(idx) else []
    kept = [l for l in kept if json.loads(l).get("id") != thread_id]
    kept.append(json.dumps({"id": thread_id, "thread_name": title, "updated_at": iso(last_ts)[:19] + "Z"},
                           ensure_ascii=False) + "\n")
    with open(idx, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(kept)

    dbp = os.path.join(home, "state_5.sqlite")
    backup = dbp + ".bak-claude-import-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    db = sqlite3.connect(dbp)
    with closing(sqlite3.connect(backup)) as b:
        db.backup(b)
    pid = ensure_project(db, cwd, os.path.basename(cwd))
    c_ms, u_ms = to_ms(first_ts), to_ms(last_ts)
    first_msg = first_user_message[:2000]
    db.execute("delete from threads where id=?", (thread_id,))
    db.execute("""insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,
        sandbox_policy,approval_mode,tokens_used,has_user_event,archived,cli_version,first_user_message,memory_mode,
        model,reasoning_effort,created_at_ms,updated_at_ms,thread_source,preview,recency_at,recency_at_ms,history_mode,
        name,project_id,originator) values(?,?,?,?,?,?,?,?,?,?,0,1,0,?,?,'enabled',?,?,?,?,?,?,?,?,?,?,?,?)""",
               (thread_id, rollout_path, c_ms // 1000, u_ms // 1000, "vscode", "openai", long_path(cwd), title,
                '{"type":"workspace-write"}', "on-request", "claude-import", first_msg, model, "medium", c_ms, u_ms, "user",
                first_msg[:200], u_ms // 1000, u_ms, "paginated", title, pid, "codex_work_desktop"))
    db.commit()
    db.close()
    return Path(rollout_path)
