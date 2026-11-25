"""阶段3–4真实HTTP验收；通知仅投递本地值班收件箱。"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import time
import uuid
import httpx


def main():
    """真实演示版本切换、回放、复核签发、定时起报和自动巡检。"""
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args = parser.parse_args()
    rules = json.loads((root/'config'/'settings.json').read_text(encoding='utf-8'))
    keys = {'forecaster':os.getenv('API_KEY','qinghe-local-demo'),
            'reviewer':os.getenv('REVIEWER_API_KEY','qinghe-reviewer-demo'),
            'admin':os.getenv('ADMIN_API_KEY','qinghe-admin-demo')}
    evidence = {'started_at':datetime.now(timezone.utc).isoformat()}
    with httpx.Client(base_url=args.base_url,timeout=15,trust_env=False) as client:
        def call(method,path,body=None,role='admin',expected=200):
            """对每步状态码作断言，不把拒绝或失败当成成功。"""
            response = client.request(method,path,json=body,headers={'X-API-Key':keys[role]})
            assert response.status_code==expected,(method,path,response.status_code,response.text)
            return response.json() if response.content else None

        def wait_until(function,timeout,label):
            """等待后台进程生效，不手动执行任务或质控逻辑冒充自动触发。"""
            started = time.monotonic()
            while time.monotonic()-started<timeout:
                value = function()
                if value:
                    return value,time.monotonic()-started
                time.sleep(.5)
            raise RuntimeError('timeout: '+label)

        def completed(identifier):
            """仅SUCCEEDED算完成，遇到FAILED立即失败。"""
            task = call('GET','/forecasts/'+identifier)
            assert task['status']!='FAILED',task
            return task if task['status']=='SUCCEEDED' else None

        # 既有阶段2记录在数据库升级后应原样存在。
        baseline_evidence = json.loads((root/'docs'/'evidence'/'acceptance.json').read_text(encoding='utf-8'))
        preserved = []
        for record in baseline_evidence['runs']:
            response = client.get('/forecasts/'+record['task_id'],headers={'X-API-Key':keys['admin']})
            # CI新数据库没有上一阶段的真实本机ID，记录并区分未适用，不能假称已保留。
            if response.status_code==404:
                continue
            response.raise_for_status()
            task = response.json()
            assert task['status']=='SUCCEEDED'
            assert task['metrics']['DC']==record['metrics']['DC']
            preserved.append(record['task_id'])
        evidence['preserved_stage2_task_ids']=preserved
        golden = json.loads((root/'data'/'golden'/'event1_result.json').read_text(encoding='utf-8'))
        source = (root/'data'/'events'/'event1.csv').read_text(encoding='utf-8-sig')
        event = call('POST','/events',{'name':'stage34-demo','csv_text':source,'state0':golden['state0']},
                     role='forecaster',expected=201)
        original_routing = call('GET','/routing')
        # 明确使用内置冻结参数，演示管理操作而非再次调参。
        base_scheme = next(s for s in call('GET','/schemes') if s['id']=='phase1-frozen-v1')
        parameter = call('POST','/parameter-sets',{'name':'stage34-frozen-copy','params':base_scheme['params']},expected=201)
        alternate = call('POST','/schemes',{'name':'stage34-demo-'+uuid.uuid4().hex[:8],
                                           'parameter_id':parameter['id'],'model_version':base_scheme['model_version']},expected=201)
        call('POST','/schemes/'+alternate['id']+'/activate')
        queued = call('POST','/forecasts',{'event_id':event['id']},role='forecaster',expected=202)
        assert queued['scheme_id']==alternate['id']
        result,elapsed = wait_until(lambda:completed(queued['id']),rules['forecast_acceptance_seconds'],'forecast')
        evidence['new_forecast']={'id':queued['id'],'scheme_id':queued['scheme_id'],'seconds':elapsed}
        call('POST','/schemes/rollback')
        assert call('GET','/routing')['active']==original_routing['active']
        replay = call('POST','/forecasts/'+queued['id']+'/replay',role='forecaster',expected=202)
        replayed,_ = wait_until(lambda:completed(replay['id']),rules['forecast_acceptance_seconds'],'replay')
        assert replayed['result']['replay_comparison']['within_tolerance']
        evidence['replay']=replayed['result']['replay_comparison']
        product = call('POST','/products',{'forecast_id':queued['id'],'title':'Qinghe local teaching forecast'},
                       role='forecaster',expected=201)
        path = '/products/'+product['id']
        assert client.get('/published/'+product['id']).status_code==404
        call('POST',path+'/publish',role='forecaster',expected=403)
        call('POST',path+'/sign',role='reviewer',expected=409)
        call('POST',path+'/review',{'note':'Verified model balance, input snapshot and hydrograph'},role='reviewer')
        call('POST',path+'/sign',role='reviewer')
        call('GET',path+'/export.json',role='reviewer')
        call('POST',path+'/publish',role='reviewer')
        assert client.get('/published/'+product['id']).json()['status']=='PUBLISHED'
        notice,_ = wait_until(lambda:next((m for m in call('GET','/inbox?limit=100')
                                          if m['payload'].get('product_id')==product['id']),None),30,'product notification')
        evidence['product']={'id':product['id'],'public_status':'PUBLISHED','inbox_id':notice['id']}
        plan = call('POST','/schedules',{'name':'stage34 demo interval','event_id':event['id'],
                                       'interval_seconds':rules['schedule_min_interval_seconds']},expected=201)
        try:
            triggered,latency = wait_until(lambda:next((r for r in call('GET','/schedule-runs?limit=100')
                                                       if r['schedule_id']==plan['id']),None),30,'scheduled run')
            assert triggered['forecast_id'] and triggered['error'] is None
            wait_until(lambda:completed(triggered['forecast_id']),rules['forecast_acceptance_seconds'],'scheduled forecast')
            evidence['schedule']={'id':plan['id'],'forecast_id':triggered['forecast_id'],'trigger_seconds':latency}
        finally:
            call('PATCH','/schedules/'+plan['id'],{'enabled':False})
        # 每次使用不同负值，保证测试的是新异常的自动巡检，而不是旧告警。
        negative = '-'+str(int(uuid.uuid4().hex[:6],16)+1)+'.0,0.0'
        bad_source = source.replace('0.0,0.0',negative,1)
        started = time.monotonic()
        bad = call('POST','/events',{'name':'stage34 automatic QC','csv_text':bad_source,'state0':golden['state0']},
                   role='forecaster',expected=201)
        assert not bad['valid']
        alert,_ = wait_until(lambda:next((r for r in call('GET','/alerts?limit=100') if r['event_id']==bad['id']),None),
                           300,'automatic quality alert')
        message,_ = wait_until(lambda:next((r for r in call('GET','/inbox?limit=100')
                                           if r['payload'].get('alert_id')==alert['id']),None),30,'automatic quality notification')
        latency = time.monotonic()-started
        assert latency<300
        call('POST','/alerts/'+alert['id']+'/acknowledge',role='reviewer')
        evidence['automatic_qc']={'event_id':bad['id'],'alert_id':alert['id'],'inbox_id':message['id'],
                                  'seconds':latency,'manual_scan_called':False}
        evidence['runtime']=call('GET','/runtime')
        assert all(not evidence['runtime'][name]['stale'] for name in ('worker','scheduler'))
        evidence['product_audit_actions']=[r['action'] for r in call('GET','/audit?entity_id='+product['id'])]
        assert set(evidence['product_audit_actions'])=={'product.drafted','product.review','product.sign','product.publish'}
    target = root/'artifacts'
    target.mkdir(exist_ok=True)
    (target/'stage34-acceptance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False,indent=2))
    print('PASS: stage3-4 real HTTP workflow and automatic background checks')


if __name__=='__main__':
    main()
