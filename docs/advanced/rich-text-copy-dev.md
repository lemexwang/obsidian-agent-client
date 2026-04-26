---
category: 技术笔记
project: Agent Client 增强
priority: Medium
tags: [Obsidian, Plugin, RichText, Outlook, HTML, Clipboard]
created: 2026-04-22
status: 归档
---

# 📄 Agent Client 增强 - 全局富文本复制插件开发说明

## 🎯 插件概述
该插件名为 **Rich Text Copy Tool** (`obsidian-rich-copy`)，是一个专门为解决 Obsidian 笔记内容粘贴到 Outlook、Teams 和 Word 等办公软件时格式丢失问题而开发的微型插件。

## 🛠️ 技术核心实现

### 1. 部署位置
插件位于两个库的以下路径：
- `Lemex_Vault/.obsidian/plugins/obsidian-rich-copy/`
- `Alice_Study_2026/.obsidian/plugins/obsidian-rich-copy/`

### 2. 关键逻辑
*   **注入方式**：通过 `layout-change` 事件监听，自动在每个 `MarkdownView` 的 `containerEl` 右下角注入一个固定定位（`position: absolute`）的悬浮按钮。
*   **渲染逻辑**：调用 Obsidian 原生 API `MarkdownRenderer.render`，确保渲染效果与软件内所见基本一致。
*   **Outlook 兼容性优化（关键）**：
    *   **内联样式注入**：由于 Outlook 邮件客户端会过滤掉大部分 CSS 类名，插件在复制前会遍历 HTML 元素，将样式（字体、颜色、背景、边框）直接写入元素的 `style` 属性中。
    *   **样式标准**：针对 H1-H3 标题、代码块（Pre/Code）、表格（Table/TD/TH）进行了特定的内联样式定义。
*   **剪贴板写入**：使用 `navigator.clipboard.write` 配合 `ClipboardItem`，同时封装 `text/plain` (Markdown) 和 `text/html` (富文本) 两种格式。

## 📋 维护与故障排除

### 常见维护场景
1.  **按钮消失**：
    *   **原因**：Obsidian 核心更新可能修改了视图容器的类名，或者插件在某些特殊视图（如看板）下未被触发。
    *   **修复**：检查 `main.js` 中的 `iterateAllLeaves` 和 `MarkdownView` 匹配逻辑。
2.  **样式微调**：
    *   如果需要修改粘贴到邮件后的字体大小或标题颜色，可直接编辑 `main.js` 中的 `applyInlineStyles` 函数内的 `styles` 对象。
3.  **重新生效**：
    *   修改 `main.js` 后，无需重新编译，只需在 Obsidian 中关闭并重新打开该插件即可。

### 稳定性评估
该插件采用“原生 API + 零依赖”设计方案，受 Obsidian 版本更新影响的风险极低。只要 Obsidian 保持对 `MarkdownRenderer` 的支持，该功能即可长期有效。

---
**由 Gemini AI 辅助开发并记录于 2026-04-22**