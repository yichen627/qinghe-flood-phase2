"""阶段3–4业务状态、角色、调度、通知和迁移的验收测试。"""
from datetime import datetime,timezone,timedelta
import json
import sqlite3
import pytest
from app.settings import model_version,digest
from app.repository import Repository
from app.services import run_one
from app.workflows import scheduler_tick,quality_scan
from test_pipeline import event_body,ingest,enqueue,headers


def admin(system):
    """管理员角色认证，身份不来自请求body。"""
    return {'X-API-Key':system[2].admin_key}


def reviewer(system):
    """模拟值班长独立操作凭据。"""
    return {'X-API-Key':system[2].reviewer_key}


def request(system,method,path,body=None,role='admin',status=200):
    """发送请求并在断言失败时保留接口返回详情。"""
    auth = admin(system) if role=='admin' else reviewer(system) if role=='reviewer' else headers(system)
    response = system[0].request(method,path,json=body,headers=auth)
    assert response.status_code==status,response.text
    return response.json() if response.content else None


def scheme(system,changed=False):
    """生成测试参数版本，变更只用于合成权限/切换验证，不率定event4。"""
    params = dict(system[2].params)
    if changed:
        params['K'] *= 1.02
    parameter = request(system,'POST','/parameter-sets',{'name':'test parameters','params':params},status=201)
    record = request(system,'POST','/schemes',{'name':'test scheme','parameter_id':parameter['id'],
                                            'model_version':model_version()},status=201)
    return record,parameter


def successful_task(system):
    """先运行模型，产品创建不绕过预报状态。"""
    identifier = enqueue(system,ingest(system)['id'])
    run_one(system[3],system[2],system[4])
    return identifier


def test_roles_and_immutable_parameters(system):
    """预报员不能修改参数，参数版本禁止SQL覆盖；非ASCII错误密钥也返回401。"""
    request(system,'POST','/parameter-sets',{'name':'forbidden','params':system[2].params},role='forecaster',status=403)
    created,_ = scheme(system)
    with pytest.raises(sqlite3.IntegrityError):
        with system[3].connect() as db:
            db.execute('UPDATE parameter_sets SET name=? WHERE id=?',('overwrite',created['parameter_id']))
    response = system[0].get('/routing',headers={'X-API-Key':'wrong-key'})
    assert response.status_code==401


def test_scheme_switch_rollout_rollback_and_archive(system):
    """方案切换只影响未来任务，稳定灰度0/100可验证，归档不物理删除。"""
    event = ingest(system)
    original_id = enqueue(system,event['id'])
    original = system[3].get('forecasts',original_id)['snapshot_json']
    alternate,_ = scheme(system,changed=True)
    request(system,'POST','/rollouts',{'scheme_id':alternate['id'],'percentage':100})
    second = enqueue(system,event['id'])
    assert system[3].get('forecasts',second)['scheme_id']==alternate['id']
    request(system,'POST','/rollouts',{'scheme_id':alternate['id'],'percentage':0})
    third = enqueue(system,event['id'])
    assert system[3].get('forecasts',third)['scheme_id']=='phase1-frozen-v1'
    request(system,'POST',f"/schemes/{alternate['id']}/activate")
    assert request(system,'GET','/routing')['active']==alternate['id']
    request(system,'POST','/schemes/rollback')
    assert request(system,'GET','/routing')['active']=='phase1-frozen-v1'
    assert system[3].get('forecasts',original_id)['snapshot_json']==original
    unused,_ = scheme(system)
    request(system,'DELETE',f"/schemes/{unused['id']}",status=204)
    assert system[3].get('schemes',unused['id'])['deleted']==1
    request(system,'POST','/forecasts',{'event_id':event['id'],'scheme_id':unused['id']},role='forecaster',status=404)
    request(system,'DELETE','/schemes/phase1-frozen-v1',status=409)


def test_register_unavailable_model_cannot_activate(system):
    """元信息注册不意味着算法已部署；禁止静默换成当前算法执行。"""
    record = request(system,'POST','/models',{'name':'not deployed','version':'a'*64,'image_ref':'example/not-deployed:v2'},status=201)
    created = request(system,'POST','/schemes',{'name':'future model','model_version':record['id'],
                                             'parameter_id':'phase1-params-v1'},status=201)
    request(system,'POST',f"/schemes/{created['id']}/activate",status=409)


def test_replay_original_snapshot_after_switch(system):
    """切换当前参数后回放仍使用原输入和参数，结果与原预报一致。"""
    identifier = successful_task(system)
    old = system[3].get('forecasts',identifier)
    alternative,_ = scheme(system,changed=True)
    request(system,'POST',f"/schemes/{alternative['id']}/activate")
    replay = request(system,'POST',f'/forecasts/{identifier}/replay',role='forecaster',status=202)
    assert replay['scheme_id']=='phase1-frozen-v1'
    run_one(system[3],system[2],system[4])
    replayed = request(system,'GET','/forecasts/'+replay['id'])
    assert replayed['result']['replay_comparison']['within_tolerance']
    assert replayed['result']['replay_comparison']['max_abs_q_difference']==0
    assert system[3].get('forecasts',identifier)==old
    response = system[0].get(f'/forecasts/{identifier}/analysis.md',headers=headers(system))
    assert response.status_code==200 and '| DC |' in response.text


