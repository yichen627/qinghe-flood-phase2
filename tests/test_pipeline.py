"""阶段二可验收测试，覆盖正常链路、质控、失败和版本契约。"""
import json
from pathlib import Path
import httpx
import numpy as np
import pytest
from app.contracts import ForecastCreate
from app.settings import ROOT,model_version
from app.services import run_one,queue_forecast


def event_body(event='event1'):
    """读取该场CSV与一期独立初态，绝不共用初态。"""
    golden = json.loads((ROOT/'data'/'golden'/f'{event}_result.json').read_text(encoding='utf-8'))
    return {'name':event,'csv_text':(ROOT/'data'/'events'/f'{event}.csv').read_text(encoding='utf-8-sig'),
            'state0':golden['state0']}


def headers(system):
    """构造非持久化演示认证头。"""
    return {'X-API-Key':system[2].api_key}


def ingest(system,body=None):
    """用HTTP入库并校验成功状态。"""
    response = system[0].post('/events',json=body or event_body(),headers=headers(system))
    assert response.status_code==201,response.text
    return response.json()


def enqueue(system,event_id):
    """通过API创建持久化任务。"""
    response = system[0].post('/forecasts',json={'event_id':event_id},headers=headers(system))
    assert response.status_code==202,response.text
    return response.json()['id']


@pytest.mark.parametrize('event',['event1','event2','event3','event4'])
def test_golden_pipeline(system,event):
    """UC1/UC3：四场HTTP链路、全序列黄金回归、守恒与图像。"""
    api,model,settings,repo,bridge = system
    identifier = enqueue(system,ingest(system,event_body(event))['id'])
    assert api.get(f'/forecasts/{identifier}/plot.png',headers=headers(system)).status_code==409
    assert run_one(repo,settings,bridge)
    task = api.get(f'/forecasts/{identifier}',headers=headers(system)).json()
    assert task['status']=='SUCCEEDED',task
    golden = json.loads((ROOT/'data'/'golden'/f'{event}_result.json').read_text(encoding='utf-8'))
    out = task['result']['simulation']
    np.testing.assert_allclose(out['Q'],[r['Q'] for r in golden['rows']],rtol=1e-10,atol=1e-8)
    assert max(map(abs,out['balance']))<1e-7
    assert max(map(abs,out['source_balance']))<1e-7
    assert task['metrics']['DC']==pytest.approx(golden['metrics']['DC'],abs=1e-9)
    if event=='event4':
        assert task['metrics']['DC']>=settings.rules['validation_dc_min']
    assert all('Q_obs' not in row for row in task['snapshot']['model_request']['inputs'])
    assert task['snapshot']['model_request']['state0']==golden['state0']
    image = api.get(f'/forecasts/{identifier}/plot.png',headers=headers(system))
    assert image.headers['content-type']=='image/png'
    assert image.content.startswith(b'\x89PNG\r\n\x1a\n')


@pytest.mark.parametrize('suffix',['负值','缺测','乱序'])
def test_bad_csv_persisted_and_blocked(system,suffix):
    """FR-M1：坏数据留库、逐行问题可查且拒绝预测。"""
    body = event_body()
    body['csv_text'] = (ROOT/'data'/'invalid'/f'event1_{suffix}.csv').read_text(encoding='utf-8-sig')
    record = ingest(system,body)
    assert not record['valid'] and record['error_count']>0
    detail = system[0].get('/events/'+record['id'],headers=headers(system)).json()
    assert detail['raw_csv']==body['csv_text']
    assert any(i['severity']=='ERROR' and i['row']>=2 for i in detail['issues'])
    assert system[0].post('/forecasts',json={'event_id':record['id']},headers=headers(system)).status_code==409


def test_dedup_warning_and_pagination(system):
    """WARNING可预报；重复导入不覆盖；分页参数受限。"""
    first,second = ingest(system),ingest(system)
    assert first['id']==second['id'] and second['duplicate']
    assert first['valid'] and first['warning_count']>0
    assert len(system[0].get('/events',headers=headers(system)).json())==1
    assert system[0].get('/events?limit=0',headers=headers(system)).status_code==422


def test_no_observation_forecast(system):
    """允许没有实测Q的未来输入，指标为空，流量仍计算。"""
    body = event_body()
    body['csv_text'] = '\n'.join(','.join(line.split(',')[:-1]) for line in body['csv_text'].splitlines())
    identifier = enqueue(system,ingest(system,body)['id'])
    run_one(system[3],system[2],system[4])
    task = system[0].get('/forecasts/'+identifier,headers=headers(system)).json()
    assert task['status']=='SUCCEEDED'
    assert task['metrics']['observed_count']==0 and task['metrics']['DC'] is None


