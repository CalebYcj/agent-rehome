# Agent Rehome

版本 **0.6.0** · [English](README.en.md) · [MIT](LICENSE)

如果你在某个编程 Agent 里跟进了一个项目，聊了几十轮、攒了不少背景，后来想换另一个工具接着做，或者换了台新电脑，通常只能开个空白对话把来龙去脉重新讲一遍。

Agent Rehome 用来省掉这步麻烦。它会直接读取你电脑上保存的本地聊天记录，连同项目文件和历史附件一起整理好，写进新工具的本地目录里。搬完之后，原来的对话会出现在新软件的左侧栏、归在对应的项目下面，点开就能沿着之前的上下文继续聊。

因为全程读的都是本地文件，旧软件不需要打开，账号退出了或者额度用完了也照样能搬。原有的聊天记录留在原地不会改动；往目标软件写入之前，脚本也会先把涉及的本地数据备份一份。

## 支持的软件

目前支持在 Windows 和 macOS 上跨工具迁移，也支持同一款工具换电脑恢复：

| 软件 | Windows | macOS | Skill 放置目录 |
| --- | --- | --- | --- |
| **Codex**（ChatGPT 桌面端 / CLI） | 支持 | 支持 | `~/.agents/skills/agent-rehome/` 或 `~/.codex/skills/agent-rehome/` |
| **Claude Code** | 支持 | 支持 | `~/.claude/skills/agent-rehome/` |
| **WorkBuddy** | 支持 | 支持 | `~/.workbuddy/skills/agent-rehome/`（或直接按工作区接收） |
| **DeepSeek Harness**（`dsh`） | 支持 | 视架构与运行环境而定（见 [DSH 说明](docs/DSH_RUNTIME.md)） | `~/.dsh/skills/agent-rehome/` |
| **Antigravity Desktop** | 支持 | 支持 | `~/.gemini/antigravity/skills/agent-rehome/` |

不同客户端底层的存储结构差别很大，每条路线实际在什么版本测过、有哪些已知边界，都如实记在 [平台验收记录](docs/VALIDATION.md) 里。

## 怎么用

这是一个给 Agent 阅读和执行的 Skill，正常使用时不需要你自己记命令行参数。

