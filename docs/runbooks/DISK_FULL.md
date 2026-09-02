# Disk Full Runbook

## Detection and severity

- 生产文件系统利用率超过 85% 触发 `SEV1`，超过 95% 或写入失败升级 `SEV0`。
- 数据库、WAL、日志或备份写入失败时立即 `HALTED`。

## Immediate actions

1. 停止非关键研究、模型训练和缓存增长，确认数据库/WAL/账本仍可持久化。
2. 识别增长来源与保留策略；先移动已加密、已校验且可重建的非权威工件。
3. 扩容或挂载新卷，验证权限、空间、inode 和备份目标。

## Forbidden actions

- 禁止删除 PostgreSQL/WAL、权威账本、未复制备份或当前事件数据。
- 禁止使用递归通配删除或在未核验路径时执行清理。

## Evidence and recovery

- 保存磁盘/ inode 趋势、移除清单、哈希、扩容证据和数据库一致性检查。
- 空间低于 75%、写入稳定、恢复点可用且账本/对账通过后人工恢复。
