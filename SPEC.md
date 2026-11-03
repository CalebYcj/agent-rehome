# agent-exchange/v2

实现状态：架构测试版。协议与来源适配器在 `scripts/exchange.py`，目标写入器继续通过显式 v1 适配层工作。只有 Claude、Codex 两种来源已实现；新增 Agent 必须提供读取、损失审计和写入适配器，不能仅修改枚举宣称支持。

## 两条路线

同类迁移保留来源原生数据。Codex 使用 ReHome Desktop 或 codex-rehome-skill；Claude 使用 `claude_native.py`。跨 Agent 使用下面的交换格式。显式 `--convert` 允许同类走有损转换，仅供测试、诊断。

Claude 原生包独立使用 `claude-native/v1`：manifest 含来源 ID、version、标题、安全登记模板和文件清单；`raw/project/` 保存主 JSONL、同 ID 子目录和可选 memory，`raw/file-history/` 保存可选检查点。文件按 SHA-256 核对。原生恢复不使用转换事件、不生成上下文摘要。

## 目录项目包

恢复时，多条来源映射同一目标且 SHA256 相同则只写入、校验一次，restore.json 的 deduplicated 记录目标、哈希、包内来源路径及 source_count/skipped_copies；不同内容仍在创建目标目录前拒绝，并指出冲突的包内路径。

```text
manifest.json                     schema=agent-exchange/v2, type=project
project/                          项目文件
attachments/<sha256>.<suffix>     内容寻址附件
sessions/<id>/events.jsonl        标准事件流
sessions/<id>/losses.json         损失清单
sessions/<id>/raw-native/         可选、显式 --native 的 Claude 原生包
```

manifest 字段：

- `source`: agent、os；每个会话的 source 另含 agent_version（未知为 null）。
- `project`: name、root_hint、files[{path,sha256,bytes,permissions?}]。
- `attachments`: 附件表，含 path、sha256、bytes、name、original、mode，以及 image、mime（若适用）。事件使用 `{ref:sha256}` 并可携带该次出现的 name/original/mode/image/mime；不内嵌字节。同一内容只存一份，但每次出现的来源名称和路径分别保留。
- `sessions`: id、metadata、events{path,sha256}、losses{path,sha256}、branches[{id,events_ref}]，可选 native{path,manifest_sha256}。metadata 包含 source/title/project/session/losses_summary，不内嵌会话内容。
- `losses_summary`: 按 `kind:reason:action` 计数；`project_losses` 记录无法打包的会话、附件等，skipped 保留诊断细节。

引用必须是包内相对 POSIX 路径；拒绝绝对路径、反斜杠、冒号、`..` 和解析后逃逸包根的链接。读取先校验引用、hash、身份和分支，再操作目标。v2 恢复仍返回内部 v1 投影供旧写入器使用。

## 单会话对象与事件

单会话 export 输出 JSON 对象：schema、type=session、source、title、project、session、events、losses、losses_summary。`source` 包含 agent、session_id、path、exported_at、agent_version；session 包含 id、branches、forked_from、subagent_of。v1 缺失的来源、分支事实保持 null，不猜造。

每个事件都有 `id,parent_id,seq,ts,turn_id,branch,kind,raw_ref`。seq 从 0 连续递增，以标准化投影顺序为准。主线消息/工具按可见历史顺序生成，未投影的来源审计事件随后附加；因此 seq 不是原文件行号。原文件顺序应查 raw_ref。parent_id 只指向已出现事件；来源分支及原生父链完整保留属于原生/raw 路线，跨 Agent 不承诺完整复建。

raw_ref 为 null，或 `{file,line,sha256,block?}`：file 为来源文件名，line 是从 1 开始的物理行号，sha256 对该行原始字节计算（不含行尾，首行 BOM 计入），block 可指 content 数组下标。它是溯源定位，不能代替未携带的原始文件。旧 v1 无来源行时不补造。

| kind | 内容 |
|---|---|
| user_message | text, attachments[] |
| assistant_message | text, phase |
| tool_call | call_id, name, raw_name, args, input_text, description |
| tool_result | call_id, output, is_error, status, exit_code, completion_time_known |
| reasoning | visibility=plain/summary/encrypted/omitted；本适配器仅导出 omitted/encrypted 标记，不恢复隐藏思考 |
| compaction | origin=native/rehome, summary_visible, covers_until；来源压缩标记与目标摘要分开 |
| notice | data；后台通知、桌面回执等来源说明 |
| ext | agent, type, data；历史扩展，不激活权限或设置、不送入目标模型上下文 |

