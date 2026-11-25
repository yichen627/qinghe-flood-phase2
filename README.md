# 青河流域洪水预报系统 二期阶段一至四

陈一 · 河海大学计算机与软件学院 · 软件工程24级1班 · 2406050103 · 个人完成。

目前完成阶段1–4：六站CSV入库与即时质控、独立模型HTTP服务、持久化预报、结果/指标与PNG、参数版本和方案管理、复核签发发布、快照回放、操作审计、定时起报、自动质控与本地值班通知。尚未宣称阶段5–6整体部署验收和正式报告包全部完成。API文档页是操作入口，不是选做的Web工作台。

## 一条命令启动

安装并启动Docker Desktop（Linux容器），克隆后进入仓库根目录：

```powershell
docker compose up -d --build --wait api worker
```

打开 http://localhost:8000/docs 。`x-api-key`按角色填写：预报员`qinghe-local-demo`、值班长`qinghe-reviewer-demo`、管理员`qinghe-admin-demo`。模型使用独立MODEL_API_KEY，只在容器网络8001端口提供服务。API仅绑定127.0.0.1。内置密钥适合个人本机教学；可复制`.env.example`为`.env`更换四类密钥，不能设置为相同值。

## 一键演示与验收

```powershell
docker compose exec -T api python scripts/demo.py
docker compose exec -T api python scripts/demo_workflows.py
docker compose cp api:/app/artifacts/. ./artifacts
docker compose run --rm --no-deps test
```

第一个演示完成4场黄金回归与坏数据拦截；第二个完成方案切换回滚、原快照回放、产品签发发布、定时起报及自动巡检通知，约需等待一次60秒巡检周期，写stage34-acceptance.json。通知只写本地值班收件箱，不连接微信群或邮件；演示定时任务验证后会停用。演示会新增记录，切换后恢复原活动方案。

现有api、model、worker、scheduler四个容器，原启动命令通过依赖自动拉起scheduler。持久卷中的schema1自动迁移至schema2，不清空旧记录。停止用`docker compose down`，不要为重启删除卷。升级与备份见docs/OPERATIONS_STAGE34.md。

## 手动使用

1. POST `/events`，JSON提供name、csv_text和该场state0。CSV列见data/events，初态见data/golden中对应文件的state0。不可用同一初态替代四场。
2. 查询返回的valid及issues。ERROR数据保留入库但不允许起报；WARNING使用泰森复算值继续，观测Q可缺失。
3. GET `/schemes`查看方案；内置`phase1-frozen-v1`保留。新参数只能通过POST `/parameter-sets`创建不可变版本，再POST `/schemes`绑定模型。管理员可激活、灰度、回滚或归档方案，详见docs/STAGE34_GUIDE.md。
4. POST `/forecasts`，body为`{"event_id":"上一步ID","scheme_id":"phase1-frozen-v1"}`，返回202和任务ID；省略scheme_id时使用当前活动/灰度规则。
5. GET `/forecasts/{id}`轮询QUEUED→RUNNING→SUCCEEDED/FAILED。成功时可查完整快照、Q、DC/RMSE和峰值指标。
6. GET `/forecasts/{id}/plot.png`获取蓝色实测/橙色模拟图；未成功返回409。GET `/events`及`/forecasts`支持limit/offset分页。

没有实测Q的未来预报仍可计算，指标为null。部分实测缺测时只用有效时段计算DC/RMSE，峰值指标为null，避免压缩时间索引造成错误峰时。零方差DC为null。时间未带偏移时解释为Asia/Shanghai；课程6h、mm、m³/s和U=92.6严格检查。

## 分层与文件

```text
app/api.py                 接口层
app/contracts.py           API结构与字段校验
app/services.py            应用编排
app/repository.py          SQLite存储与原子任务领取
app/quality.py             数据领域校验
app/model_client.py        HTTP适配器
app/model_api.py            独立模型服务
app/engine.py               一期纯函数引擎 原样复用
app/worker.py               单worker持久任务执行
app/governance_api.py       角色 方案 产品 回放 调度 审计接口
app/workflows.py            阶段3–4应用业务
app/governance_store.py     原子写入 审计与通知事务
app/migrations.py           schema1到2原地迁移
app/scheduler.py            独立定时起报 质控和站内通知
app/runtime_check.py        后台进程心跳健康检查
config/                    冻结参数和全部业务阈值
data/events/               四场CSV
data/golden/               独立初态及一期已检验的固定输出
data/invalid/              负值 缺测 乱序样本
docs/                      SRS API 数据库设计 验收说明
tests/                     黄金回归 接口及异常测试
scripts/                   OpenAPI导出 真实HTTP演示
```

模型不依赖数据库或业务API；应用经ModelClient HTTP调用simulate。引擎源码摘要统一换行符，Windows和Linux一致。每次任务保存完整参数、初态、输入快照和摘要，执行前核对算法版本。参数版本不可覆盖，管理接口只能创建新版本。回放使用原任务快照，历史算法未部署时明确拒绝，不用新模型冒充复现。

## 本地开发与测试

Python3.12推荐，用独立虚拟环境安装requirements.txt，再执行：

```powershell
python scripts/export_openapi.py
python -m pytest -q
```

无Docker时可在四个终端分别运行：

```powershell
uvicorn app.model_api:app --host 127.0.0.1 --port 8001
uvicorn app.api:app --host 127.0.0.1 --port 8000
python -m app.worker
python -m app.scheduler
```

模型绘图使用matplotlib无界面后端，无需显示器。模型所有每步水量平衡断言保留，不得使用`python -O`。数据库默认var/system.db。没有重新率定，event4在一期已经开封，仅用于固定回归而非新盲测。

API契约以requirements.txt锁定环境为准；使用本机其他FastAPI/Pydantic版本可能生成不同JSON。不要用未锁定版本导出的文档覆盖契约。推荐直接在容器运行测试。

## 故障排查与当前限制

`docker compose ps`检查状态；`docker compose logs --tail 100 api model worker scheduler`看日志。QUEUED长期不变先看worker；FAILED看error及版本，POST `/forecasts/{id}/replay`可用原快照新建任务。HTTP超时30秒转FAILED，失联RUNNING在120秒租约后转FAILED并通知。任务不静默自动重试。worker和scheduler都有数据库心跳及容器健康检查，GET `/runtime`可查看滞后。

数据库为单机SQLite WAL，HTTP调用不持有写事务。演示使用三类角色密钥做操作授权，不是多用户登录平台，不提供密码找回或SSO。当前只支持一个已部署算法，注册其他镜像元信息不会自动下载部署；历史算法需要先重新部署才可回放。通知采用事务出站队列、退避重试、死信和本地值班收件箱；未连接外部群聊/邮件。

参数及阈值来自config；schema版本2。升级保留旧数据与快照，不补造升级前操作记录。测试及运行证据见docs/TEST_REPORT_STAGE34.md，后续正式总结报告仍待阶段6整理。
