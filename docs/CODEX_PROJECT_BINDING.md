# Codex 项目归属与工作目录验收

涉及Codex项目归属时先读本文件。来源端只打包/列清单，接收端Agent自己恢复、写入、登记、归组及验收；Codex同类使用本Skill的原生平移，可以在App运行时写入。原生项目工具和文件检查仍需分别取证，本文不授权额外续聊或绕过拒绝。

## 批量恢复后的侧边栏完成条件

Claude → Codex 同机迁移由 Codex 直接读取 Claude 本地数据，不依赖 Claude 应用运行、登录或回复。批量 `move` 或 `restore` 写入的回执中，每个项目的 `sidebar` 包含目标目录、**全部**导入会话 ID 和登记请求状态。单项目或旧批次从各项目的 `.rehome/restore.json` 取目标目录和 `sessions[].id`。只处理本次迁移的项目和会话。迁移完成后的归档或侧边栏整理是用户的新决定，后续核对不要把这些项目重新加回去。

1. 用 `list_projects` 按规范化后的完整路径及目标主机匹配项目，不能按重名标题匹配。已发起 folder-open 的项目先复查，尚未发起的由接收端使用原生添加项目入口。超时只说明仍未登记，只有看到实际信任提示时才请用户核对路径并确认。确认后从原回执继续。
2. 分页用 `list_threads` 核对每条导入 ID。已正确归属的跳过；其余用 `move_thread_to_project` 绑定至匹配的原生项目 ID。若提示聊天不在侧边栏，用 `navigate_to_codex_page` 按 ID 原生打开后重试一次，再复查。只打开聊天，无需发送消息。遇到安全拒绝时保留结果和具体原因。
3. 再读原生项目和聊天列表，逐一核对项目存在、每条聊天归在对应项目、工作目录匹配，并核对原生侧边栏项目项。归档会话按其原有归档状态核对。报告已核对数和未完成的项目或对话；全部符合时才报告侧边栏同步完成。脚本成功退出或数据库里已有记录仅证明写入阶段完成。

## 桌面登记与能力降级（原文）

零会话的Codex项目恢复也会尝试登记，结果写入restore.json的desktop_project_registry；不为登记伪造会话或新建目标数据库。--no-desktop不调用登记，dry-run不产生登记副作用。没有待绑定会话时thread_binding_required为[]，仍须独立核对registered及原生项目列表；空列表不代表登记成功。Windows运行中走既有folder-open，Mac自动入口不可用时明确返回待验收，不能用Windows成功替代Mac证据。

**Codex：** 脚本独立写 rollout、索引、数据库与归档；依赖目标已有且兼容的 state_5.sqlite。Windows 项目恢复可尝试运行中桌面程序的 folder-open 入口创建项目，不自动重启。完整项目归属还需要 Codex APP 中的 Agent 调用 `list_projects`、`move_thread_to_project` 和 `list_threads`：按精确路径取真实项目 ID，先按会话 ID 原生打开，再逐条绑定本批次聊天，最后核对全部 ID。若首次移动提示任务不在侧边栏，按 ID 打开后重试一次。不要通过改写运行中全局状态冒充成功。

在 Claude、终端或其他没有 Codex 原生工具的环境，可用 restore 的 `--no-desktop` 只写文件和会话，之后由用户在 Codex APP 添加恢复文件夹、关联聊天，或由具备原生工具的 Agent 完成。报告“文件/会话已写入，项目侧边栏待验收”。自动入口不可用时同样明确报告降级状态，不能把工具缺失当成文件迁移失败。

## 项目归属、cwd和续聊前后的独立检查（原文）

Mac 实测发现：原生续聊可能将已导入会话的 `threads.cwd` 改为默认新聊天目录；`move_thread_to_project` 成功和侧边栏归组正确，也不保证工作目录正确。原因尚未确定，不推断为所有版本的固定行为。

先等待官方 folder-open 创建的项目出现在 `list_projects`，按精确根路径选 ID，再原生绑定会话。首次未出现不能直接判失败，也不能在项目未核实前发送续聊。分别用 `list_threads` 核对项目 ID、`read_thread` 核对 cwd；数据库里的 `project_id` 不等于原生侧边栏归属证据。

在原生打开后、授权续聊前及续聊完成后执行只读检查：

```text
python -B scripts/check_codex_binding.py --thread-id "<new-test-thread-id>" --cwd "<expected-project-absolute-path>"
```

该检查只核对数据库 cwd 和 rollout 的 session_meta，不代替原生加载、项目归属或续聊验收。若出现漂移，停止该会话中的项目操作，保留前后证据；不要自动循环改库、重启、重导入或改写历史 turn_context 来伪造持久修复。仅修正当前记录也必须报告“当前绑定已修复，续聊持久性待验证”。跨端交接包含补丁、测试和脱敏复现报告，真实聊天及备份留在私有目录。

检查器同时列出最近记录的 turn_context 是否匹配；它是历史观测，不等于当前运行时状态，也不参与静态 binding_matches 的判定。因此数据库修回后 binding_matches 为真，仍不能证明曾漂移的运行时已被持久修复。缺失历史上下文返回 null，不默认为通过。

在任何授权续聊前，必须先取得原生项目归属与原生 read_thread.cwd 均正确的证据；不能把归组和首次续聊并发发起。没有可核实的原生工具时报告待验收。官方 App Server 的轮次接口允许覆盖 cwd；仅当实际调用方和当前版本支持时显式传入核实过的目标目录。没有暴露 cwd 参数的工具不能靠提示词、编造元数据或另开隐藏 CLI 代替。Windows 的一次“先归组再续聊”检查通过；Mac 后续也回传了修复后同一会话的一次授权续聊通过。两者均不足以证明该顺序能消除所有漂移；任何新续聊仍需对具体目标会话取得授权。

## 规则与 Skill 目录

已验收的 Codex 会话只在第一轮记录 Skill 目录，同机续聊和恢复后均未刷新。跨机后历史里的目录仍指向来源机，原生迁移保留这些历史路径。AGENTS.md 每轮重新注入。详见主交接第 121 节。

## 回执口径

导入器写入workspace-write/on-request、memory disabled只是加载前的保守默认值，不是持续运行策略。App加载后按目标用户当前权限模式恢复；Windows/Mac样本均观察到记录变为never/disabled。加载前后策略要单独报告，不能把用户当前模式误诊为来源权限被激活，也不能宣称导入默认值始终有效；restore.json.runtime_policy_note记录此边界。无需为迁移修改用户全局权限模式。

分别报告文件/数据库记录、原生项目ID、read_thread.cwd、历史上下文、授权续聊前后状态；检查工具缺失的项目写待验收，不凭数据库字段或一次成功样本扩大结论。样本记录见 [VALIDATION.md](VALIDATION.md)，安装及恢复命令见 [README.md](../README.md)。
