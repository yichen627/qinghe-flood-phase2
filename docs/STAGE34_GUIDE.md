# 阶段3与4操作指南

入口 http://localhost:8000/docs ，每个请求的x-api-key按角色填写。使用仓库默认教学配置时：

| 角色 | 密钥 | 权限 |
|---|---|---|
| 预报员 | qinghe-local-demo | 导入、起报、回放、草稿、读取业务结果 |
| 值班长 | qinghe-reviewer-demo | 读取、复核、签发、发布、值班消息、告警确认、审计 |
| 管理员 | qinghe-admin-demo | 读取、导入起报、模型/参数/方案管理、调度、巡检、死信重试、审计 |

管理员不能签发，预报员不能管理参数或发布。角色从密钥确定，不从body或任意actor头接受。默认密钥是本机演示凭据，不是正式用户账户；请勿把API直接暴露公网。

## 参数和方案

1. GET `/models`查看当前模型SHA256。POST `/models`登记新版本元信息，body含name/version/image_ref；该操作不会自动部署镜像。
2. POST `/parameter-sets`，body为`{"name":"新版本名称","params":完整参数对象}`。复制GET `/schemes`内params可创建等效版本，演示时无需再次调参。
3. POST `/schemes`，body为`{"name":"方案名","parameter_id":"上一步ID","model_version":"已登记SHA256"}`。
4. POST `/schemes/{id}/activate`激活；POST `/schemes/rollback`回到上一活动方案。GET `/routing`查询结果。
5. POST `/rollouts`，body为`{"scheme_id":"候选方案ID","percentage":20}`。不指定方案的新预报按事件指纹的稳定分桶选择候选方案；同事件重复请求落在同一桶。0关闭灰度，100全部使用候选方案。显式scheme_id绕过分桶。
6. DELETE `/schemes/{id}`为软归档。内置、活动、候选、待回滚及启用计划引用的方案不能归档。旧任务仍可查询/回放，参数版本不能改写或删除。

只能激活当前model服务实际部署的算法SHA。若需升级算法，应先保留旧镜像、部署新镜像和登记版本；本轮没有自动管理历史多镜像的功能。切换方案时还会在起报时校验该场初态与容量是否兼容。

## 原快照回放

对SUCCEEDED或FAILED任务POST `/forecasts/{id}/replay`，返回新任务ID。新任务直接复制原模型请求，不读取现行事件、当前参数或活动方案。成功后result.replay_comparison显示与原成功结果的最大Q差和容差判断。历史算法未部署返回409，不用新算法冒充历史重算。

GET `/forecasts/{id}/analysis.md`可下载误差摘要；峰误差为有符号百分数，峰时误差单位小时。不得利用event4的分析继续调参。

## 产品复核与签发

1. 预报员POST `/products`：`{"forecast_id":"成功任务ID","title":"产品标题"}`。创建DRAFT，内容和SHA256不可再修改；需要修改应新建草稿。
2. 值班长POST `/products/{id}/review`：`{"note":"核对输入、过程线及指标后的意见"}`，转REVIEWED。
3. 值班长POST `/products/{id}/sign`，转SIGNED并记录签发角色与UTC时刻。
4. GET `/products/{id}/export.json`导出签发产品；DRAFT/REVIEWED禁止正式导出。
5. 值班长POST `/products/{id}/publish`，转PUBLISHED且同事务创建站内值班通知。匿名GET `/published/{id}`只有这时才返回产品，之前一直404。

重复、越级和错误角色操作分别返回409或403。这里是业务签发和内容摘要，不是基于证书的密码学数字签名，也没有连接真实微信群或邮箱。

## 自动起报和质控

管理员POST `/schedules`，例：`{"name":"每小时预报","event_id":"事件ID","scheme_id":null,"interval_seconds":3600}`。省略next_run_at立即到期；也可填写带时区ISO时间。scheme_id为空在触发时选当前方案，指定则固定方案。PATCH `/schedules/{id}` body `{"enabled":false}`停用，历史不删除。

GET `/schedule-runs`查每次触发及错误。后台每秒检查到期计划，重启后依照数据库恢复；错过的周期合并触发一次。若新方案不兼容初态，保存失败触发和通知，不静默丢计划。

独立scheduler默认每60秒重读原始入库CSV做质控，ERROR变化按事件和问题摘要去重告警。GET `/alerts`查询，POST `/alerts/{id}/acknowledge`确认。管理员也能POST `/quality/scans`手动巡检，但真实自动验收脚本不调用此接口。

GET `/inbox`是本地值班收件箱，GET `/notifications`查看出站投递状态、次数和错误。默认最多尝试3次，失败间隔5秒，到上限FAILED，管理员POST `/notifications/{id}/retry`显式重试。DELIVERED不可再次投递。数据规模较大或后台进程故障时5分钟目标可能无法保证，需看心跳、日志及队列滞后。

## 留痕和运行状态

GET `/audit?entity_id=对象ID`查对应操作链，审计表SQL层禁止更新删除。GET `/runtime`查worker/scheduler心跳与stale标记；容器也按同一状态做健康检查。升级前的阶段2数据和快照保留，但不会补造当时不存在的身份审计。
