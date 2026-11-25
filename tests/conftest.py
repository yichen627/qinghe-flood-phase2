"""独立临时数据库和模型HTTP测试客户端。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from dataclasses import replace
from fastapi.testclient import TestClient
from app.api import create_app
from app.model_api import create_app as create_model_app
from app.repository import Repository
from app.settings import Settings


@pytest.fixture
def system(tmp_path):
    """每项测试独立数据库；通过模型HTTP接口测试适配器。"""
    settings = replace(Settings.load(),database=str(tmp_path/'test.db'))
    repo = Repository(settings.database)
    repo.initialize()
    with TestClient(create_app(settings,repo)) as api,TestClient(create_model_app(settings)) as model:
        class Bridge:
            """测试传输替身，仅替换网络连接，不绕过模型HTTP处理。"""
            def simulate(self,request):
                """向模型接口发HTTP请求并检查状态码。"""
                response = model.post('/simulate',json=request,headers={'X-API-Key':settings.model_key})
                response.raise_for_status()
                return response.json()
        yield api,model,settings,repo,Bridge()
