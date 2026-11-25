"""单实例持久化预报worker；定时起报与巡检在后续阶段实现。"""
import logging
import signal
import time
from .model_client import ModelClient
from .repository import Repository
from .settings import Settings
from .services import run_one


def main():
    """轮询持久化队列，SIGTERM仅在当前任务结束后退出。"""
    settings = Settings.load()
    repo = Repository(settings.database)
    repo.initialize()
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
        if not run_one(repo,settings,client):
            time.sleep(settings.rules['worker_poll_seconds'])


if __name__ == '__main__':
    main()
