"""从干净Git提交生成工程包、文档包、完整历史和SHA256清单。"""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    """在项目仓库执行Git并保留失败信息。"""
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def main():
    """只打包受Git跟踪的已提交文件，避免泄漏本机数据库和凭据。"""
    if git('status', '--porcelain').strip():
        raise RuntimeError('Commit or resolve all tracked and untracked changes before packaging')
    target = ROOT / 'delivery'
    target.mkdir(exist_ok=True)
    commit = git('rev-parse', 'HEAD').decode().strip()
    branch = git('branch', '--show-current').decode().strip()
    paths = [p.decode('utf-8') for p in git('ls-files', '-z').split(b'\0') if p]
    assert 'reports/陈一_2406050103_洪水预报系统二期总结报告.docx' in paths
    assert 'reports/陈一_2406050103_洪水预报系统二期总结报告.pdf' in paths
    bundle = target / 'qinghe-history.bundle'
    subprocess.run(['git', '-C', str(ROOT), 'bundle', 'create', str(bundle), '--all'], check=True)
    subprocess.run(['git', '-C', str(ROOT), 'bundle', 'verify', str(bundle)], check=True)
    manifest = {'version': '1.0.0', 'commit': commit, 'branch': branch,
                'files': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}}
    for name, chosen in [('qinghe-phase2-source.zip', paths),
                         ('qinghe-phase2-documents.zip', [p for p in paths if p.startswith(('docs/', 'reports/')) or p=='README.md'])]:
        with zipfile.ZipFile(target/name, 'w', zipfile.ZIP_DEFLATED) as archive:
            for p in chosen:
                archive.write(ROOT/p, 'qinghe-phase2/'+p)
            archive.writestr('qinghe-phase2/DELIVERY_MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(target/name) as archive:
            assert archive.testzip() is None
    outputs = [bundle, target/'qinghe-phase2-source.zip', target/'qinghe-phase2-documents.zip']
    checksums = '\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in outputs)+'\n'
    (target/'SHA256SUMS.txt').write_text(checksums, encoding='utf-8')
    (target/'DELIVERY_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'commit': commit, 'outputs': [str(p) for p in outputs]}, ensure_ascii=False, indent=2))


if __name__=='__main__':
    main()
