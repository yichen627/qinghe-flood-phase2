"""最终部署验收：小批量任务及真实scheduler/worker重启后的计划恢复。"""
from datetime import datetime,timezone,timedelta
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT/'artifacts'


def main():
    """prepare/verify之间由宿主机真正重启进程，不用内存模拟。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['burst','prepare-restart','verify-restart','cleanup'])
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args = parser.parse_args()
    TARGET.mkdir(exist_ok=True)
    auth = {'X-API-Key':os.getenv('ADMIN_API_KEY','qinghe-admin-demo')}
    with httpx.Client(base_url=args.base_url,headers=auth,timeout=15,trust_env=False) as client:
        def call(method,path,body=None,expected=200):
            """统一HTTP断言，不吞掉业务失败。"""
            response = client.request(method,path,json=body)
            assert response.status_code==expected,(response.status_code,response.text)
            return response.json()

        def wait_task(identifier,timeout=180):
            """等待实际worker执行，模型失败直接中止验收。"""
            started = time.monotonic()
            while time.monotonic()-started<timeout:
                result = call('GET','/forecasts/'+identifier)
                if result['status']=='SUCCEEDED':
                    return result
                if result['status']=='FAILED':
                    raise RuntimeError(str(result))
                time.sleep(.25)
            raise TimeoutError(identifier)

        base = json.loads((ROOT/'data'/'golden'/'event1_result.json').read_text(encoding='utf-8'))
        if args.action in ('burst','prepare-restart'):
            event = call('POST','/events',{'name':'final acceptance event1','state0':base['state0'],
                                         'csv_text':(ROOT/'data'/'events'/'event1.csv').read_text(encoding='utf-8-sig')},201)
        if args.action=='burst':
            started = time.monotonic()
            submitted = [call('POST','/forecasts',{'event_id':event['id'],'scheme_id':'phase1-frozen-v1'},202)['id']
                         for _ in range(12)]
            results = [wait_task(identifier) for identifier in submitted]
            differences = [max(abs(v-r['Q']) for v,r in zip(t['result']['simulation']['Q'],base['rows'])) for t in results]
            assert max(differences)<1e-8
            elapsed = time.monotonic()-started
            assert elapsed<180
            record = {'kind':'bounded 12-task burst, not a general load SLA','tasks':len(submitted),
                      'task_ids':submitted,'elapsed_seconds':elapsed,'max_Q_difference':max(differences)}
            (TARGET/'burst-acceptance.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
            print(json.dumps(record,indent=2))
        elif args.action=='prepare-restart':
            control = call('POST','/forecasts',{'event_id':event['id'],'scheme_id':'phase1-frozen-v1'},202)
            result = wait_task(control['id'])
            fingerprint = hashlib.sha256(json.dumps(result['snapshot'],sort_keys=True).encode()).hexdigest()
            due = (datetime.now(timezone.utc)+timedelta(seconds=15)).isoformat()
            plan = call('POST','/schedules',{'name':'final restart recovery','event_id':event['id'],
                                           'scheme_id':'phase1-frozen-v1','interval_seconds':3600,'next_run_at':due},201)
            state = {'schedule_id':plan['id'],'control_task_id':control['id'],
                     'snapshot_sha256':fingerprint,'prepared_at':datetime.now(timezone.utc).isoformat(),
                     'scheduled_for':due}
            (TARGET/'restart-state.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
            print('prepared:',plan['id'],flush=True)
        else:
            state = json.loads((TARGET/'restart-state.json').read_text(encoding='utf-8'))
            if args.action=='cleanup':
                call('PATCH','/schedules/'+state['schedule_id'],{'enabled':False})
                print('restart probe plan disabled')
                return
            started = time.monotonic()
            try:
                while time.monotonic()-started<180:
                    matching = [r for r in call('GET','/schedule-runs?limit=100') if r['schedule_id']==state['schedule_id']]
                    if matching:
                        break
                    time.sleep(.5)
                else:
                    raise TimeoutError('restart schedule not recovered')
                assert len(matching)==1 and matching[0]['error'] is None,matching
                recovered = wait_task(matching[0]['forecast_id'])
                original = call('GET','/forecasts/'+state['control_task_id'])
                fingerprint = hashlib.sha256(json.dumps(original['snapshot'],sort_keys=True).encode()).hexdigest()
                assert fingerprint==state['snapshot_sha256']
                assert recovered['result']['simulation']['Q']==original['result']['simulation']['Q']
                status = call('GET','/runtime')
                assert not status['scheduler']['stale'] and not status['worker']['stale']
                evidence = {**state,'recovered_task_id':recovered['id'],'schedule_run_count':len(matching),
                            'snapshot_preserved':True,'Q_identical':True,'runtime':status,
                            'verified_at':datetime.now(timezone.utc).isoformat()}
                (TARGET/'restart-acceptance.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
                print(json.dumps(evidence,indent=2))
            finally:
                call('PATCH','/schedules/'+state['schedule_id'],{'enabled':False})


if __name__=='__main__':
    main()
