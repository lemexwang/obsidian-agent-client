# Agent Client 插件 RAG 功能重新配置指南

## 1. 背景

本笔记用于在 “Agent Client” 插件通过Obsidian官方社区市场更新后，重新恢复我们手动添加的**检索增强生成（RAG）**功能。

**重要**：官方的插件更新会覆盖我们修改过的代码，导致RAG功能失效。因此，每次更新后，都需要按照本指南的步骤重新配置。

## 2. 关键文件位置

- **已修改的源代码目录**：我们所有包含RAG功能的源代码都保存在这个文件夹中。这是我们的”黄金版本”。
  ```
  /Users/alice/Obsidian_Local_Archives/_temp_obsidian_plugins_safety/agent-client/
  ```
  - 当前分支：`rag-0.9.4`（基于官方 `0.9.4` tag，含所有 RAG 修改）
  - RAG 修改为未提交的工作区变更（`git stash` 保存，通过 `git stash pop` 恢复）

- **编译后的目标文件**：每次编译成功后，会在此源代码目录的根路径下生成 `main.js` 文件。

- **插件安装目录（需要覆盖的目标）**：
  - **Alice_Study_2026 库**: `/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Alice_Study_2026/.obsidian/plugins/agent-client/`
  - **Lemex_Vault 库**: `/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Lemex_Vault/.obsidian/plugins/agent-client/`

## 3. 下次更新步骤（官方发布新版本时）

当官方发布新版本，请按以下步骤操作（或让AI操作）：

### 步骤 1: 进入源代码目录，保存 RAG 修改

```bash
cd /Users/alice/Obsidian_Local_Archives/_temp_obsidian_plugins_safety/agent-client/
git stash   # 保存当前 RAG 修改
```

### 步骤 2: 拉取最新代码，切换到新版本 tag

```bash
git fetch origin
# 查看可用 tag（找到最新版本号，例如 0.9.5）
git tag | sort -V | tail -5
# 切换到新版本，创建新的 RAG 分支
git checkout <新版本tag> -b rag-<新版本号>
```

### 步骤 3: 恢复 RAG 修改，解决冲突

```bash
git stash pop
# 如有冲突，让 AI 介入解决，然后：
git add .
```

### 步骤 4: 安装依赖并编译

```bash
npm install
npm run build
```

**注意**：如果编译失败，说明官方更新与 RAG 代码有冲突，需要 AI 介入解决后再编译。

### 步骤 5: 复制编译好的文件

```bash
cp main.js “/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Alice_Study_2026/.obsidian/plugins/agent-client/”
cp main.js “/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Lemex_Vault/.obsidian/plugins/agent-client/”
cp manifest.json “/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Alice_Study_2026/.obsidian/plugins/agent-client/”
cp manifest.json “/Users/alice/Library/Mobile Documents/iCloud~md~obsidian/Documents/Lemex_Vault/.obsidian/plugins/agent-client/”
```

### 步骤 6: 重载 Obsidian

回到Obsidian，使用快捷键 `Cmd+P` 打开命令面板，搜索并执行 “**Reload app without saving**” 命令。

重载完成后，RAG功能即可恢复正常。您可能需要去插件设置中重新打开 “**Enable Automatic RAG**” 开关。

## 4. 历史版本记录

| 日期 | 官方版本 | RAG 分支 | 备注 |
|------|---------|---------|------|
| 2026-03-28 | 0.9.4 | `rag-0.9.4` | 首次升级到 0.9.4，解决 ChatMessages.tsx 冲突 |
