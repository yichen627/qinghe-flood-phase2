"""独立持久调度进程：起报、周期质控、站内通知及心跳。"""
import logging
import signal
import time
from .repository import Repository
from .settings import Settings,model_version
from .workflows import scheduler_tick,quality_scan


def main():
    """单实例轮询，错误记录后继续，任务与通知均有数据库幂等键。"""
    settings = Settings.load()
    repo = Repository(settings.database)
    repo.initialize()
    repo.seed(settings,model_version())
    running = True
    next_quality = 0.
    logging.basicConfig(level=logging.INFO)

    def stop(signum,frame):
        """终止后不再启动新调度周期。"""
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    while running:
        detail = {'status':'ok'}
        try:
            detail['scheduled_count'] = scheduler_tick(repo,settings)
            if time.monotonic()>=next_quality:
                scan = quality_scan(repo,settings)
                detail['quality_scan_id'] = scan['id']
                next_quality = time.monotonic()+settings.rules['qc_interval_seconds']
            delivered = 0
            while delivered<settings.rules['notification_batch_size'] and repo.dispatch_one(settings.rules):
                delivered += 1
            detail['notification_count'] = delivered
        except Exception as exc:
            logging.exception('scheduler cycle failed')
            detail = {'status':'error','error':f'{type(exc).__name__}: {str(exc)[:300]}'}
        try:
            repo.heartbeat('scheduler',detail)
        except Exception:
            logging.exception('scheduler heartbeat failed')
        time.sleep(settings.rules['scheduler_poll_seconds'])


if __name__ == '__main__':
    main()
