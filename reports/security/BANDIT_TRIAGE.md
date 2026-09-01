# Bandit 精确豁免审查

P02/P04 保留以下逐行豁免，没有按测试编号全局关闭 Bandit 规则：

- `B404`/`B603`：只用于 `scripts/` 的固定本地工具调用。可执行文件由当前解释器或
  `shutil.which` 解析，参数由仓库常量构造，不启用 shell，也不接受用户拼接命令。
- `B310`：只用于固定 HTTPS 的 PostgreSQL 归档和 Apache Parquet 小样本。前者先做 URL
  全等检查并校验 SHA-256；后者固定 host/commit/path、限制响应不超过 1 MiB，并同时校验
  SHA-256 与 Git blob identity。
- `B608`：只用于 `point_in_time_join` 的 DuckDB 查询组装。所有可插值项都是先通过
  `^[A-Za-z_][A-Za-z0-9_]*$` allow-list 的标识符；值数据通过 Arrow 注册表传入，注入负向
  测试和 PIT 属性测试均通过。
- `B405`/`B314`：只用于 P04 RSS/Atom 标准库 XML 解析。输入固定限制为 1 MiB，解析前按
  大小写不敏感方式拒绝 `DOCTYPE` 与 `ENTITY` 声明，并有外部实体负向测试；未因该边界
  新增 XML 依赖。

Git blob SHA-1 显式使用 `usedforsecurity=False`，不用于安全判定。最终 Bandit 结果为
0 findings；`nosec` 只记录上述已验证边界。
