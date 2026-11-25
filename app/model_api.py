"""独立模型HTTP服务，无数据库依赖。"""
import secrets
from fastapi import FastAPI,Header,HTTPException
from .contracts import SimulationRequest
from .engine import simulate
from .settings import Settings,model_version


def create_app(settings=None):
    """创建独立服务实例，密钥与规则外置。"""
    settings = settings or Settings.load()
    app = FastAPI(title='Qinghe model service',version='0.2.0')

    @app.get('/health')
    def health():
        """返回算法版本供依赖检查。"""
        return {'status':'ok','model_version':model_version()}

    @app.post('/simulate')
    def run(body:SimulationRequest,x_api_key:str=Header(default='')):
        """执行纯函数模型；版本、物理边界及每步水量平衡均校验。"""
        if not secrets.compare_digest(x_api_key.encode(),settings.model_key.encode()):
            raise HTTPException(401,'Invalid model API key')
        if body.model_version != model_version():
            raise HTTPException(409,'Model source version mismatch')
        try:
            if len(body.inputs)>settings.rules['max_event_rows']:
                raise ValueError('模型输入超限')
            result = simulate([r.model_dump() for r in body.inputs],body.params,body.state0)
            if any(v > 1e-9 for v in result['initial_adjustment'].values()):
                raise ValueError('初态超容量，拒绝静默截断')
            return {k:v.tolist() if hasattr(v,'tolist') else v for k,v in result.items()}
        except (ValueError,KeyError,TypeError,AssertionError,OverflowError) as exc:
            raise HTTPException(422,str(exc)) from exc
    return app


app = create_app()