def test_product_review_sign_publish_and_notification(system):
    """UC2完整门禁：角色及状态均合法才可签发发布，通知只投递一次。"""
    identifier = successful_task(system)
    product = request(system,'POST','/products',{'forecast_id':identifier,'title':'Qinghe forecast'},role='forecaster',status=201)
    path = '/products/'+product['id']
    assert system[0].get('/published/'+product['id']).status_code==404
    request(system,'POST',path+'/sign',role='reviewer',status=409)
    request(system,'GET',path+'/export.json',status=409)
    request(system,'POST',path+'/review',{'note':'wrong role'},role='forecaster',status=403)
    request(system,'POST',path+'/review',{'note':'checked water balance and hydrograph'},role='reviewer')
    request(system,'POST',path+'/publish',role='reviewer',status=409)
    signed = request(system,'POST',path+'/sign',role='reviewer')
    assert signed['signed_by']=='reviewer' and signed['content_sha256']==product['content_sha256']
    assert request(system,'GET',path+'/export.json')['status']=='SIGNED'
    request(system,'POST',path+'/publish',role='reviewer')
    assert system[0].get('/published/'+product['id']).json()['status']=='PUBLISHED'
    request(system,'POST',path+'/publish',role='reviewer',status=409)
    assert len(request(system,'GET','/notifications'))==1
    assert system[3].dispatch_one(system[2].rules)
    assert not system[3].dispatch_one(system[2].rules)
    assert len(request(system,'GET','/inbox'))==1
    request(system,'GET','/inbox',role='forecaster',status=403)
    actions = [r['action'] for r in request(system,'GET','/audit?entity_id='+product['id'])]
    assert set(actions)=={'product.drafted','product.review','product.sign','product.publish'}
    with pytest.raises(sqlite3.IntegrityError):
        with system[3].connect() as db:
            db.execute('DELETE FROM audit_log')


def test_product_only_from_success_and_content_immutable(system):
    """运行中任务不能建产品；草稿内容不能在复核后被替换。"""
    identifier = enqueue(system,ingest(system)['id'])
    request(system,'POST','/products',{'forecast_id':identifier,'title':'too early'},status=409)
    run_one(system[3],system[2],system[4])
    product = request(system,'POST','/products',{'forecast_id':identifier,'title':'immutable'},status=201)
    with pytest.raises(sqlite3.IntegrityError):
        with system[3].connect() as db:
            db.execute('UPDATE products SET content_json=? WHERE id=?',('{}',product['id']))


def test_durable_schedule_coalesces_and_deduplicates(system):
    """数据库重开后计划可恢复，同一到期时刻不产生重复任务。"""
    event = ingest(system)
    current = datetime.now(timezone.utc)
    due = (current-timedelta(hours=1)).isoformat()
    schedule = request(system,'POST','/schedules',{'name':'periodic','event_id':event['id'],
                                                'interval_seconds':5,'next_run_at':due},status=201)
    reopened = Repository(system[2].database)
    assert scheduler_tick(reopened,system[2],current)==1
    assert scheduler_tick(system[3],system[2],current)==0
    assert len(request(system,'GET','/schedule-runs'))==1
    assert datetime.fromisoformat(system[3].get('schedules',schedule['id'])['next_run_at'])>current
    assert scheduler_tick(reopened,system[2],current+timedelta(seconds=6))==1
    assert len(request(system,'GET','/forecasts'))==2
    request(system,'PATCH','/schedules/'+schedule['id'],{'enabled':False})
    assert scheduler_tick(reopened,system[2],current+timedelta(minutes=1))==0
    request(system,'POST','/schedules',{'name':'naive','event_id':event['id'],'interval_seconds':5,
                                      'next_run_at':'2026-11-25T10:00:00'},status=422)


def test_schedule_current_scheme_and_delete_guard(system):
    """固定方案计划禁止归档引用；未指定方案的计划在触发时解析激活方案。"""
    event = ingest(system)
    alternative,_ = scheme(system)
    plan = request(system,'POST','/schedules',{'name':'fixed','event_id':event['id'],
                                            'scheme_id':alternative['id'],'interval_seconds':60},status=201)
    request(system,'DELETE','/schemes/'+alternative['id'],status=409)
    request(system,'PATCH','/schedules/'+plan['id'],{'enabled':False})
    request(system,'DELETE','/schemes/'+alternative['id'],status=204)


def test_quality_rescan_alert_dedup_and_ack(system):
    """UC5重扫原始CSV，去重告警和通知，确认操作保留身份。"""
    body = event_body()
    body['csv_text']=body['csv_text'].replace('0.0,0.0','-1.0,0.0',1)
    event = ingest(system,body)
    assert not event['valid']
    first = quality_scan(system[3],system[2])
    quality_scan(system[3],system[2])
    assert first['error_count']==1
    alerts = request(system,'GET','/alerts')
    assert len(alerts)==1 and alerts[0]['event_id']==event['id']
    assert len(request(system,'GET','/notifications'))==1
    system[3].dispatch_one(system[2].rules)
    assert len(request(system,'GET','/inbox'))==1
    acknowledged = request(system,'POST','/alerts/'+alerts[0]['id']+'/acknowledge',role='reviewer')
    assert acknowledged['acknowledged_by']=='reviewer'


