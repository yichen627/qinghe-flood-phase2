"""外置配置与稳定摘要，不包含动态模型状态。"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os

ROOT = Path(__file__).resolve().parents[1]


def encode(value):
    """严格JSON编码，禁止NaN与Infinity进入持久化快照。"""
    return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)


def digest(value):
    """对结构化对象生成稳定SHA256摘要。"""
    return hashlib.sha256(encode(value).encode()).hexdigest()


def model_version():
    """统一CRLF/LF后计算引擎源码摘要，使Windows和容器版本一致。"""
    content = (ROOT/'app'/'engine.py').read_text(encoding='utf-8')
    return hashlib.sha256(content.encode()).hexdigest()


@dataclass(frozen=True)
class Settings:
    """每个应用实例独立配置，参数只读、模型状态不保存在这里。"""
    database: str
    model_url: str
    api_key: str
    model_key: str
    rules: dict
    params: dict
    params_hash: str
    reviewer_key: str = 'qinghe-reviewer-demo'
    admin_key: str = 'qinghe-admin-demo'

    @classmethod
    def load(cls):
        """读取环境及配置文件并验证课程单位、权重和冻结参数。"""
        rules = json.loads(Path(os.getenv('SETTINGS_FILE',ROOT/'config'/'settings.json')).read_text(encoding='utf-8'))
        frozen = json.loads((ROOT/'config'/'params_frozen.json').read_text(encoding='utf-8'))
        # 一期冻结摘要使用默认ensure_ascii编码，保持原始校验算法。
        actual = hashlib.sha256(json.dumps(frozen['params'],sort_keys=True,allow_nan=False).encode()).hexdigest()
        if actual != frozen['sha256']:
            raise ValueError('一期冻结参数被修改')
        if rules['unit_conversion'] != 92.6 or rules['dt_hours'] != 6:
            raise ValueError('课程单位配置错误')
        weights = rules['station_weights']
        if len(weights) != 6 or any(v < 0 for v in weights.values()) or abs(sum(weights.values())-1)>1e-9:
            raise ValueError('六站泰森权重非法')
        instance = cls(os.getenv('DATABASE_PATH',str(ROOT/'var'/'system.db')),
                   os.getenv('MODEL_URL','http://127.0.0.1:8001'),
                   os.getenv('API_KEY','qinghe-local-demo'),
                   os.getenv('MODEL_API_KEY','qinghe-model-demo'),rules,frozen['params'],actual,
                   os.getenv('REVIEWER_API_KEY','qinghe-reviewer-demo'),
                   os.getenv('ADMIN_API_KEY','qinghe-admin-demo'))
        if len({instance.api_key,instance.admin_key,instance.reviewer_key,instance.model_key}) != 4:
            raise ValueError('四类密钥必须不同，避免角色越权')
        positive = ('model_timeout_seconds','worker_poll_seconds','task_lease_seconds','scheduler_poll_seconds',
                    'qc_interval_seconds','schedule_min_interval_seconds','schedule_batch_size',
                    'notification_batch_size','notification_max_attempts','notification_retry_seconds',
                    'runtime_stale_seconds')
        if any(not isinstance(rules[k],(int,float)) or rules[k]<=0 for k in positive):
            raise ValueError('调度、租约、批量和重试配置必须为正数')
        if rules['qc_alert_severity'] not in ('ERROR','WARNING'):
            raise ValueError('质控告警级别只能为ERROR或WARNING')
        if rules['task_lease_seconds']<=rules['model_timeout_seconds']+rules['worker_poll_seconds']:
            raise ValueError('任务租约必须大于单次HTTP超时及轮询时间')
        if rules['runtime_stale_seconds']<=rules['model_timeout_seconds']:
            raise ValueError('心跳有效期必须大于模型HTTP超时')
        if rules['qc_interval_seconds']+rules['scheduler_poll_seconds']>300:
            raise ValueError('自动质控周期不得超过UC5的5分钟目标')
        return instance
