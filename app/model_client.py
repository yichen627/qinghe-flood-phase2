"""模型HTTP适配器，应用服务不直接调用引擎simulate。"""
import httpx


class ModelClient:
    """设置明确超时，默认不自动重试不确定请求。"""
    def __init__(self,settings):
        """保存不可变连接配置。"""
        self.settings = settings

    def simulate(self,request):
        """通过独立HTTP服务执行模型，HTTP错误交由任务层记录。"""
        with httpx.Client(timeout=self.settings.rules['model_timeout_seconds'],trust_env=False) as client:
            response = client.post(self.settings.model_url+'/simulate',json=request,
                                   headers={'X-API-Key':self.settings.model_key})
            response.raise_for_status()
            return response.json()
