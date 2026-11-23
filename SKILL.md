---
name: agent-rehome
description: 换 AI 不用从头再来。迁移 Codex、Claude Code、WorkBuddy、DeepSeek Harness（DSH）与 Antigravity Desktop 的聊天和项目，或把 Codex、Claude Code 的全局规则搬到新电脑。Use when the user wants to move supported agent conversations, projects, or global rules between agents or computers.
---

# Agent Rehome

## 首要验收：目标产品左侧栏

在目标应用确认原生会话出现在左侧栏。整项目恢复时，项目和全部迁入会话必须在左侧栏正确归组。点开旧会话核对历史，在同一会话续聊并检查工作目录。项目文件、附件、原生登记、界面和续聊分别记录结果。只验证了文件读回或登记时，报告对应阶段，整体迁移仍待验收。

## 这是什么

换主力 AI 的时候，最舍不得的是以前的聊天记录和做到一半的项目。Agent Rehome 帮你把它们搬到新的 AI 里：

- **聊天记录**：在新 AI 的侧边栏里都能翻到。
- **项目**：文件和分组一起搬，接着聊时它知道做到哪、约定过什么。
- **习惯**：你给旧 AI 定的全局规则，看过、同意后也能带上。
- **Skill**：你自己装的 Skill，看过清单、同意后也能带上。

**怎么用**：在新的 AI 里说"用 Agent Rehome 把 Codex 的项目全搬过来"（反过来就说 Claude）。它会先列出清单给你确认，再一次搬完。旧的 AI 不用打开，原来的对话也不会动。

以下是给 Agent 看的操作说明。

迁移 Skill，Python 3.10+（压缩 Codex 来源需要可选 zstd，见 README）；先读 [README](README.md) 的安装与用法，格式边界见 [SPEC](SPEC.md)。

## 开始前：检查 Python

来源端和接收端都要 Python 3.10+。先运行 `python --version`，不行再试 `python3 --version`；Windows 还可试 `py -3 --version`。
没有或版本过低时，停下来告诉用户：本 Skill 需要 Python 3.10 或以上，可从 https://www.python.org/downloads/ 下载，装好后再继续。用户同意后才可代为安装。Windows 上 `python` 可能只会打开应用商店，以能输出版本号为准。
读取压缩的 Codex 记录时如果报缺少解压器，告诉用户原因，用户同意后运行 `python -m pip install zstandard`，或换用 Python 3.14+。

## 先判断路线

1. 确认用户指定的来源/目标 Agent、单会话或整项目、同机或跨机；不能拿最近会话代替指定来源。
2. **默认走接收端单端路线。** 打包只读来源 Agent 在本机的数据文件，不需要调用来源 Agent，也不需要它在运行、已登录或还有额度。Codex 和 Claude Code 批量迁移用 `batch_rehome.py move`，其余来源按各自项目路线打包和恢复。来源数据在另一台电脑时，可复制来源数据目录和项目文件夹过来，再用 `--source-home` 指向数据根。来源端先打包时，接收端仍负责恢复、原生登记、归组和验收。`--source-home` 和 `--target-home` 都指数据根。
3. 打包完成后，醒目告诉用户包在哪、下一步做什么，再给一句可复制的话；打包结果的 `user_next_steps` 已写好这些内容，单会话和整项目都有。本 Skill 不联网传包：跨机时用户把整个包复制过去（U 盘、移动硬盘或局域网共享），不要传到公开位置。另一台电脑也要先装好本 Skill 和 Python。
4. Claude 同类走原样平移；Codex 同类按 ReHome 原则原生平移；跨 Agent 走有损转换。平台有限结论见 [验收记录](docs/VALIDATION.md)。

### Claude → Claude

