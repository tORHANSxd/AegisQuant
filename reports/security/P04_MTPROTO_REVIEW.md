# P04 MTProto 安全评审结论

状态：`disabled / awaiting independent security review`。

P04 不实现、不启用也不模拟 Telegram MTProto 登录。原因是 MTProto 研究账号需要人工登录、会话文件加密、专用低权限账号、频道 allowlist、会话撤销和登录审计；这些条件尚未由项目业主逐项批准。

当前仅实现 Telegram Bot API 的离线契约与授权频道解析。禁止私聊、未授权群组、明文验证码、Cookie、密码、Bot Token 和 session 文件进入项目。
