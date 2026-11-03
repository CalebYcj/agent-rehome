---
name: agent-rehome
description: 迁移 Claude Code/Codex 会话或整项目、换机及重绑定路径时使用，按同类平移或跨 Agent 转换选路。Use for Claude/Codex conversation and project migration, computer changes and path rebinding.
---

# Agent Rehome

第三方迁移 Skill，Python 3.10+（压缩 Codex 来源需要可选 zstd，见 README）；先读 [README](README.md) 的安装与用法，格式边界见 [SPEC](SPEC.md)。

## 先判断路线

1. 确认用户指定的来源/目标 Agent、单会话或整项目、同机或跨机；不能拿最近会话代替指定来源。
2. 同机优先共享本地路径；跨机携带固定源码和数据包。--source-home/--target-home 是数据根，不是项目目录。
3. Claude 同类走原样平移；Codex 同类交给 ReHome；跨 Agent 走有损转换。平台有限结论见 [验收记录](docs/VALIDATION.md)。

### Claude → Claude

单会话用原生 transfer；整项目先用 project_rehome.py pack --native 打包，再 restore 到全新目录。
```text
python scripts/agent_rehome.py transfer --from "claude:<id-or-jsonl>" --to claude --cwd "<existing-target-project>" --dry-run
python scripts/project_rehome.py pack --from claude --project "<source-project>" --native --include-memory --include-checkpoints --out "<new-package>"
python scripts/project_rehome.py restore "<native-project-package>" --to claude --cwd "<new-target-project>" --dry-run
```
跨机单会话使用 agent_rehome.py export --native 加 import，完整命令见 README。
原生历史不加摘要；只按 manifest 来源根及别名重定位顶层 cwd，保留子目录，正文/工具/thinking 字节不改。

### Codex → Codex

使用 ReHome Desktop 的盘点、预览和恢复，或 codex-rehome-skill 自身入口；不在本 Skill 内重写。
--convert 仅限用户明确选择的同类转换诊断，不能当作无损平移。此路线的操作命令以 ReHome 自身说明为准。

### Claude ↔ Codex

单会话用 transfer；整项目用 project_rehome.py pack/restore。反向迁移交换来源与目标，完整命令见 README。
```text
python scripts/agent_rehome.py transfer --from "claude:<id-or-jsonl>" --to codex --cwd "<existing-target-project>" --dry-run
python scripts/project_rehome.py restore "<exchange-project-package>" --to claude --cwd "<new-target-project>" --dry-run
```
先预览、检查 manifest/skipped/损失与目录，再在已有授权范围内去掉 --dry-run 执行；pack 包须全新且在来源工程外。
转换可生成预算摘要；完整归档不等于模型加载全部历史。losses_summary、.rehome/losses/ 和 .rehome/exchange/ 保留降级证据。

## 安全与判断边界

- 不复制账号凭据、登录状态、信任或权限白名单；目标权限用 default，不把历史授权变成当前授权，不执行历史任务。
- 跨 Agent 不恢复不可见推理或加密模型状态；Claude 原生 thinking 只作为来源历史保留，不激活来源权限。
- 数据包含私人对话/源码，不能公开；真实聊天、原始证据和备份留私有目录，公开报告先脱敏；排除规则和秘密扫描并非穷尽，二进制旁车不扫描内容，必须报告数量与字节数。
- 写前备份；不覆盖未知同 ID、已变化/续聊的历史、已有恢复目录或同名 memory；保留来源不移动/删除，来源历史更新后，转换路线用 --new-copy 另存快照，原生同 ID 仍拒绝；不绕过拒绝。
- 检查包的路径、哈希和损失清单，未知事件无对应损失条目时拒绝；凭据文件名和旁车/包内符号链接仍拒绝，会话 JSONL 须合法 UTF-8，原生项目根声明的别名与此不同；项目外 cwd 原样保留，只报数量。
- 跨 Agent 模型/版本从显式参数或目标配置/历史取得，不猜；Claude 原生版本沿用来源，自定义目标根需显式桌面登记目录。
- 重启和目录信任由用户完成，Agent 不代点或自动关闭/重启；CLI 与桌面认证可能不同，不能复制凭据解决登录。
- 未经对具体会话授权，不发送续聊验证；不伪造工具执行、退出码或验收证据，未知保持未知。
- 未见过的格式、报错或拒绝时，停止依赖该操作的写入，报告原因、失败阶段和最小必要信息；保留证据，不自行改数据绕过去。
- 回退前停止目标写入并保留新增内容；按备份清单恢复，SQLite 用在线备份，不盲目用旧共享数据库/索引覆盖其他聊天。
- 部分失败保留 restore.json 和备份，不自动删目录或宣称整批回滚；不改运行中全局状态、循环改库/重导入或改历史来冒充成功。

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
