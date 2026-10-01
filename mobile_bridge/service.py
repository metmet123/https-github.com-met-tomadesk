from __future__ import annotations
import base64
import hashlib
import json
from uuid import UUID, uuid4
from alert_notes.sync_identity import utc_now_ms
from .codec import decode, patch
from .markdown_codec import to_markdown,from_markdown


class MobileService:
    def __init__(self, store, busy=lambda: set()):
        self.store=store; self.busy=busy
        store.conn.execute('CREATE TABLE IF NOT EXISTS mobile_receipts(op_id TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,result TEXT NOT NULL)')
        store.conn.execute('CREATE TABLE IF NOT EXISTS mobile_markdown_sources(sync_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, source TEXT NOT NULL)')
        store.conn.commit()

    def snapshot(self):
        notes=[]
        for row in self.store.conn.execute("SELECT * FROM notes WHERE deleted_at='' ORDER BY pinned DESC,updated_at DESC"):
            item=dict(row)
            canonical, parts=decode(item['content'])
            # Stable IDs also for legacy notes, without changing the PC source on reads.
            item.update(base_content=canonical,blocks=parts,base_hash=hashlib.sha256(item['content'].encode()).hexdigest())
            content_hash=hashlib.sha256(item['content'].encode()).hexdigest()
            md=self.store.conn.execute('SELECT content_hash,source FROM mobile_markdown_sources WHERE sync_id=?',(item['sync_id'],)).fetchone()
            item['markdown_native']=bool(md and md[0]==content_hash)
            item['markdown']=md[1] if item['markdown_native'] else to_markdown(item['content'])
            item['attachments']=[dict(a) for a in self.store.note_attachments(item['id'])]
            notes.append(item)
        schedules=[dict(r) for r in self.store.conn.execute("SELECT id,title,start_at,end_at,all_day,status FROM schedule_items WHERE deleted_at='' ORDER BY start_at")]
        return dict(notes=notes,schedules=schedules,server_id=self.store.device_id,capabilities=['markdown_document_v1'])

    def apply(self, change):
        op=str(UUID(change['op_id']))
        digest=hashlib.sha256(json.dumps(change,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        receipt=self.store.conn.execute('SELECT payload_hash,result FROM mobile_receipts WHERE op_id=?',(op,)).fetchone()
        if receipt:
            if receipt[0]!=digest: raise ValueError('같은 요청 ID의 내용이 바뀌었습니다.')
            return json.loads(receipt[1])
        sid=str(UUID(change['sync_id']))
        row=self.store.note_by_sync_id(sid,include_trashed=True)
        new=bool(change.get('new'))
        if new and row: raise ValueError('이미 존재하는 메모입니다.')
        conflict=not new and (row is None or row['deleted_at'] or row['id'] in self.busy() or
                    int(change['base_revision'])!=row['revision'] or change['base_hash']!=hashlib.sha256(row['content'].encode()).hexdigest())
        source=str(change.get('base_content',''))
        # Client supplies its original canonical snapshot so conflict copies preserve
        # offline edits, not a mixture of the PC's newer document and old patches.
        if len(source)>4_000_000: raise ValueError('메모가 너무 큽니다.')
        markdown=change.get('markdown') if 'markdown' in change else None
        if 'markdown' in change and not isinstance(markdown,str): raise ValueError('Markdown 문서 형식이 잘못되었습니다.')
        # Markdown cannot reliably preserve the desktop's inline alarm links.
        # Keep the alarm-bearing original and save the mobile edit as a separate copy.
        if markdown is not None and row is not None and 'toma-alarm:' in row['content']:
            conflict=True
        content=from_markdown(markdown) if markdown is not None else patch(source,change.get('edits',[]),change.get('additions',[]))
        title=str(change.get('title','새 메모')).strip()[:500] or '새 메모'
        conn=self.store.conn
        conn.execute('BEGIN IMMEDIATE')
        try:
            now=self.store._now_key(); stamp=utc_now_ms()
            backup_sid=None
            if markdown is not None and row is not None and not conflict:
                cached=conn.execute('SELECT content_hash FROM mobile_markdown_sources WHERE sync_id=?',(sid,)).fetchone()
                if not cached or cached[0]!=hashlib.sha256(row['content'].encode()).hexdigest():
                    _,backup_sid,_=self._copy_note(row['content'],row['title']+' · Markdown 변환 전 원본',self.store.note_attachments(row['id']),now,stamp)
            if new or conflict:
                target_sid=str(uuid4()) if conflict else sid
                title += ' · 모바일 충돌 사본' if conflict else ''
                target,target_sid,content,mapping=self._copy_note(content,title,change.get('attachments',[]),now,stamp,target_sid,sid if conflict else '',with_mapping=True)
                if markdown is not None:
                    markdown=self._rewrite_images(markdown,mapping)
            else:
                target=row['id']; target_sid=sid
                conn.execute('UPDATE notes SET title=?,content=?,revision=revision+1,modified_at_utc=?,updated_at=?,origin_device_id=? WHERE id=?',
                             (title,content,stamp,now,'mobile',target))
            if markdown is not None:
                conn.execute('INSERT OR REPLACE INTO mobile_markdown_sources(sync_id,content_hash,source) VALUES(?,?,?)',
                             (target_sid,hashlib.sha256(content.encode()).hexdigest(),markdown))
            result=dict(sync_id=target_sid,conflict=bool(conflict),op_id=op)
            if backup_sid: result['markdown_backup_sync_id']=backup_sid
            conn.execute('INSERT INTO mobile_receipts VALUES(?,?,?)',(op,digest,json.dumps(result)))
            conn.commit()
            self.store.sync_inline_alarms(target, content)
            return result
        except Exception:
            conn.rollback(); raise

    @staticmethod
    def _rewrite_images(content,mapping):
        import re
        return re.sub(r'toma-note-image://(?:attachment/)?(\d+)',lambda m: 'toma-note-image://'+str(mapping.get(int(m[1]),int(m[1]))),content)

    def _copy_note(self,content,title,attachments,now,stamp,sid=None,conflict_of='',with_mapping=False):
        conn=self.store.conn; sid=sid or str(uuid4())
        target=conn.execute('INSERT INTO notes(title,content,created_at,updated_at,sync_id,revision,modified_at_utc,origin_device_id,conflict_of_sync_id) VALUES(?,?,?,?,?,1,?,?,?)',
                            (title,content,now,now,sid,stamp,'mobile',conflict_of)).lastrowid
        mapping={}
        for a in attachments:
            raw=base64.b64decode(a['data_base64'],validate=True)
            if len(raw)>8*1024*1024: raise ValueError('첨부파일 크기 제한을 넘었습니다.')
            aid=conn.execute('INSERT INTO note_attachments(note_id,mime_type,data_base64,width,height,created_at,sync_id,revision,modified_at_utc,origin_device_id) VALUES(?,?,?,?,?,?,?,1,?,?)',
                             (target,str(a['mime_type']),a['data_base64'],int(a['width']),int(a['height']),now,str(uuid4()),stamp,'mobile')).lastrowid
            mapping[int(a['id'])]=aid
        content=self._rewrite_images(content,mapping)
        conn.execute('UPDATE notes SET content=? WHERE id=?',(content,target))
        return (target,sid,content,mapping) if with_mapping else (target,sid,content)
