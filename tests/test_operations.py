import importlib.util
import json
from datetime import datetime,timedelta,timezone


def load(root,name):
    spec=importlib.util.spec_from_file_location('ops_'+name,root/'ops'/(name+'.py'))
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def test_backup_retention_preserves_daily_and_weekly_and_rejects_symlink(tmp_path):
    from pathlib import Path
    import pytest
    module=load(Path(__file__).parents[1],'backup'); module.BACKUPS=tmp_path
    now=datetime(2026,10,12,tzinfo=timezone.utc)
    for n in range(40):
        name='live-db-'+str(n)
        (tmp_path/(name+'.age')).write_bytes(b'encrypted-fixture')
        (tmp_path/(name+'.json')).write_text(json.dumps({'createdAt':(now-timedelta(days=n)).isoformat(),'filename':name+'.age'}))
    module.retention(tmp_path)
    retained=list(tmp_path.glob('*.age'))
    assert 7<=len(retained)<=11
    assert all((tmp_path/('live-db-'+str(n)+'.age')).exists() for n in range(7))
    foreign=tmp_path/'foreign.age'; foreign.symlink_to(tmp_path/'live-db-0.age')
    (tmp_path/'live-db-unsafe.json').write_text(json.dumps({'createdAt':now.isoformat(),'filename':'foreign.age'}))
    with pytest.raises(ValueError,match='invalid archive'): module.retention(tmp_path)