def test_outbox_retry_and_no_duplicate_delivery(system):
    """投递失败退避，达到次数上限进入死信，管理员可显式重试一次。"""
    body = event_body()
    body['csv_text']=body['csv_text'].replace('0.0,0.0','-1.0,0.0',1)
    ingest(system,body)
    quality_scan(system[3],system[2])
    for _ in range(system[2].rules['notification_max_attempts']):
        assert system[3].dispatch_one(system[2].rules,fail_reason='injected local delivery failure')
        with system[3].connect() as db:
            db.execute("UPDATE notification_outbox SET available_at='2020-01-01T00:00:00+00:00'")
    notice = request(system,'GET','/notifications')[0]
    assert notice['status']=='FAILED'
    assert not system[3].dispatch_one(system[2].rules)
    request(system,'POST','/notifications/'+notice['id']+'/retry')
    system[3].dispatch_one(system[2].rules)
    assert len(request(system,'GET','/inbox'))==1
    request(system,'POST','/notifications/'+notice['id']+'/retry',status=409)


def test_audit_actor_and_runtime_status(system):
    """身份来自凭据，worker与scheduler心跳可判断缺失和恢复。"""
    event = ingest(system)
    records = request(system,'GET','/audit?entity_id='+event['id'])
    assert records[0]['actor']=='forecaster'
    assert request(system,'GET','/runtime')['scheduler']['stale']
    system[3].heartbeat('scheduler',{'status':'ok'})
    assert not request(system,'GET','/runtime')['scheduler']['stale']


def test_v1_migration_preserves_existing_data(tmp_path):
    """v1真实表结构原地升级，保留事件和历史任务，无需删除持久卷。"""
    path = tmp_path/'old.db'
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE events(id TEXT PRIMARY KEY,fingerprint TEXT UNIQUE,name TEXT,
          created_at TEXT,raw_csv TEXT,rows_json TEXT,issues_json TEXT,state0_json TEXT,valid INTEGER);
          CREATE TABLE forecasts(id TEXT PRIMARY KEY,event_id TEXT REFERENCES events(id),scheme_id TEXT,
          status TEXT,created_at TEXT,updated_at TEXT,snapshot_json TEXT,result_json TEXT,error TEXT);
          PRAGMA user_version=1;''')
        db.execute("INSERT INTO events VALUES('old-event','abc','old','2026','csv','[]','[]','{}',1)")
        db.execute("INSERT INTO forecasts VALUES('old-task','old-event','phase1-frozen-v1','SUCCEEDED','2026','2026','{}','{}',NULL)")
    repo = Repository(str(path))
    repo.initialize()
    repo.initialize()
    assert repo.get('events','old-event')['name']=='old'
    assert repo.get('forecasts','old-task')['status']=='SUCCEEDED'
    with repo.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==2


def test_due_schedule_failure_is_recorded_and_notifies(system):
    """计划建立后新方案不兼容初态时，触发失败可查且产生本地通知。"""
    event = ingest(system)
    plan = request(system,'POST','/schedules',{'name':'late binding','event_id':event['id'],'interval_seconds':60},status=201)
    params = dict(system[2].params,WUM=10.)
    parameter = request(system,'POST','/parameter-sets',{'name':'capacity mismatch','params':params},status=201)
    alternate = request(system,'POST','/schemes',{'name':'smaller capacity','parameter_id':parameter['id'],
                                               'model_version':model_version()},status=201)
    request(system,'POST','/schemes/'+alternate['id']+'/activate')
    assert scheduler_tick(system[3],system[2])==1
    result = request(system,'GET','/schedule-runs')[0]
    assert result['schedule_id']==plan['id'] and result['forecast_id'] is None and result['error']
    assert request(system,'GET','/notifications')[0]['kind']=='SCHEDULE_FAILED'


def test_replay_unavailable_historical_model_is_rejected(system):
    """历史模型不再部署时明确拒绝，不用新模型冒充历史回放。"""
    identifier = successful_task(system)
    row = system[3].get('forecasts',identifier)
    snapshot = json.loads(row['snapshot_json'])
    snapshot['model_request']['model_version']='b'*64
    snapshot['request_sha256']=digest(snapshot['model_request'])
    historic = system[3].queue(row['event_id'],row['scheme_id'],snapshot)
    system[3].claim(system[2].rules['task_lease_seconds'])
    system[3].finish(historic['id'],error='historical model no longer available')
    request(system,'POST',f"/forecasts/{historic['id']}/replay",role='forecaster',status=409)
    with pytest.raises(sqlite3.IntegrityError):
        with system[3].connect() as db:
            db.execute('UPDATE forecasts SET snapshot_json=? WHERE id=?',('{}',identifier))
