# 阶段3与4升级和运行维护

## 已有环境升级

不要删除持久卷。先在运行中的API容器使用SQLite在线备份，再更新代码并启动：

```powershell
docker compose exec -T api python -c "import sqlite3; a=sqlite3.connect('/var/qinghe/system.db'); b=sqlite3.connect('/var/qinghe/pre-stage34.db'); a.backup(b); b.close(); a.close()"
docker compose up -d --build --wait api worker
```

本轮实际升级前已做pre-stage34.db备份。schema1→2创建新表和约束，不清空events/forecasts；迁移事务失败会回滚。新API启动完成迁移后，scheduler和worker才按依赖启动。命名卷不进Git，备份文件也不提交仓库。

代码回滚不能直接把旧代码运行在新schema上。需要回退时先停止API/worker/scheduler，保留当前数据库和WAL，按备份恢复至独立卷，再配套启动旧版本；不得把恢复旧库当成正常应用升级方式。

## 状态和排查

```powershell
docker compose ps
docker compose logs --tail 100 api model worker scheduler
docker compose exec -T api python scripts/demo_workflows.py
docker compose cp api:/app/artifacts/. ./artifacts
```

API和model用HTTP健康检查，worker/scheduler用持久心跳检查。默认心跳超过180秒或最近周期出错为不健康；长任务HTTP超时30秒，worker停止宽限40秒。部署只运行一个worker和一个scheduler。

QUEUED长期不动看worker；计划没触发看enabled、next_run_at时区和scheduler心跳；FAILED看error，可通过replay显式新建任务；旧模型SHA不可用需先部署对应镜像。通知检查outbox状态，FAILED使用管理员retry；不要删除通知表以清空失败计数。

本地收件箱投递在同一个数据库事务内插入inbox并标记DELIVERED，outbox_id唯一约束保证幂等。投递失败使用保存点回滚该次投递，保留失败次数与退避时间；SQLite本身完全不可写时错误只能留在容器日志，恢复数据库后再继续处理。

## 配置和范围

API_KEY、REVIEWER_API_KEY、ADMIN_API_KEY及MODEL_API_KEY必须不同。配置改动后重新创建服务。业务阈值、轮询、质控周期、通知重试和回放容差在config/settings.json，质控周期和轮询之和不得超过300秒。默认只为ERROR产生质控通知，面雨量WARNING仍保存可查。

计划使用UTC时间持久化，课程输入时段保留Asia/Shanghai偏移。暂停期间的多个错过周期合并成一次，不补齐整段历史起报。API绑定localhost，角色密钥是教学级认证，没有SSO、密码恢复或真实人员账号管理。

外部微信、邮件和短信均未接入；本地值班收件箱是可验收的演示通知通道。若课程要求真实外部推送，应在明确接收人、授权和凭据后另行接入，不能把本地投递宣称为已送达外部群。
