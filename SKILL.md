---
name: agent-rehome
description: 迁移 Claude Code/Codex 会话或整项目、换机及重绑定路径时使用，按同类平移或跨 Agent 转换选路。Use for Claude/Codex conversation and project migration, computer changes and path rebinding.
---

# Agent Rehome

迁移 Skill，Python 3.10+（压缩 Codex 来源需要可选 zstd，见 README）；先读 [README](README.md) 的安装与用法，格式边界见 [SPEC](SPEC.md)。

## 开始前：检查 Python

来源端和接收端都要 Python 3.10+。先运行 `python --version`，不行再试 `python3 --version`；Windows 还可试 `py -3 --version`。
没有或版本过低时，停下来告诉用户：本 Skill 需要 Python 3.10 或以上，可从 https://www.python.org/downloads/ 下载，装好后再继续。用户同意后才可代为安装。Windows 上 `python` 可能只会打开应用商店，以能输出版本号为准。
读取压缩的 Codex 记录时如果报缺少解压器，告诉用户原因，用户同意后运行 `python -m pip install zstandard`，或换用 Python 3.14+。

## 先判断路线

1. 确认用户指定的来源/目标 Agent、单会话或整项目、同机或跨机；不能拿最近会话代替指定来源。
2. 来源端只打包或列清单；接收端Agent自己恢复、写入、登记、归组、验收。同机共享路径，跨机带固定源码/包；--source-home/--target-home是数据根。
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

## 安全与判断边界

- 不复制账号凭据、登录状态、信任或权限白名单；目标权限用 default，不把历史授权变成当前授权，不执行历史任务。
- 跨 Agent 不恢复不可见推理或加密模型状态；Claude 原生 thinking 只作为来源历史保留，不激活来源权限。
- 数据包含私人对话/源码，不能公开；配置密钥命中拒绝，--allow-secrets-in-config须明确确认且不等于脱敏；真实证据留私有目录。扫描非穷尽，二进制旁车不扫描内容，报告数量与字节数。
- 写前备份；不覆盖未知同ID、分叉历史、已有恢复目录或同名memory；来源不移动/删除，另存用--new-copy；Claude仅显式--fast-forward可追加经验证无分叉的历史，不重写共享旧行。
- 检查包的路径、哈希和损失清单，未知事件无对应损失条目时拒绝；凭据文件名和旁车/包内符号链接仍拒绝，会话 JSONL 须合法 UTF-8，原生项目根声明的别名与此不同；项目外 cwd 原样保留，只报数量。
- 跨 Agent 模型/版本从显式参数或目标配置/历史取得，不猜；Claude 原生版本沿用来源，自定义目标根需显式桌面登记目录。
- 重启和目录信任由用户完成，Agent 不代点或自动关闭/重启；CLI 与桌面认证可能不同，不能复制凭据解决登录。
- 未经对具体会话授权，不发送续聊验证；不伪造工具执行、退出码或验收证据，未知保持未知。
- 未见过的格式、报错或拒绝时，停止依赖该操作的写入，报告原因、失败阶段和最小必要信息；保留证据，不自行改数据绕过去。
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
