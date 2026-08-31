# ADR-0004：P01 领域契约与 PostgreSQL 技术栈

- 状态：Accepted
- 日期：2026-08-31
- 阶段：P01

## 背景

P01 要求纯领域核心、真实 PostgreSQL 迁移、Inbox/Outbox 幂等和 Python 3.13/3.14
兼容。主机没有 Docker、已安装 PostgreSQL 或可用 WSL 发行版，且安全约束禁止
索取或保存数据库密码。

## 决定

1. 领域契约使用 Pydantic 2.13.5 的严格、冻结模型；基础设施不得被 domain 导入。
2. 数据库层使用 SQLAlchemy 2.0.52 Core、Alembic 1.19.1 和 Psycopg 3.3.4。
3. 数据库契约以 PostgreSQL 18.6 为准，不采用 PostgreSQL 19 Beta 3。
4. Windows 使用 EDB `postgresql-18.6-1-windows-x64-binaries.zip`，仅建立项目内、
   loopback、一次性测试集群；不安装系统服务。
5. ZIP 的本次实际 SHA-256 固化为
   `fbe23da234ee31547bf8a36d29dfd81e82b849df2d2b78d2eecb43d360252f8c`，setup
   脚本下载后必须匹配才可解压。
6. 事件与配置 schema 从 Pydantic model 确定性生成并纳入 Registry 哈希验证。

## 官方证据

- PostgreSQL Windows 页面列出 18.6 为支持版本，并将高级用户 ZIP 指向 EDB：
  <https://www.postgresql.org/download/windows/>
- PostgreSQL 发布页同时列出 18.6 正式版与 19 Beta 3：
  <https://www.postgresql.org/docs/release/>
- EDB binary 页面列出 installer 18.6 的 Windows x86-64 archive：
  <https://www.enterprisedb.com/download-postgresql-binaries>
- SQLAlchemy 2.0 PostgreSQL dialect 支持 Psycopg 3 sync/async dialect：
  <https://docs.sqlalchemy.org/en/20/dialects/postgresql.html>
- Psycopg 3 安装文档声明支持 Windows、Python 3.10–3.14 和 PostgreSQL 10–18：
  <https://www.psycopg.org/psycopg3/docs/basic/install.html>
- 精确 Python 包版本由 PyPI JSON API 于 2026-08-31 核对，并由 `uv.lock` 固化。

## 后果

- 领域测试无需数据库，迁移/幂等测试必须运行真实 PostgreSQL。
- 343,808,005 byte ZIP 仅存在于被 Git 忽略的 `.tools/`，不会进入工件清单。
- trust 认证只允许用于 loopback 一次性测试集群，不得复用到任何共享环境。
- 未来切换托管 PostgreSQL 时保留 SQL/Event 契约，但必须新建 ADR 和兼容测试。

## 回退条件

若 EDB 不再提供受支持的 Windows archive，优先迁移到官方支持的本地容器或 WSL
PostgreSQL；禁止回退到 SQLite 或 Mock 后继续宣称 PostgreSQL 验收通过。
