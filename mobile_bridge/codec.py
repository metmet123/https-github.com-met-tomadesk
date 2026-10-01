"""Block patches run in Qt's GUI thread; untouched rich content stays in Qt."""
from __future__ import annotations
import re
from PyQt6.QtGui import QTextCursor, QTextBlockFormat, QTextCharFormat
from alert_notes.rich_memo_edit import RichMemoTextEdit
from alert_notes.block_identity import block_ids, BlockIdentityData, HEADING_FOLDED_PROPERTY


def blocks(editor):
    ids = block_ids(editor.document())
    result = []
    block = editor.document().begin()
    while block.isValid():
        text = block.text()
        cursor = QTextCursor(block)
        images=[]
        alarm_chip=False
        it=block.begin()
        while not it.atEnd():
            frag=it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                images.append(frag.charFormat().toImageFormat().name())
            if frag.isValid() and frag.charFormat().anchorHref().startswith('toma-alarm:'):
                alarm_chip=True
            it+=1
        level=editor.heading_level(block)
        kind='heading' if level else 'toggle' if text.startswith(('▾ ','▸ ')) else 'check' if text.startswith(('☐ ','☑ ')) else 'text'
        result.append(dict(id=ids[block.blockNumber()],text=text,kind=kind,level=level,
                           indent=block.blockFormat().indent(),closed=text.startswith('▸ ') or bool(block.blockFormat().property(HEADING_FOLDED_PROPERTY)),
                           readonly=bool(images) or alarm_chip or cursor.currentTable() is not None,images=images))
        block=block.next()
    return result


def decode(content):
    editor=RichMemoTextEdit()
    try:
        editor.set_content(content)
        return editor.content(),blocks(editor)
    finally:
        editor.deleteLater()


def patch(content, edits, additions):
    if len(edits)>2000 or len(additions)>2000:
        raise ValueError('한 번에 편집할 수 있는 블록 수를 넘었습니다.')
    editor=RichMemoTextEdit()
    try:
        editor.set_content(content)
        records={b['id']:b for b in blocks(editor)}
        for edit in edits:
            bid=edit['id']
            if bid not in records:
                raise ValueError('수정할 블록을 찾지 못했습니다. 새로 동기화하세요.')
            record=records[bid]
            if record['readonly']:
                raise ValueError('이미지·표·알림 칩 블록은 PC에서 편집하세요.')
            block=editor.document().findBlockByNumber(next(i for i,b in enumerate(blocks(editor)) if b['id']==bid))
            cursor=QTextCursor(block)
            text=str(edit.get('text',record['text']))
            if '\n' in text or '\r' in text or len(text)>100000:
                raise ValueError('블록 텍스트 길이 또는 줄바꿈이 잘못되었습니다.')
            if text != block.text():
                cursor.setPosition(block.position())
                cursor.setPosition(block.position()+block.length()-1,QTextCursor.MoveMode.KeepAnchor)
                # Preserve block-level formatting and identity. Inline formatting on
                # the edited paragraph follows its first character; other blocks untouched.
                cursor.insertText(text)
                cursor.block().setUserData(BlockIdentityData(bid))
            if 'closed' in edit and record['kind']=='heading':
                fmt=cursor.blockFormat(); fmt.setProperty(HEADING_FOLDED_PROPERTY,bool(edit['closed'])); cursor.setBlockFormat(fmt)
        for addition in additions:
            text=str(addition.get('text',''))
            if '\n' in text or '\r' in text or len(text)>100000:
                raise ValueError('새 블록은 한 줄씩 추가하세요.')
            cursor=QTextCursor(editor.document()); cursor.movePosition(QTextCursor.MoveOperation.End)
            if not editor.document().isEmpty(): cursor.insertBlock()
            fmt=QTextBlockFormat(); fmt.setIndent(max(0,min(12,int(addition.get('indent',0)))))
            level=max(0,min(4,int(addition.get('level',0)))); fmt.setHeadingLevel(level)
            if level and addition.get('closed'): fmt.setProperty(HEADING_FOLDED_PROPERTY,True)
            cursor.setBlockFormat(fmt); cursor.setCharFormat(QTextCharFormat()); cursor.insertText(text)
        return editor.content()
    finally:
        editor.deleteLater()