单会话用原生 transfer；整项目先用 project_rehome.py pack --native 打包，再 restore 到全新目录。
```text
python scripts/agent_rehome.py transfer --from "claude:<id-or-jsonl>" --to claude --cwd "<existing-target-project>" --dry-run
python scripts/project_rehome.py pack --from claude --project "<source-project>" --native --include-memory --include-checkpoints --out "<new-package>"
python scripts/project_rehome.py restore "<native-project-package>" --to claude --cwd "<new-target-project>" --dry-run
```
跨机单会话使用 agent_rehome.py export --native 加 import，完整命令见 README。
原生历史不加摘要；只按 manifest 来源根及别名重定位顶层 cwd，保留子目录，正文/工具/thinking 字节不改。
Claude同ID默认拒绝；--new-copy另存归属ID与旁车，--fast-forward只把无分叉新增行追加回原会话原cwd，二者互斥；先看dry-run追加行数，细则见README。

### Codex → Codex

本 Skill 原生 transfer 或 export --native / import；整项目 pack --from codex --native / restore --to codex，命令见 README。
Codex可在App运行时自己恢复：有界数据库事务、索引追加校验、rollout独占新建；目标先初始化数据库，同ID拒绝。--new-copy另存；分页lineage拒绝、外部文件不收集，--convert仅诊断。

### Claude ↔ Codex

单会话用 transfer；整项目用 project_rehome.py pack/restore。反向迁移交换来源与目标，完整命令见 README。
```text
python scripts/agent_rehome.py transfer --from "claude:<id-or-jsonl>" --to codex --cwd "<existing-target-project>" --dry-run
python scripts/project_rehome.py restore "<exchange-project-package>" --to claude --cwd "<new-target-project>" --dry-run
```
先预览体积和磁盘需求。超大项目优先用 pack --files reference，接收端指向已搬好的目录；--strict-files 要求文件清单完全匹配。默认排除 Git。周边配置及差异见 restore.json。

转换可生成预算摘要；完整归档不等于模型加载全部历史。losses_summary、.rehome/losses/ 和 .rehome/exchange/ 保留降级证据。

### WorkBuddy 项目交换

Claude Code ↔ WorkBuddy 可直接转换，迁移步骤只用 Python 和两端的本地文件。WorkBuddy 来源用 `pack --from workbuddy`，Claude 目标用 `restore --to claude`。Claude 来源用 `pack --from claude`，再走下方 WorkBuddy 接收步骤。同机时由接收方执行，跨机只传迁移包。直接双向的文件、历史和隔离登记已有证据，桌面原生验收按平台记录。

Windows 和 macOS 的 WorkBuddy 样本均可用 `project_rehome.py pack --from workbuddy` 导出工作区、聊天、工具记录及附件。项目外的普通附件用 `--attachment-root` 指定可读取目录。Claude Code 和 Codex 接收沿用整项目的 `restore` 流程。

运行 `python scripts/workbuddy_receive.py <包目录> --cwd <新工作区>` 准备项目文件、便携历史和附件。Windows WorkBuddy 接收 Codex 原生迁移时，再运行 `python scripts/workbuddy_native.py <已准备工作区> --template-space <目标账号现有本地分组ID>`。使用当前已登录账号匹配的明确分组，先备份，再为本次恢复创建独立新分组。主窗口重开后验左栏、旧历史、附件和续聊。命令返回登记阶段及未投影项，未经实机确认不报完成。

Mac WorkBuddy 5.11.3 在 macOS 14.8.9 Intel 上已有合成项目原生接收证据；第二步显式加 `--experimental-macos`，先用对应该账号的本地合成分组和原生顶层聊天核实数据库、目录编码与归属。其他版本仍需各自复查。需要文件接手时，从 `.rehome/restore-workbuddy.json` 读取历史与附件索引。对已经转换过的会话，优先使用原交换包保留完整历史与附件结构。

### DeepSeek Harness 项目交换

