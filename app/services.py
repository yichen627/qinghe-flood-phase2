"""应用层：质控入库、预报编排和结果评估。"""
import json
import math
import time
import numpy as np
from .quality import inspect_csv
from .settings import digest,model_version
from .engine import calc_dc,calc_rmse,calc_peak_relative_error,calc_peak_time_error


class BusinessError(Exception):
    """具有HTTP状态码的业务错误，不包含数据库细节。"""
    def __init__(self,status,detail):
        """保存可返回客户端的错误说明。"""
        self.status,self.detail = status,detail


def validate_state(state,params):
    """确保初态有限、非负、必要字段齐全且不超过对应容量。"""
    required = ('WU','WL','WD','S','QI','QG')
    if any(k not in state for k in required):
        raise BusinessError(422,'初态缺少WU/WL/WD/S/QI/QG')
    if any(not math.isfinite(v) or v < 0 for v in state.values()):
        raise BusinessError(422,'初态必须有限且非负')
    for key,cap in zip(('WU','WL','WD','S'),('WUM','WLM','WDM','SM')):
        if state[key]>params[cap]+1e-9:
            raise BusinessError(422,f'初始{key}超过{cap}')


def import_event(repo,settings,body):
    """质控结果与原始CSV一起保存，包括不可用于计算的坏数据。"""
    validate_state(body.state0,settings.params)
    if len(body.csv_text.encode('utf-8')) > settings.rules['max_csv_bytes']:
        raise BusinessError(413,'CSV超过配置大小上限')
    rows,issues = inspect_csv(body.csv_text,settings.rules)
    fingerprint = digest({'csv':body.csv_text,'state0':body.state0,'rules':settings.rules})
    row,duplicate = repo.insert_event(fingerprint,body.name,body.csv_text,rows,issues,body.state0)
    return {**event_summary(row),'issues':json.loads(row['issues_json']),'duplicate':duplicate}


def event_summary(row):
    """把数据库记录转换为无原文的大纲。"""
    issues = json.loads(row['issues_json'])
    return {k:row[k] for k in ('id','name','created_at')} | {
        'valid':bool(row['valid']),'row_count':len(json.loads(row['rows_json'])),
        'error_count':sum(i['severity']=='ERROR' for i in issues),
        'warning_count':sum(i['severity']=='WARNING' for i in issues)}


def task_summary(row):
    """统一任务列表与详情摘要。"""
    result = json.loads(row['result_json']) if row['result_json'] else None
    return {k:row[k] for k in ('id','event_id','scheme_id','status','created_at','updated_at','error')} | {
        'metrics':result['metrics'] if result else None}


def queue_forecast(repo,settings,body):
    """只使用合格事件，创建完整不可变输入快照。"""
    row = repo.get('events',body.event_id)
    if row is None:
        raise BusinessError(404,'Event not found')
    if not row['valid']:
        raise BusinessError(409,'事件存在ERROR质控问题，禁止起报')
    rows,state = json.loads(row['rows_json']),json.loads(row['state0_json'])
    request = {'inputs':[{'P':r['P'],'EM':r['EM']} for r in rows],
               'params':settings.params,'state0':state,'model_version':model_version()}
    snapshot = {'model_request':request,'event_rows':rows,'event_name':row['name'],
                'params_sha256':settings.params_hash,'event_fingerprint':row['fingerprint'],
                'request_sha256':digest(request),'source':'phase1-frozen-v1'}
    return task_summary(repo.queue(row['id'],body.scheme_id,snapshot))


def run_one(repo,settings,client):
    """领取一个持久化任务，经HTTP计算并记录成功或失败；没有任务返回False。"""
    task = repo.claim(settings.rules['task_lease_seconds'])
    if not task:
        return False
    started = time.monotonic()
    try:
        snapshot = json.loads(task['snapshot_json'])
        request = snapshot['model_request']
        if digest(request) != snapshot['request_sha256']:
            raise ValueError('任务快照摘要不符')
        simulation = client.simulate(request)
        q = np.asarray(simulation['Q'],float)
        if q.shape != (len(snapshot['event_rows']),) or not np.isfinite(q).all() or (q < -1e-8).any():
            raise ValueError('模型HTTP返回无效流量')
        for field in ('balance','source_balance'):
            balance = np.asarray(simulation[field],float)
            if balance.shape != q.shape or not np.isfinite(balance).all() or np.max(np.abs(balance))>1e-7:
                raise ValueError('模型HTTP返回水量平衡不通过')
        pairs = [(i,r['Q_obs']) for i,r in enumerate(snapshot['event_rows']) if r['Q_obs'] is not None]
        metrics = {'DC':None,'RMSE':None,'peak_relative_error_pct':None,'peak_time_error_h':None,
                   'observed_count':len(pairs)}
        if pairs:
            observed = [v for _,v in pairs]
            simulated = [float(q[i]) for i,_ in pairs]
            metrics['RMSE'] = calc_rmse(observed,simulated)
            if len(pairs)>1 and np.var(observed)>0:
                metrics['DC'] = calc_dc(observed,simulated)
            # 峰值指标仅在完整观测时计算，避免缺测造成错峰和索引压缩。
            if len(pairs)==len(q) and max(observed)>0:
                metrics['peak_relative_error_pct'] = calc_peak_relative_error(observed,simulated)
                metrics['peak_time_error_h'] = calc_peak_time_error(observed,simulated,settings.rules['dt_hours'])
        result = {'simulation':simulation,'metrics':metrics,
                  'elapsed_seconds':time.monotonic()-started}
        repo.finish(task['id'],result=result)
    except Exception as exc:
        # 错误摘要不包含API密钥及完整HTTP请求；保留任务供诊断和显式重算。
        repo.finish(task['id'],error=f'{type(exc).__name__}: {str(exc)[:500]}')
    return True
