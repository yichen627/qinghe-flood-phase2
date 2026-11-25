"""单实例持久化预报worker，与独立调度/巡检进程解耦。"""
import logging
import signal
import time
from .model_client import ModelClient
from .repository import Repository
from .settings import Settings,model_version
from .services import run_one


def main():
    """轮询持久化队列，SIGTERM仅在当前任务结束后退出。"""
    settings = Settings.load()
    repo = Repository(settings.database)
    repo.initialize()
    repo.seed(settings,model_version())
    client = ModelClient(settings)
    running = True

    def stop(signum,frame):
        """通过局部闭包接收停止信号，不存储模型动态状态。"""
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    logging.basicConfig(level=logging.INFO)
    logging.info('forecast worker started')
    while running:
        try:
            worked = run_one(repo,settings,client)
            repo.heartbeat('worker',{'status':'ok','worked':worked})
        except Exception as exc:
            logging.exception('worker cycle failed')
            repo.heartbeat('worker',{'status':'error','error':str(exc)[:300]})
            worked = False
        if not worked:
            time.sleep(settings.rules['worker_poll_seconds'])


if __name__ == '__main__':
    main()
