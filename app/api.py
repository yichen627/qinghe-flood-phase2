"""HTTP接口层，仅负责校验、鉴权、调用应用服务及序列化。"""
from contextlib import asynccontextmanager
import json
import secrets
from fastapi import FastAPI,Header,HTTPException,Query,Response
from fastapi.responses import JSONResponse
from .contracts import EventCreate,ForecastCreate,EventSummary,ForecastSummary
from .repository import Repository
from .settings import Settings,model_version
from . import services
from .governance_store import StoreConflict
from . import __version__


def create_app(settings=None,repository=None):
    """创建可测试实例；运行期状态只在数据库中，不放模型全局变量。"""
    settings = settings or Settings.load()
    repo = repository or Repository(settings.database)

    @asynccontextmanager
    async def lifespan(app):
        """启动时幂等创建持久化schema。"""
        repo.initialize()
        repo.seed(settings,model_version())
        yield

    app = FastAPI(title='Qinghe flood forecast system',version=__version__,lifespan=lifespan)

    @app.exception_handler(services.BusinessError)
    async def business_error(request,exc):
        """业务错误不伪装为成功HTTP200。"""
        return JSONResponse(status_code=exc.status,content={'detail':exc.detail})

    @app.exception_handler(StoreConflict)
    async def store_conflict(request,exc):
        """状态竞争与非法迁移返回409，不伪装成系统错误。"""
        return JSONResponse(status_code=409,content={'detail':str(exc)})

    def require_key(key,roles=('forecaster','reviewer','admin')):
        """从密钥确定身份，拒绝客户端自报身份或越权。"""
        credentials = {'forecaster':settings.api_key,'reviewer':settings.reviewer_key,'admin':settings.admin_key}
        for role,credential in credentials.items():
            if secrets.compare_digest(key.encode(),credential.encode()):
                if role not in roles:
                    raise HTTPException(403,'Role is not allowed for this operation')
                return role
        raise HTTPException(401,'Invalid API key')

    def require_row(table,identifier):
        """把实体不存在映射成404。"""
        row = repo.get(table,identifier)
        if row is None:
            raise HTTPException(404,'Resource not found')
        return row

    @app.get('/health')
    def health():
        """检查本应用数据库可读，模型健康由Compose单独检查。"""
        try:
            with repo.connect() as db:
                db.execute('SELECT COUNT(*) FROM forecasts').fetchone()
            return {'status':'ok','schema_version':2,'application_version':__version__}
        except Exception as exc:
            raise HTTPException(503,'Database unavailable') from exc

    @app.post('/events',status_code=201)
    def create_event(body:EventCreate,x_api_key:str=Header(default='')):
        """导入CSV并立即质控；ERROR数据也入库存档，禁止预测。"""
        actor = require_key(x_api_key,('forecaster','admin'))
        return services.import_event(repo,settings,body,actor)

    @app.get('/events',response_model=list[EventSummary])
    def list_events(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """分页查询导入及质控摘要。"""
        require_key(x_api_key)
        return [services.event_summary(r) for r in repo.listing('events',limit,offset)]

    @app.get('/events/{identifier}')
    def get_event(identifier:str,x_api_key:str=Header(default='')):
        """查询CSV原文、逐行问题、标准记录和独立初态。"""
        require_key(x_api_key)
        row = require_row('events',identifier)
        return {**services.event_summary(row),'raw_csv':row['raw_csv'],
                'issues':json.loads(row['issues_json']),'rows':json.loads(row['rows_json']),
                'state0':json.loads(row['state0_json']),'fingerprint':row['fingerprint']}

    @app.get('/schemes')
    def schemes(x_api_key:str=Header(default='')):
        """返回方案绑定版本、参数摘要和归档状态。"""
        require_key(x_api_key)
        rows = repo.listing('schemes',100,0)
        return [dict(row,params=json.loads(repo.get('parameter_sets',row['parameter_id'])['params_json']),
                     params_sha256=repo.get('parameter_sets',row['parameter_id'])['sha256']) for row in rows]

    @app.post('/forecasts',status_code=202,response_model=ForecastSummary)
    def create_forecast(body:ForecastCreate,x_api_key:str=Header(default='')):
        """创建QUEUED任务，由独立worker实际执行。"""
        actor = require_key(x_api_key,('forecaster','admin'))
        return services.queue_forecast(repo,settings,body,actor)

    @app.get('/forecasts',response_model=list[ForecastSummary])
    def list_forecasts(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """按创建时刻分页查询任务状态和指标。"""
        require_key(x_api_key)
        return [services.task_summary(r) for r in repo.listing('forecasts',limit,offset)]

    @app.get('/forecasts/{identifier}')
    def get_forecast(identifier:str,x_api_key:str=Header(default='')):
        """返回参数、输入、模型版本快照以及计算结果或失败原因。"""
        require_key(x_api_key)
        row = require_row('forecasts',identifier)
        return {**services.task_summary(row),'snapshot':json.loads(row['snapshot_json']),
                'result':json.loads(row['result_json']) if row['result_json'] else None}

    @app.get('/forecasts/{identifier}/plot.png',responses={200:{'content':{'image/png':{}}}})
    def plot(identifier:str,x_api_key:str=Header(default='')):
        """仅成功任务生成蓝色实测和橙色模拟PNG。"""
        require_key(x_api_key)
        row = require_row('forecasts',identifier)
        if row['status'] != 'SUCCEEDED':
            raise HTTPException(409,'Forecast has not succeeded')
        from .charts import forecast_png
        return Response(forecast_png(json.loads(row['snapshot_json']),json.loads(row['result_json'])),media_type='image/png')

    from .governance_api import register_routes
    register_routes(app,repo,settings,require_key)
    from .workbench import register_workbench
    register_workbench(app,require_key)
    return app


app = create_app()
