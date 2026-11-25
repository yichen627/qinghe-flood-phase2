"""SQLite仓储层，只负责存储、状态迁移和事务。"""
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import json
import sqlite3
import uuid
from .settings import encode


def now():
    """UTC审计时刻，业务CSV保留Asia/Shanghai偏移。"""
    return datetime.now(timezone.utc).isoformat()


class Repository:
    """每次操作独立连接；HTTP调用期间不占SQLite写锁。"""
    def __init__(self,path):
        """初始化数据库路径，禁止把连接跨线程共享。"""
        self.path = path

    @contextmanager
    def connect(self):
        """在退出时提交或回滚并关闭连接。"""
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        connection = sqlite3.connect(self.path,timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        """幂等创建schema v1；后续结构修改必须迁移而非重建。"""
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):
                raise RuntimeError('不支持的数据库版本')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS events(
              id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL UNIQUE,name TEXT NOT NULL,
              created_at TEXT NOT NULL,raw_csv TEXT NOT NULL,rows_json TEXT NOT NULL,
              issues_json TEXT NOT NULL,state0_json TEXT NOT NULL,valid INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS forecasts(
              id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),
              scheme_id TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN
              ('QUEUED','RUNNING','SUCCEEDED','FAILED')),created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,snapshot_json TEXT NOT NULL,
              result_json TEXT,error TEXT);
            CREATE INDEX IF NOT EXISTS forecasts_status ON forecasts(status,created_at);
            PRAGMA user_version=1;
            ''')

    def insert_event(self,fingerprint,name,raw,rows,issues,state):
        """原文与规范化记录一并入库，幂等指纹避免重复覆盖。"""
        with self.connect() as db:
            identifier = uuid.uuid4().hex
            db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?)',
                       (identifier,fingerprint,name,now(),raw,encode(rows),encode(issues),
                        encode(state),int(not any(i['severity']=='ERROR' for i in issues))))
            row = dict(db.execute('SELECT * FROM events WHERE fingerprint=?',(fingerprint,)).fetchone())
        return row,row['id'] != identifier

    def get(self,table,identifier):
        """仅允许访问已知实体，值参数绑定，找不到返回None。"""
        if table not in ('events','forecasts'):
            raise ValueError('未知实体')
        with self.connect() as db:
            row = db.execute(f'SELECT * FROM {table} WHERE id=?',(identifier,)).fetchone()
        return dict(row) if row else None

    def listing(self,table,limit,offset):
        """稳定分页，限制在接口层验证。"""
        if table not in ('events','forecasts'):
            raise ValueError('未知实体')
        with self.connect() as db:
            return [dict(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                                               (limit,offset)).fetchall()]

    def queue(self,event_id,scheme_id,snapshot):
        """任务创建即冻结完整输入、模型、参数和初态快照。"""
        identifier = uuid.uuid4().hex
        timestamp = now()
        with self.connect() as db:
            db.execute('INSERT INTO forecasts VALUES(?,?,?,?,?,?,?,?,?)',
                       (identifier,event_id,scheme_id,'QUEUED',timestamp,timestamp,encode(snapshot),None,None))
        return self.get('forecasts',identifier)

    def claim(self,lease_seconds):
        """单worker原子领取；失联任务保留FAILED记录，不静默重算。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE forecasts SET status='FAILED',error='Worker lease expired',updated_at=? "
                       "WHERE status='RUNNING' AND (julianday(?) - julianday(updated_at))*86400 > ?",
                       (now(),now(),lease_seconds))
            row = db.execute("SELECT * FROM forecasts WHERE status='QUEUED' ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE forecasts SET status='RUNNING',updated_at=? WHERE id=? AND status='QUEUED'",
                       (now(),row['id']))
            return dict(row)

    def finish(self,identifier,result=None,error=None):
        """只允许RUNNING任务完成，避免覆盖已有终态。"""
        with self.connect() as db:
            updated = db.execute("UPDATE forecasts SET status=?,result_json=?,error=?,updated_at=? WHERE id=? AND status='RUNNING'",
                                 ('FAILED' if error else 'SUCCEEDED',None if result is None else encode(result),error,now(),identifier))
            if updated.rowcount != 1:
                raise RuntimeError('任务不是RUNNING，拒绝覆盖')
