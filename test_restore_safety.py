import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
from alert_notes import database_bundle as bundle
from alert_notes.external_ai_policy import ExternalAIPolicy
from alert_notes.sqlite_store import NoteReminderStore,SETTING_COLUMNS

@pytest.fixture
def pair(tmp_path):
    conns=[]
    for name in ['a','b']:
        conn=sqlite3.connect(tmp_path/(name+'.db'))
        conn.execute('CREATE TABLE records(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
        conn.execute("INSERT INTO records VALUES(1,'before')");conn.commit()
        conns.append(conn)
    yield conns
    for conn in conns: conn.close()

def targets(pair):return {k:(c,{'records':('id','value')}) for k,c in zip(['a','b'],pair)}
def backup(tmp_path,rows=None):
    rows=rows or [{'id':1,'value':'after'}]
    p=tmp_path/'bundle.json'
    p.write_text(json.dumps({'format':'sqlite-database-bundle','version':1,'databases':{
        'a':{'records':[{'id':1,'value':'after'}]},'b':{'records':rows}}}),encoding='utf-8')
    return p
def values(pair):return [c.execute('SELECT value FROM records').fetchone()[0] for c in pair]

def test_success_both_connections_observe_one_commit(pair,tmp_path):
    assert bundle.import_database_bundle(targets(pair),backup(tmp_path))=={'a','b'}
    assert values(pair)==['after','after']

def test_second_database_constraint_failure_rolls_back_both(pair,tmp_path):
    path=backup(tmp_path,[{'id':1,'value':'x'},{'id':1,'value':'y'}])
    with pytest.raises(sqlite3.IntegrityError):bundle.import_database_bundle(targets(pair),path)
    assert values(pair)==['before','before']

@pytest.mark.parametrize('bad',[{},[],None,{'records':None},{'records':[None]},{'records':[{'value':'no id'}]},{'records':[{'id':1,'value':{}}]}])
def test_bad_structure_rejected_before_any_change(pair,tmp_path,bad):
    path=backup(tmp_path); payload=json.loads(path.read_text())
    payload['databases']['b']=bad;path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):bundle.import_database_bundle(targets(pair),path)
    assert values(pair)==['before','before']

@pytest.mark.parametrize('version',[0,2,True,'1'])
def test_unknown_version_rejected(pair,tmp_path,version):
    path=backup(tmp_path);p=json.loads(path.read_text());p['version']=version;path.write_text(json.dumps(p))
    with pytest.raises(ValueError):bundle.import_database_bundle(targets(pair),path)
    assert values(pair)==['before','before']

def test_injected_write_failure_rolls_back_all(pair,tmp_path,monkeypatch):
    real=bundle._insert_rows
    def fail(conn,table,columns,rows,database='main'):
        if database=='restore_1':raise sqlite3.OperationalError('simulated disk write failure')
        return real(conn,table,columns,rows,database)
    monkeypatch.setattr(bundle,'_insert_rows',fail)
    with pytest.raises(sqlite3.OperationalError):bundle.import_database_bundle(targets(pair),backup(tmp_path))
    assert values(pair)==['before','before']

def test_foreign_key_failure_rolls_back_all(pair,tmp_path):
    pair[1].execute('CREATE TABLE child(id INTEGER PRIMARY KEY,parent INTEGER REFERENCES records(id))')
    pair[1].execute('INSERT INTO child VALUES(1,1)');pair[1].commit()
    path=backup(tmp_path,[{'id':2,'value':'would orphan child'}])
    with pytest.raises(ValueError,match='참조'):bundle.import_database_bundle(targets(pair),path)
    assert values(pair)==['before','before']

def test_wal_is_rejected_without_changing_journal_mode(pair,tmp_path):
    pair[1].execute('PRAGMA journal_mode=WAL')
    with pytest.raises(ValueError,match='저널'):bundle.import_database_bundle(targets(pair),backup(tmp_path))
    assert values(pair)==['before','before']
    assert pair[1].execute('PRAGMA journal_mode').fetchone()[0]=='wal'

def test_pending_changes_are_not_committed(pair,tmp_path):
    pair[1].execute("UPDATE records SET value='unsaved'")
    with pytest.raises(ValueError):bundle.import_database_bundle(targets(pair),backup(tmp_path))
    assert pair[1].in_transaction
    pair[1].rollback();assert values(pair)==['before','before']

