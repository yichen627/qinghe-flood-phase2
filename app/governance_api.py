"""阶段3–4接口：角色校验后调用应用服务，数据库写入留在仓储。"""
from datetime import datetime,timezone
import json
from fastapi import Header,HTTPException,Query,Response
from .contracts import (ParameterCreate,ModelCreate,SchemeCreate,RolloutCreate,
                        ProductCreate,ReviewCreate,ScheduleCreate,ScheduleToggle)
from . import workflows as workflow
from .settings import model_version,encode


def register_routes(app,repo,settings,authorize):
    """注册方案、产品、回放、调度、巡检、通知和审计路由。"""
    @app.get('/models')
    def models(x_api_key:str=Header(default='')):
        """列出模型部署注册表。"""
        authorize(x_api_key)
        return repo.listing('model_versions',100,0)

    @app.post('/models',status_code=201)
    def create_model(body:ModelCreate,x_api_key:str=Header(default='')):
        """管理员登记模型镜像信息，不动态执行上传代码。"""
        actor = authorize(x_api_key,('admin',))
        identifier = repo.registry_create('model',body.name,body.model_dump(),actor)
        return repo.get('model_versions',identifier)

    @app.get('/parameter-sets')
    def parameters(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """分页查看不可变参数版本。"""
        authorize(x_api_key)
        return [workflow.decoded(r) for r in repo.listing('parameter_sets',limit,offset)]

    @app.post('/parameter-sets',status_code=201)
    def create_parameters(body:ParameterCreate,x_api_key:str=Header(default='')):
        """管理员创建新版本，已有版本不可修改删除。"""
        return workflow.create_parameters(repo,body,authorize(x_api_key,('admin',)))

    @app.post('/schemes',status_code=201)
    def create_scheme(body:SchemeCreate,x_api_key:str=Header(default='')):
        """创建绑定模型与参数版本的新方案。"""
        return workflow.create_scheme(repo,body,authorize(x_api_key,('admin',)))

    @app.get('/routing')
    def routing(x_api_key:str=Header(default='')):
        """查看活动、上一方案和灰度比例。"""
        authorize(x_api_key)
        return repo.routing_state()

    @app.post('/schemes/rollback')
    def rollback(x_api_key:str=Header(default='')):
        """管理员回滚至上一活动方案，不改变既有快照。"""
        return repo.switch_scheme(None,authorize(x_api_key,('admin',)),model_version(),rollback=True)

    @app.post('/schemes/{identifier}/activate')
    def activate(identifier:str,x_api_key:str=Header(default='')):
        """仅允许激活当前模型服务已部署的算法。"""
        return repo.switch_scheme(identifier,authorize(x_api_key,('admin',)),model_version())

    @app.post('/rollouts')
    def rollout(body:RolloutCreate,x_api_key:str=Header(default='')):
        """按事件指纹稳定分桶灰度，显式选择方案不经过分桶。"""
        return repo.switch_scheme(body.scheme_id,authorize(x_api_key,('admin',)),model_version(),body.percentage)

    @app.delete('/schemes/{identifier}',status_code=204)
    def archive(identifier:str,x_api_key:str=Header(default='')):
        """归档保留引用，活动或正在调度的方案不可归档。"""
        repo.archive_scheme(identifier,authorize(x_api_key,('admin',)))
        return Response(status_code=204)

    @app.post('/forecasts/{identifier}/replay',status_code=202)
    def replay(identifier:str,x_api_key:str=Header(default='')):
        """从原快照新建任务，同时保留原任务及比较结果。"""
        return workflow.replay(repo,settings,identifier,authorize(x_api_key,('forecaster','admin')))

    @app.get('/forecasts/{identifier}/analysis.md')
    def analysis(identifier:str,x_api_key:str=Header(default='')):
        """导出可复核的历史误差分析。"""
        authorize(x_api_key)
        return Response(workflow.analysis_markdown(repo,identifier),media_type='text/markdown',
                        headers={'Content-Disposition':'attachment; filename="error-analysis.md"'})

    @app.post('/products',status_code=201)
    def draft_product(body:ProductCreate,x_api_key:str=Header(default='')):
        """预报员或管理员从成功任务生成不可变草稿。"""
        return workflow.draft_product(repo,body,authorize(x_api_key,('forecaster','admin')))

    @app.get('/products')
    def products(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """内部产品列表，未发布内容不出现在匿名接口。"""
        authorize(x_api_key)
        return [workflow.decoded(r) for r in repo.listing('products',limit,offset)]

    @app.get('/products/{identifier}')
    def get_product(identifier:str,x_api_key:str=Header(default='')):
        """内部查看业务签名、复核意见和冻结内容。"""
        authorize(x_api_key)
        return workflow.product(repo,identifier)

    @app.post('/products/{identifier}/review')
    def review(identifier:str,body:ReviewCreate,x_api_key:str=Header(default='')):
        """只有值班长角色可复核，不允许草稿直接签发。"""
        actor = authorize(x_api_key,('reviewer',))
        repo.transition_product(identifier,'review',actor,body.note)
        return workflow.product(repo,identifier)

    @app.post('/products/{identifier}/sign')
    def sign(identifier:str,x_api_key:str=Header(default='')):
        """值班长签发已经复核的产品，记录内容摘要和时刻。"""
        repo.transition_product(identifier,'sign',authorize(x_api_key,('reviewer',)))
        return workflow.product(repo,identifier)

    @app.post('/products/{identifier}/publish')
    def publish(identifier:str,x_api_key:str=Header(default='')):
        """发布SIGNED产品并原子生成本地值班通知，不向外部发送。"""
        repo.transition_product(identifier,'publish',authorize(x_api_key,('reviewer',)))
        return workflow.product(repo,identifier)

    @app.get('/products/{identifier}/export.json')
    def export_product(identifier:str,x_api_key:str=Header(default='')):
        """签发后才允许导出正式JSON产品。"""
        authorize(x_api_key)
        product = workflow.product(repo,identifier)
        if product['status'] not in ('SIGNED','PUBLISHED'):
            raise HTTPException(409,'Only signed products can be exported')
        return Response(encode(product),media_type='application/json',
                        headers={'Content-Disposition':'attachment; filename="forecast-product.json"'})

    @app.get('/published/{identifier}')
    def published(identifier:str):
        """匿名端点仅返回已经发布的产品，不泄漏未签发草稿。"""
        return workflow.product(repo,identifier,public=True)

    @app.post('/schedules',status_code=201)
    def create_schedule(body:ScheduleCreate,x_api_key:str=Header(default='')):
        """创建间隔起报计划，服务重启后继续按数据库计划运行。"""
        return workflow.create_schedule(repo,settings,body,authorize(x_api_key,('admin',)))

    @app.get('/schedules')
    def schedules(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """查询计划及上次失败原因。"""
        authorize(x_api_key)
        return repo.listing('schedules',limit,offset)

    @app.patch('/schedules/{identifier}')
    def toggle_schedule(identifier:str,body:ScheduleToggle,x_api_key:str=Header(default='')):
        """启停任务，保留所有调度历史。"""
        actor = authorize(x_api_key,('admin',))
        workflow.require(repo,'schedules',identifier)
        repo.schedule_toggle(identifier,body.enabled,actor)
        return repo.get('schedules',identifier)

    @app.get('/schedule-runs')
    def schedule_runs(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """查看每次触发、关联预报及错误。"""
        authorize(x_api_key)
        return repo.listing('schedule_runs',limit,offset)

    @app.post('/quality/scans',status_code=201)
    def quality_scan(x_api_key:str=Header(default='')):
        """管理员可手动触发相同巡检逻辑，自动模式由scheduler独立执行。"""
        return workflow.quality_scan(repo,settings,authorize(x_api_key,('admin',)))

    @app.get('/quality/scans')
    def scans(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """查询巡检批次与异常事件数量。"""
        authorize(x_api_key)
        return repo.listing('qc_scans',limit,offset)

    @app.get('/alerts')
    def alerts(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """读取去重后的质控告警及确认信息。"""
        authorize(x_api_key,('reviewer','admin'))
        return [workflow.decoded(r) for r in repo.listing('alerts',limit,offset)]

    @app.post('/alerts/{identifier}/acknowledge')
    def acknowledge(identifier:str,x_api_key:str=Header(default='')):
        """值班长或管理员确认告警。"""
        actor = authorize(x_api_key,('reviewer','admin'))
        workflow.require(repo,'alerts',identifier)
        repo.acknowledge_alert(identifier,actor)
        return workflow.decoded(repo.get('alerts',identifier))

    @app.get('/notifications')
    def notifications(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """查询本地通知出站队列的投递状态和失败次数。"""
        authorize(x_api_key,('reviewer','admin'))
        return [workflow.decoded(r) for r in repo.listing('notification_outbox',limit,offset)]

    @app.post('/notifications/{identifier}/retry')
    def retry(identifier:str,x_api_key:str=Header(default='')):
        """管理员显式重试死信，DELIVERED不能再次投递。"""
        repo.retry_notification(identifier,authorize(x_api_key,('admin',)))
        return workflow.decoded(repo.get('notification_outbox',identifier))

    @app.get('/inbox')
    def inbox(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),x_api_key:str=Header(default='')):
        """站内值班收件箱，真实落库，不连接微信或邮件。"""
        authorize(x_api_key,('reviewer','admin'))
        return [workflow.decoded(r) for r in repo.listing('inbox',limit,offset)]

    @app.get('/audit')
    def audit(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),entity_id:str|None=None,
              x_api_key:str=Header(default='')):
        """按对象查询只追加的操作记录，角色身份从密钥推导。"""
        authorize(x_api_key,('reviewer','admin'))
        return [workflow.decoded(r) for r in repo.audit_listing(limit,offset,entity_id)]

    @app.get('/runtime')
    def runtime(x_api_key:str=Header(default='')):
        """查看worker与scheduler心跳及滞后，判断自动任务是否在运行。"""
        authorize(x_api_key)
        rows = {r['id']:workflow.decoded(r) for r in repo.listing('runtime_status',100,0)}
        for name in ('worker','scheduler'):
            row = rows.setdefault(name,{'id':name,'created_at':None,'detail':{}})
            age = (datetime.now(timezone.utc)-datetime.fromisoformat(row['created_at'])).total_seconds() if row['created_at'] else None
            row['stale'] = age is None or age>settings.rules['runtime_stale_seconds']
        return rows