未知退出码为 null，未知状态为 unknown，未知完成时间不虚构；转接旧写入器时仍遵守其已验证的目标格式。工具结果必须关联同分支先前调用，缺结果需要明确损失记录。非主线、reasoning、compaction、notice、ext 和未知 kind 需要对应的损失记录，不能因认识字段名而静默跳过。

## 损失清单

每项必须含 kind、reason、action，以及 event 或 raw_ref；来源适配器同时给出两者。可选 stage、count、resolved_by。

- reason：unsupported_by_target / encrypted / harness_injected / sensitive / missing_file。
- action：dropped / textified / summarized / kept_raw_only。
- action 表示目标投影的处理，不等于从包中物理删除。ext 中可以留只读信息；`kept_raw_only` 不代表一定携带完整 raw，需核对 native 引用；来源文件没有带上时只有定位和白名单说明。
- 恢复的附件可将对应损失标为 resolved_by；仍保留审计条目，但不计入未解决汇总。仅当具体附件确已关联时才能标记。
- `count` 是该条目覆盖的源轮数等辅助事实；汇总统计损失条目数，不把轮数与事件数混加。

合成示例（hash 和 ID 由读取器计算）：

```json
{"kind":"thinking","reason":"unsupported_by_target","action":"dropped","event":"event-reference","raw_ref":{"file":"fixture.jsonl","line":2,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","block":0}}
```

Claude thinking、sidechain/meta/压缩摘要、file-history、非图片附件及桌面 turn 工具，Codex Reasoning、ContextCompaction、加密 compacted 等均有来源审计。桌面 wrap_up 和通知可文字化；不把它们当作新用户消息。跨 Agent 的分支只保留来源扩展，目标只投影主线。

目标派生摘要单独登记 stage=derived-context/action=summarized，不冒充源压缩。结果 JSON、`.rehome/losses/<target>/<id>.json`、项目 `.rehome/restore.json` 提供汇总；`.rehome/exchange/<target>/<id>.json` 保留导入时完整规范对象。摘要和预算只影响目标恢复上下文，不能作为包的唯一历史。

## v1 升级与兼容

继续读取 `agent-transcript/v1` 和 `agent-project/v1`。turn 转为 user_message，message 转 assistant_message，tool 拆成 call/result，ID 由协议 namespace、来源 ID 和位置确定性生成，原有时间保持不变。v1 缺失的推理、侧支和原始字节无法补回；不宣称升级后变成无损。未来未知 item 必须有对应损失条目，才可进入扩展记录。

项目默认输出 v2；v1 读取不依赖重新打包。同类 v1 转换恢复仍需 `--convert`，避免误把有损旧包当原样平移。Claude 原样整项目恢复需显式 pack --native，缺 raw 立即拒绝。

## 原生平移的边界

只对 JSONL 每行顶层 cwd 字符串做词法重定位，BOM、CRLF、空白、消息、工具和 thinking 保持原字节；不猜测其他路径字段。来源 version 原样保留，空白目标不强制提供版本。源原生 compact_boundary/摘要原样保留；不增加任何新摘要。

**来源根与子目录：** 单会话快照把第一条带非空 cwd 的记录作为启动目录写入 manifest 的 source.cwd；整项目 pack 用已解析的 --project 路径覆盖各原生快照的 source.cwd，不能把首条记录所在子目录当成项目根。同时保留用户给出的项目路径的绝对原写法（不解析符号链接）；若与resolve后的写法不同，写入 source.cwd_aliases 字符串列表，包含这两种项目根，并按两种编码路径盘点原生Claude会话。恢复时依次尝试声明的别名，更具体的匹配根优先，因此 /var 与 /private/var 两种cwd都能保留相同相对子目录。load/plan/restore只读取这些显式字段，不解析会话里旧路径的符号链接、不依赖来源文件系统；缺少source.cwd或根/别名类型错误直接拒绝。旧包没有cwd_aliases时仍只使用source.cwd，Windows普通路径语义不变。来源项目根允许经过符号链接，并不放宽会话旁车、检查点或包内文件的符号链接拒绝规则。旧整项目包若 source.cwd 记录的是子目录而不是项目根，应重新打包，恢复端不会推断修正。

