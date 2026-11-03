# Agent Rehome

Claude Code ↔ Codex 原生聊天与项目迁移 Skill。保留可见历史，让目标端能加载并接着聊；支持多个会话、项目文件、历史附件和换电脑后的项目路径重绑定。

版本 **0.4.0-preview.1** · [English](README.en.md) · [MIT](LICENSE)

第三方工具，非 Anthropic 或 OpenAI 官方。它会直接写入应用数据目录，应用升级可能改变格式。先备份，在副本中预览；不要把包含私人历史的迁移包上传到公开仓库。

预览版：Windows 与 macOS 已有原样平移和双向跨 Agent 整项目的有限验收样本；这不是所有版本或项目的兼容保证。Mac 端 Agent 请按 [MAC_TEST.md](MAC_TEST.md) 执行，先运行 `python3 -B scripts/doctor.py` 只读检查。

## 路线与验收状态

平台矩阵和有限样本统一见 [docs/VALIDATION.md](docs/VALIDATION.md)；Codex 项目归属与 cwd 漂移流程见 [docs/CODEX_PROJECT_BINDING.md](docs/CODEX_PROJECT_BINDING.md)。不要将某次样本通过扩大为全部平台通过。

同类默认走原样平移，跨 Agent 走 [agent-exchange/v2](SPEC.md)，包含可追溯损失清单。新项目包按引用保存事件、附件、分支，仍可读取旧 v1 包。跨 Agent 转换仍可能生成预算摘要；Claude 原样平移不生成新摘要、不压缩历史。

### Claude 原样迁移用法

```text
python scripts/agent_rehome.py transfer --from "claude:<source-jsonl>" --source-home "<source-claude-home>" --to claude --target-home "<target-claude-home>" --cwd "<existing-target-project>" --dry-run
python scripts/agent_rehome.py export --from "claude:<source-jsonl>" --source-home "<source-claude-home>" --native --include-memory --include-checkpoints --out "<new-native-package>"
python scripts/agent_rehome.py import "<native-package>" --to claude --target-home "<target-claude-home>" --cwd "<existing-target-project>" --dry-run
python scripts/project_rehome.py pack --from claude --project "<source-project>" --source-home "<source-claude-home>" --native --include-memory --include-checkpoints --out "<new-project-package>"
python scripts/project_rehome.py restore "<project-package>" --to claude --target-home "<target-claude-home>" --cwd "<new-target-project>" --dry-run
```

预览确认后移除 `--dry-run` 执行。默认不带 memory/检查点；同名 memory 或同会话 ID 拒绝覆盖，同机应使用隔离目标根。保留原生 JSONL、同 ID 子目录、thinking 和工具字节，只改顶层 cwd。源已有压缩保留，源 version 不改，因此空白目标无须另填版本。

可用 `--source-desktop-registry` 指定来源登记，`--desktop-registry` 指定已核实的目标登记目录。默认来源目录仅在使用本机默认 Claude 根时尝试 Windows / macOS 自动发现（Mac 范围限 MAC-C1 已核实布局）；复制来的数据根需显式提供。登记只继承 title/model/effort，源 permissionMode 留作来源说明，目标为 default；不复制登录、信任和白名单。会话同名目录的二进制旁车与可选二进制检查点可按原字节携带，manifest 标记 binary=true；非 UTF-8 二进制不扫描内容凭据，结果 warnings 报告数量和字节数。能解码的文本仍做凭据检查，凭据文件名和符号链接仍拒绝；会话 JSONL 必须是合法 UTF-8。历史正文里指向旧位置的绝对旁车路径不改，warnings 会提示，文件已携带不等于图片引用在新电脑可用。脚本不自动重启应用。

跨 Agent 返回 `losses_summary`，详细清单在 `.rehome/losses/`，完整标准事件对象在 `.rehome/exchange/`；项目结果 `.rehome/restore.json` 汇总来源降级和目标摘要。附件字节恢复不保证原生控件完全一致，不自动消除同一来源行的所有附件降级记录。未知事件没有对应损失条目时拒绝。

## 要求和支持范围

- Python 3.10+；未压缩会话只需标准库，压缩 Codex rollout 的可选依赖见下。
- 目标 Agent 已初始化，Codex 目标应已有兼容的 `state_5.sqlite`。
- Windows 原有验收：Claude Code 2.1.309、Codex CLI 0.166.0-alpha.5.1；桌面项目分组在 Windows Codex 26.1027.3384.0 实测。Mac 有限验收样本见 docs/VALIDATION.md，不代表全平台通过；Mac Claude 桌面登记/加载仅有已记录的有限样本，Linux 仍未验收。
- 模型和 Claude Code 版本从目标配置/历史读取。跨 Agent 转换首次目标没有可读设置时，显式传 `--model "<target-model>"`，或 `--claude-model "<target-model>" --claude-version "<target-version>"`。这些值应取自你安装的目标环境，不要照抄其他机器。


### Codex 旧格式与压缩来源

可读取新版 item_completed 和旧版 user_message／agent_message；工具按 call_id 配对。混合格式优先保留新版对应项，按出现次数去重；不把 developer、AGENTS 等 provider 注入当用户消息。reasoning、未知事件及缺失工具结果进入损失清单，不恢复隐藏推理。

支持 `.jsonl` 和 `.jsonl.zst`；单会话 ID 优先查 threads.rollout_path，兼容无 rollout- 前缀的恢复文件，并查找 sessions／archived_sessions。项目 pack 纳入该项目已归档会话，仍按数据库 cwd 精确选项目。数据库路径只在选定数据根内解析；根外文件可显式提供单会话路径。

