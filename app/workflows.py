"""方案、回放、产品与调度的应用层业务；不在接口层写SQL。"""
from datetime import datetime,timezone,timedelta
import json
import math
from . import services
from .engine import check_params
from .quality import inspect_csv
from .settings import digest,model_version
from .governance_store import StoreConflict,timestamp


def require(repo,table,identifier):
    """不存在统一映射404。"""
    row = repo.get(table,identifier)
    if row is None:
        raise services.BusinessError(404,'Resource not found')
    return row


def decoded(row):
    """把数据库JSON列解码为API对象，保留其他元数据。"""
    result = {}
    for key,value in row.items():
        result[key[:-5] if key.endswith('_json') else key] = json.loads(value) if key.endswith('_json') and value else value
    return result


def create_parameters(repo,body,actor):
    """验证完整参数的物理合法性后创建新版本，不修改一期文件。"""
    try:
        check_params(body.params)
        digest(body.params)
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        raise services.BusinessError(422,str(exc)) from exc
    identifier = repo.registry_create('parameter',body.name,
                                      {'params':body.params,'sha256':digest(body.params)},actor)
    return decoded(repo.get('parameter_sets',identifier))


def create_scheme(repo,body,actor):
    """绑定已有模型和不可变参数版本。"""
    require(repo,'parameter_sets',body.parameter_id)
    require(repo,'model_versions',body.model_version)
    identifier = repo.scheme_create(body.name,body.parameter_id,body.model_version,actor)
    return decoded(repo.get('schemes',identifier))


def replay(repo,settings,identifier,actor):
    """使用原任务快照，不读取当前事件、当前参数或激活方案。"""
    original = require(repo,'forecasts',identifier)
    if original['status'] not in ('SUCCEEDED','FAILED'):
        raise services.BusinessError(409,'运行中任务不能回放')
    snapshot = json.loads(original['snapshot_json'])
    if digest(snapshot['model_request']) != snapshot['request_sha256']:
        raise services.BusinessError(409,'原任务快照摘要不符')
    if snapshot['model_request']['model_version'] != model_version():
        raise services.BusinessError(409,'历史算法未部署，请先部署对应模型镜像')
    snapshot['replay_of'] = identifier
    return services.task_summary(repo.queue(original['event_id'],original['scheme_id'],snapshot,actor))


def draft_product(repo,body,actor):
    """从成功任务冻结发布内容，与以后参数切换隔离。"""
    task = require(repo,'forecasts',body.forecast_id)
    if task['status'] != 'SUCCEEDED':
        raise services.BusinessError(409,'只能对成功预报建立产品')
    snapshot,result = json.loads(task['snapshot_json']),json.loads(task['result_json'])
    content = {'title':body.title,'forecast_id':task['id'],'event_name':snapshot['event_name'],
               'scheme_id':task['scheme_id'],'params_sha256':snapshot['params_sha256'],
               'model_version':snapshot['model_request']['model_version'],'metrics':result['metrics'],
               'times':[r['time'] for r in snapshot['event_rows']],'Q':result['simulation']['Q'],
               'unit':'m³/s','time_step_hours':snapshot['model_request']['params']['dt_h']}
    identifier = repo.product_create(task['id'],body.title,content,actor)
    return decoded(repo.get('products',identifier))


def product(repo,identifier,public=False):
    """发布前禁止公开；每次导出核对不可变产品摘要。"""
    row = require(repo,'products',identifier)
    if public and row['status']!='PUBLISHED':
        raise services.BusinessError(404,'Published product not found')
    if digest(json.loads(row['content_json'])) != row['content_sha256']:
        raise services.BusinessError(409,'产品内容摘要不符')
    return decoded(row)


def create_schedule(repo,settings,body,actor):
    """创建可重启恢复的间隔计划，拒绝无时区的绝对起报时间。"""
    if body.interval_seconds<settings.rules['schedule_min_interval_seconds']:
        raise services.BusinessError(422,'计划间隔小于配置下限')
    services.build_snapshot(repo,settings,body.event_id,body.scheme_id)
    try:
        moment = datetime.fromisoformat(body.next_run_at) if body.next_run_at else datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise ValueError('next_run_at必须包含时区')
        due = moment.astimezone(timezone.utc).isoformat()
    except ValueError as exc:
        raise services.BusinessError(422,str(exc)) from exc
    identifier = repo.schedule_create(body,due,actor)
    return decoded(repo.get('schedules',identifier))


def scheduler_tick(repo,settings,current=None):
    """原子提交到期计划，暂停期间错过的多个周期合并为一次。"""
    current = current or datetime.now(timezone.utc)
    count = 0
    for schedule in repo.due_schedules(settings.rules['schedule_batch_size'],current.isoformat()):
        snapshot,error,selected = None,None,schedule['scheme_id']
        try:
            snapshot = services.build_snapshot(repo,settings,schedule['event_id'],schedule['scheme_id'])
            snapshot['schedule_id'] = schedule['id']
            snapshot['scheduled_for'] = schedule['next_run_at']
            selected = snapshot['source']
        except Exception as exc:
            error = f'{type(exc).__name__}: {str(exc)[:300]}'
        due = datetime.fromisoformat(schedule['next_run_at'])
        steps = max(1,math.floor((current-due).total_seconds()/schedule['interval_seconds'])+1)
        next_due = (due+timedelta(seconds=steps*schedule['interval_seconds'])).isoformat()
        if repo.commit_schedule_run(schedule,snapshot,selected,next_due,error):
            count += 1
    return count


def quality_scan(repo,settings,actor='scheduler'):
    """重读所有入库原始CSV自动巡检，问题变化去重告警。"""
    checks = []
    for event in repo.all_events():
        try:
            _,issues = inspect_csv(event['raw_csv'],settings.rules)
        except Exception as exc:
            issues = [{'severity':'ERROR','code':'SCAN_FAILURE','row':0,'field':'CSV','message':str(exc)[:300]}]
        checks.append((event['id'],issues))
    identifier = repo.save_quality_scan(checks,settings.rules,actor)
    return decoded(repo.get('qc_scans',identifier))


def analysis_markdown(repo,identifier):
    """导出历史事件的可复核误差摘要，未完成任务不可导出。"""
    row = require(repo,'forecasts',identifier)
    if row['status']!='SUCCEEDED':
        raise services.BusinessError(409,'任务尚未成功')
    snapshot,result = json.loads(row['snapshot_json']),json.loads(row['result_json'])
    q = result['simulation']['Q']
    pairs = [(r['Q_obs'],q[i]) for i,r in enumerate(snapshot['event_rows']) if r['Q_obs'] is not None]
    text = ['# 青河洪水预报误差分析',f"任务：{identifier}",f"场次：{snapshot['event_name']}",
            f"参数摘要：{snapshot['params_sha256']}",f"模型版本：{snapshot['model_request']['model_version']}",
            ]
    table = ['| 指标 | 数值 |','|---|---:|']
    for key,value in result['metrics'].items():
        table.append(f'| {key} | {value if value is not None else "未定义或无完整观测"} |')
    text.append('\n'.join(table))
    if pairs:
        bias = sum(s-o for o,s in pairs)/len(pairs)
        text.append(f'\n有效观测时段平均偏差：{bias:.6f} m³/s。')
    text.append('\n峰现误差以6h离散时段计，正值为模拟偏晚；峰误差为有符号百分数。缺测观测不参与RMSE/DC，峰值指标只在观测完整时计算。分析不能用于对event4重新调参。')
    return '\n\n'.join(text)+'\n'
