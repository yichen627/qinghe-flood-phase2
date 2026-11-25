# API契约与阶段边界

契约先于业务实现建立。API默认http://localhost:8000，模型服务http://model:8001（只在Compose网络内）。除health及OpenAPI文档外，请求带X-API-Key；演示值见README。模型服务用独立MODEL_API_KEY。

| 方法与路径 | 输入 | 成功响应 | 失败 |
|---|---|---|---|
| GET /health | 无 | 服务与数据库状态 | 503 |
| POST /events | name、csv_text、state0 | 201，event_id、valid、问题列表及去重标志 | 422结构错误、413过大 |
| GET /events | limit、offset | 事件摘要列表 | 401 |
| GET /events/{id} | ID | 元数据、质控问题、规范化记录 | 404 |
| GET /schemes | 无 | 方案和绑定参数版本、归档状态 | 401 |
| POST /forecasts | event_id、可空scheme_id | 202，QUEUED任务ID | 404事件/方案不存在，409数据或模型版本不合格 |
| GET /forecasts | limit、offset | 状态、时间、指标和错误摘要 | 401 |
| GET /forecasts/{id} | ID | 任务快照和结果 | 404 |
| GET /forecasts/{id}/plot.png | ID | image/png | 404、409未成功 |
| POST 模型服务 /simulate | inputs、params、state0、model_version | Q过程、终态、平衡残差等 | 401、409版本不符、422物理输入非法 |

状态码和字段的机器契约为docs/openapi.json及docs/model-openapi.json。校验错误采用FastAPI的detail结构；业务错误也用detail。接口不提供CSV文件路径参数，防止任意读服务端文件。

模型版本为engine源码SHA256。模型服务执行前必须核对版本；已有快照与当前源码不符时拒绝，不静默用新算法重算旧任务。版本登记和快照回放已在阶段3实现，任意历史镜像自动部署不在本轮范围。

## 阶段3–4契约扩展

阶段3–4已实现注册及回放。业务API版本0.4.0；全部精确字段和响应以openapi.json为准。未知密钥401、已识别但越权403、对象不存在404、状态冲突409、字段/物理输入非法422。

| 资源 | 路由与行为 | 写权限 |
|---|---|---|
| 模型 | GET/POST /models，登记元信息，不自动部署 | 管理员 |
| 参数 | GET/POST /parameter-sets，只新增版本 | 管理员 |
| 方案 | POST /schemes，DELETE /schemes/{id}归档，POST /schemes/{id}/activate，POST /schemes/rollback | 管理员 |
| 灰度 | GET /routing，POST /rollouts | 管理员写 |
| 回放 | POST /forecasts/{id}/replay，GET /forecasts/{id}/analysis.md | 预报员/管理员回放，角色均可读 |
| 草稿 | GET/POST /products，GET /products/{id} | 预报员/管理员创建 |
| 签发发布 | POST /products/{id}/review、/sign、/publish，GET /products/{id}/export.json | 值班长迁移 |
| 公开产品 | GET /published/{id}，未发布返回404 | 匿名只读 |
| 定时计划 | GET/POST /schedules，PATCH /schedules/{id}，GET /schedule-runs | 管理员写 |
| 巡检 | GET/POST /quality/scans，GET /alerts，POST /alerts/{id}/acknowledge | 管理员巡检，值班长/管理员确认 |
| 通知 | GET /notifications，POST /notifications/{id}/retry，GET /inbox | 值班长/管理员读，管理员重试 |
| 留痕运行 | GET /audit?entity_id=...，GET /runtime | 值班长/管理员审计，各角色读运行状态 |

完整步骤和body示例见STAGE34_GUIDE.md。模型服务独立密钥与三类业务角色密钥互不替代。
