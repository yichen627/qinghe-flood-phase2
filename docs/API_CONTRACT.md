# API契约与阶段边界

契约先于业务实现建立。API默认http://localhost:8000，模型服务http://model:8001（只在Compose网络内）。除health及OpenAPI文档外，请求带X-API-Key；演示值见README。模型服务用独立MODEL_API_KEY。

| 方法与路径 | 输入 | 成功响应 | 失败 |
|---|---|---|---|
| GET /health | 无 | 服务与数据库状态 | 503 |
| POST /events | name、csv_text、state0 | 201，event_id、valid、问题列表及去重标志 | 422结构错误、413过大 |
| GET /events | limit、offset | 事件摘要列表 | 401 |
| GET /events/{id} | ID | 元数据、质控问题、规范化记录 | 404 |
| GET /schemes | 无 | 内置只读冻结方案 | 401 |
| POST /forecasts | event_id、scheme_id | 202，QUEUED任务ID | 404事件不存在，422未知方案，409数据不合格 |
| GET /forecasts | limit、offset | 状态、时间、指标和错误摘要 | 401 |
| GET /forecasts/{id} | ID | 任务快照和结果 | 404 |
| GET /forecasts/{id}/plot.png | ID | image/png | 404、409未成功 |
| POST 模型服务 /simulate | inputs、params、state0、model_version | Q过程、终态、平衡残差等 | 401、409版本不符、422物理输入非法 |

状态码和字段的机器契约为docs/openapi.json及docs/model-openapi.json。校验错误采用FastAPI的detail结构；业务错误也用detail。接口不提供CSV文件路径参数，防止任意读服务端文件。

模型版本为engine源码SHA256。模型服务执行前必须核对版本；已有快照与当前源码不符时拒绝，不静默用新算法重算旧任务。完整版本注册和回放计划后续阶段完成。
