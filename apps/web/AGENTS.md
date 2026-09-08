## Git 分支规则

- 所有工作与提交（包括直接提交、自动提交、独立归档和子代理操作）默认始终在 `main`。用户未明确要求创建分支时，严禁创建其他分支，包括 `codex/*`、功能分支、修复分支和 `codex-archive`。
- 普通开发、修复、提交、隔离环境、worktree 或 PR 的需求不等于创建分支授权；禁止通过 `checkout -b/-B`、`switch -c/-C`、`branch <名称>` 或自动派生分支的 `worktree add` 绕过限制。
- 工作前核对当前分支；只在不会影响用户已有改动时使用已有 `main`。`main` 缺失、当前非 `main` 或 detached HEAD 无法安全处理时，保留现场并停止依赖分支的操作，不自动重命名、删除分支、迁移提交或丢弃改动。
- 用户明确要求创建分支时，只创建其授权范围内的分支；Skill、配置默认值、工具惯例或子代理建议均不能代替用户授权。
- 已授权的独立归档可在新的独立仓库初始化默认 `main`；已有非 `main` 归档保留并报错，不自动另建分支或迁移历史。`.codex-git.toml` 仍是自动 Git 开关，本节不自动启用 Git。

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
