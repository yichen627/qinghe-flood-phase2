# 青河洪水预报系统运行维护手册

适用版本1.0.0，单机Docker Desktop Linux容器。入口仅绑定127.0.0.1，默认API端口8000。模型8001仅在Compose网络内开放。

## 首次部署

```powershell
git clone --branch codex/final-delivery git@github.com:yichen627/qinghe-flood-phase2.git
cd qinghe-flood-phase2
docker compose up -d --build --wait api worker
docker compose ps
```

worker的依赖会自动启动model、api、scheduler。访问 http://localhost:8000/docs 。镜像固定Python基础镜像摘要，requirements.lock锁定全部Python依赖；首次构建需要联网下载。API_PORT环境变量可更改宿主端口。不要用python -O关闭水量平衡断言。

## 配置与角色

复制.env.example为.env后可修改API_KEY、REVIEWER_API_KEY、ADMIN_API_KEY、MODEL_API_KEY，四者必须不同。默认值仅供本机教学。预报员创建任务和草稿；值班长复核、签发、发布和确认告警；管理员管理方案、调度和死信重试。管理员不能代替值班长签发。密钥与数据库不提交Git。

config/settings.json管理单位、泰森权重、质控阈值、轮询、HTTP超时、租约、重试及回放容差。修改后重建服务。不要修改一期冻结配置以追逐检验场指标。时间计划使用带偏移的ISO8601时间，数据库归一到UTC；无偏移课程CSV解释为Asia/Shanghai。

## 日常检查

```powershell
docker compose ps
docker compose logs --tail 100 api model worker scheduler
docker compose exec -T api python scripts/demo.py
docker compose exec -T api python scripts/demo_workflows.py
docker compose cp api:/app/artifacts/. ./artifacts
```

GET /health确认应用与数据库；GET /runtime确认worker和scheduler心跳。运行演示会新增记录，计划验证结束停用，方案恢复至演示前活动方案。质控自动通知最多需等待一次60秒巡检周期。GET /notifications查出站状态，GET /inbox查本地实际收件记录。外部邮件、微信与短信未接入。

QUEUED不动先查worker；FAILED查任务error及模型SHA。模型HTTP超时30秒；失联RUNNING超过120秒租约转FAILED，保留原始记录，可显式回放创建新任务。暂停时错过多个计划周期只合并补触发一次。worker/scheduler默认心跳阈值180秒，不健康时先查日志，不要清空数据库。

## 停止和升级

```powershell
docker compose stop worker scheduler
docker compose stop api model
docker compose up -d --build --wait api worker
```

同一Compose项目重启保留命名卷。docker compose down保留卷；不要用down -v进行常规重启。更新前先备份；schema1到2自动事务迁移，旧记录和快照保留。旧代码不能直接配新schema回滚，应恢复配套备份到独立卷再验证。当前按单API进程、单worker和单scheduler部署，不做水平扩容。

## 在线备份和完整性检查

在仓库目录执行，示例备份为/var/qinghe/manual-backup.db；同名备份会更新，重要历史备份应另取名称。

```powershell
docker compose exec -T api python -c "import sqlite3; a=sqlite3.connect('/var/qinghe/system.db'); b=sqlite3.connect('/var/qinghe/manual-backup.db'); a.backup(b); print(b.execute('PRAGMA integrity_check').fetchone()[0]); b.close(); a.close()"
docker compose cp api:/var/qinghe/manual-backup.db ./manual-backup.db
```

必须看到ok。使用SQLite backup API形成一致快照，不能只复制运行中主db而遗漏WAL。备份包含业务输入、产品和审计，应保存在受控本机目录；不要纳入Git或交付包。

## 独立卷恢复演练

以下命令把宿主备份恢复到新项目卷，不覆盖原系统；restore项目API使用18001端口。先确认主系统目录中的manual-backup.db就是要恢复的备份。恢复目的库已存在时命令主动失败。

```powershell
$env:API_PORT='18001'
docker compose -p qinghe-restore run --rm --no-deps -v "${PWD}:/backup:ro" api python -c "import pathlib,sqlite3; p=pathlib.Path('/var/qinghe/system.db'); assert not p.exists(), 'Destination already exists'; a=sqlite3.connect('file:/backup/manual-backup.db?mode=ro&immutable=1',uri=True); assert a.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; b=sqlite3.connect(p); a.backup(b); print(b.execute('PRAGMA integrity_check').fetchone()[0]); b.close(); a.close()"
docker compose -p qinghe-restore up -d --wait api worker
```

immutable=1仅用于backup API产出的、当前无人写入的独立备份，使WAL格式备份可在只读目录打开；不能对活动数据库使用。脚本scripts/verify_restore.py可进一步核对全部表行数、外键和任务快照摘要。

在 http://localhost:18001/docs 查询原任务、快照、产品和审计，确认后停止恢复项目并恢复端口变量：

```powershell
docker compose -p qinghe-restore down
Remove-Item Env:API_PORT
```

down保留恢复卷便于复核。若恢复库中有启用计划，scheduler启动后会执行到期计划；演练前应停用计划或仅启动api/model检查历史数据。正式替换原库需先停止所有写入进程，保留旧卷及原备份，再切换经验证的卷；不要直接覆盖活动数据库。

## 验收与交付

完整操作见DEMO.md，指标和可复核证据见FINAL_TEST_REPORT.md及evidence目录。源代码包不包含运行数据库、.env和缓存；Git bundle保存完整提交历史。交付包由scripts/package_delivery.py生成，附SHA256清单。报告单独保留可编辑Word及PDF。