1. **把 Skill 放进新工具里**
   去 [Releases](https://github.com/CalebYcj/agent-rehome/releases/latest) 下载最新的压缩包并解压，把里面的 `agent-rehome` 文件夹放到**你准备搬过去用的那个软件**对应的目录（见上表）。你也可以直接把这个仓库链接发给目标 Agent，让它照说明自己装好。

2. **确认电脑上有 Python 3.10+**
   脚本只依赖 Python 标准库（只有读取旧版 `.zst` 压缩记录时才需要额外的解压库）。不确定装没装的话，直接让 Agent 帮你检查就行。
   <details>
   <summary>macOS 安装 Python 的小提示</summary>

   macOS 自带的 `python3` 有时只是一个提示安装命令行工具的空壳，或者版本低于 3.10。可以先在终端跑一下 `python3 --version`；如果版本不够，去 [Python 官网下载页](https://www.python.org/downloads/macos/) 装一个 3.10 以上的版本即可，不要去删改系统自带的 Python。
   </details>

3. **直接跟新工具说你要搬什么**
   打开目标软件，用平常说话的方式告诉它就行，比如：
   `用 Agent Rehome 把我 Codex 里的项目全搬过来`（也可以指定某一个项目，或者把 Codex 换成 Claude、WorkBuddy、DSH、Antigravity）。
   它会先扫描并列出一份预览清单给你确认，你同意后才真正写入。如果是换电脑，先把旧电脑上的数据文件夹（如 `.codex`、`.claude`、`.workbuddy`、`.dsh` 或 `.gemini/antigravity`）连同项目目录拷到新电脑，再告诉 Agent 放在哪即可。

4. **重开软件，从左侧栏点开继续聊**
   大多数桌面客户端只在启动时加载本地索引，或者需要在退出时完成离线登记。按 Agent 给出的最后一步提示正常退出并重开一次软件，确认对话已经挂在左侧栏对应的项目下，就能接着用了。

## 还能顺带搬什么

- **批量项目、全局规则与个人 Skill**：一次搬空整个软件里的项目时，可以把全局提示词（如 `~/.codex/AGENTS.md`、`~/.claude/CLAUDE.md`）以及你自己装过的通用 Skill 一并带上。恢复时这些内容默认只展示预览，等你确认后才会安装，遇到同名文件会自动跳过，不会覆盖你现有的配置。
- **超大项目只搬对话**：如果项目文件夹本身很大，没必要打进迁移包里来回拷。你可以先把代码目录挪过去，再让工具用引用模式（`--files reference`）只打包对话记录、配置和附件，恢复时会自动帮你核对两边文件有没有遗漏或差异。

## 用之前需要了解的几件事

- **迁移包不要外传**：生成的迁移包里装着完整的私人对话和项目代码，留在本地或自己的移动硬盘里就好，千万不要上传到公开仓库或网盘。
- **客户端大更新可能影响兼容**：由于需要直接读写各家软件的本地数据库和会话文件，后续如果某款客户端改了底层存储格式，部分路线可能需要等适配更新。每次写入前生成的自动备份都在目标数据目录的 `rehome-backups/` 下，单项目的详细恢复记录保存在项目内的 `.rehome/` 目录。
- **跨工具搬家只保留可见上下文**：在同款软件之间迁移时，脚本会尽量保留原始记录；跨软件迁移则会转换成统一的交换格式。原工具里的隐藏推理过程（thinking）、加密压缩块、账号登录态以及目录信任权限不会带过去，没法原样保留的条目都会写进 `.rehome/losses/` 供你备查。像 `.mcp.json` 这类可能自动连接外部服务的配置，恢复时会先归档到 `.rehome/surroundings/originals/`，不会在项目根目录下自动生效。

## 进阶用法与文档

如果你想了解协议结构、各端验收细项，或者更喜欢在终端里手动跑脚本，可以查看下面的文档和命令清单：

- [平台与路线验收记录](docs/VALIDATION.md)
- [交换包格式与技术规范](SPEC.md)
- [Codex 侧边栏归组与工作目录说明](docs/CODEX_PROJECT_BINDING.md)
- [DeepSeek Harness 运行环境说明](docs/DSH_RUNTIME.md) · [中断与恢复处理](docs/RECOVERY.md)

<details>
<summary>展开查看手动命令行参考与自检脚本</summary>

所有命令默认都建议先加 `--dry-run` 看一遍预览，确认无误后再去掉 `--dry-run` 正式执行。环境不确定时可以先跑只读体检：

```bash
python3 -B scripts/doctor.py
```

**1. 一次搬完某个工具里的全部项目（最常用）**

```bash
python scripts/batch_rehome.py list --from all
python scripts/batch_rehome.py move --from codex --to claude --root "<新项目父目录>" --dry-run
python scripts/batch_rehome.py move --from codex --to claude --root "<新项目父目录>"

# 预览并按需安装随包带过来的全局规则与个人 Skill
python scripts/global_rules.py install "<批量包目录>" --to claude --apply
python scripts/user_skills.py install "<批量包目录>" --to claude --apply
```

**2. 单个项目打包与恢复（Codex / Claude Code）**

```bash
# 跨工具通用交换包（不带 --native；同款工具原样平移可加 --native）
python scripts/project_rehome.py pack --from codex --project "<源项目>" --out "<新包目录>"
python scripts/project_rehome.py restore "<包目录>" --to claude --cwd "<新项目目录>" --dry-run

# 超大项目仅用引用清单核对代码文件
python scripts/project_rehome.py pack --from codex --project "<源项目>" --out "<新包目录>" --files reference
python scripts/project_rehome.py restore "<包目录>" --to codex --cwd "<已拷好的项目目录>" --strict-files --dry-run
```

**3. 单条会话直接迁移**

```bash
python scripts/agent_rehome.py transfer --from "claude:<会话ID或jsonl路径>" --to codex --cwd "<已存在的目标项目>" --dry-run
```

**4. WorkBuddy / DeepSeek Harness / Antigravity 专项命令**

```bash
# WorkBuddy：导出用 project_rehome.py pack --from workbuddy；原生接收分两步：
python scripts/workbuddy_receive.py "<便携交换包>" --cwd "<新工作区>"
python scripts/workbuddy_native.py "<新工作区>" --template-space "<目标账号现有本地分组ID>"

# DeepSeek Harness：导出用 project_rehome.py pack --from dsh；接收写入并在退出宿主后离线登记：
python scripts/dsh_native.py "<便携交换包>" --cwd "<新项目>" --dsh-home "<DSH数据目录>"
python scripts/dsh_native.py --cwd "<新项目>" --dsh-home "<DSH数据目录>" --register-offline "<备份文件>"

# Antigravity Desktop：导出用 project_rehome.py pack --from antigravity；反向接收先暂存再在退出应用后登记：
python scripts/antigravity_stage.py "<便携交换包>" --cwd "<新工作区>" --profile "<隔离暂存目录>"
python scripts/antigravity_desktop.py --cwd "<新工作区>" --project-id "<原生项目ID>" --apply
```

**5. 本地回归测试与隐私扫描**

测试全程在隔离的临时 `HOME` 下用合成数据运行，不会触碰本机真实会话或联网：

```bash
python -B scripts/run_tests.py
python -B scripts/privacy_scan.py .
```

</details>
