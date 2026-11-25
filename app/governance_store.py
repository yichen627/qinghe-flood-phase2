"""阶段3–4仓储扩展：所有写入与审计、通知事务保持一致。"""
from datetime import datetime,timezone,timedelta
import json
import uuid
from .settings import encode,digest


class StoreConflict(Exception):
    """状态、引用或并发操作冲突，接口映射为409。"""


def timestamp():
    """统一UTC ISO8601时间用于排序和租约。"""
    return datetime.now(timezone.utc).isoformat()


def audit(db,actor,action,entity_id,detail=None):
    """仅追加审计，禁止记录密钥。"""
    db.execute('INSERT INTO audit_log VALUES(?,?,?,?,?,?)',
               (uuid.uuid4().hex,timestamp(),actor,action,entity_id,encode(detail or {})))


def insert_task(db,event_id,scheme_id,snapshot,actor):
    """任务快照和创建审计在同一事务中写入。"""
    identifier = uuid.uuid4().hex
    time = timestamp()
    db.execute('INSERT INTO forecasts VALUES(?,?,?,?,?,?,?,?,?)',
               (identifier,event_id,scheme_id,'QUEUED',time,time,encode(snapshot),None,None))
    audit(db,actor,'forecast.queued',identifier,{'event_id':event_id,'scheme_id':scheme_id,
                                               'replay_of':snapshot.get('replay_of')})
    return identifier


def state(db):
    """读取路由状态，不在进程全局缓存动态方案。"""
    row = db.execute("SELECT value_json FROM system_state WHERE key='routing'").fetchone()
    return json.loads(row[0])


def outbox(db,key,kind,reference,payload):
    """同业务提交一起写出站通知，业务幂等键防止重复通知。"""
    time = timestamp()
    db.execute('INSERT OR IGNORE INTO notification_outbox '
               '(id,created_at,dedup_key,kind,reference_id,payload_json,status,available_at) VALUES(?,?,?,?,?,?,?,?)',
               (uuid.uuid4().hex,time,key,kind,reference,encode(payload),'PENDING',time))


