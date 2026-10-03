/**
 * TomaDesk Telegram ingress: run pollTelegram with a time-driven trigger.
 *
 * Script Properties (set in Apps Script, never in Git): TG_BOT_TOKEN,
 * TG_BOT_ID, TG_ALLOWED_USER_ID, TG_ALLOWED_CHAT_ID, TG_INCOMING_FOLDER_ID.
 * The script stores only paired private plain text in a private Drive folder.
 * TG_NEXT_OFFSET and TG_LAST_POLL_UTC are maintained by this script.
 */
function pollTelegram() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return { skipped: 'already_running' };
  try {
    const props = PropertiesService.getScriptProperties();
    const config = readConfig_(props);
    const folder = DriveApp.getFolderById(config.folderId);
    if (folder.getSharingAccess() !== DriveApp.Access.PRIVATE) {
      throw new Error('Telegram incoming folder must not be link-shared or public');
    }
    let offset = readOffset_(props);
    const updates = getUpdates_(config.token, offset);
    let saved = 0;
    let ignored = 0;
    let replyQueued = 0;
    let commands = 0;
    updates.sort((a, b) => a.update_id - b.update_id);
    for (const update of updates) {
      if (!Number.isSafeInteger(update.update_id) || update.update_id < 0) {
        throw new Error('Telegram returned an invalid update_id');
      }
      if (update.update_id < offset) continue;
      const record = pairedTextRecord_(update, config);
      const queryCommand = pairedQueryCommand_(update, config);
      if (queryCommand) {
        // Send before advancing offset so a network failure can be retried.
        // A failure after send but before offset storage may repeat the reply.
        sendMessage_(config.token, config.chatId, snapshotReply_(folder, queryCommand));
        commands += 1;
      } else if (record) {
        // Drive persistence must complete before this offset is acknowledged.
        // A crash after createFile but before setProperty is safe: retry finds
        // the same name and verifies the content before advancing again.
        saveRecord_(folder, record);
        saved += 1;
      } else {
        ignored += 1; // Unsupported/unauthorized content is never copied.
      }
      offset = update.update_id + 1;
      props.setProperty('TG_NEXT_OFFSET', String(offset));
      if (record) {
        // A reply failure must not roll back or block a durable incoming file.
        try {
          saveReply_(folder, {
            schema_version: 1, transport: 'telegram_reply', bot_id: config.botId,
            update_id: update.update_id, chat_id: config.chatId, state: 'received',
            applied_count: 0, processed_at_utc: record.received_at_utc
          });
          replyQueued += 1;
        } catch (_error) {
          props.setProperty('TG_LAST_REPLY_ERROR_UTC', new Date().toISOString());
        }
      }
    }
    const repliesSent = sendPendingReplies_(folder, config);
    props.setProperty('TG_LAST_POLL_UTC', new Date().toISOString());
    return { saved: saved, ignored: ignored, commands: commands, next_offset: offset,
      reply_queued: replyQueued, replies_sent: repliesSent };
  } finally {
    lock.releaseLock();
  }
}

function readConfig_(props) {
  const token = props.getProperty('TG_BOT_TOKEN');
  const folderId = props.getProperty('TG_INCOMING_FOLDER_ID');
  if (!token || !folderId) throw new Error('Telegram token or incoming folder is not configured');
  return {
    token: token,
    folderId: folderId,
    botId: positiveId_(props.getProperty('TG_BOT_ID'), 'bot'),
    userId: positiveId_(props.getProperty('TG_ALLOWED_USER_ID'), 'user'),
    chatId: positiveId_(props.getProperty('TG_ALLOWED_CHAT_ID'), 'chat')
  };
}

function positiveId_(raw, label) {
  if (!/^[1-9][0-9]*$/.test(String(raw || '')) || !Number.isSafeInteger(Number(raw))) {
    throw new Error('Invalid Telegram ' + label + ' ID');
  }
  return Number(raw);
}

function readOffset_(props) {
  const raw = props.getProperty('TG_NEXT_OFFSET');
  if (raw === null || raw === '') return 0;
  if (!/^(0|[1-9][0-9]*)$/.test(raw) || !Number.isSafeInteger(Number(raw))) {
    throw new Error('Invalid saved Telegram offset');
  }
  return Number(raw);
}

