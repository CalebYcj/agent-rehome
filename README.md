# Agent Rehome

Claude Code ↔ Codex 原生聊天与项目迁移 Skill。保留可见历史，让目标端能加载并接着聊；支持多个会话、项目文件、历史附件和换电脑后的项目路径重绑定。

版本 **0.2.0-mac-preview.1** · [English](README.en.md) · [MIT](LICENSE)

第三方工具，非 Anthropic 或 OpenAI 官方。它会直接写入应用数据目录，应用升级可能改变格式。先备份，在副本中预览；不要把包含私人历史的迁移包上传到公开仓库。

macOS 适配测试候选版：路径、SQLite URI、附件名称和 POSIX 权限处理已更新；Mac 原生加载与续聊尚未验收。Mac 端 Agent 请按 [MAC_TEST.md](MAC_TEST.md) 执行，先运行 `python3 -B scripts/doctor.py` 只读检查。

## 要求和支持范围

- Python 3.10+，无需第三方 Python 包。
- 目标 Agent 已初始化，Codex 目标应已有兼容的 `state_5.sqlite`。
- 仅 Windows 实测：Claude Code 2.1.309、Codex CLI 0.166.0-alpha.5.1；桌面项目分组在 Windows Codex 26.1027.3384.0 实测。macOS/Linux 的桌面会话登记未核实，不宣称跨平台验收通过。
- 模型和 Claude Code 版本从目标配置/历史读取。首次目标没有可读设置时，显式传 `--model "<target-model>"`，或 `--claude-model "<target-model>" --claude-version "<target-version>"`。这些值应取自你安装的目标环境，不要照抄其他机器。

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

**Claude 桌面版：** Windows 下默认尝试登记 Code 会话；应用按正常流程重启后才会加载新登记，工具不会自行重启。首次使用新目录需由用户确认信任。独立 CLI 的登录状态可能与桌面不同，本工具不复制认证信息。`--no-desktop` 只写历史。自定义目标数据根不自动登记，需要 `--desktop-registry "<verified-registry-directory>"`；未找到目录时 JSON 结果包含 warnings，侧边栏仍待验证。

**Codex：** 脚本独立写入 rollout、数据库、索引和归档。项目恢复在 Windows 可尝试运行中桌面程序的文件夹入口；完整侧边栏归组需要 Codex APP 的原生 `list_projects`、`move_thread_to_project`、`list_threads` 工具。Agent 按精确恢复路径找到项目、绑定全部导入会话，再核对结果。

在终端或其他没有这些原生工具的 Agent 中，可使用：

```text
python scripts/project_rehome.py restore "<package-directory>" --to codex --cwd "<new-project>" --no-desktop
```

这会独立恢复文件和会话；之后在 Codex APP 中添加恢复文件夹并关联聊天，或交给具备原生工具的 Agent。未完成分组时应报告“文件与历史已写入，侧边栏待验收”，不能报告完整恢复成功。

## 保留与限制

- 可见用户/助手文字、工具调用及结果；显示样式以目标端当前原生界面为准，不保证两个产品逐像素一致。
- 长会话默认预算为64000保守估算额度，通过摘要及完整尾轮续聊；完整历史在会话及 `.rehome/history/` 中。摘要不是全部细节，估算不是官方分词。
- 项目中的可恢复图片及文件附件重映射到 `.rehome/attachments/`。历史文本快照可能仅为片段；缺失且历史未内嵌的附件无法补回。
- 不迁移账号、凭据、工具权限、不可见推理、加密模型状态或 Git 历史。历史授权与待办不会成为恢复后自动执行的指令。
- 不保证所有扩展事件、分支或未来版本的格式兼容。子目录是否继承信任尚未验证。

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