使用 Python 3.14 自带的 Zstandard，或 Python 3.10+ 与可选的 `zstandard` 包。来源端以 `project_rehome.py pack --from dsh --project <工作区> --source-home <DSH 数据目录> --out <包目录>` 导出 V4 根会话、项目文件、图片和可解析的文件引用。目标 Codex、Claude Code 或 WorkBuddy 按各自接收步骤加载同一便携包。

Intel Mac 或 DSH 无法启动时，先用 `dsh_native.py --probe --dsh-home <明确的数据目录>` 只读核对环境与登记格式，再按 [DSH 运行环境判断](docs/DSH_RUNTIME.md) 选择官方 Web、桌面或离线工作流。已有本地 V4 历史可离线导出。目标运行不了时可以先恢复到隔离目录，后续在可用目标端从便携包恢复并完成界面验收。

DSH 接收用 `dsh_native.py <包目录> --cwd <新项目目录> --dsh-home <DSH 数据目录>` 写入新会话。目标 DSH 宿主退出后，用 `dsh_native.py --cwd <新项目目录> --dsh-home <DSH 数据目录> --register-offline <新的备份文件>` 登记项目并备份工作区记录。重开 DSH，从左栏检查标题、归组和历史，点开历史 PNG / TXT，再在原会话验证续聊与工作目录。迁移脚本可独立运行。Windows 合成实机样本覆盖 Codex → DSH 以及 WorkBuddy 5.11.3 ↔ DSH Desktop 0.2.2-rc.5。其他平台与 SSH 宿主需要各自验收。专属工具卡、分支、推理与 DSH 全局设置尚待适配。

### 从 Antigravity Desktop 导出项目

用 `project_rehome.py pack --from antigravity --project <来源项目> --out <新包目录>` 只读导出单根项目的主线聊天、项目文件和历史上传附件。默认读取 `~/.gemini/antigravity`，可用 `--source-home` 指定数据根。等待来源会话结束，再生成交换包。Codex、Claude Code、WorkBuddy 和 DSH 使用各自接收流程，继续核对目标左栏、项目归属、附件和原会话续聊。

Windows Antigravity Desktop 2.33.1 的合成样本已核对正文、标题、PNG 和中文名 TXT。工具、内部推理及未知记录写入损失清单。Mac、CLI、IDE 和多根项目仍待验。

Windows Antigravity Desktop 2.33.1 接收时，用 `antigravity_stage.py <交换包> --cwd <新工作区> --profile <新隔离数据根>` 准备项目和会话。用桌面原生入口登记这个空项目，核对原生项目 ID 后用 `antigravity_desktop.py --cwd <新工作区> --project-id <项目ID>` 预览。退出 Antigravity，待其语言服务结束，再加 `--apply` 写入。重开后在项目左栏打开每条会话，核对旧消息、PNG、TXT、同会话续聊和实际 cwd。Windows 两条合成会话已有完整桌面证据，其他版本和平台分别验收。原生日志从续聊才开始时，导出器从版本 1 的会话库补读旧轮次。

Windows 退出接力已通过隔离进程验证。目标原生空项目已准备好时，可先运行 `antigravity_relay.py --cwd <新工作区> --project-id <项目ID> --launch`。启动器会预检，后台进程等应用和语言服务退出再备份与登记。查看工作区的 `.rehome/antigravity-relay.json`，状态为 `completed` 或 `already-registered` 后再重开应用验收。接力只负责离线登记，桌面关闭与重开仍按既有授权办理。

### 全部项目一次搬

用户要搬"所有项目/全部对话"时，用 batch_rehome.py。先 `list` 盘点项目和对话，再 `move --dry-run` 预演。已有迁移授权时继续正式搬，无需重复确认。批量命令完成打包和恢复，包默认放在根目录旁的 `<root>-rehome-package`。缺失项目目录的记录会列出，单独核对可恢复的历史。两段式时由来源端 pack、接收端 restore 加 --root。恢复到 Claude 后，请用户亲手确认应用实际显示的目录信任提示。

