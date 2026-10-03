const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const source = fs.readFileSync(path.join(__dirname, 'Code.gs'), 'utf8');

function update(id, text = '내일 회신') {
  return {
    update_id: id,
    message: {
      date: 1790902800,
      text,
      from: { id: 202, is_bot: false },
      chat: { id: 303, type: 'private' }
    }
  };
}

function harness(updates) {
  const values = new Map([
    ['TG_BOT_TOKEN', 'test-token-not-saved'],
    ['TG_BOT_ID', '101'],
    ['TG_ALLOWED_USER_ID', '202'],
    ['TG_ALLOWED_CHAT_ID', '303'],
    ['TG_INCOMING_FOLDER_ID', 'private-folder']
  ]);
  const files = new Map();
  const calls = [];
  let createFailure = false;
  let offsetFailure = false;
  let folderAccess = 'PRIVATE';
  let snapshotAccess = 'PRIVATE';
  let sendFailure = false;
  const sentMessages = [];
  const folder = {
    getSharingAccess: () => folderAccess,
    getFiles() {
      const matches = [...files.entries()].map(([name, content]) => ({
        getName: () => name,
        getBlob: () => ({ getDataAsString: () => content })
      }));
      return { hasNext: () => matches.length > 0, next: () => matches.shift() };
    },
    getFilesByName(name) {
      const matches = files.has(name) ? [files.get(name)] : [];
      return {
        hasNext: () => matches.length > 0,
        next: () => {
          const content = matches.shift();
          return { getBlob: () => ({ getDataAsString: () => content }),
            getSize: () => Buffer.byteLength(content),
            getSharingAccess: () => snapshotAccess };
        }
      };
    },
    createFile(name, content) {
      if (createFailure) {
        createFailure = false;
        throw new Error('Drive write failed');
      }
      files.set(name, content);
    }
  };
  const props = {
    getProperty: (name) => values.has(name) ? values.get(name) : null,
    setProperty(name, value) {
      if (name === 'TG_NEXT_OFFSET' && offsetFailure) {
        offsetFailure = false;
        throw new Error('Offset write failed');
      }
      values.set(name, value);
    }
  };
  const context = {
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    PropertiesService: { getScriptProperties: () => props },
    DriveApp: { Access: { PRIVATE: 'PRIVATE' }, getFolderById: (id) => {
      assert.equal(id, 'private-folder');
      return folder;
    } },
    UrlFetchApp: { fetch: (url, options) => {
      const payload = JSON.parse(options.payload);
      if (url.endsWith('/sendMessage')) {
        if (sendFailure) {
          sendFailure = false;
          return { getResponseCode: () => 500, getContentText: () => 'failed' };
        }
        sentMessages.push(payload);
        return { getResponseCode: () => 200, getContentText: () => '{"ok":true}' };
      }
      calls.push(payload);
      return {
        getResponseCode: () => 200,
        getContentText: () => JSON.stringify({ ok: true, result: updates })
      };
    } },
    MimeType: { PLAIN_TEXT: 'text/plain' },
    Utilities: {
      DigestAlgorithm: { SHA_256: 'SHA_256' }, Charset: { UTF_8: 'UTF_8' },
      computeDigest: (_algorithm, value) => [...crypto.createHash('sha256').update(value).digest()],
      formatDate: (_date, _zone, format) => format === 'yyyyMMdd' ? '20261003' : '2026-10-03 08:00'
    }
  };
  vm.runInNewContext(source, context);
  return {
    poll: () => context.pollTelegram(),
    values, files, calls, sentMessages,
    failCreate: () => { createFailure = true; },
    failOffset: () => { offsetFailure = true; },
    failSend: () => { sendFailure = true; },
    setFolderAccess: (access) => { folderAccess = access; },
    setSnapshotAccess: (access) => { snapshotAccess = access; }
  };
}

test('persists paired text before advancing the offset', () => {
  const h = harness([update(10), update(11, '다른 입력')]);
  const result = h.poll();
  assert.equal(result.saved, 2);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), '12');
  assert.deepEqual(h.calls[0].allowed_updates, ['message']);
  assert.equal(h.calls[0].offset, 0);
  assert.equal(h.files.size, 6);
  const saved = JSON.parse(h.files.get('telegram_101_10.json'));
  assert.equal(saved.message.text, '내일 회신');
  assert.equal(saved.message.from.id, 202);
  assert.equal(saved.transport, 'telegram');
  assert.equal(JSON.stringify(saved).includes('test-token-not-saved'), false);
  assert.equal(h.sentMessages.length, 2);
  assert.equal(h.sentMessages[0].chat_id, 303);
  assert.equal(h.sentMessages[0].text.includes('PC 검토 전'), true);
});

