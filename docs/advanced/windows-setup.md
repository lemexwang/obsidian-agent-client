# Agent Client Windows 安装与配置教程

> 本笔记记录在 Windows 环境下安装 Obsidian Agent Client 插件，并配置 Claude 和 Gemini 的完整步骤。

---

## 第一步：安装 BRAT 插件

Agent Client 目前是社区测试版，需要通过 BRAT 安装。

1. 打开 Obsidian → **设置** → **第三方插件**
2. 关闭安全模式（如果还没关）
3. 点击 **浏览**，搜索 `BRAT`，安装并启用

---

## 第二步：通过 BRAT 安装 Agent Client

1. 设置 → **BRAT** → **Add Beta Plugin**
2. 粘贴仓库地址：`https://github.com/RAIT-09/obsidian-agent-client`
3. 点击 **Add Plugin**，等待安装完成
4. 回到第三方插件列表，启用 **Agent Client**

---

## 第三步：安装 Node.js（必须）

1. 前往 [nodejs.org](https://nodejs.org) 下载 LTS 版本
2. 安装时勾选 "Add to PATH"
3. 安装完成后打开 **PowerShell**，验证：

```powershell
node -v
npm -v
```

---

## 第四步：安装 Claude Code

在 PowerShell 中运行：

```powershell
npm install -g @anthropic-ai/claude-code
```

安装完成后登录账号：

```powershell
claude
```

按提示在浏览器中完成 Anthropic 账号授权。

然后安装 ACP 适配器：

```powershell
npm install -g @agentclientprotocol/claude-agent-acp
```

---

## 第五步：安装 Gemini CLI

```powershell
npm install -g @google/gemini-cli
```

安装完成后登录：

```powershell
gemini
```

按提示用 Google 账号授权（需要 Google AI Studio API Key 或 Google 账号）。

然后安装 ACP 适配器：

```powershell
npm install -g @agentclientprotocol/gemini-agent-acp
```

---

## 第六步：在 Obsidian 中配置路径

打开 Obsidian → 设置 → **Agent Client**，填入以下路径：

| 配置项 | Windows 路径 |
|---|---|
| Node.js 路径 | `C:\Program Files\nodejs\node.exe` |
| Claude ACP 路径 | `C:\Users\你的用户名\AppData\Roaming\npm\claude-code-acp.cmd` |
| Gemini ACP 路径 | `C:\Users\你的用户名\AppData\Roaming\npm\gemini-acp.cmd` |

> 不确定路径时，在 PowerShell 中运行 `where.exe claude-code-acp` 查看实际路径。

---

## 第七步：开始使用

- 点击左侧边栏的 Agent Client 图标打开对话窗口
- 顶部下拉菜单切换 Claude / Gemini
- 输入 `@笔记名` 可引用 Vault 中的笔记
- 输入 `/` 查看可用命令

---

## 参考资料

- [Agent Client 官方文档](https://rait-09.github.io/obsidian-agent-client/)
- [GitHub 仓库](https://github.com/RAIT-09/obsidian-agent-client)
- [Obsidian 论坛介绍帖](https://forum.obsidian.md/t/new-plugin-agent-client-bring-claude-code-codex-gemini-cli-inside-obsidian/108448)
- [Medium 教程：Setup Obsidian x Gemini/Claude](https://ghostleek.medium.com/setup-obsidian-x-gemini-claude-via-cli-in-a-minute-0d23114fa055)
