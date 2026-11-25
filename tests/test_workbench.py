"""工作台入口、身份和课程样本初态边界。"""
import json
from app.settings import ROOT


def test_workbench_entry_and_role_boundary(system):
    """工作台公开壳可加载，业务数据和身份仍由服务端验证。"""
    api,_,settings,_,_ = system
    page = api.get('/')
    assert page.status_code==200 and '预报工作台' in page.text
    assert api.get('/assets/app.js').status_code==200
    assert api.get('/assets/style.css').status_code==200
    assert api.get('/workbench/session').status_code==401
    for role,key in [('forecaster',settings.api_key),('reviewer',settings.reviewer_key),('admin',settings.admin_key)]:
        assert api.get('/workbench/session',headers={'X-API-Key':key}).json()=={'role':role}
    assert api.get('/workbench/examples/event1',headers={'X-API-Key':settings.reviewer_key}).status_code==403


def test_workbench_samples_keep_independent_states(system):
    """四场示例分别读取自身state0，路径不可由客户端任意选择。"""
    api,_,settings,_,_ = system
    for name in ('event1','event2','event3','event4'):
        expected = json.loads((ROOT/'data'/'golden'/f'{name}_result.json').read_text(encoding='utf-8'))
        example = api.get('/workbench/examples/'+name,headers={'X-API-Key':settings.api_key})
        assert example.status_code==200
        assert example.json()['state0']==expected['state0']
        assert example.json()['csv_text']==(ROOT/'data'/'events'/f'{name}.csv').read_text(encoding='utf-8-sig')
    assert api.get('/workbench/examples/params_frozen',headers={'X-API-Key':settings.api_key}).status_code==404
    assert api.get('/workbench/examples/event1').status_code==401
