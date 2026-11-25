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
    """显式选择事件和只读冻结方案。"""
    event_id: str
    scheme_id: Literal['phase1-frozen-v1'] = 'phase1-frozen-v1'


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
