---
name: agent-rehome
description: 将 Claude Code 与 Codex 的会话和项目双向迁移为目标端原生历史，支持换机和项目路径重绑定。Migrate native Claude Code and Codex conversations and projects, including cross-computer path rebinding.
---

# Agent Rehome

在 Claude Code 与 Codex 之间恢复可见聊天历史，单会话可双向转换，整项目可携带文件、多个聊天及可恢复的附件。它不是桌面应用，也不是仅生成交接摘要。安装、用法和回退见 [README.md](README.md)；English: [README.en.md](README.en.md)。

macOS 测试候选版的诊断和验收流程见 [MAC_TEST.md](MAC_TEST.md)。跨系统路径适配已准备；本机模拟测试不能代替 Mac 原生验收。

## 前置条件与范围

- Python 3.10+，只用标准库。目标 Agent 的数据目录应已初始化。
- 仅在 Windows 实测：Claude Code 2.1.309、Codex CLI 0.166.0-alpha.5.1，以及对应桌面环境。其他系统/版本不保证格式兼容；先用副本和隔离目录验证。
- 这是第三方工具，非 Anthropic 或 OpenAI 官方。导入会直接改写目标应用的数据目录；应用更新后格式可能失效。
- 迁移范围是可见消息、历史工具调用和项目快照；不迁移账号、登录凭据、权限、加密的模型状态或不可见推理。不执行历史任务。

## 执行流程

1. 明确来源 Agent、指定会话/项目、目标 Agent、目标项目目录；不能用最近会话代替用户指定来源。跨机时明确复制来的数据目录。
2. 先盘点和预览。单会话命令加 `--dry-run`，项目先 pack，检查 manifest 的文件、会话、附件及 skipped。数据包可能含完整私人对话和项目源码，不应公开上传。
3. 在用户授权的迁移范围内导入。现有目标数据写前备份；不覆盖未知同 ID 会话、已变化历史或已存在恢复目录。新快照用 `--new-copy`。
4. 模型/版本优先使用显式参数，否则读取目标配置或已有历史。识别不到时按错误提示给 `--model`，或 `--claude-model` 和 `--claude-version`；不要猜值。`--target-home` 选择目标数据根，不是项目目录。
5. 分别验收文件校验、会话登记、原生加载/续聊、侧边栏归属和附件读取。写入成功不等于桌面已加载；未经授权不发送续聊验证消息。

## 单会话

以下均以本 Skill 目录为工作目录；替换尖括号内容。

```text
python scripts/agent_rehome.py transfer --from "claude:<session-id-or-jsonl>" --to codex --cwd "<target-project>" --dry-run
python scripts/agent_rehome.py transfer --from "claude:<session-id-or-jsonl>" --to codex --cwd "<target-project>"
python scripts/agent_rehome.py transfer --from "codex:<session-id-or-rollout>" --to claude --cwd "<target-project>"
```

CLI export/transfer 保留完整工具数据。长会话默认使用 64000 的保守上下文预算，可用 `--claude-context-budget` / `--codex-context-budget` 调整。完整历史仍保留，续聊只加载陈述式摘要和预算内完整尾轮；细节需回看历史或读取 `.rehome/history/`。估算非官方分词，不含目标运行时新注入的系统/工具说明。

## 整项目与换机

```text
python scripts/project_rehome.py pack --from codex --project "<source-project>" --out "<new-package-directory>"
python scripts/project_rehome.py restore "<package-directory>" --to claude --cwd "<new-project-directory>"
python scripts/agent_rehome.py export --from "claude:<session-id>" --source-home "<copied-claude-home>" --out "<transcript.json>"
python scripts/agent_rehome.py import "<transcript.json>" --to codex --target-home "<target-codex-home>" --cwd "<target-project>"
```

项目 restore 必须用全新目录，默认标题加“迁移副本”。项目包不包含 Git 历史、依赖、缓存和常见凭据配置；排除规则不等同于完整秘密扫描。附件恢复到 `.rehome/attachments` 并重映射路径。历史文本附件可能只是当时读取的片段；缺失且未嵌入历史的附件无法补回。显式会话清单可通过 pack 的 `--sessions-json` 提供，格式见 README。

同机协作可直接使用本地路径；跨机才需搬运目录包。源数据目录不因导入而移动或删除。

## 桌面加载与降级

**Claude：** 脚本独立写 JSONL；Windows 默认尝试查找桌面 Code 会话登记目录并写 local_ 登记。使用自定义目标数据根时，需显式 `--desktop-registry "<verified-registry-directory>"` 才登记；`--no-desktop` 可只写历史。不支持的系统或未找到目录时返回 warnings，不能声称侧边栏已恢复。其他平台的登记位置未核实。桌面版需按用户正常流程重启才加载登记；Agent 不自动关闭/重启应用。新目录需要用户确认信任，不代改信任设置。独立 CLI 的认证与桌面可能不共享，不能复制凭据。

**Codex：** 脚本独立写 rollout、索引、数据库与归档；依赖目标已有且兼容的 state_5.sqlite。Windows 项目恢复可尝试运行中桌面程序的 folder-open 入口创建项目，不自动重启。完整项目归属还需要 Codex APP 中的 Agent 调用 `list_projects`、`move_thread_to_project` 和 `list_threads`：按精确路径取真实项目 ID，逐条绑定本批次聊天，再核对全部 ID。若会话尚不可用，先原生打开再重试一次。不要通过改写运行中全局状态冒充成功。

在 Claude、终端或其他没有 Codex 原生工具的环境，可用 restore 的 `--no-desktop` 只写文件和会话，之后由用户在 Codex APP 添加恢复文件夹、关联聊天，或由具备原生工具的 Agent 完成。报告“文件/会话已写入，项目侧边栏待验收”。自动入口不可用时同样明确报告降级状态，不能把工具缺失当成文件迁移失败。

## 保真与数据安全

- Codex 只导出界面消息事件，过滤 harness 注入的上下文；附件头和问答卡回复转成可读文本。
- Claude 的下一步框保留 recap、ask 和按钮 label，放在对应轮末尾；过程任务清单被过滤。后台通知不增加用户轮。
- 历史工具写为目标原生工具记录；命令卡片显示以该版本/模式的原生会话为准。未知进程/退出码保持未知，不为界面补造运行事实。
- 不保证分支、所有扩展事件、附件控件样式、不同版本的逐像素一致。长会话可续聊不等于模型直接加载了全部历史。
- 导入先检查完整性与路径，数据库使用在线备份；备份路径和受管理文件清单在返回结果/目标数据根的 rehome-backups、rehome-imports 中。
- 回退前停止目标会话写入，保留迁移后新增内容；按备份清单恢复对应文件。共享 SQLite/索引可能已有其他新聊天，不能盲目恢复整个旧数据库。恢复新目录失败时保留 restore.json 和备份供排查，不自动删除或宣称整批回滚。
