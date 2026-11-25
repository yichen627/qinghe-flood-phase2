"""把SQLite备份恢复到不存在的目标库并核对表数量与任务快照摘要。"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def inventory(db):
    """记录全部用户表行数与有序任务快照摘要，不输出业务内容。"""
    names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    counts = {name: db.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in names}
    snapshots = db.execute('SELECT id,snapshot_json FROM forecasts ORDER BY id').fetchall()
    return {'table_counts': counts, 'snapshots_sha256': hashlib.sha256(json.dumps(snapshots,ensure_ascii=False).encode()).hexdigest()}


def main():
    """恢复到隔离卷，不覆盖现有数据库；完整性或数据不一致时失败。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    source, target = Path(args.source).resolve(), Path(args.target).resolve()
    if target.exists():
        raise FileExistsError(target)
    if not source.is_file():
        raise FileNotFoundError(source)
    # 只用于已经通过backup API生成且不再写入的独立备份，不用于活动库。
    with sqlite3.connect(source.as_uri()+'?mode=ro&immutable=1',uri=True) as original:
        assert original.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        before = inventory(original)
        with sqlite3.connect(target) as restored:
            original.backup(restored)
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert restored.execute('PRAGMA foreign_key_check').fetchall()==[]
            after = inventory(restored)
            assert before==after
    print(json.dumps({'integrity':'ok','foreign_keys':'ok','inventory_equal':True,**after},indent=2))


if __name__=='__main__':
    main()
