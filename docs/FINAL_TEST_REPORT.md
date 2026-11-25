# 二期最终测试与部署验收报告

版本1.1.0已补充真正的Web预报工作台，接口回归共35项通过，并完成真实浏览器验收。最新工作台证据见[WORKBENCH.md](WORKBENCH.md)及evidence/workbench目录。下文保留1.0.0基线部署、物理计算与恢复验收记录。

作者陈一，日期2026年11月25日。应用1.0.0，Python3.12，Docker Desktop Linux，依赖requirements.lock，数据库schema2。算法与冻结参数沿用一期，不重新率定event4。

## 自动化测试

最终实际容器运行 **33 passed，0 failed，0 skipped，12.04秒**。第三方库15条弃用警告未隐藏。原始JUnit为[evidence/final-junit.xml](evidence/final-junit.xml)。相比阶段3–4增加畸形CSV未闭合引号、额外列、超长字段3项，均要求错误留档、禁止起报且接口不返回500。

覆盖四场完整Q黄金回归、每步守恒、初态/单位校验、无实测及部分缺测、非数输入、PNG、OpenAPI一致性、任务原子领取和租约、快照及参数不可覆盖、权限、产品门禁、方案灰度回滚、迁移、定时去重、通知失败重试/死信及幂等。本项目测试是引擎与业务集成测试，一期更细粒度的物理单测保留在一期工程。

## 四场真实HTTP结果

| 场次 | DC | RMSE m³/s | 洪峰相对误差 % | 峰现误差 h | 耗时 s |
|---|---:|---:|---:|---:|---:|
| event1 | 0.995811 | 4.860 | -2.479 | 0 | 1.049 |
| event2 | 0.993834 | 17.910 | 4.130 | 0 | 0.543 |
| event3 | 0.995024 | 12.937 | 0.365 | 0 | 1.070 |
| event4 | 0.994047 | 8.783 | -0.597 | 0 | 0.545 |

四场40时段Q均与一期黄金结果最大差0。event4 DC≥0.85。正负洪峰误差为有符号百分比；零峰时误差指6h离散时间步。原始证据[evidence/acceptance.json](evidence/acceptance.json)，四张图同目录。数据源为一期已检验数据，二期作为固定回归，不宣称新盲测。

## 业务和部署验收

| 项目 | 实测 | 证据 |
|---|---|---|
| 产品全流程 | 未复核/未签发被拒绝，最终发布，本地通知落库 | stage34-acceptance.json |
| 回放与方案 | 最大Q差0，激活回滚不影响原快照 | stage34-acceptance.json |
| 自动起报 | 约1.009秒触发完成，验证后停用 | stage34-acceptance.json |
| 自动质控 | 43.435秒入箱，manual_scan_called=false | stage34-acceptance.json |
| 12个有限任务 | 总2.06781秒，最大Q差0 | burst-acceptance.json |
| 真实进程重启 | scheduler/worker实际重启，计划只触发1次，旧快照摘要不变，Q一致，心跳新鲜 | restart-acceptance.json |
| 新卷首次部署 | 独立项目qinghe-final-clean，四容器健康，4场及UC流程通过 | clean-install目录 |
| 新卷自动质控 | 39.362秒内本地入箱，未手动扫描 | clean-install/stage34-acceptance.json |
| 独立卷恢复 | 16张表行数一致，25条任务快照摘要一致，integrity_check及foreign_key_check通过 | restore-acceptance.json |

证据均位于docs/evidence。旧环境升级前已备份，原4条任务保留；首次安装无历史数据时脚本跳过旧任务保留检查，迁移保留由单测和既有环境升级证据验证。重启测试保留命名卷，未删除用户现有数据。

性能测量仅代表本机有限窗口和小批次，不保证任意并发或长期负载。数据库故障、进程停机、任务积压可能影响180秒预报/5分钟通知目标，需监测心跳与队列。

## GitHub远程CI

最终运行[45559724012](https://github.com/yichen627/qinghe-flood-phase2/actions/runs/45559724012)成功，对应提交`5e10d8dae55808b1cb05f3aa529a3b7251600f3a`、分支`codex/final-delivery`。连接器以仓库所有者yichen627读取确认，原始精简元数据见[evidence/final-ci.json](evidence/final-ci.json)。检查包括pytest、锁定依赖安装、真实Compose和HTTP、12任务及实际后台服务重启。报告与文档收尾提交也会触发同一CI；最新状态以Actions页面为准。

## 明确限制

单机单API进程、单worker与单scheduler；角色密钥属于本机演示认证。模型注册不自动部署任意镜像，历史算法未部署时拒绝回放。通知仅投递本地值班收件箱，没有外部微信、邮件或短信。业务签发不是证书数字签名。SQLite在线backup及独立卷恢复命令见OPERATIONS.md。恢复演练仅验证备份的一致恢复，不代表跨机房灾备或零数据丢失承诺。