def test_missing_state_and_auth(system):
    """初态缺失和超容量拒绝；匿名写入被拦截。"""
    api = system[0]
    assert api.post('/events',json=event_body()).status_code==401
    body = event_body()
    body['state0']={}
    assert api.post('/events',json=body,headers=headers(system)).status_code==422
    body['state0']=event_body()['state0']|{'S':999}
    assert api.post('/events',json=body,headers=headers(system)).status_code==422
    assert api.get('/forecasts/missing',headers=headers(system)).status_code==404
    assert api.post('/forecasts',json={'event_id':'missing'},headers=headers(system)).status_code==404


def test_model_version_and_input_boundary(system):
    """版本不符、非法雨量及模型密钥分别被拒绝。"""
    model,settings = system[1],system[2]
    request = {'inputs':[{'P':1,'EM':0}],'params':settings.params,'state0':event_body()['state0'],'model_version':'wrong'}
    auth = {'X-API-Key':settings.model_key}
    assert model.post('/simulate',json=request,headers=auth).status_code==409
    request['model_version']=model_version()
    assert model.post('/simulate',json=request).status_code==401
    request['inputs'][0]['P']=-1
    assert model.post('/simulate',json=request,headers=auth).status_code==422


def test_http_failure_persisted(system):
    """模型超时必须成为FAILED；不生成伪成功图。"""
    class BrokenClient:
        """模拟独立HTTP服务超时。"""
        def simulate(self,request):
            """抛出实际适配器可能出现的HTTP超时类型。"""
            raise httpx.ReadTimeout('test model timeout')
    identifier = enqueue(system,ingest(system)['id'])
    run_one(system[3],system[2],BrokenClient())
    record = system[0].get('/forecasts/'+identifier,headers=headers(system)).json()
    assert record['status']=='FAILED' and 'ReadTimeout' in record['error']
    assert system[0].get(f'/forecasts/{identifier}/plot.png',headers=headers(system)).status_code==409


def test_claim_once_and_snapshot(system):
    """领取原子性及输入快照，在数据库重开后仍保留。"""
    record = ingest(system)
    identifier = enqueue(system,record['id'])
    assert system[3].claim(120)['id']==identifier
    assert system[3].claim(120) is None
    from app.repository import Repository
    reopened = Repository(system[2].database)
    snapshot = json.loads(reopened.get('forecasts',identifier)['snapshot_json'])
    assert snapshot['params_sha256']==system[2].params_hash
    assert snapshot['event_rows'][0]['time'].endswith('+08:00')


def test_openapi_contract(system):
    """机器契约和已提交OpenAPI保持一致。"""
    for name,client in [('openapi.json',system[0]),('model-openapi.json',system[1])]:
        expected = json.loads((ROOT/'docs'/name).read_text(encoding='utf-8'))
        assert client.get('/openapi.json').json()==expected


def test_expired_lease_and_terminal_immutability(system):
    """worker失联任务必须可见失败，不被悄悄覆盖或再次领取。"""
    identifier = enqueue(system,ingest(system)['id'])
    repo = system[3]
    assert repo.claim(120)['id']==identifier
    with repo.connect() as db:
        db.execute('UPDATE forecasts SET updated_at=? WHERE id=?',('2020-01-01T00:00:00+00:00',identifier))
    assert repo.claim(120) is None
    assert repo.get('forecasts',identifier)['status']=='FAILED'
    with pytest.raises(RuntimeError):
        repo.finish(identifier,result={'invalid':'overwrite'})


def test_nonfinite_input_and_partial_observation(system):
    """NaN雨量保留为ERROR；单时段实测缺测不压缩峰时索引。"""
    body = event_body()
    lines = body['csv_text'].splitlines()
    cells = lines[1].split(',')
    cells[1]='NaN'
    lines[1]=','.join(cells)
    broken = ingest(system,{**body,'csv_text':'\n'.join(lines)})
    assert not broken['valid']
    lines = body['csv_text'].splitlines()
    cells = lines[1].split(',')
    cells[-1]=''
    lines[1]=','.join(cells)
    valid = ingest(system,{**body,'csv_text':'\n'.join(lines)})
    assert valid['valid']
    identifier = enqueue(system,valid['id'])
    run_one(system[3],system[2],system[4])
    result = system[0].get('/forecasts/'+identifier,headers=headers(system)).json()
    assert result['metrics']['observed_count']==39
    assert result['metrics']['peak_time_error_h'] is None