def test_write_lock_failure_leaves_other_database_unchanged(pair,tmp_path):
    pair[1].execute('BEGIN IMMEDIATE')
    # Pending caller transactions are rejected before opening a coordinator.
    with pytest.raises(ValueError):bundle.import_database_bundle(targets(pair),backup(tmp_path))
    pair[1].rollback();assert values(pair)==['before','before']

@pytest.mark.parametrize('backed_up,current',[(True,False),(False,True),(True,True),(False,False)])
def test_restore_always_blocks_ai(tmp_path,backed_up,current):
    store=NoteReminderStore(tmp_path/'notes.db')
    try:
        p=ExternalAIPolicy(store);p.save(backed_up)
        sources={'notes':(store.conn,{'settings':SETTING_COLUMNS})}
        path=bundle.export_database_bundle(sources,tmp_path/'settings.json');p.save(current)
        bundle.import_database_bundle(sources,path)
        assert not p.allowed
        with pytest.raises(PermissionError):p.require_provider()
    finally:store.close()

def test_backup_failure_preserves_previous_file(pair,tmp_path,monkeypatch):
    path=tmp_path/'existing.json';path.write_text('previous backup')
    monkeypatch.setattr(bundle.os,'replace',lambda *a:(_ for _ in ()).throw(OSError('failure')))
    with pytest.raises(OSError):bundle.export_database_bundle(targets(pair),path)
    assert path.read_text()=='previous backup'
    assert not list(tmp_path.glob('.bundle-*.tmp'))

def test_explicit_empty_table_is_valid(pair,tmp_path):
    path=backup(tmp_path);payload=json.loads(path.read_text());payload['databases']['b']['records']=[]
    path.write_text(json.dumps(payload));bundle.import_database_bundle(targets(pair),path)
    assert pair[1].execute('SELECT count(*) FROM records').fetchone()[0]==0

def test_omitted_database_is_preserved(pair,tmp_path):
    path=backup(tmp_path);payload=json.loads(path.read_text());del payload['databases']['b']
    path.write_text(json.dumps(payload));bundle.import_database_bundle(targets(pair),path)
    assert values(pair)==['after','before']

def test_process_exit_before_commit_recovers_both_databases(pair,tmp_path):
    path=backup(tmp_path)
    script=tmp_path/'crash_restore.py'
    script.write_text('''import sys,sqlite3,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from alert_notes import database_bundle as b
conns=[sqlite3.connect(p) for p in sys.argv[2:4]]
real=b._insert_rows
def crash(conn,table,columns,rows,database='main'):
    real(conn,table,columns,rows,database)
    if database=='restore_1': os._exit(17)
b._insert_rows=crash
b.import_database_bundle({k:(c,{'records':('id','value')}) for k,c in zip(['a','b'],conns)},Path(sys.argv[4]))
''',encoding='utf-8')
    result=subprocess.run([sys.executable,str(script),str(Path(__file__).parent),str(tmp_path/'a.db'),str(tmp_path/'b.db'),str(path)],timeout=30)
    assert result.returncode==17
    assert values(pair)==['before','before']

def test_read_only_target_is_not_bypassed(pair,tmp_path):
    pair[1].execute('PRAGMA query_only=ON')
    with pytest.raises(ValueError,match='읽기 전용'):bundle.import_database_bundle(targets(pair),backup(tmp_path))
    assert values(pair)==['before','before']

def test_commit_failure_rolls_back_all(pair,tmp_path,monkeypatch):
    real=sqlite3.connect
    def connect(*args,**kwargs):
        conn=real(*args,**kwargs)
        conn.set_authorizer(lambda action,arg,*rest: sqlite3.SQLITE_DENY
                            if action==sqlite3.SQLITE_TRANSACTION and arg=='COMMIT' else sqlite3.SQLITE_OK)
        return conn
    monkeypatch.setattr(bundle.sqlite3,'connect',connect)
    with pytest.raises(sqlite3.DatabaseError):bundle.import_database_bundle(targets(pair),backup(tmp_path))
    assert values(pair)==['before','before']