**Codex 侧边栏验收是迁移最后一步。** Claude 无法登录或启动时，仍由 Codex 从本机 Claude 数据目录直接读取、恢复、添加项目、逐条归组并验收。文件写入、索引可查、登记请求已发、用户点过信任，都是中间状态。按 [Codex 项目绑定流程](docs/CODEX_PROJECT_BINDING.md) 从恢复回执继续，逐一核对侧边栏项目、聊天归属与 cwd 后才报告完成。若只缺用户处理实际出现的信任提示，汇报该阻塞并保留回执，用户确认后继续归组。对已迁入或已归档的项目只处理当前请求范围，切勿用重导入替代归组。

批量包里如果有 global-rules（全局规则，也就是"主人格"），restore 只会给出 global_rules 预览。先把要写入的位置、撤销方法、每一条 mentions 行和 warnings 原样告诉用户，用户明确同意后，再运行 `global_rules.py install <批量包> --to <目标> --apply`。不要替用户改写原文；用户想改时，让用户自己改，或由用户逐条说明怎么改。

批量包里如果有 user-skills（用户自己装的 Skill），restore 只会给出 user_skills 预览。把要装的清单（名字、说明、是否带脚本）、跳过的清单和原因、每一条 warnings 原样告诉用户，让用户决定装哪些；用户明确同意后，再运行 `user_skills.py install <批量包> --to <目标> --apply`，只装一部分就加 `--only <名字>`。目标已有同名 Skill 时跳过，不覆盖。Skill 原样复制，不改写；跨 Agent 时要告诉用户有些可能不能直接用。插件、内置 Skill 和本 Skill 自己不搬。不想带就加 `--no-user-skills`。

macOS 接收个人 Skill 使用同一安装命令（通常用 python3）：Claude 的目标是 ~/.claude/skills，Codex 是 ~/.agents/skills。先预览，再按既有授权或用户确认 apply；新开会话加载，必要时由用户重启。Windows 脚本路径、PowerShell/.exe 依赖和 CPU 架构不能靠原样复制适配。Mac 实机效果未验收，完整步骤见 README 的 macOS 接收个人 Skill。
```text
python scripts/batch_rehome.py list --from all
python scripts/batch_rehome.py move --from codex --to claude --root "<new-parent-directory>" --dry-run
python scripts/batch_rehome.py move --from codex --to claude --root "<new-parent-directory>" --source-home "<copied-old-.codex>"   # 旧数据从别的电脑复制来时
```

## 已知故障的自动修复

迁移命令报错、回执显示分步未完成，或目标端验收不符时，先按 [迁移故障恢复](docs/RECOVERY.md) 查证。信号、会话 ID、目标目录和版本都匹配时，在既有授权内执行对应修复，然后复查未通过的步骤。优先用原回执和已写入的会话继续。需要更换运行路线时保留已通过的结果，按实际完成的阶段报告。

## 安全与判断边界

