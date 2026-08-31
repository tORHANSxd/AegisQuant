# Bandit 精确豁免审查

P00 对 Bandit `B404`/`B603` 的豁免仅限 `scripts/` 中的固定本地工具调用：可执行文件由
当前解释器或 `shutil.which` 解析，参数由仓库常量构造，均未启用 shell，也不接受用户
拼接命令。每个调用点均有对应 `nosec` 理由，新增调用仍会被 Bandit 阻断。

`security_scan.py` 的 `secret_store_access_performed: False` 是机器审计结果布尔值，不是
密码或秘密，故对该行精确豁免 `B105`。没有按测试编号全局关闭 Bandit 规则。