zstd 只在压缩来源出现时需要：依次使用 Python 3.14+ 的 compression.zstd、已安装的 zstandard（`python -m pip install zstandard`）、系统 zstd（仅 `-d -c`）。缺少三者明确报错，不静默漏掉压缩会话。来源不改，解压在内存中完成；失败不自动安装依赖。真实历史可能很大，应预留解压内存。此可选依赖不影响未压缩来源与目标写入。

### macOS 的 Python 准备

需要可实际运行的 Python 3.10 或以上。macOS 默认可能没有可用 Python；出现 python3 命令也不代表环境已准备好，某些机器的系统命令只会提示安装开发者工具。先运行 `python3 --version`，确认版本至少 3.10。

没有合适版本时，可从 [Python 官方 macOS 下载页](https://www.python.org/downloads/macos/) 获取与本机系统兼容的 Python 3.10+ 安装包，按[官方安装说明](https://docs.python.org/3/using/mac.html)安装；已有独立 Python 环境也可直接使用其完整解释器路径。安装后重新核对版本，再运行本 Skill。不修改或删除系统自带 Python；未压缩会话无需第三方包；压缩会话的解压方式见下。MAC-C1 使用的是临时 Python 3.12.16，该结果不代表 macOS 自带此环境。

## 安装

下载或克隆本仓库后，将整个目录复制为下列目录之一，保持其中 `SKILL.md` 和 `scripts/` 同级。目标目录已存在时，先备份旧 Skill，不要混合两版文件。

- Claude Code：`~/.claude/skills/agent-rehome/`
- Codex：`~/.agents/skills/agent-rehome/`

Windows 的 `~` 是当前用户主目录。也可以直接在下载的目录运行脚本，无需安装 Skill。向 Agent 提出“使用 agent-rehome，将指定 Claude/Codex 会话迁移到另一端”，并给出来源 ID/文件与目标项目路径。

测试源码仓库（暂无正式 Release）：

```text
git clone https://github.com/CalebYcj/agent-rehome.git
cd agent-rehome
```

当前为 macOS 测试预览版，请按 MAC_TEST.md 验收后使用，不代表 macOS 已适配通过。

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

## 迁移后怎么打开

**Claude 桌面版：** Windows 和 macOS 默认尝试登记 Code 会话；Mac 布局为 `~/Library/Application Support/Claude/claude-code-sessions/<org>/<account>/local_*.json`，已核实的环境及样本边界见 [验收记录](docs/VALIDATION.md)；应用按正常流程重启后才会加载新登记，工具不会自行重启。首次使用新目录需由用户确认信任。独立 CLI 的登录状态可能与桌面不同，本工具不复制认证信息。`--no-desktop` 只写历史。自定义目标数据根不自动登记，需要 `--desktop-registry "<verified-registry-directory>"`；未找到目录时 JSON 结果包含 warnings，侧边栏仍待验证。

**Codex：** 文件写入与原生项目分组分别验收。涉及目标 Codex 的项目归属、工作目录及续聊前后检查，按 [CODEX_PROJECT_BINDING.md](docs/CODEX_PROJECT_BINDING.md) 操作；登记不代表应用已加载。

在终端或其他没有这些原生工具的 Agent 中，可使用：

```text
python scripts/project_rehome.py restore "<package-directory>" --to codex --cwd "<new-project>" --no-desktop
```

这会独立恢复文件和会话；之后在 Codex APP 中添加恢复文件夹并关联聊天，或交给具备原生工具的 Agent。未完成分组时应报告“文件与历史已写入，侧边栏待验收”，不能报告完整恢复成功。

## 保留与已知限制

- 验收只限 [已记录的平台、版本和样本](docs/VALIDATION.md)，不保证所有历史、扩展、分支或逐像素一致。第三方工具直接写应用数据，应用更新后格式可能失效。
- `.jsonl.zst` 需要可选解压器：Python 3.14+ 的 compression.zstd、zstandard 或系统 zstd；缺少时明确报错，不静默跳过压缩会话。解压在内存中完成。
- 数据库盘点只读取所选 Codex 数据根内的会话，不跟随根外路径读取手动移走的冷存档；整项目不会把这类根外记录算作成功。显式提供根外单会话文件路径属于另一个明确来源选择。
- 无可识别可见消息的来源：单会话导出拒绝，跨 Agent 项目 pack 写入 skipped；检查每项原因，不能将其视为空聊天或整批成功。
- 跨 Agent 不恢复不可见推理、加密压缩记录、系统注入或账号/工具权限；降级见 losses_summary 和详细损失清单。历史授权、待办不会变成恢复后的执行指令。Claude 同类原样历史字节保留规则另见 SPEC。
- Claude 原样平移不改正文中的旧绝对路径，例如旧截图路径；旁车字节已复制不保证这些引用在新电脑可用。
- Claude 目标的文件附件显示为文字路径链接，保留来源“提到文件”的语义，不生成原生附件卡片或伪造 Read 缓存。文件内容需目标模型按路径读取，可能只保留来源文本快照片段。
- Codex 目标文件显示为原生文件芯片；本机点击曾打开终端，与原生文件点击的一致性未验证，不能保证打开编辑器或预览。图片有缩略图/预览的 Windows 样本通过，Mac 模型附件访问仍未实测。
- 长会话跨 Agent 可能依靠预算摘要；早期主题和细节的把握可能偏弱。完整归档在 `.rehome/history/`，不等于模型加载了全部历史，额度估算不是官方分词。
- 重启 Claude 桌面版和确认目录信任由用户完成，工具不代点或自动重启；上层目录信任能否覆盖子目录、多账号登记目录仍待验收。
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