function getUpdates_(token, offset) {
  let response;
  try {
    response = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/getUpdates', {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ offset: offset, limit: 100, timeout: 10, allowed_updates: ['message'] }),
      muteHttpExceptions: true
    });
  } catch (_error) {
    // UrlFetch errors can contain the token-bearing URL. Never log or rethrow.
    throw new Error('Telegram getUpdates network request failed');
  }
  if (response.getResponseCode() !== 200) throw new Error('Telegram getUpdates HTTP failure');
  let body;
  try {
    body = JSON.parse(response.getContentText());
  } catch (_error) {
    throw new Error('Telegram getUpdates returned invalid JSON');
  }
  if (!body || body.ok !== true || !Array.isArray(body.result)) {
    throw new Error('Telegram getUpdates returned an error');
  }
  return body.result;
}

function pairedTextRecord_(update, config) {
  const message = update.message;
  if (!message || !message.chat || !message.from) return null;
  if (message.chat.type !== 'private' || message.chat.id !== config.chatId ||
      message.from.id !== config.userId || message.from.is_bot !== false) return null;
  if (message.business_connection_id || message.sender_chat || message.forward_origin ||
      message.is_automatic_forward) return null;
  if (typeof message.text !== 'string' || !message.text.trim() ||
      message.text.trimStart().startsWith('/') || message.text.length > 20000) return null;
  if (!Number.isSafeInteger(message.date) || message.date < 0) return null;
  return {
    schema_version: 1,
    transport: 'telegram',
    bot_id: config.botId,
    update_id: update.update_id,
    received_at_utc: new Date().toISOString(),
    message: {
      date: message.date,
      text: message.text,
      from: { id: message.from.id, is_bot: false },
      chat: { id: message.chat.id, type: 'private' }
    }
  };
}

function pairedQueryCommand_(update, config) {
  const message = update.message;
  if (!(message && message.chat && message.from &&
    message.chat.type === 'private' && message.chat.id === config.chatId &&
    message.from.id === config.userId && message.from.is_bot === false &&
    !message.business_connection_id && !message.sender_chat &&
    !message.forward_origin && !message.is_automatic_forward &&
    typeof message.text === 'string' &&
    Number.isSafeInteger(message.date) && message.date >= 0)) return null;
  const match = /^\/(today|task|dday)\s*$/.exec(message.text);
  return match ? match[1] : null;
}

function snapshotReply_(folder, command) {
  const matches = folder.getFilesByName('tomadesk_snapshot_v1.json');
  if (!matches.hasNext()) return 'TomaDesk: 조회 Snapshot이 없습니다. PC에서 공개 항목과 게시 폴더를 설정해 주세요.';
  const file = matches.next();
  if (matches.hasNext() || file.getSharingAccess() !== DriveApp.Access.PRIVATE ||
      file.getSize() > 2 * 1024 * 1024) {
    return 'TomaDesk: 조회 Snapshot 파일을 확인할 수 없습니다.';
  }
  let snapshot;
  try {
    snapshot = JSON.parse(file.getBlob().getDataAsString());
  } catch (_error) {
    return 'TomaDesk: 조회 Snapshot 파일을 읽을 수 없습니다.';
  }
  if (!validSnapshot_(snapshot)) return 'TomaDesk: 조회 Snapshot 형식이 올바르지 않습니다.';
  const now = new Date();
  const ageMinutes = Math.floor((now.getTime() - Date.parse(snapshot.generated_at_utc)) / 60000);
  const ageText = ageMinutes < -5 ? 'PC 시각 확인 필요' :
    ageMinutes > 15 ? '오래됨 · ' + ageMinutes + '분 전' :
    Math.max(0, ageMinutes) + '분 전';
  const date = Utilities.formatDate(now, 'Asia/Seoul', 'yyyyMMdd');
  const stamp = Utilities.formatDate(new Date(snapshot.generated_at_utc),
    'Asia/Seoul', 'yyyy-MM-dd HH:mm');
  const today = snapshot.items.filter(item => item.start_at.slice(0, 8) === date);
  const overdue = snapshot.items.filter(item => item.kind === 'task' &&
    item.status !== 'completed' && item.start_at.slice(0, 8) < date);
  const pendingTasks = snapshot.items.filter(item => item.kind === 'task' &&
    item.status !== 'completed');
  const ddayTasks = pendingTasks.filter(item => item.count_as_dday);
  const headline = command === 'task' ? 'TomaDesk 미완료 할 일' :
    command === 'dday' ? 'TomaDesk D-Day' :
    'TomaDesk 오늘 조회 (' + date.slice(0, 4) + '-' + date.slice(4, 6) + '-' + date.slice(6) + ')';
  const lines = [headline, 'PC 게시: ' + stamp + ' · ' + ageText];
  if (command === 'task') {
    lines.push('미완료 할 일 ' + pendingTasks.length + '건');
    for (const item of pendingTasks.slice(0, 15)) {
      lines.push('• ' + item.start_at.slice(0, 4) + '-' + item.start_at.slice(4, 6) +
        '-' + item.start_at.slice(6, 8) + ' ' + item.title.slice(0, 100));
    }
    if (pendingTasks.length > 15) lines.push('• 외 ' + (pendingTasks.length - 15) + '건');
    return lines.join('\n').slice(0, 4000);
  }
  if (command === 'dday') {
    lines.push('D-Day 항목 ' + ddayTasks.length + '건');
    const todayUtc = Date.UTC(Number(date.slice(0, 4)), Number(date.slice(4, 6)) - 1,
      Number(date.slice(6, 8)));
    for (const item of ddayTasks.slice(0, 15)) {
      const due = item.start_at.slice(0, 8);
      const dueUtc = Date.UTC(Number(due.slice(0, 4)), Number(due.slice(4, 6)) - 1,
        Number(due.slice(6, 8)));
      const days = Math.round((dueUtc - todayUtc) / 86400000);
      const label = days === 0 ? 'D-Day' : days > 0 ? 'D-' + days : 'D+' + (-days);
      lines.push('• ' + label + ' ' + item.title.slice(0, 100));
    }
    if (ddayTasks.length > 15) lines.push('• 외 ' + (ddayTasks.length - 15) + '건');
    return lines.join('\n').slice(0, 4000);
  }
  lines.push('오늘 ' + today.length + '건 / 기한 지난 할 일 ' + overdue.length + '건');
  for (const item of today.slice(0, 10)) lines.push('• ' + item.title.slice(0, 100) +
    (item.status === 'completed' ? ' (완료)' : ''));
  if (today.length > 10) lines.push('• 외 ' + (today.length - 10) + '건');
  if (overdue.length) {
    lines.push('기한 지난 할 일:');
    for (const item of overdue.slice(0, 5)) lines.push('• ' + item.title.slice(0, 100));
    if (overdue.length > 5) lines.push('• 외 ' + (overdue.length - 5) + '건');
  }
  return lines.join('\n').slice(0, 4000);
}

