# P06 后续动作

1. 保持 P06 为 `in_progress`，等待全部工程完成后由项目业主明确发起统一验收；届时重新运行
   仍适用门禁并单独生成 `ACCEPTANCE.md`，不得倒填或伪造验收时间。
2. 本轮不开始 P07。若项目业主要求继续实施，必须先完整读取 P07 规格、建立需求追踪矩阵和
   P07 计划，再依据 ADR-0010 把 P06 作为“实现验证完成、正式验收延期”加入延期队列。
3. 若接入真实历史费率、funding、borrow、保证金或 instrument rule，只能使用可归档的官方
   来源和精确生效区间；缺失数据继续失败关闭，不用当前规则倒灌历史。
4. 若需要场所级强平、保险基金、ADL 或 queue-aware 撮合，新增独立版本化契约、Golden Case、
   压力回放和 superseding ADR；不得悄悄提高现有三档成交模型的精度声明。
5. 将开发机 Node 对齐 24.20.0，并在 Nautilus/Pandas 上游稳定兼容后处理
   `Timestamp.utcnow` 弃用警告。
6. 继续保持 `LIVE_TRADING` 锁；任何未来账户级工作都需要单独授权、最小权限和秘密库方案，
   不得在对话、仓库、报告或 fixture 中传递密码、Cookie、验证码或 API Secret。
