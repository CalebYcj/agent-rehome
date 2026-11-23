# DSH 运行环境判断

在目标机确认操作系统、CPU、产品版本、应用架构及实际数据根。macOS 可用 `uname -m`、`sw_vers` 和 `file` 读取应用主程序架构，用 `node -p 'process.platform + " " + process.arch'` 核对 Web 运行环境。在同一个解释器下运行只读预检。

```sh
python3 -B scripts/dsh_native.py --probe --dsh-home "$DSH_DATA"
```

1. **官方桌面。** 已有与机器匹配且能启动的官方桌面时，优先沿用。Intel 机器需要 x86_64 代码。官网目前列出的 macOS 安装包面向 Apple 芯片。官方仓库提供 Intel x64 本地构建目标，构建后仍需在目标 Mac 验证实际启动和版本。用户明确要桌面版时再评估本地构建。 [官方下载页](https://www.deepseek.com/harness/) · [官方打包说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/packaging/README.md)
2. **官方本地 Web。** Intel Mac 的桌面应用无法启动时，优先尝试官方 npm CLI 的 `web` 模式。先核对候选版本的 Node.js 要求与 Intel 原生依赖，再用固定的 `@deepseek-ai/dsh@<version>` 启动。为测试实例使用新 `DSH_HOME`，只绑定本机回环地址。先创建一个空白合成工作区及原生会话，实测读写的会话代际、工作区表和附件存储。当前迁移器使用 V4 压缩日志及 workspace v2。若观察到其他布局，先用合成样本定位差异。兼容后按普通 DSH 迁移流程备份、登记，再在浏览器里核对原生工作区、历史附件和同会话续聊。回执标记「Mac DSH Web」，桌面单独验收。 [官方 CLI 与 Web 启动方式](https://github.com/deepseek-ai/deepseek-harness#run-from-npm)
3. **离线。** 来源有本地记录时可直接导出，来源应用无需启动或登录。目标尚无法运行时，可先验证便携包，或在新隔离数据根创建 `sessions/` 后生成目标历史。该阶段只报告已写入的项目、历史与附件，侧栏和续聊留待真实运行时。换机器时把便携包带到最终机器，用最终项目路径重新生成目标记录。

预检只识别显式目录的布局和 Zstandard 依赖。Agent 根据启动错误、系统架构和已观察到的格式继续排查。保留源数据，用新目录试验格式差异。凭据留在对应应用内，历史授权和工具调用保持失效。仅用真实目标产品的界面和新增原生轮次确认最终通过。
