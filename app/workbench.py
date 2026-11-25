"""本地预报工作台静态入口与经过认证的课程示例。"""
import json
from fastapi import Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .settings import ROOT


def register_workbench(app,authorize):
    """复用原服务认证，不在浏览器保存模型状态或另建数据库。"""
    @app.get('/',include_in_schema=False)
    def index():
        """提供真实预报工作台，API文档仍保留在/docs。"""
        return FileResponse(ROOT/'app'/'web'/'index.html',headers={'Cache-Control':'no-cache'})

    @app.get('/workbench/session')
    def session(x_api_key:str=Header(default='')):
        """由服务端确认角色，避免前端自行声明权限。"""
        return {'role':authorize(x_api_key)}

    @app.get('/workbench/examples/{name}')
    def example(name:str,x_api_key:str=Header(default='')):
        """仅允许四场既有课程数据和各自初态，不读取任意客户端路径。"""
        authorize(x_api_key,('forecaster','admin'))
        if name not in ('event1','event2','event3','event4'):
            raise HTTPException(404,'Example not found')
        baseline = json.loads((ROOT/'data'/'golden'/f'{name}_result.json').read_text(encoding='utf-8'))
        return {'name':name,'state0':baseline['state0'],
                'csv_text':(ROOT/'data'/'events'/f'{name}.csv').read_text(encoding='utf-8-sig')}

    app.mount('/assets',StaticFiles(directory=ROOT/'app'/'web'),name='workbench-assets')