test('Drive failure leaves the failing update unacknowledged', () => {
  const h = harness([update(10)]);
  h.failCreate();
  assert.throws(() => h.poll(), /Drive write failed/);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), undefined);
  assert.equal(h.files.size, 0);
  assert.equal(h.poll().saved, 1);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), '11');
});

test('retry after a saved file but failed offset does not duplicate it', () => {
  const h = harness([update(10)]);
  h.failOffset();
  assert.throws(() => h.poll(), /Offset write failed/);
  assert.equal(h.files.size, 1);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), undefined);
  assert.equal(h.poll().saved, 1);
  assert.equal(h.files.size, 3);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), '11');
  assert.equal(h.sentMessages.length, 1);
});

test('existing file with changed content stops before acknowledging', () => {
  const h = harness([update(10)]);
  h.poll();
  h.values.set('TG_NEXT_OFFSET', '0');
  h.files.set('telegram_101_10.json', JSON.stringify({ schema_version: 1, bot_id: 101,
    update_id: 10, message: { text: 'tampered' } }));
  assert.throws(() => h.poll(), /conflicts/);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), '0');
});

test('malformed existing file stops without leaking its content', () => {
  const h = harness([update(10)]);
  h.files.set('telegram_101_10.json', '{private message content');
  assert.throws(() => h.poll(), /conflicts with an existing record/);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), undefined);
});

test('link-shared folder is rejected before fetching or saving', () => {
  const h = harness([update(10)]);
  h.setFolderAccess('ANYONE_WITH_LINK');
  assert.throws(() => h.poll(), /must not be link-shared/);
  assert.equal(h.calls.length, 0);
  assert.equal(h.files.size, 0);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), undefined);
});

test('other users, groups, commands and media never enter Drive', () => {
  const stranger = update(10); stranger.message.from.id = 999;
  const group = update(11); group.message.chat.type = 'group';
  const command = update(12, '/start');
  const media = update(13); delete media.message.text; media.message.photo = [{}];
  const h = harness([stranger, group, command, media]);
  const result = h.poll();
  assert.equal(result.ignored, 4);
  assert.equal(h.files.size, 0);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), '14');
});

test('failed status send retains queued reply without repeating the incoming record', () => {
  const h = harness([update(10)]);
  h.failSend();
  assert.throws(() => h.poll(), /sendMessage HTTP failure/);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), '11');
  assert.equal(h.files.has('telegram_101_10.json'), true);
  assert.equal(h.files.has('reply_101_10_received.json'), true);
  assert.equal(h.files.has('sent_reply_101_10_received.json'), false);
  assert.equal(h.poll().replies_sent, 1);
  assert.equal(h.sentMessages.length, 1);
});

test('terminal reply is delivered once; repeated polls honor the sent marker', () => {
  const h = harness([]);
  h.files.set('reply_101_90_applied.json', JSON.stringify({
    schema_version: 1, transport: 'telegram_reply', bot_id: 101,
    update_id: 90, chat_id: 303, state: 'applied', applied_count: 2,
    processed_at_utc: '2026-10-02T23:00:00Z'
  }));
  assert.equal(h.poll().replies_sent, 1);
  assert.equal(h.sentMessages[0].text, 'TomaDesk: 2개 항목 반영 완료.');
  assert.equal(h.files.has('sent_reply_101_90_applied.json'), true);
  assert.equal(h.poll().replies_sent, 0);
  assert.equal(h.sentMessages.length, 1);
});

test('wrong chat in a terminal reply fails closed', () => {
  const h = harness([]);
  h.files.set('reply_101_90_rejected.json', JSON.stringify({
    schema_version: 1, transport: 'telegram_reply', bot_id: 101,
    update_id: 90, chat_id: 999, state: 'rejected', applied_count: 0,
    processed_at_utc: '2026-10-02T23:00:00Z'
  }));
  assert.throws(() => h.poll(), /reply file is invalid/);
  assert.equal(h.sentMessages.length, 0);
});

function snapshot(items, generatedAt = new Date().toISOString()) {
  return { schema_version: 1, generated_at_utc: generatedAt,
    server_id: 'pc-1', visibility: 'explicit_allowlist_v1', items,
    source_revision: crypto.createHash('sha256').update(JSON.stringify(items)).digest('hex') };
}

test('/today reads only allowlisted snapshot and reports freshness', () => {
  const h = harness([update(21, '/today')]);
  h.files.set('tomadesk_snapshot_v1.json', JSON.stringify(snapshot([{
    all_day: false, count_as_dday: false, end_at: '202610031601', id: 'opaque',
    kind: 'event', revision: 'r1', start_at: '202610031500', status: 'pending',
    title: '공개 일정'
  }])));
  const result = h.poll();
  assert.equal(result.commands, 1);
  assert.equal(result.saved, 0);
  assert.equal(h.files.has('telegram_101_21.json'), false);
  assert.match(h.sentMessages[0].text, /공개 일정/);
  assert.match(h.sentMessages[0].text, /PC 게시:/);
  assert.equal(h.values.get('TG_NEXT_OFFSET'), '22');
});

