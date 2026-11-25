"""容器心跳健康检查，不启动HTTP或调度器。"""
from datetime import datetime,timezone
import json
import sys
from .repository import Repository
from .settings import Settings


def main():
    """最近心跳正常且未超时才返回成功。"""
    settings = Settings.load()
    row = Repository(settings.database).get('runtime_status',sys.argv[1])
    if not row:
        raise SystemExit(1)
    age = (datetime.now(timezone.utc)-datetime.fromisoformat(row['created_at'])).total_seconds()
    if age>settings.rules['runtime_stale_seconds'] or json.loads(row['detail_json']).get('status')!='ok':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