class GovernanceStore:
    """被Repository复用的数据库操作，无HTTP和模型计算依赖。"""
    def seed(self,settings,version):
        """首次登记一期参数、当前部署版本和默认方案，不覆盖用户切换结果。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            time = timestamp()
            db.execute('INSERT OR IGNORE INTO model_versions VALUES(?,?,?,?)',
                       (version,'一期v2三水源引擎','qinghe-phase2:stage34',time))
            db.execute('INSERT OR IGNORE INTO parameter_sets VALUES(?,?,?,?,?)',
                       ('phase1-params-v1','一期冻结参数',encode(settings.params),settings.params_hash,time))
            db.execute('INSERT OR IGNORE INTO schemes VALUES(?,?,?,?,?,0)',
                       ('phase1-frozen-v1','一期冻结方案','phase1-params-v1',version,time))
            initial = {'active':'phase1-frozen-v1','previous':None,'canary':None,'percentage':0}
            changed = db.execute('INSERT OR IGNORE INTO system_state VALUES(?,?)',('routing',encode(initial)))
            if changed.rowcount:
                audit(db,'system','registry.seed','phase1-frozen-v1',{'model_version':version})

    def registry_create(self,kind,name,payload,actor):
        """登记不可变模型或参数元信息。"""
        identifier = payload['version'] if kind=='model' else uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if kind=='model':
                if db.execute('SELECT 1 FROM model_versions WHERE id=?',(identifier,)).fetchone():
                    raise StoreConflict('模型版本已经登记')
                db.execute('INSERT INTO model_versions VALUES(?,?,?,?)',
                           (identifier,name,payload['image_ref'],timestamp()))
            elif kind=='parameter':
                db.execute('INSERT INTO parameter_sets VALUES(?,?,?,?,?)',
                           (identifier,name,encode(payload['params']),payload['sha256'],timestamp()))
            else:
                raise ValueError('未知registry类型')
            audit(db,actor,kind+'.created',identifier,{'name':name})
        return identifier

    def scheme_create(self,name,parameter_id,version,actor):
        """显式绑定已存在的两个不可变版本。"""
        identifier = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO schemes VALUES(?,?,?,?,?,0)',
                       (identifier,name,parameter_id,version,timestamp()))
            audit(db,actor,'scheme.created',identifier,{'parameter_id':parameter_id,'model_version':version})
        return identifier

    def resolve_scheme(self,event_fingerprint,scheme_id=None):
        """在事务一致性读中解析显式、激活或稳定灰度分桶方案。"""
        with self.connect() as db:
            routing = state(db)
            selected = scheme_id or routing['active']
            if scheme_id is None and routing['canary']:
                bucket = int(event_fingerprint[:8],16)%100
                if bucket < routing['percentage']:
                    selected = routing['canary']
            row = db.execute('SELECT s.*,p.params_json,p.sha256 FROM schemes s JOIN parameter_sets p '
                             'ON s.parameter_id=p.id WHERE s.id=? AND s.deleted=0',(selected,)).fetchone()
        return dict(row) if row else None

    def routing_state(self):
        """返回当前路由及可回滚对象。"""
        with self.connect() as db:
            return state(db)

    def switch_scheme(self,scheme_id,actor,current_version,percentage=None,rollback=False):
        """激活、灰度和回滚原子更新，既有任务快照不变。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            routing = state(db)
            selected = routing['previous'] if rollback else scheme_id
            if not selected:
                raise StoreConflict('没有可回滚方案')
            scheme = db.execute('SELECT * FROM schemes WHERE id=? AND deleted=0',(selected,)).fetchone()
            if not scheme:
                raise StoreConflict('方案不存在或已归档')
            if scheme['model_version'] != current_version:
                raise StoreConflict('当前模型服务未部署此模型版本')
            before = dict(routing)
            if percentage is None:
                if selected != routing['active']:
                    routing['previous'],routing['active'] = routing['active'],selected
                routing.update(canary=None,percentage=0)
                action = 'scheme.rollback' if rollback else 'scheme.activated'
            else:
                routing.update(canary=selected if percentage else None,percentage=percentage)
                action = 'scheme.rollout'
            db.execute("UPDATE system_state SET value_json=? WHERE key='routing'",(encode(routing),))
            audit(db,actor,action,selected,{'before':before,'after':routing})
        return routing

    def archive_scheme(self,identifier,actor):
        """归档而非物理删除；保留所有历史引用，活动方案禁止归档。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            routing = state(db)
            if identifier in ('phase1-frozen-v1',routing['active'],routing['canary'],routing['previous']):
                raise StoreConflict('内置、活动、灰度或待回滚方案不可归档')
            if db.execute('SELECT 1 FROM schedules WHERE scheme_id=? AND enabled=1',(identifier,)).fetchone():
                raise StoreConflict('方案仍被启用的定时任务引用，请先停用任务')
            result = db.execute('UPDATE schemes SET deleted=1 WHERE id=? AND deleted=0',(identifier,))
            if not result.rowcount:
                raise StoreConflict('方案不存在或已归档')
            audit(db,actor,'scheme.archived',identifier)

    def product_create(self,forecast_id,title,content,actor):
        """保存不可变草稿及来源摘要。"""
        identifier,time = uuid.uuid4().hex,timestamp()
        with self.connect() as db:
            db.execute('INSERT INTO products '
                       '(id,forecast_id,title,status,created_at,updated_at,content_json,content_sha256) VALUES(?,?,?,?,?,?,?,?)',
                       (identifier,forecast_id,title,'DRAFT',time,time,encode(content),digest(content)))
            audit(db,actor,'product.drafted',identifier,{'forecast_id':forecast_id,'content_sha256':digest(content)})
        return identifier

    def transition_product(self,identifier,action,actor,note=None):
        """复核、签发、发布严格状态机；发布与通知同一事务。"""
        transitions = {'review':('DRAFT','REVIEWED'),'sign':('REVIEWED','SIGNED'),
                       'publish':('SIGNED','PUBLISHED')}
        before,after = transitions[action]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM products WHERE id=?',(identifier,)).fetchone()
            if not row or row['status'] != before:
                raise StoreConflict(f'产品必须处于{before}状态')
            if digest(json.loads(row['content_json'])) != row['content_sha256']:
                raise StoreConflict('产品内容摘要不符，禁止签发发布')
            time = timestamp()
            columns = {'review':('reviewed_by','reviewed_at'),'sign':('signed_by','signed_at'),
                       'publish':('published_by','published_at')}
            actor_col,time_col = columns[action]
            db.execute(f'UPDATE products SET status=?,updated_at=?,{actor_col}=?,{time_col}=? WHERE id=?',
                       (after,time,actor,time,identifier))
            if action=='review':
                db.execute('UPDATE products SET review_note=? WHERE id=?',(note,identifier))
            audit(db,actor,'product.'+action,identifier,{'from':before,'to':after,'note':note})
            if action=='publish':
                outbox(db,'product:'+identifier,'PRODUCT_PUBLISHED',identifier,
                       {'product_id':identifier,'title':row['title'],'content_sha256':row['content_sha256'],
                        'signed_by':row['signed_by'],'signed_at':row['signed_at'],'published_at':time})

    def save_quality_scan(self,checks,rules,actor):
        """写巡检结果、去重告警及出站通知，不覆盖原始CSV。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            error_count = 0
            for event_id,issues in checks:
                db.execute('INSERT INTO qc_status VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                           'created_at=excluded.created_at,issues_json=excluded.issues_json,rules_sha256=excluded.rules_sha256',
                           (event_id,timestamp(),encode(issues),digest(rules)))
                relevant = [i for i in issues if i['severity']=='ERROR' or rules['qc_alert_severity']=='WARNING']
                if not relevant:
                    continue
                error_count += 1
                identifier = uuid.uuid4().hex
                signature = digest({'issues':relevant,'rules':rules})
                inserted = db.execute('INSERT OR IGNORE INTO alerts '
                                      '(id,event_id,signature,created_at,issues_json) VALUES(?,?,?,?,?)',
                                      (identifier,event_id,signature,timestamp(),encode(relevant)))
                if inserted.rowcount:
                    audit(db,actor,'quality.alert',identifier,{'event_id':event_id,'issue_count':len(relevant)})
                    outbox(db,'alert:'+identifier,'QUALITY_ALERT',identifier,
                           {'alert_id':identifier,'event_id':event_id,'issues':relevant})
            scan_id = uuid.uuid4().hex
            db.execute('INSERT INTO qc_scans VALUES(?,?,?,?)',(scan_id,timestamp(),len(checks),error_count))
            audit(db,actor,'quality.scan',scan_id,{'checked_count':len(checks),'error_event_count':error_count})
        return scan_id

    def acknowledge_alert(self,identifier,actor):
        """确认告警幂等，保留第一次确认人和时刻。"""
        with self.connect() as db:
            changed = db.execute('UPDATE alerts SET acknowledged_by=?,acknowledged_at=? '
                                 'WHERE id=? AND acknowledged_at IS NULL',(actor,timestamp(),identifier))
            if changed.rowcount:
                audit(db,actor,'alert.acknowledged',identifier)

    def schedule_create(self,body,due,actor):
        """持久化定时计划，重启后仍按next_run_at触发。"""
        identifier = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?,?)',
                       (identifier,body.name,body.event_id,body.scheme_id,body.interval_seconds,
                        int(body.enabled),due,timestamp(),None))
            audit(db,actor,'schedule.created',identifier,body.model_dump())
        return identifier

    def schedule_toggle(self,identifier,enabled,actor):
        """停用不删除计划及历史，启用后合并错过的触发。"""
        with self.connect() as db:
            db.execute('UPDATE schedules SET enabled=? WHERE id=?',(int(enabled),identifier))
            audit(db,actor,'schedule.enabled' if enabled else 'schedule.disabled',identifier)

    def due_schedules(self,limit,current):
        """按UTC到期时间读取有限批次，实际提交再次校验版本。"""
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM schedules WHERE enabled=1 AND next_run_at<=? '
                                               'ORDER BY next_run_at,id LIMIT ?',(current,limit))]

    def commit_schedule_run(self,schedule,snapshot,scheme_id,next_due,error=None):
        """起报、计划推进和审计原子提交；并发同一触发最多生成一次。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM schedules WHERE id=?',(schedule['id'],)).fetchone()
            if not current or not current['enabled'] or current['next_run_at'] != schedule['next_run_at']:
                return None
            forecast_id = insert_task(db,schedule['event_id'],scheme_id,snapshot,'scheduler') if not error else None
            run_id = uuid.uuid4().hex
            db.execute('INSERT INTO schedule_runs VALUES(?,?,?,?,?,?)',
                       (run_id,schedule['id'],schedule['next_run_at'],timestamp(),forecast_id,error))
            db.execute('UPDATE schedules SET next_run_at=?,last_error=? WHERE id=?',(next_due,error,schedule['id']))
            audit(db,'scheduler','schedule.triggered' if not error else 'schedule.failed',schedule['id'],
                  {'forecast_id':forecast_id,'scheduled_for':schedule['next_run_at'],'error':error})
            if error:
                outbox(db,'schedule-failure:'+run_id,'SCHEDULE_FAILED',schedule['id'],
                       {'schedule_id':schedule['id'],'scheduled_for':schedule['next_run_at'],'error':error})
            return run_id

    def dispatch_one(self,rules,fail_reason=None):
        """本地收件箱投递与出站状态同事务；失败退避，达到上限进入FAILED。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM notification_outbox WHERE status='PENDING' AND available_at<=? "
                             'ORDER BY created_at,id LIMIT 1',(timestamp(),)).fetchone()
            if not row:
                return False
            attempts = row['attempts']+1
            db.execute('SAVEPOINT delivery')
            try:
                if fail_reason:
                    raise RuntimeError(fail_reason)
                json.loads(row['payload_json'])
                db.execute('INSERT OR IGNORE INTO inbox VALUES(?,?,?,?,?)',
                           (uuid.uuid4().hex,row['id'],timestamp(),'duty-room',row['payload_json']))
                db.execute("UPDATE notification_outbox SET attempts=?,status='DELIVERED',delivered_at=?,last_error=NULL WHERE id=?",
                           (attempts,timestamp(),row['id']))
                db.execute('RELEASE delivery')
                audit(db,'scheduler','notification.delivered',row['id'],{'channel':'local-duty-inbox'})
            except Exception as exc:
                db.execute('ROLLBACK TO delivery')
                db.execute('RELEASE delivery')
                status = 'FAILED' if attempts>=rules['notification_max_attempts'] else 'PENDING'
                next_time = (datetime.now(timezone.utc)+timedelta(seconds=rules['notification_retry_seconds'])).isoformat()
                db.execute('UPDATE notification_outbox SET attempts=?,status=?,available_at=?,last_error=? WHERE id=?',
                           (attempts,status,next_time,str(exc)[:300],row['id']))
                audit(db,'scheduler','notification.failed',row['id'],{'attempt':attempts,'status':status})
        return True

    def retry_notification(self,identifier,actor):
        """死信显式重试，不允许重复投递已成功消息。"""
        with self.connect() as db:
            changed = db.execute("UPDATE notification_outbox SET status='PENDING',attempts=0,available_at=?,last_error=NULL "
                                 "WHERE id=? AND status='FAILED'",(timestamp(),identifier))
            if not changed.rowcount:
                raise StoreConflict('只有FAILED通知可重试')
            audit(db,actor,'notification.retry',identifier)

    def heartbeat(self,name,detail):
        """持久化进程运行状态，便于检测调度停止。"""
        with self.connect() as db:
            db.execute('INSERT INTO runtime_status VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'created_at=excluded.created_at,detail_json=excluded.detail_json',
                       (name,timestamp(),encode(detail)))

    def add_audit(self,actor,action,entity_id,detail=None):
        """写只追加的系统操作记录。"""
        with self.connect() as db:
            audit(db,actor,action,entity_id,detail)

    def all_events(self):
        """巡检读取所有持久化事件，包含被阻断的坏数据。"""
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM events ORDER BY created_at,id')]

    def audit_listing(self,limit,offset,entity_id=None):
        """按对象筛选操作链；支持分页，避免无限日志响应。"""
        with self.connect() as db:
            if entity_id:
                rows = db.execute('SELECT * FROM audit_log WHERE entity_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                                  (entity_id,limit,offset))
            else:
                rows = db.execute('SELECT * FROM audit_log ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(limit,offset))
            return [dict(r) for r in rows]