test('Python Snapshot v1 SHA-256 serialization matches Apps Script validation', () => {
  const items = [{ all_day: false, count_as_dday: false, end_at: '202610031601',
    id: 'opaque', kind: 'event', revision: 'r1', start_at: '202610031500',
    status: 'pending', title: '공개 일정' }];
  const value = snapshot(items);
  // Generated with Python json.dumps(sort_keys=True, ensure_ascii=False,
  // separators=(',', ':')) and hashlib.sha256 over UTF-8 bytes.
  assert.equal(value.source_revision,
    'fec28ebfcad30d044623aefb56e011a22e231d8d26b641b8b669ab34a00e0ef2');
});

test('/today does not display corrupted or extra-field snapshots', () => {
  const h = harness([update(21, '/today')]);
  const value = snapshot([]);
  value.private_note = 'do not show';
  h.files.set('tomadesk_snapshot_v1.json', JSON.stringify(value));
  h.poll();
  assert.match(h.sentMessages[0].text, /형식이 올바르지/);
  assert.equal(h.sentMessages[0].text.includes('do not show'), false);
});

test('/today marks an old PC snapshot stale and refuses a changed item hash', () => {
  const stale = harness([update(22, '/today')]);
  stale.files.set('tomadesk_snapshot_v1.json', JSON.stringify(snapshot([],
    new Date(Date.now() - 31 * 60_000).toISOString())));
  stale.poll();
  assert.match(stale.sentMessages[0].text, /오래됨/);

  const tampered = harness([update(23, '/today')]);
  const value = snapshot([]);
  value.items.push({ all_day: false, count_as_dday: false, end_at: '202610031601',
    id: 'opaque', kind: 'event', revision: 'r1', start_at: '202610031500',
    status: 'pending', title: '조작된 일정' });
  tampered.files.set('tomadesk_snapshot_v1.json', JSON.stringify(value));
  tampered.poll();
  assert.match(tampered.sentMessages[0].text, /형식이 올바르지/);
  assert.equal(tampered.sentMessages[0].text.includes('조작된 일정'), false);
});

test('/today rejects unauthorized command without sending or saving', () => {
  const command = update(21, '/today'); command.message.from.id = 999;
  const h = harness([command]);
  assert.equal(h.poll().ignored, 1);
  assert.equal(h.sentMessages.length, 0);
  assert.equal(h.files.size, 0);
});

test('/today refuses a link-shared snapshot file even in a private folder', () => {
  const h = harness([update(24, '/today')]);
  h.files.set('tomadesk_snapshot_v1.json', JSON.stringify(snapshot([])));
  h.setSnapshotAccess('ANYONE_WITH_LINK');
  h.poll();
  assert.match(h.sentMessages[0].text, /파일을 확인할 수 없습니다/);
});

function task(title, due, options = {}) {
  return { all_day: false, count_as_dday: Boolean(options.dday),
    end_at: due, id: title, kind: 'task', revision: 'r1', start_at: due,
    status: options.completed ? 'completed' : 'pending', title };
}

test('/task shows only pending allowlisted tasks and no Action is created', () => {
  const h = harness([update(25, '/task')]);
  h.files.set('tomadesk_snapshot_v1.json', JSON.stringify(snapshot([
    task('처리할 일', '202610031500'), task('완료한 일', '202610031600', { completed: true })
  ])));
  const result = h.poll();
  assert.equal(result.commands, 1);
  assert.equal(result.saved, 0);
  assert.match(h.sentMessages[0].text, /처리할 일/);
  assert.equal(h.sentMessages[0].text.includes('완료한 일'), false);
  assert.equal(h.files.has('telegram_101_25.json'), false);
});

test('/dday uses Seoul calendar dates and excludes ordinary or completed tasks', () => {
  const h = harness([update(26, '/dday')]);
  h.files.set('tomadesk_snapshot_v1.json', JSON.stringify(snapshot([
    task('이틀 뒤', '202610051500', { dday: true }),
    task('이틀 지남', '202610011500', { dday: true }),
    task('일반 할 일', '202610051500'),
    task('완료 항목', '202610051500', { dday: true, completed: true })
  ])));
  h.poll();
  assert.match(h.sentMessages[0].text, /D-2 이틀 뒤/);
  assert.match(h.sentMessages[0].text, /D\+2 이틀 지남/);
  assert.equal(h.sentMessages[0].text.includes('일반 할 일'), false);
  assert.equal(h.sentMessages[0].text.includes('완료 항목'), false);
});