function validSnapshot_(value) {
  if (!value || Object.keys(value).sort().join(',') !==
      'generated_at_utc,items,schema_version,server_id,source_revision,visibility') return false;
  if (value.schema_version !== 1 || value.visibility !== 'explicit_allowlist_v1' ||
      typeof value.server_id !== 'string' || !value.server_id ||
      typeof value.source_revision !== 'string' ||
      !/^[a-f0-9]{64}$/.test(value.source_revision) ||
      typeof value.generated_at_utc !== 'string' ||
      Number.isNaN(Date.parse(value.generated_at_utc)) || !Array.isArray(value.items)) return false;
  const itemFields = 'all_day,count_as_dday,end_at,id,kind,revision,start_at,status,title';
  if (!value.items.every(item => item && Object.keys(item).sort().join(',') === itemFields &&
    typeof item.id === 'string' && typeof item.title === 'string' &&
    (item.kind === 'event' || item.kind === 'task') &&
    /^\d{12}$/.test(item.start_at) &&
    (item.status === 'pending' || item.status === 'completed') &&
    typeof item.all_day === 'boolean' && typeof item.count_as_dday === 'boolean')) return false;
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(value.items), Utilities.Charset.UTF_8);
  const digest = bytes.map(value => ('0' + (value & 255).toString(16)).slice(-2)).join('');
  return digest === value.source_revision;
}

function saveRecord_(folder, record) {
  const name = 'telegram_' + record.bot_id + '_' + record.update_id + '.json';
  const matches = folder.getFilesByName(name);
  if (matches.hasNext()) {
    let existing;
    try {
      existing = JSON.parse(matches.next().getBlob().getDataAsString());
    } catch (_error) {
      throw new Error('Telegram update file conflicts with an existing record');
    }
    if (matches.hasNext() || existing.schema_version !== 1 ||
        existing.bot_id !== record.bot_id || existing.update_id !== record.update_id ||
        JSON.stringify(existing.message) !== JSON.stringify(record.message)) {
      throw new Error('Telegram update file conflicts with an existing record');
    }
    return;
  }
  folder.createFile(name, JSON.stringify(record), MimeType.PLAIN_TEXT);
}

