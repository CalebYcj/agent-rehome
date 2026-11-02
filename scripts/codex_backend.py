"""Internal Codex writer used by the guarded agent_rehome.py entry point.

Not a standalone command: validation, backups and no-overwrite guards are
provided by the caller.
"""
from contextlib import closing
import base64, mimetypes
from pathlib import Path
from platform_paths import storage_path,path_key
import argparse
import datetime as dt
import glob
import json
import os
import shutil
import sqlite3
import sys
import uuid

NS = uuid.UUID("6f1c2a9e-4b7d-4c1e-9a3f-c1a0dec0de01")
TOOL_RESULT_LIMIT = 1500
TOOL_INPUT_LIMIT = 600


def iso(ts):
    return ts if ts else dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def to_ms(ts):
    return int(dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


def clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"\n…[已截断，原长 {len(text)} 字符]"


def find_session(arg):
    if os.path.isfile(arg):
        return arg
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{arg}.jsonl"))
    if not hits:
        sys.exit(f"找不到 Claude 会话: {arg}")
    return hits[0]


def result_text(content):
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
        elif c.get("type") == "image":
            parts.append("[图片]")
    return "\n".join(parts)


def describe_tool(block):
    inp = block.get("input") or {}
    name = block.get("name", "tool")
    desc = inp.get("description") or ""
    body = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("url") or inp.get("prompt")
    if body is None:
        body = json.dumps(inp, ensure_ascii=False)
    head = f"[Claude 工具调用 · {name}]" + (f" {desc}" if desc else "")
    return f"{head}\n```\n{clip(str(body), TOOL_INPUT_LIMIT)}\n```"


def parse_claude(path, include_tools):
    """Return (turns, title, first_ts, last_ts). Each turn: {'user': (ts, text), 'agent': [(ts, text)]}."""
    records = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    title = None
    results = {}
    for r in records:
        if r.get("type") == "custom-title":
            title = r.get("customTitle") or r.get("title") or title
        msg = r.get("message") or {}
        if r.get("type") == "user" and isinstance(msg.get("content"), list):
            for c in msg["content"]:
                if c.get("type") == "tool_result":
                    results[c.get("tool_use_id")] = result_text(c.get("content"))

    turns, first_ts, last_ts = [], None, None
    for r in records:
        if r.get("type") not in ("user", "assistant") or r.get("isMeta") or r.get("isSidechain"):
            continue
        ts = r.get("timestamp")
        msg = r.get("message") or {}
        content = msg.get("content")
        if r["type"] == "user":
            if isinstance(content, str):
                text = content
            else:
                text = "\n".join(c.get("text", "") for c in content or [] if c.get("type") == "text")
            if not text.strip():
                continue  # tool_result carrier
            turns.append({"user": (ts, text), "agent": []})
        else:
            if not turns:
                continue
            for c in content or []:
                if c.get("type") == "text" and c.get("text", "").strip():
                    turns[-1]["agent"].append((ts, c["text"]))
                elif c.get("type") == "tool_use" and include_tools:
                    out = results.get(c.get("id"))
                    text = describe_tool(c)
                    if out is not None:
                        text += f"\n结果：\n```\n{clip(out, TOOL_RESULT_LIMIT)}\n```"
                    turns[-1]["agent"].append((ts, text))
        first_ts = first_ts or ts
        last_ts = ts or last_ts
    return turns, title, first_ts, last_ts


class Rollout:
    def __init__(self, thread_id):
        self.thread_id = thread_id
        self.lines = []

    def add(self, ts, typ, payload, **extra):
        rec = {"timestamp": iso(ts), "ordinal": len(self.lines), "type": typ, "payload": payload}
        rec.update(extra)
        self.lines.append(rec)


def build_rollout(thread_id, turns, cwd, model, first_ts, source_path):
    ro = Rollout(thread_id)
    ro.add(first_ts, "session_meta", {
        "session_id": thread_id, "id": thread_id, "timestamp": iso(first_ts), "cwd": cwd,
        "originator": "codex_work_desktop", "cli_version": "claude-import", "source": "vscode",
        "thread_source": "user", "model_provider": "openai", "history_mode": "paginated",
        "imported_from": {"agent": "claude_code", "path": source_path},
    })
    note = ("这是迁移过来的可见对话历史（工具调用以文本保留，不代表新授权）。"
            "继续对话时请把它当作已发生的上下文，当前工作目录为：" + cwd)
    for i, turn in enumerate(turns):
        turn_id = str(uuid.uuid5(NS, f"{thread_id}/turn/{i}"))
        uts, utext = turn["user"]
        start_s = to_ms(uts) // 1000
        ro.add(uts, "event_msg", {"type": "task_started", "turn_id": turn_id, "root_turn_id": turn_id,
                                  "started_at": start_s, "model_context_window": 475000,
                                  "collaboration_mode_kind": "default"})
        ro.add(uts, "turn_context", {"turn_id": turn_id, "root_turn_id": turn_id, "cwd": cwd,
                                     "approval_policy": "on-request", "sandbox_policy": {"type": "workspace-write", "writable_roots": [], "network_access": False, "exclude_tmpdir_env_var": False, "exclude_slash_tmp": False},
                                     "model": model, "effort": "medium", "summary": "none"})
        if i == 0:
            ro.add(uts, "response_item", {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": note}]})
        uid = str(uuid.uuid5(NS, f"{turn_id}/user"))
        ro.add(uts, "response_item", {"type": "message", "role": "user",
                                      "content": [{"type": "input_text", "text": utext}]})
        ro.add(uts, "event_msg", {"type": "item_completed", "thread_id": thread_id, "turn_id": turn_id,
                                  "item": {"type": "UserMessage", "id": uid,
                                           "content": [{"type": "text", "text": utext, "text_elements": []}]},
                                  "started_at_ms": to_ms(uts), "completed_at_ms": to_ms(uts)})
        attachments = globals().get("import_attachments", [])
        if i < len(attachments):
            for att in attachments[i]:
                if not att.get("image"): continue
                path = Path(att["local_path"])
                mime = att.get("mime") or mimetypes.guess_type(path)[0] or "image/png"
                url = "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode()
                # Real sampled Codex UI local_image + provider input_image formats.
                ro.lines[-2]["payload"]["content"].append({"type":"input_image","image_url":url,"detail":"original"})
                ro.lines[-1]["payload"]["item"]["content"].append({"type":"local_image","path":str(path)})
        last_text, end_ts = "", uts
        for j, (ats, atext) in enumerate(turn["agent"]):
            ats = ats or uts
            phase = "final_answer" if j == len(turn["agent"]) - 1 else "commentary"
            mid = f"msg_{uuid.uuid5(NS, f'{turn_id}/agent/{j}').hex}"
            ro.add(ats, "event_msg", {"type": "item_completed", "thread_id": thread_id, "turn_id": turn_id,
                                      "item": {"type": "AgentMessage", "id": mid,
                                               "content": [{"type": "Text", "text": atext}], "phase": phase},
                                      "started_at_ms": to_ms(ats), "completed_at_ms": to_ms(ats)})
            ro.add(ats, "response_item", {"type": "message", "status": "completed", "role": "assistant",
                                          "content": [{"type": "output_text", "text": atext, "annotations": []}],
                                          "phase": phase})
            last_text, end_ts = atext, ats
        ro.add(end_ts, "event_msg", {"type": "task_complete", "turn_id": turn_id, "root_turn_id": turn_id,
                                     "last_agent_message": last_text[:500], "started_at": start_s,
                                     "completed_at": to_ms(end_ts) // 1000,
                                     "duration_ms": max(0, to_ms(end_ts) - to_ms(uts))})
    return ro


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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session", help="Claude 会话 id 或 .jsonl 路径")
    ap.add_argument("--cwd", required=True, help="Codex 里的目标项目目录")
    ap.add_argument("--title", help="Codex 中显示的标题（默认用 Claude 标题）")
    ap.add_argument("--project-name", help="若目标目录还不是 Codex 项目，新建项目时用的名字")
    ap.add_argument("--no-project", action="store_true", help="不创建/关联 Codex 项目")
    ap.add_argument("--model", help="Target model; auto-detected from target config/history")
    ap.add_argument("--no-tools", action="store_true", help="不保留工具调用记录")
    ap.add_argument("--codex-home", default=os.path.expanduser("~/.codex"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="覆盖已在 Codex 中继续过的线程")
    a = ap.parse_args()
    from target_settings import codex_model
    a.model = codex_model(Path(a.codex_home).resolve(), a.model)

    src = find_session(a.session)
    claude_id = os.path.splitext(os.path.basename(src))[0]
    cwd = os.path.abspath(a.cwd)
    turns, ctitle, first_ts, last_ts = parse_claude(src, not a.no_tools)
    if not turns:
        sys.exit("会话里没有可迁移的对话")
    title = a.title or ctitle or turns[0]["user"][1].strip().splitlines()[0][:60]
    thread_id = globals().get("target_thread_id") or str(uuid.uuid5(NS, "claude/" + claude_id))
    ro = build_rollout(thread_id, turns, cwd, a.model, first_ts, src)

    stamp = dt.datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
    rel = os.path.join("sessions", stamp.strftime("%Y"), stamp.strftime("%m"), stamp.strftime("%d"),
                       f"rollout-{stamp.strftime('%Y-%m-%dT%H-%M-%S')}-{thread_id}.jsonl")
    rollout_path = os.path.normpath(os.path.join(a.codex_home, rel))
    src = os.path.normpath(src)
    print(f"Claude 会话 : {src}\n轮次       : {len(turns)}\nCodex 线程 : {thread_id}\n标题       : {title}\n"
          f"rollout    : {rollout_path}\n目标项目   : {cwd}")
    if a.dry_run:
        return
    if os.path.exists(rollout_path) and not a.force:
        with open(rollout_path, encoding="utf-8") as f:
            if any('"token_count"' in l for l in f):
                sys.exit("这个线程已经在 Codex 里继续聊过了，重新导入会覆盖 Codex 侧的新内容。确需覆盖请加 --force。")

    os.makedirs(os.path.dirname(rollout_path), exist_ok=True)
    with open(rollout_path, "w", encoding="utf-8", newline="\n") as f:
        for rec in ro.lines:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    idx = os.path.join(a.codex_home, "session_index.jsonl")
    kept = [l for l in open(idx, encoding="utf-8")] if os.path.exists(idx) else []
    kept = [l for l in kept if json.loads(l).get("id") != thread_id]
    kept.append(json.dumps({"id": thread_id, "thread_name": title, "updated_at": iso(last_ts)[:19] + "Z"},
                           ensure_ascii=False) + "\n")
    with open(idx, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(kept)

    dbp = os.path.join(a.codex_home, "state_5.sqlite")
    backup = dbp + ".bak-claude-import-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    src_db = sqlite3.connect(dbp)
    with closing(sqlite3.connect(backup)) as b:
        src_db.backup(b)
    db = src_db
    pid = None if a.no_project else ensure_project(db, cwd, a.project_name or os.path.basename(cwd))
    c_ms, u_ms = to_ms(first_ts), to_ms(last_ts)
    first_msg = turns[0]["user"][1][:2000]
    db.execute("delete from threads where id=?", (thread_id,))
    db.execute("""insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,
        sandbox_policy,approval_mode,tokens_used,has_user_event,archived,cli_version,first_user_message,memory_mode,
        model,reasoning_effort,created_at_ms,updated_at_ms,thread_source,preview,recency_at,recency_at_ms,history_mode,
        name,project_id,originator) values(?,?,?,?,?,?,?,?,?,?,0,1,0,?,?,'enabled',?,?,?,?,?,?,?,?,?,?,?,?)""",
               (thread_id, rollout_path, c_ms // 1000, u_ms // 1000, "vscode", "openai", long_path(cwd), title,
                '{"type":"workspace-write"}', "on-request", "claude-import", first_msg, a.model, "medium", c_ms, u_ms, "user",
                first_msg[:200], u_ms // 1000, u_ms, "paginated", title, pid, "codex_work_desktop"))
    db.commit()
    db.close()
    print(f"已写入。数据库备份：{backup}\n可通过 Codex 原生接口加载；侧边栏和项目归属仍需单独核对。")


if __name__ == "__main__":
    sys.exit("Internal writer: use agent_rehome.py for guarded imports.")
