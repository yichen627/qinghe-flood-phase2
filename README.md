# 青河流域洪水预报系统 二期阶段一与二

陈一 · 河海大学计算机与软件学院 · 软件工程24级1班 · 2406050103 · 个人完成。

本次仅交付需求契约与预报链路，不是二期全部成品。已有：六站CSV入库、即时质控、独立模型HTTP服务、持久化起报任务、结果/指标查询与PNG对比图。未做：复核签发发布、方案增删切换、定时起报/巡检通知、完整回放和操作审计。API文档页是操作入口，不是选做的Web工作台。

## 一条命令启动

安装并启动Docker Desktop（Linux容器），克隆后进入仓库根目录：

```powershell
docker compose up -d --build --wait api worker
```

打开 http://localhost:8000/docs 。每个业务接口的 `x-api-key` 填 `qinghe-local-demo`。模型只在容器网络8001端口提供服务，没有对宿主机开放。API仅绑定127.0.0.1。内置密钥适合个人本机教学；如需更换，复制`.env.example`为`.env`并修改API_KEY/MODEL_API_KEY，重新创建服务。

## 一键演示与验收

```powershell
docker compose exec -T api python scripts/demo.py
docker compose cp api:/app/artifacts/. ./artifacts
docker compose run --rm --no-deps test
```

演示真实调用API→SQLite→独立worker→模型HTTP服务，完成4场黄金事件和坏数据拦截，保存4张对比图、acceptance.json。首次可能需要等待下载镜像。命名卷持久化输入和结果；停止用`docker compose down`，不要为重启而删除卷。

## 手动使用

1. POST `/events`，JSON提供name、csv_text和该场state0。CSV列见data/events，初态见data/golden中对应文件的state0。不可用同一初态替代四场。
2. 查询返回的valid及issues。ERROR数据保留入库但不允许起报；WARNING使用泰森复算值继续，观测Q可缺失。
3. GET `/schemes`读取一期冻结参数；本阶段只支持只读`phase1-frozen-v1`。
4. POST `/forecasts`，body为`{"event_id":"上一步ID","scheme_id":"phase1-frozen-v1"}`，返回202和任务ID。
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
config/                    冻结参数和全部业务阈值
data/events/               四场CSV
data/golden/               独立初态及一期已检验的固定输出
data/invalid/              负值 缺测 乱序样本
docs/                      SRS API 数据库设计 验收说明
tests/                     黄金回归 接口及异常测试
scripts/                   OpenAPI导出 真实HTTP演示
```

模型不依赖数据库或业务API；应用不直接调用simulate，只经ModelClient HTTP调用。引擎源代码版本摘要统一换行符，Windows和Linux一致。每次任务保存完整参数、初态、输入快照和摘要，模型HTTP执行前核对算法版本，防止静默用不同算法执行快照。参数不能通过本阶段接口修改。

## 本地开发与测试

Python3.12推荐，用独立虚拟环境安装requirements.txt，再执行：

```powershell
python scripts/export_openapi.py
python -m pytest -q
```

无Docker时可在三个终端分别运行：

```powershell
uvicorn app.model_api:app --host 127.0.0.1 --port 8001
uvicorn app.api:app --host 127.0.0.1 --port 8000
python -m app.worker
```

模型绘图使用matplotlib无界面后端，无需显示器。模型所有每步水量平衡断言保留，不得使用`python -O`。数据库默认var/system.db。没有重新率定，event4在一期已经开封，仅用于固定回归而非新盲测。

API契约以requirements.txt锁定环境为准；使用本机其他FastAPI/Pydantic版本可能生成不同JSON。不要用未锁定版本导出的文档覆盖契约。推荐直接在容器运行测试。

## 故障排查与当前限制

`docker compose ps`检查状态；`docker compose logs --tail 100 api model worker`查看日志。QUEUED长期不变先看worker；FAILED看error及模型版本。模型HTTP超时按配置30秒转FAILED，不伪装成功；失联RUNNING在120秒租约后转FAILED，新建任务可显式重算。单worker部署，不要横向扩展；目前没有心跳与优雅重试完整策略。

数据库为单机SQLite WAL，任务领取事务与HTTP执行分离。API单进程，演示访问密钥不是完整用户角色系统。健康检查覆盖API数据库和模型服务；worker是否工作以demo及任务推进为准。正式运维手册及身份权限在后续阶段补齐。

参数及阈值来自config；schema版本1。未来schema修改应提供迁移，不可删库重建充当升级。
