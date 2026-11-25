"""HTTP输入输出结构，供OpenAPI与运行校验共同使用。"""
from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field,FiniteFloat


class StrictInput(BaseModel):
    """禁止拼错字段被静默忽略。"""
    model_config = ConfigDict(extra='forbid')


class EventCreate(StrictInput):
    """UTF-8 CSV及该场独立初态；CSV路径不从客户端传入。"""
    name: str = Field(min_length=1,max_length=100)
    csv_text: str = Field(min_length=1,max_length=1048576)
    state0: dict[str,FiniteFloat]


class ForecastCreate(StrictInput):
    """选择事件和方案；不指定方案时按当前激活及灰度规则选择。"""
    event_id: str
    scheme_id: str|None = None


class ParameterCreate(StrictInput):
    """每次创建新不可变参数版本，不覆盖既有记录。"""
    name: str = Field(min_length=1,max_length=100)
    params: dict[str,Any]


class ModelCreate(StrictInput):
    """注册模型部署元信息，不接受上传并执行任意源代码。"""
    name: str = Field(min_length=1,max_length=100)
    version: str = Field(pattern=r'^[0-9a-f]{64}$')
    image_ref: str = Field(min_length=1,max_length=300)


class SchemeCreate(StrictInput):
    """方案绑定不可变参数版本与已登记模型版本。"""
    name: str = Field(min_length=1,max_length=100)
    parameter_id: str
    model_version: str


class RolloutCreate(StrictInput):
    """事件指纹稳定分桶，只影响未来未显式选择方案的任务。"""
    scheme_id: str
    percentage: int = Field(ge=0,le=100)


class ProductCreate(StrictInput):
    """仅从成功预报创建不可变产品草稿。"""
    forecast_id: str
    title: str = Field(min_length=1,max_length=200)


class ReviewCreate(StrictInput):
    """值班长复核意见。"""
    note: str = Field(min_length=1,max_length=2000)


class ScheduleCreate(StrictInput):
    """持久化间隔任务，可绑定固定方案或在触发时选择激活方案。"""
    name: str = Field(min_length=1,max_length=100)
    event_id: str
    scheme_id: str|None = None
    interval_seconds: int = Field(ge=1,le=31536000)
    next_run_at: str|None = None
    enabled: bool = True


class ScheduleToggle(StrictInput):
    """停用保留历史，不删除已有任务。"""
    enabled: bool


class ModelInput(StrictInput):
    """模型只接收雨量和蒸发，不接收实测流量。"""
    P: FiniteFloat = Field(ge=0)
    EM: FiniteFloat = Field(ge=0)


class SimulationRequest(StrictInput):
    """显式参数、初态及期望引擎版本。"""
    inputs: list[ModelInput] = Field(min_length=1,max_length=2000)
    params: dict[str,Any]
    state0: dict[str,Any]
    model_version: str


class Issue(BaseModel):
    """行号为CSV原始行号，severity控制是否允许计算。"""
    severity: Literal['ERROR','WARNING']
    code: str
    row: int
    field: str
    message: str


class EventSummary(BaseModel):
    """不在列表中重复传输CSV全文。"""
    id: str
    name: str
    created_at: str
    valid: bool
    row_count: int
    error_count: int
    warning_count: int


class ForecastSummary(BaseModel):
    """任务状态、指标、失败原因与版本摘要。"""
    id: str
    event_id: str
    scheme_id: str
    status: Literal['QUEUED','RUNNING','SUCCEEDED','FAILED']
    created_at: str
    updated_at: str
    error: str|None = None
    metrics: dict[str,float|int|None]|None = None
