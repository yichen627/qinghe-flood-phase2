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
        return cls(os.getenv('DATABASE_PATH',str(ROOT/'var'/'system.db')),
                   os.getenv('MODEL_URL','http://127.0.0.1:8001'),
                   os.getenv('API_KEY','qinghe-local-demo'),
                   os.getenv('MODEL_API_KEY','qinghe-model-demo'),rules,frozen['params'],actual)
