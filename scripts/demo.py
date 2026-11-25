"""真实Compose环境的四场端到端验收，不能用进程内测试替代。"""
import argparse
import json
import os
from pathlib import Path
import time
import httpx


def main():
    """入库→持久任务→worker→模型HTTP→查询→PNG→黄金回归。"""
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args = parser.parse_args()
    target = root/'artifacts'
    target.mkdir(exist_ok=True)
    rules = json.loads((root/'config'/'settings.json').read_text(encoding='utf-8'))
    evidence = []
    with httpx.Client(base_url=args.base_url,headers={'X-API-Key':os.getenv('API_KEY','qinghe-local-demo')},
                      timeout=15,trust_env=False) as client:
        for event in ('event1','event2','event3','event4'):
            base = json.loads((root/'data'/'golden'/f'{event}_result.json').read_text(encoding='utf-8'))
            response = client.post('/events',json={'name':event,'state0':base['state0'],
                                                  'csv_text':(root/'data'/'events'/f'{event}.csv').read_text(encoding='utf-8-sig')})
            response.raise_for_status()
            imported = response.json()
            assert imported['valid'],imported
            started = time.monotonic()
            response = client.post('/forecasts',json={'event_id':imported['id']})
            response.raise_for_status()
            identifier = response.json()['id']
            while True:
                response = client.get('/forecasts/'+identifier)
                response.raise_for_status()
                task = response.json()
                if task['status'] in ('SUCCEEDED','FAILED'):
                    break
                if time.monotonic()-started>rules['forecast_acceptance_seconds']:
                    raise RuntimeError('超过UC1的180秒验收时间')
                time.sleep(.5)
            assert task['status']=='SUCCEEDED',task
            elapsed = time.monotonic()-started
            predicted = task['result']['simulation']['Q']
            error = max(abs(a-b['Q']) for a,b in zip(predicted,base['rows']))
            assert len(predicted)==len(base['rows']) and error<1e-8,error
            assert elapsed<rules['forecast_acceptance_seconds']
            if event=='event4':
                assert task['metrics']['DC']>=rules['validation_dc_min']
            image = client.get(f'/forecasts/{identifier}/plot.png')
            image.raise_for_status()
            assert image.content.startswith(b'\x89PNG')
            (target/f'{event}.png').write_bytes(image.content)
            evidence.append({'event':event,'task_id':identifier,'status':task['status'],
                             'wall_seconds':elapsed,'max_Q_difference':error,'metrics':task['metrics'],
                             'params_sha256':task['snapshot']['params_sha256'],
                             'model_version':task['snapshot']['model_request']['model_version']})
            print(event,task['metrics'],'seconds',round(elapsed,3),flush=True)
        bad = client.post('/events',json={'name':'negative-rainfall','state0':base['state0'],
                                         'csv_text':(root/'data'/'invalid'/'event1_负值.csv').read_text(encoding='utf-8-sig')})
        bad.raise_for_status()
        assert not bad.json()['valid']
        blocked = client.post('/forecasts',json={'event_id':bad.json()['id']})
        assert blocked.status_code==409
    (target/'acceptance.json').write_text(json.dumps({'runs':evidence,'bad_data_blocked':True},ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: real HTTP golden chain, PNGs, invalid-data rejection')


if __name__ == '__main__':
    main()
