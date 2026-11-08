# Agent Rehome

版本 **0.5.0** · [English](README.en.md) · [MIT](LICENSE)

把 Codex、Claude Code 的对话和项目，搬到另一个 Agent 接着做。

在 Codex 里做了几个月的项目，想换 Claude 接着做？不用从头再讲一遍。两边装上这个 Skill，在原来的 Agent 里说一句“打包”，在新的 Agent 里说一句“接收”，聊天记录、图片和项目文件就一起搬过去，新的 Agent 直接接着聊。

- Codex → Claude、Claude → Codex 都能搬，同类之间也能搬
- Windows、macOS 都能用，换电脑也能搬
- 单条对话、整个项目都可以
- 原来的对话不动，随时能回去
- 免费开源（MIT）

## 快速上手

1. **装 Skill**：下载最新 [Release](https://github.com/CalebYcj/agent-rehome/releases/latest) 并解压，把里面的 `agent-rehome` 文件夹放到：
   - Claude Code：`~/.claude/skills/agent-rehome/`
   - Codex：`~/.agents/skills/agent-rehome/`

   搬出和搬入的两边都要装。也可以把本仓库链接发给你的 Agent，请它按这里的说明安装。
2. **准备 Python 3.10+**：没有的话，Agent 会告诉你去哪下载。
3. **打包**：在原来的 Agent 里说：`用 Agent Rehome 打包这个项目`。
4. **接收**：同一台电脑直接进行；换电脑时先把整个包复制过去。然后在新的 Agent 里说：`用 Agent Rehome 接收这个搬家包：<包的位置>`。
5. **接着聊**：按 Agent 的提示完成剩下的一两步，打开迁移过来的对话就能继续。

> 搬家包里有你的私人对话和项目文件，不要上传到公开的地方。迁移会写入应用数据，建议先备份。

下面是命令行用法和技术细节。

---

Claude Code ↔ Codex 原生聊天与项目迁移 Skill。保留可见历史，让目标端能加载并接着聊；支持多个会话、项目文件、历史附件和换电脑后的项目路径重绑定。

它会直接写入应用数据目录，应用升级可能改变格式。先备份，在副本中预览；不要把包含私人历史的迁移包上传到公开仓库。

Windows 与 macOS 上，同类搬运和双向跨 Agent 整项目都有实测，已测范围见[验收记录](docs/VALIDATION.md)。环境有疑问时，先运行 `python3 -B scripts/doctor.py` 只读检查。

## 路线与验收状态

平台矩阵和有限样本统一见 [docs/VALIDATION.md](docs/VALIDATION.md)；Codex 项目归属与 cwd 漂移流程见 [docs/CODEX_PROJECT_BINDING.md](docs/CODEX_PROJECT_BINDING.md)。不要将某次样本通过扩大为全部平台通过。

同类默认走原样平移，跨 Agent 走 [agent-exchange/v2](SPEC.md)，包含可追溯损失清单。新项目包按引用保存事件、附件、分支，仍可读取旧 v1 包。跨 Agent 转换仍可能生成预算摘要；Claude 原样平移不生成新摘要、不压缩历史。

### Codex 原样迁移用法（Windows 和 macOS 有限样本通过）

本 Skill 按 ReHome 原则实现同类平移。来源端只打包或列出需要迁移的项目、会话、文件；接收端 Agent 自己恢复、写入、登记、归组并验收。先初始化目标 Codex 数据库；Codex 可以在 App 运行时自己恢复，也支持同一条路径离线写入，不要求另一 Agent 代写。Windows/macOS 原生加载分别验收，不能沿用 ReHome App 的旧结论。

```text
python scripts/agent_rehome.py transfer --from "codex:<id-or-rollout>" --source-home "<source-codex-home>" --to codex --target-home "<target-codex-home>" --cwd "<existing-target-project>" --dry-run
python scripts/agent_rehome.py export --from "codex:<id-or-rollout>" --source-home "<source-codex-home>" --native --out "<new-native-package>"
python scripts/agent_rehome.py import "<native-package>" --to codex --target-home "<target-codex-home>" --cwd "<existing-target-project>" --dry-run
python scripts/project_rehome.py pack --from codex --project "<source-project>" --source-home "<source-codex-home>" --native --out "<new-project-package>"
python scripts/project_rehome.py restore "<new-project-package>" --to codex --target-home "<target-codex-home>" --cwd "<new-target-project>" --dry-run
```

核对预览后去掉 --dry-run。同 ID 默认拒绝；同机另存必须显式加 --new-copy，仅重映射归属 ID。reasoning、压缩及加密状态保留原字节；分页依赖明确拒绝；外部生成图片/本地引用未自动收集。包内 limitations、备份和失败阶段见 [SPEC](SPEC.md)。异常回滚会话事务；项目文件保留并记失败，不承诺中断后自动整批回退。项目登记与续聊按绑定文档另验收。

原生写入在线备份后，SQLite写锁等待预算2秒；索引只追加，追加前核对原内容，追加后核对原前缀和完整新增行，rollout独占新建。并发冲突会回滚SQL及本次文件；索引仅在本次完整追加块仍位于末尾时自动撤销，有其他尾部数据或部分写入就保留现场并在备份manifest标记人工核查，不覆盖共享索引/数据库。App运行时通过原生folder-open登记，结果的thread_binding_required列出待原生绑定的线程；--no-desktop只写会话。目录信任仍由用户完成，Agent不操作安全弹窗或重启App。

项目预览列出文件数、逻辑字节数、最大的10个文件、按顶层目录及扩展名分布、排除目录体积。预览阶段不读取会话正文。原生 Codex rollout 按来源时间写入 sessions/YYYY/MM/DD/rollout-时间-ID.jsonl；来源元数据及首记录均无时间时拒绝，不用当前时间补造。

Codex 原生标题优先取 session_index 最后一条 thread_name，再取数据库 title、首条可见用户消息前60字符、ID；数据库旧 title 可能不是侧边栏显示值。--new-copy 同时更新当前 session_meta 中匹配来源 ID 的 id/session_id，正文、工具输出和祖先引用仍保持原字节。旧导入副本不原地修补，修复后需新包、新目标重新验收。

### Claude 原样迁移用法

```text
python scripts/agent_rehome.py transfer --from "claude:<source-jsonl>" --source-home "<source-claude-home>" --to claude --target-home "<target-claude-home>" --cwd "<existing-target-project>" --dry-run
python scripts/agent_rehome.py export --from "claude:<source-jsonl>" --source-home "<source-claude-home>" --native --include-memory --include-checkpoints --out "<new-native-package>"
python scripts/agent_rehome.py import "<native-package>" --to claude --target-home "<target-claude-home>" --cwd "<existing-target-project>" --dry-run
python scripts/project_rehome.py pack --from claude --project "<source-project>" --source-home "<source-claude-home>" --native --include-memory --include-checkpoints --out "<new-project-package>"
python scripts/project_rehome.py restore "<project-package>" --to claude --target-home "<target-claude-home>" --cwd "<new-target-project>" --dry-run
```

预览确认后移除 `--dry-run` 执行。默认不带 memory/检查点；同名 memory 或同会话 ID 拒绝覆盖，同机应使用隔离目标根。保留原生 JSONL、同 ID 子目录、thinking 和工具字节，只改顶层 cwd。源已有压缩保留，源 version 不改，因此空白目标无须另填版本。

Claude原生往返遇到同ID时可二选一：`--new-copy`按来源ID、主历史哈希和目标cwd确定新ID，改写结构化sessionId值（仅匹配来源ID），同步命名会话/旁车/检查点目录和桌面登记；正文里旧ID/绝对路径及二进制字节保持不变。已有原会话不改。`--fast-forward`只用于现有记录是传入记录的前缀：逐行比较所有非cwd字段及uuid顺序，拒绝分叉和冲突旁车；相同历史返回unchanged，新增行仅追加到原会话所在项目，保持其原cwd，已有旁车只核对，新旁车独占创建。两参数互斥，跨Agent不支持快进。

```text
python scripts/project_rehome.py restore "<native-claude-project-package>" --to claude --new-copy --cwd "<new-project-copy>" --dry-run
python scripts/project_rehome.py restore "<native-claude-return-package>" --to claude --fast-forward --cwd "<new-project-files-copy>" --dry-run
```

快进预览列出每条会话将追加的行数；项目文件仍复制到全新--cwd，历史却回到已存在的原会话，restore.json.sessions[].cwd分别记录实际位置。只需单会话快进可用agent_rehome.py import/transfer的同名参数。写前保留原历史备份及journal，写前后检查并发变化；不重写旧行、不整份恢复旧历史。部分失败保留新旁车/现场并标partial-write-needs-review，不保证跨进程全局事务或自动回滚；检查证据后再决定下一步，禁止盲目重试。原桌面登记继续沿用。快进预演与写入都检测目标会话进程。仅 `live_process_check=clear` 可继续。检测不可用时预演警告，正式写入停止。有运行进程时，由用户在应用内停止该会话或退出并重开应用，再重新预演。clear 表示在命令行和会话进程记录中均未发现运行进程，检测范围有限。如果这条会话仍在其他地方打开，例如终端，请先关闭它，再重新预演。快进成功后可打开原会话续聊。续聊后核对第一条新提问的 parentUuid 是否指向追加历史最后一条带 UUID 的记录。

CLI统一使用UTF-8输出，旧控制台无法编码时转义不可编码字符；已完成写入不因私用区/中文字符的输出编码失败而误报失败。若restore.json.filename_warnings提示私用区路径，可能是旧搬运文件名解码损伤，脚本保留原名，不猜测改名。

可用 `--source-desktop-registry` 指定来源登记，`--desktop-registry` 指定已核实的目标登记目录。默认来源目录仅在使用本机默认 Claude 根时尝试 Windows / macOS 自动发现（macOS 范围限已核实的登记布局）；复制来的数据根需显式提供。登记只继承 title/model/effort，源 permissionMode 留作来源说明，目标为 default；不复制登录、信任和白名单。会话同名目录的二进制旁车与可选二进制检查点可按原字节携带，manifest 标记 binary=true；非 UTF-8 二进制不扫描内容凭据，结果 warnings 报告数量和字节数。能解码的文本仍做凭据检查，凭据文件名和符号链接仍拒绝；会话 JSONL 必须是合法 UTF-8。历史正文里指向旧位置的绝对旁车路径不改，warnings 会提示，文件已携带不等于图片引用在新电脑可用。脚本不自动重启应用。

跨 Agent 返回 `losses_summary`，详细清单在 `.rehome/losses/`，完整标准事件对象在 `.rehome/exchange/`；项目结果 `.rehome/restore.json` 汇总来源降级和目标摘要。附件字节恢复不保证原生控件完全一致，不自动消除同一来源行的所有附件降级记录。未知事件没有对应损失条目时拒绝。

## 要求和支持范围

### 大项目、引用清单和 Git

完整复制以可用磁盘容量为限。打包和恢复按卷估算新增文件、附件、历史及备份的写入需求，并额外预留 64 MiB。失败时显示缺少的字节数。容量按逻辑字节估算，稀疏文件在目标上可能占用完整空间，检查结果也会受其他进程随后写入影响。旧命令的 `--allow-large` 仍可传入。

超大项目建议把项目文件自行搬到目标机，再让 Skill 打包会话、可迁移的规则和配置、技能及附件。引用清单保存相对路径、字节数和 SHA-256。接收端指向已经搬好的目录，报告 `missing`、`extra`、`different`。比较范围采用与来源相同的排除规则，已有项目文件保留，缺少的周边可补齐。默认继续，`--strict-files` 在发现差异时阻止写入。引用包两端都应使用 preview.2 或兼容版本。

```text
python scripts/project_rehome.py pack --from codex --project "<source>" --out "<package>" --native --files reference
python scripts/project_rehome.py restore "<package>" --to codex --cwd "<already-copied-project>" --strict-files --dry-run
```

默认排除 `.git`，可通过 `--include-git` 纳入真实 Git 目录。完整复制模式携带 Git 数据，引用模式将其纳入清单。预览单列 Git 字节数。含凭据迹象的远程 URL 或 Git 配置会被拒绝，先清理源配置再打包。工作树的 `.git` 指针文件不携带。

项目和附件文件按块传输。跨 Agent 项目恢复对超过 16 MiB 的图片保留文件链接及原始字节，小图沿用原生内嵌显示。会话本身的 JSON、原生历史和旁车仍遵循对应写入器的格式及内存需求。项目周边的结构化配置使用独立的 8 MiB 解析预算。

发布 ZIP 采用 ZIP64 与 UTF-8 文件名标志，`CHECKSUMS.json` 覆盖除清单自身外的全部发布文件。

- Python 3.10+；未压缩会话只需标准库，压缩 Codex rollout 的可选依赖见下。
- 目标 Agent 已初始化，Codex 目标应已有兼容的 `state_5.sqlite`。
- Windows 原有验收：Claude Code 2.1.309、Codex CLI 0.166.0-alpha.5.1；桌面项目分组在 Windows Codex 26.1027.3384.0 实测。Mac 有限验收样本见 docs/VALIDATION.md，不代表全平台通过；Mac Claude 桌面登记/加载仅有已记录的有限样本，Linux 仍未验收。
- 模型和 Claude Code 版本从目标配置/历史读取。跨 Agent 转换首次目标没有可读设置时，显式传 `--model "<target-model>"`，或 `--claude-model "<target-model>" --claude-version "<target-version>"`。这些值应取自你安装的目标环境，不要照抄其他机器。


### Codex 旧格式与压缩来源

可读取新版 item_completed 和旧版 user_message／agent_message；工具按 call_id 配对。混合格式优先保留新版对应项，按出现次数去重；不把 developer、AGENTS 等 provider 注入当用户消息。reasoning、未知事件及缺失工具结果进入损失清单，不恢复隐藏推理。

支持 `.jsonl` 和 `.jsonl.zst`；单会话 ID 优先查 threads.rollout_path，兼容无 rollout- 前缀的恢复文件，并查找 sessions／archived_sessions。项目 pack 纳入该项目已归档会话，仍按数据库 cwd 精确选项目。数据库路径只在选定数据根内解析；根外文件可显式提供单会话路径。

zstd 只在压缩来源出现时需要：依次使用 Python 3.14+ 的 compression.zstd、已安装的 zstandard（`python -m pip install zstandard`）、系统 zstd（仅 `-d -c`）。缺少三者明确报错，不静默漏掉压缩会话。来源不改，解压在内存中完成；失败不自动安装依赖。真实历史可能很大，应预留解压内存。此可选依赖不影响未压缩来源与目标写入。

### Python 准备

Windows 和 macOS 都需要 Python 3.10+，来源端和接收端都要。Agent 会先检查，缺少时提示你从 [Python 官网](https://www.python.org/downloads/)下载。

#### macOS

需要可实际运行的 Python 3.10 或以上。macOS 默认可能没有可用 Python；出现 python3 命令也不代表环境已准备好，某些机器的系统命令只会提示安装开发者工具。先运行 `python3 --version`，确认版本至少 3.10。

没有合适版本时，可从 [Python 官方 macOS 下载页](https://www.python.org/downloads/macos/) 获取与本机系统兼容的 Python 3.10+ 安装包，按[官方安装说明](https://docs.python.org/3/using/mac.html)安装；已有独立 Python 环境也可直接使用其完整解释器路径。安装后重新核对版本，再运行本 Skill。不修改或删除系统自带 Python；未压缩会话无需第三方包；压缩会话的解压方式见下。早期 macOS 样本使用的是临时 Python 3.12.16，该结果不代表 macOS 自带此环境。

## 安装

下载或克隆本仓库后，将整个目录复制为下列目录之一，保持其中 `SKILL.md` 和 `scripts/` 同级。目标目录已存在时，先备份旧 Skill，不要混合两版文件。

- Claude Code：`~/.claude/skills/agent-rehome/`
- Codex：`~/.agents/skills/agent-rehome/`

Windows 的 `~` 是当前用户主目录。也可以直接在下载的目录运行脚本，无需安装 Skill。向 Agent 提出“使用 agent-rehome，将指定 Claude/Codex 会话迁移到另一端”，并给出来源 ID/文件与目标项目路径。

也可以直接克隆源码：

```text
git clone https://github.com/CalebYcj/agent-rehome.git
cd agent-rehome
```

macOS 与 Windows 用同一份 Skill。已测范围见[验收记录](docs/VALIDATION.md)。

## 单会话

在本目录运行，替换所有 `<...>`。目标项目目录必须事先存在。

```text
python scripts/agent_rehome.py transfer --from "claude:<session-id-or-jsonl>" --to codex --cwd "<target-project>" --dry-run
python scripts/agent_rehome.py transfer --from "claude:<session-id-or-jsonl>" --to codex --cwd "<target-project>"
python scripts/agent_rehome.py transfer --from "codex:<session-id-or-rollout>" --to claude --cwd "<target-project>" --dry-run
python scripts/agent_rehome.py transfer --from "codex:<session-id-or-rollout>" --to claude --cwd "<target-project>"
```

`--source-home` / `--target-home` 分别指定来源/目标 Agent 的数据根目录（`.claude` 或 `.codex`），不是项目目录。默认使用当前主目录下对应数据根。来源历史更新后用 `--new-copy` 另存快照；已有会话不会被覆盖。

## 整项目与换电脑

项目包包含当前文件、匹配该项目的多个聊天和可恢复附件。包目录必须是全新的、位于源项目外；恢复目录也必须全新，不能合并进已有工程。

```text
python scripts/project_rehome.py pack --from codex --project "<source-project>" --out "<new-package-directory>"
python scripts/project_rehome.py restore "<package-directory>" --to claude --cwd "<new-restored-project>"
```

换电脑时，把目录包搬到新电脑并运行 restore，`--cwd` 指定新工程路径。若已复制来源 `.codex`/`.claude` 数据目录，pack 可加 `--source-home "<copied-agent-home>"`。只导出单会话时：

```text
python scripts/agent_rehome.py export --from "claude:<session-id>" --source-home "<copied-claude-home>" --out "<transcript.json>"
python scripts/agent_rehome.py import "<transcript.json>" --to codex --cwd "<target-project>" --target-home "<target-codex-home>" --dry-run
```

检查预览后，去掉 `--dry-run` 执行。同一电脑可直接交付文件路径，不必另外压缩。

pack 默认按来源历史中的项目路径匹配会话。要指定精确来源清单，用 `--sessions-json "<inventory.json>"`，内容为数组：

```json
[{"snapshot":"<native-session-jsonl-path>","title":"<conversation-title>"}]
```

显式清单里的 Codex 历史应为原生来源；脚本拒绝把已迁入的 Codex 副本误当原生来源再次打包。单会话转换可用于其他场景。项目不包含 `.git`、安装依赖和常见凭据文件；打包前仍需审查自定义敏感文件。

## 一次搬全部项目

`batch_rehome.py` 先列出来源 Agent 里所有有对话的项目，再一次全部打包，接收端一次全部恢复。每个项目内部仍走上面的整项目打包和恢复，所以单项目的全部检查都照常生效，包括密钥扫描、空间检查、全新目标目录和备份。某个项目失败只记录原因，其余项目继续。

```text
python scripts/batch_rehome.py list --from all
python scripts/batch_rehome.py pack --from codex --to claude --out "<new-batch-directory>" --dry-run
python scripts/batch_rehome.py pack --from codex --to claude --out "<new-batch-directory>"
python scripts/batch_rehome.py restore "<batch-directory>" --to claude --root "<new-parent-directory>" --dry-run
python scripts/batch_rehome.py restore "<batch-directory>" --to claude --root "<new-parent-directory>"
```

- `list` 只读，按最近使用排序，列出项目路径、对话数，以及项目文件夹还在不在。
- `pack --to` 写接收端 Agent。同类迁移自动走原样平移，跨 Agent 走转换。默认打包全部项目，`--project` 可重复使用，只挑其中几个。
- 包目录里每个项目一个子文件夹，名字取项目文件夹名，重名的依次加 `-2`、`-3`。另有 `batch.json` 记录每个项目的结果。
- `restore` 把每个项目恢复到 `<root>/<名字>`，汇总写在 `<root>/rehome-batch-restore.json`。目标已存在的项目会跳过，不会合并。Claude 端全部恢复完后只需重启一次桌面版。目录信任也只需一次：用根目录新开一个会话并确认信任，下面的项目都沿用（Windows 桌面版已实测）。
- Codex 端不同：Codex 每添加一个项目文件夹都要单独确认一次信任，不沿用上层文件夹。恢复时会一个接一个弹出，共几个项目就几次。预演结果的 `user_notice` 会提前说明次数。用户只需逐个核对路径并确认，添加项目和归组由 Agent 完成。某个项目超过 60 秒还没登记，会标为 `pending`，Agent 稍后复查，不重复发起添加。
- 项目文件夹已经删除的对话这次会跳过，并在结果里标出来。这些对话仍可以用单会话命令单独转。

### 全局规则（主人格）

全局规则文件对所有对话都生效。Codex 的是 `~/.codex/AGENTS.md`，如果有非空的 `AGENTS.override.md`，就以它为准。Claude 的是 `~/.claude/CLAUDE.md`。

批量打包时，这个文件默认一起带上，同样会做密钥扫描；不想带就加 `--no-global-rules`。恢复时只给出预览，不会自动写入。

```text
python scripts/global_rules.py install "<batch-directory>" --to claude          # 预览
python scripts/global_rules.py install "<batch-directory>" --to claude --apply  # 用户看过并同意后再写
```

- **到 Claude：** 原文存成 `~/.claude/rehome/global-rules-from-codex.md`，再在 `~/.claude/CLAUDE.md` 末尾加一行 `@rehome/...` 引用。用户自己的内容不会被改。要撤销，删掉这一行即可。
- **到 Codex：** Codex 不支持引用，所以把原文追加到它实际读取的那个文件末尾，前后加开始、结束标记。要撤销，删掉这一整段即可。合并后如果超过 32 KiB，会提示可能被截断。
- 原文不改写。预览会列出所有提到旧 Agent 名字、路径或工具名的行，比如"你是 Codex"、`apply_patch`，由用户决定要不要改。Claude 原文里的 `@` 引用文件不会跟着搬，只列出来。
- 写入前会先备份。重复安装同一份会自动跳过。目标位置已经有内容不同的同名文件或段落时会停下，不覆盖。
- 单独搬全局规则用 `global_rules.py pack --from codex --out "<new-directory>"`。

## 迁移后怎么打开

**Claude 桌面版：** Windows 和 macOS 默认尝试登记 Code 会话；Mac 布局为 `~/Library/Application Support/Claude/claude-code-sessions/<org>/<account>/local_*.json`，已核实的环境及样本边界见 [验收记录](docs/VALIDATION.md)；应用按正常流程重启后才会加载新登记，工具不会自行重启。首次使用新目录需由用户确认信任。独立 CLI 的登录状态可能与桌面不同，本工具不复制认证信息。`--no-desktop` 只写历史。自定义目标数据根不自动登记，需要 `--desktop-registry "<verified-registry-directory>"`；未找到目录时 JSON 结果包含 warnings，侧边栏仍待验证。

**Codex：** 文件写入与原生项目分组分别验收。涉及目标 Codex 的项目归属、工作目录及续聊前后检查，按 [CODEX_PROJECT_BINDING.md](docs/CODEX_PROJECT_BINDING.md) 操作；登记不代表应用已加载。

在终端或其他没有这些原生工具的 Agent 中，可使用：

```text
python scripts/project_rehome.py restore "<package-directory>" --to codex --cwd "<new-project>" --no-desktop
```

这会独立恢复文件和会话；之后在 Codex APP 中添加恢复文件夹并关联聊天，或交给具备原生工具的 Agent。未完成分组时应报告“文件与历史已写入，侧边栏待验收”，不能报告完整恢复成功。

Codex 项目要跨 Agent 转换，请用不带 `--native` 的 `pack` 生成交换包，再用 `restore --convert`。Codex 原生项目包没有可直接转换的中立事件。

## 保留与已知限制

- Codex 同类恢复的有限样本保留压缩记录且可以续聊。尚未证明模型解开了其中的加密内容。压缩需由用户在应用中手动触发，本工具不触发压缩。
- 跨账号迁移未验证。Codex 的 Skill 目录在已测续聊中未刷新，跨机历史仍记录来源机路径。

- 项目 `.claude/` 只收集 settings.json、skills、commands、agents；项目 `.codex/` 只收集 config.toml/config.json/settings.json。settings.local、凭据、缓存和未知目录跳过并报告；用户级规则、Skills、插件不收集。
- 跨 Agent 在目标缺失时桥接逐目录规则：Codex→Claude 生成 `@AGENTS.md` 引用；Claude→Codex 生成注明来源的 AGENTS.md 副本，`@` 引用只列出、不展开。Skills按目录复制，保留源文件，目标已有同名目录跳过；工具名未转换。所有生成/跳过项见 `.rehome/restore.json` 的 `surroundings`。
- `.mcp.json` 在同Agent及跨Agent恢复时均原样归档到 `.rehome/surroundings/originals/.mcp.json`，项目根不留生效副本，避免目标应用信任目录后自动连接。报告服务器及启动命令，不列环境变量值；如需启用，用户明确审查/批准后手动复制回项目根，恢复不代启用。Claude settings 的 hooks、来源权限和已知自动启动字段从生效副本移除；含可执行或权限字段的 Codex 配置整体隔离。跨Agent commands/子Agent只提示，不转换；hooks脚本不自动启用，应用加载另验收。
- `.mcp.json`、Claude settings 和 Codex 项目配置在打包前用现有密钥特征扫描；命中拒绝且不创建包。明确使用 `--allow-secrets-in-config` 可允许该配置进入私有包，覆盖清单会记录路径；原字节仍可能含密钥，不能公开。这不是完整秘密检测，也不会安装用户级工具或插件。

- 验收只限 [已记录的平台、版本和样本](docs/VALIDATION.md)，不保证所有历史、扩展、分支或逐像素一致。本工具直接写应用数据，应用更新后格式可能失效。
- `.jsonl.zst` 需要可选解压器：Python 3.14+ 的 compression.zstd、zstandard 或系统 zstd；缺少时明确报错，不静默跳过压缩会话。解压在内存中完成。
- 数据库盘点只读取所选 Codex 数据根内的会话，不跟随根外路径读取手动移走的冷存档；整项目不会把这类根外记录算作成功。显式提供根外单会话文件路径属于另一个明确来源选择。
- 无可识别可见消息的来源：单会话导出拒绝，跨 Agent 项目 pack 写入 skipped；检查每项原因，不能将其视为空聊天或整批成功。
- 跨 Agent 保留可见历史，跳过来源压缩摘要并丢弃加密压缩项；不可见推理、系统注入和账号或工具权限也不恢复。详见损失清单。历史授权、待办不会变成恢复后的执行指令。Claude 同类原样历史字节保留规则另见 SPEC。
- Claude 原样平移不改正文中的旧绝对路径，例如旧截图路径；旁车字节已复制不保证这些引用在新电脑可用。
- Claude 目标的文件附件显示为文字路径链接，保留来源“提到文件”的语义，不生成原生附件卡片或伪造 Read 缓存。文件内容需目标模型按路径读取，可能只保留来源文本快照片段。
- Codex 目标文件显示为原生文件芯片；本机点击曾打开终端，与原生文件点击的一致性未验证，不能保证打开编辑器或预览。图片缩略图、附件点击和项目归组显示的界面证据有限。macOS 已有同类恢复后模型看内嵌图的样本。
- 长会话跨 Agent 可能依靠预算摘要；早期主题和细节的把握可能偏弱。完整归档在 `.rehome/history/`，不等于模型加载了全部历史，额度估算不是官方分词。
- 重启 Claude 桌面版和确认目录信任由用户完成，工具不代点或自动重启；Windows 桌面版已实测上层目录信任能覆盖子目录，macOS 和多账号登记目录仍待验收。
- 不迁移凭据或 Git 历史。源文件不移动/删除，未知冲突拒绝覆盖；本工具不会自动回滚失败批次。

## 备份与回退

导入器对涉及的已有文件逐个备份，SQLite 使用在线备份；结果包含 backup 路径。目标数据根下 `rehome-backups/` 保存备份清单，`rehome-imports/` 保存受管理文件和指纹。项目恢复报告为 `<restored-project>/.rehome/restore.json`。保留来源、报告和备份直到验收完成。

回退没有“一键还原”命令。先让目标会话停止写入，保留导入后新增的内容，再按备份清单恢复相关文件、处理本次新增文件。共享数据库和索引可能包含别的新聊天，不应盲目用整库备份覆盖。桌面登记和项目归属需要单独核对；失败批次不会自动全盘回滚。

## 自检与隐私扫描

```text
python -B scripts/run_tests.py
python -B scripts/privacy_scan.py .
```

每个测试使用新的临时 HOME，测试写入只能在临时目录，禁止访问真实 Agent 数据、网络或外部进程。全部数据为合成夹具，无需安装/登录 Agent。隐私扫描检查用户主目录绝对路径、邮箱、非夹具会话 ID 和常见凭据模式；它不是通用秘密检测器，发布前仍应人工检查额外文件。

本目录是可独立上传的内容，不包含开发者交接记录、历史迁移包或真实测试会话。
