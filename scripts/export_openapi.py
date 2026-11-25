"""导出实际API结构为版本化契约，不启动数据库或网络服务。"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.api import create_app
from app.model_api import create_app as create_model_app


def main():
    """生成两份与实际接口一致的OpenAPI JSON。"""
    target = Path(__file__).resolve().parents[1]/'docs'
    for name,app in [('openapi.json',create_app()),('model-openapi.json',create_model_app())]:
        (target/name).write_text(json.dumps(app.openapi(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