function saveReply_(folder, reply) {
  const name = replyName_(reply);
  const matches = folder.getFilesByName(name);
  if (matches.hasNext()) {
    let existing;
    try {
      existing = JSON.parse(matches.next().getBlob().getDataAsString());
    } catch (_error) {
      throw new Error('Telegram reply file conflicts with an existing record');
    }
    if (matches.hasNext() || !sameReply_(existing, reply)) {
      throw new Error('Telegram reply file conflicts with an existing record');
    }
    return;
  }
  folder.createFile(name, JSON.stringify(reply), MimeType.PLAIN_TEXT);
}

function replyName_(reply) {
  return 'reply_' + reply.bot_id + '_' + reply.update_id + '_' + reply.state + '.json';
}

function sameReply_(a, b) {
  return a && b && a.schema_version === b.schema_version &&
    a.transport === b.transport && a.bot_id === b.bot_id &&
    a.update_id === b.update_id && a.chat_id === b.chat_id &&
    a.state === b.state && a.applied_count === b.applied_count &&
    a.processed_at_utc === b.processed_at_utc;
}

function sendPendingReplies_(folder, config) {
  const files = folder.getFiles();
  let sent = 0;
  while (files.hasNext() && sent < 20) {
    const file = files.next();
    const name = file.getName();
    const match = /^reply_([1-9][0-9]*)_(0|[1-9][0-9]*)_(received|applied|rejected)\.json$/.exec(name);
    if (!match || Number(match[1]) !== config.botId) continue;
    let reply;
    try {
      reply = JSON.parse(file.getBlob().getDataAsString());
    } catch (_error) {
      throw new Error('Telegram reply file contains invalid JSON');
    }
    if (!validReply_(reply, config) || replyName_(reply) !== name ||
        Number(match[2]) !== reply.update_id || match[3] !== reply.state) {
      throw new Error('Telegram reply file is invalid');
    }
    const sentName = 'sent_' + name;
    const markers = folder.getFilesByName(sentName);
    if (markers.hasNext()) {
      let marker;
      try {
        marker = JSON.parse(markers.next().getBlob().getDataAsString());
      } catch (_error) {
        throw new Error('Telegram sent marker is invalid');
      }
      if (markers.hasNext() || !sameReply_(marker, reply)) {
        throw new Error('Telegram sent marker conflicts with a reply');
      }
      continue;
    }
    sendMessage_(config.token, config.chatId, replyText_(reply));
    // Telegram has no idempotency key for sendMessage. A crash after send but
    // before this marker may repeat a status message; never repeat the Action.
    folder.createFile(sentName, JSON.stringify(reply), MimeType.PLAIN_TEXT);
    sent += 1;
  }
  return sent;
}

function validReply_(reply, config) {
  if (!reply || Object.keys(reply).sort().join(',') !==
      'applied_count,bot_id,chat_id,processed_at_utc,schema_version,state,transport,update_id') return false;
  return reply.schema_version === 1 && reply.transport === 'telegram_reply' &&
    reply.bot_id === config.botId && reply.chat_id === config.chatId &&
    Number.isSafeInteger(reply.update_id) && reply.update_id >= 0 &&
    ['received', 'applied', 'rejected'].includes(reply.state) &&
    Number.isSafeInteger(reply.applied_count) && reply.applied_count >= 0 &&
    (reply.state !== 'applied' || reply.applied_count > 0) &&
    typeof reply.processed_at_utc === 'string' &&
    !Number.isNaN(Date.parse(reply.processed_at_utc));
}

function replyText_(reply) {
  if (reply.state === 'received') return 'TomaDesk: 입력을 접수했습니다. PC 검토 전입니다.';
  if (reply.state === 'applied') return 'TomaDesk: ' + reply.applied_count + '개 항목 반영 완료.';
  return 'TomaDesk: 입력을 반영하지 않고 종료했습니다.';
}

function sendMessage_(token, chatId, message) {
  let response;
  try {
    response = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
      method: 'post', contentType: 'application/json',
      payload: JSON.stringify({ chat_id: chatId, text: message }),
      muteHttpExceptions: true
    });
  } catch (_error) {
    // The original error may contain the token-bearing request URL.
    throw new Error('Telegram sendMessage network request failed');
  }
  if (response.getResponseCode() !== 200) throw new Error('Telegram sendMessage HTTP failure');
  let body;
  try {
    body = JSON.parse(response.getContentText());
  } catch (_error) {
    throw new Error('Telegram sendMessage returned invalid JSON');
  }
  if (!body || body.ok !== true) throw new Error('Telegram sendMessage returned an error');
}
