---
alwaysApply: true
scene: git_message
---

1. <Header>: 必须是单行，格式为 `<type>(<scope>): <short summary>`
   - <type> 必须是以下之一：
     - feat: 新增功能
     - fix: 修复 Bug
     - refactor: 代码重构（既不修复错误也不添加功能的代码更改）
     - docs: 文档变更（如 README 修改）
     - style: 代码格式调整（不影响运行逻辑的空格、分号等变动）
     - chore: 构建过程或辅助工具的变动（如修改 .gitignore, uv.lock, requirements.txt）
     - perf: 提高性能的代码更改
   - <scope>: 可选，代表修改的模块或文件名（例如: venv, encoder, config），如果是全局修改则省略括号。
   - <short summary>: 用一句简短、笃定的话概括改动。首字母小写，结尾不加句号。

2. <Body> (可选): 如果改动较为复杂，请在 Header 下方空一行，用列表（-）详细说明：
   - 为什么要做这个改动？
   - 改动的核心逻辑是什么？
   - 是否有需要注意的副作用？

3. <Footer> (可选): 涉及重大变更（BREAKING CHANGE）或关联 Issue 时使用。

# Tone & Language Style
- 必须使用【中文】编写短评和内容（如果我要求英文除外）。
- 语气要专业、精炼、使用祈使句（例如：使用“修复...”，而不是“我修复了...”或“这个问题被修复了”）。
- 绝不废话，不要输出除 Git Message 本身之外的任何解释、Markdown 代码块外壳或提示语。
