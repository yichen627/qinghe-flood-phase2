# 最终交付验收清单

| 要求 | 实现位置 | 验证方式 |
|---|---|---|
| M1 数据入库与质控 | quality、repository、events API | CSV异常测试及demo.py坏数据拦截 |
| M2 预报流水线 | api→services→model_client→独立model_api，worker/scheduler | 四场真实HTTP回归、定时起报和重启恢复 |
| M3 结果管理 | forecasts、charts、analysis.md | 全过程线指标及event1–4 PNG |
| M4 方案管理 | governance_api、workflows、governance_store | 不可变参数集、绑定、稳定灰度、激活、回滚、归档保护 |
| M5 留痕 | 快照SQL保护及只追加audit | 回放差0、快照保护、迁移和重启前后摘要一致 |
| UC1 快速起报 | /events、/forecasts | 40时段场次约0.54–1.07秒，有限12任务约2.07秒 |
| UC2 产品复核签发 | /products | 越级与角色拒绝，DRAFT→REVIEWED→SIGNED→PUBLISHED |
| UC3 历史复盘 | replay、analysis.md、plot.png | 原快照新建任务、全Q对比和导出 |
| UC4 模型与方案治理 | /models、/parameter-sets、/schemes、/rollouts | 当前已部署算法版本校验，历史SHA不可用拒绝冒充 |
| UC5 自动巡检通知 | scheduler、outbox、inbox | 自动43.435秒内站内可见，无手动扫描 |
| 三层与HTTP模型独立 | app模块和Compose四服务 | API/应用/持久化适配分层，模型不依赖业务库 |
| 契约与配置 | docs/openapi.json、model-openapi.json、config、.env.example | OpenAPI一致性测试、参数和阈值外置 |
| 部署与CI | Dockerfile、compose.yaml、.github/workflows/ci.yml | 一命令启动、健康检查、GitHub远程CI |
| 文档和数据 | SRS、DATABASE、README、OPERATIONS、reports、data | 交付包及SHA256清单 |

本项目以个人形式完成，报告只列陈一。选做的专门Web工作台、集合预报和外部消息通道未交付；交互使用API文档，本地收件箱承担教学通知。是否接受个人形式与本地通知口径，以课程教师要求为准。event4是一期已检验的固定回归场，不重新宣称盲测。
