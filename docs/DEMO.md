# 二期演示与验收步骤

## 自动演示

从仓库根目录执行，默认端口8000；服务全部健康后再运行。

```powershell
docker compose up -d --build --wait api worker
docker compose run --rm --no-deps test
docker compose exec -T api python scripts/demo.py
docker compose exec -T api python scripts/demo_workflows.py
docker compose exec -T api python scripts/final_probe.py burst
docker compose exec -T api python scripts/final_probe.py prepare-restart
docker compose restart scheduler worker
docker compose exec -T api python scripts/final_probe.py verify-restart
docker compose cp api:/app/artifacts/. ./artifacts
```

约1至3分钟，首次下载构建时间另计。演示创建数据、任务、产品及审计；定时计划演示完成后自动停用。若手动中断重启验收，执行final_probe.py cleanup停用它创建的计划。不要并行运行多份演示以免方案切换互相干扰。

demo.py对4场洪水独立初态进行真实HTTP预报，逐时段比较一期黄金Q，导出4张PNG，验证坏数据不能起报。demo_workflows.py完成方案切换回滚、原快照回放、产品复核签发发布、定时起报及自动质控通知。自动质控不调用手动扫描端点；首次安装没有历史阶段2记录时跳过旧记录保留检查，迁移保留另有单元测试及已有环境升级证据。

burst只验证12个有限任务的批量耗时与正确性，不代表任意并发负载SLA。restart在宿主实际重启worker/scheduler后验证计划只触发一次、旧快照不变、结果一致和心跳恢复。

## 课堂操作顺序

1. 打开/docs，预报员密钥qinghe-local-demo导入CSV并提交预报，查询任务、指标和plot.png；展示ERROR数据已入库但禁止起报。
2. 管理员密钥qinghe-admin-demo查询/models、/parameter-sets和/routing，演示新方案绑定、激活与回滚；历史任务快照不变。
3. 预报员生成/products草稿，直接发布应409；切换值班长qinghe-reviewer-demo依次review、sign、publish。仅PUBLISHED产品可匿名查询/published/{id}。
4. 历史任务replay后展示最大Q差为0；analysis.md导出DC、RMSE和峰值误差。
5. 查询/schedules、/schedule-runs、/alerts、/notifications及/inbox，展示自动触发及本地通知；查询/audit对应操作链。
6. 展示Git历史、GitHub Actions绿色运行、SRS、OpenAPI、运维手册及个人总结报告。

接口字段以docs/openapi.json为准；完整人工请求示例见STAGE34_GUIDE.md。模型注册只登记元信息，不自动部署其他算法；教学角色密钥和业务签发记录不等同正式身份系统或密码学签名。