- 不复制账号凭据、登录状态、信任或权限白名单；目标权限用 default，不把历史授权变成当前授权，不执行历史任务。
- 跨 Agent 不恢复不可见推理或加密模型状态；Claude 原生 thinking 只作为来源历史保留，不激活来源权限。
- 数据包含私人对话/源码，不能公开；配置密钥命中拒绝，--allow-secrets-in-config须明确确认且不等于脱敏；真实证据留私有目录。扫描非穷尽，二进制旁车不扫描内容，报告数量与字节数。
- 写前备份；不覆盖未知同ID、分叉历史、已有恢复目录或同名memory；来源不移动/删除，另存用--new-copy；Claude仅显式--fast-forward可追加经验证无分叉的历史，不重写共享旧行。
- 检查包的路径、哈希和损失清单，未知事件无对应损失条目时拒绝；凭据文件名和旁车/包内符号链接仍拒绝，会话 JSONL 须合法 UTF-8，原生项目根声明的别名与此不同；项目外 cwd 原样保留，只报数量。
- 跨 Agent 模型/版本从显式参数或目标配置/历史取得，不猜；Claude 原生版本沿用来源，自定义目标根需显式桌面登记目录。
- 重启和目录信任由用户完成，Agent 不代点或自动关闭/重启；CLI 与桌面认证可能不同，不能复制凭据解决登录。
- 未经对具体会话授权，不发送续聊验证；不伪造工具执行、退出码或验收证据，未知保持未知。
- 证据不匹配恢复规则、格式未知或操作被拒绝时，停止依赖该操作的写入，保留证据，报告失败阶段和最小必要信息。
- 回退前停止目标写入并保留新增内容；按备份清单恢复，SQLite 用在线备份，不盲目用旧共享数据库/索引覆盖其他聊天。
- 部分失败保留 restore.json 和备份，不自动删目录或宣称整批回滚；不改运行中全局状态、循环改库/重导入或改历史来冒充成功。

Claude 快进预演与写入均检测目标会话进程。只有 `live_process_check=clear` 时才继续。发现进程，由用户在应用内停止该会话或退出并重开应用，随后重新预演。快进后打开原会话，核对第一条新提问的 parentUuid 是否指向追加历史的最后一条有 UUID 的记录。clear 表示在命令行和会话进程记录中均未发现运行进程，检测范围有限。如果这条会话仍在其他地方打开，例如终端，请先关闭它，再重新预演。快进成功后可打开原会话续聊。

## 桌面加载与续聊

恢复结果有 `user_next_steps` 时，醒目展示操作方式、目标目录、会话标题和可复制的首句。项目内可查看 `.rehome/NEXT_STEPS.md`。Claude 需要重启时由用户操作。Codex 由接收端使用官方入口打开目录，精确匹配项目根，按 ID 原生加载、归组，并用原生工具复查归属与 cwd。项目暂为空时，接收端继续完成归组。

如需目录信任，让用户打开指定的恢复会话，粘贴首句并发送，出现提示时核对路径并亲手确认。使用实际恢复会话完成信任，随后可经授权向同一文件夹的其余会话发送验证消息。Agent 不使用电脑操作重启、结束进程、点击或截图验收。

需要重启或点选时优先用平台的结束选项或提问按钮，提供「已重启，继续」或「已打开，继续」及「稍后再说」。确认后通过原生工具核对会话可见性与归属，再取得续聊授权。没有按钮时提供醒目文字与可复制首句。

## 验收与能力不足

分别报告文件、登记、原生加载、侧边栏、续聊、权限、工作目录和附件；写入成功不等于已经加载，本机隔离测试不能代替异端原生验收。
涉及 Codex 项目归属时，先读 [项目绑定流程](docs/CODEX_PROJECT_BINDING.md)，归组与 cwd 必须在授权续聊前后分别核对。
缺少原生工具或登记目录时明确降级/待验收；可用 --no-desktop 写文件后交具备能力的 Agent，不扩大结论。
跨 Agent 不保证分支、扩展或逐像素一致；Claude 文件是路径链接，Codex 文件芯片点击一致性待验收；原生正文旧绝对路径不改，复制不等于引用可用。
显示和上下文细节、备份位置/回退见 README；损失、二进制与来源根规则见 SPEC；平台证据按需读验收记录。

## 详细参考

- [README 中文](README.md) / [English](README.en.md)：安装、命令、模型/版本、桌面登记、备份与回退。
- [SPEC.md](SPEC.md)：交换格式、原生字节、来源根别名、损失、二进制旁车与旧路径限制。
- [docs/VALIDATION.md](docs/VALIDATION.md)：平台矩阵和有边界的历史验收。
- [docs/CODEX_PROJECT_BINDING.md](docs/CODEX_PROJECT_BINDING.md)：原生项目归属、cwd 漂移及续聊前后证据。