顶层 cwd 等于来源根或位于其目录边界内时，映射为目标根加原相对子目录，而非压平成根。Windows 来源比较不区分大小写并兼容 / 与 \；保留子目录原大小写，目标为 POSIX 时使用 /，目标为 Windows 时使用 \。POSIX 来源比较区分大小写；纯路径归一化处理 . 和 ..，不查询来源文件系统，不把前缀相同的其他目录误当子目录。

项目外或其他盘符的 cwd 保留原字面值（含原有 JSON 转义），空 cwd 保持不变。每条原生恢复结果提供 outside_cwd_rows、outside_cwd_values，并在 warnings 里只报告项目外非空 cwd 的行数和不同原始字符串数量；统计含主会话及子 Agent JSONL，不列出这些路径。memory、file-history 和非会话旁车不参与 cwd 重定位。底层 rewrite_cwd(data, old_root, new_root, stats=None, aliases=()) 要求显式传两个根；不再提供把所有 cwd 压平的旧双参数行为。

同 sessionId、同名 memory 文件、重复目的路径或任何包校验失败均在写前拒绝。dry-run 无写入。整项目先检查本批所有会话；实际写入前保存 backup.json，所有新文件使用独占创建。不承诺整批原子回滚；中途失败保留目标、清单和备份以便诊断。

来源登记仅取 title/model/effort 和来源 permissionMode 说明；目标 permissionMode=default，不继承绕过确认、信任、凭据、白名单。会话 JSONL 必须是合法 UTF-8。会话自有的 `<sid>/` 同名目录（包括 tool-results、subagents 及 custom-title.json 等）和可选 file-history 检查点允许非 UTF-8 旁车文件按原字节携带并校验 SHA-256；不将这个许可扩大到项目 memory 等其他范围。

原生文件清单逐项记录 `binary` 布尔值：严格 UTF-8 解码失败才是 true，能解码的内容仍执行凭据正则检查，不根据文件扩展名跳过。binary=true 的内容不做凭据正则扫描，不宣称其中没有秘密；恢复结果的 `binary_files` / `binary_bytes` 和 warnings 报告所选二进制文件数量、总字节数及未扫描事实。load 和 plan 根据实际字节重新确认 binary 标记，不能用伪造标记绕过文本检查；旧版没有该字段的全文本原生包按 false 兼容。非 UTF-8 的会话 JSONL 仍拒绝。

FORBIDDEN_FILES 中的文件名、源目录/包内符号链接、命中文本凭据规则的内容依旧拒绝；哈希、防覆盖和写前检查规则不变。秘密检测非穷尽，原生包属于私人数据，不得作为发布物上传。

**旁车路径限制：** 文件被带到目标目录，不代表历史中的引用自动可用。JSONL 正文中指向来源位置的绝对路径（例如 Image: source: <old-session>/tool-results/x.jpg）按原样平移规则不改写；跨机后旧位置可能不存在。restore 的 warnings 明确提示这些绝对路径保持不变。需要查看旁车时按目标目录定位，不以本轮字节恢复宣称原生图片展示/附件读取已通过。

这些协议检查通过只证明隔离文件处理，不能代替 Claude 桌面加载、续聊、侧边栏与实际附件验收。

## Codex 来源兼容边界

新版界面 item_completed 保持原映射；旧 event_msg/user_message、agent_message 映射可见消息，response_item/function_call、custom_tool_call 与输出按 call_id 配对，web_search_call 用 call_id 或 id 对应 web_search_end。混合来源以匹配的新版项为准，重复文本按次数匹配，保留重复用户轮次。缺少工具输出时保留空输出、未知状态及 missing_tool_result 损失，不编造成功或退出码。provider reasoning 标记 encrypted／omitted；未知来源记录保留来源引用和损失项。developer/system/provider user 注入不变成可见轮次。旧图片只记录附件损失，不承诺自动恢复旧图片控件。

压缩 .jsonl.zst 的 raw_ref.file 仍是压缩来源文件名，line 与 sha256 指向解压后的原始 JSONL 行；行校验再次只读解压并检查来源一致。交换 schema 不变。项目盘点含已归档记录，通过数据库 cwd 归属，不把所有归档都归入当前项目。选定数据根内支持数据库精确路径及 sessions／archived_sessions 相对重定位；不会按任意旧绝对路径跨越数据根。
