# VMD AI Runtime Protocol (Skeleton)

Transport: HTTP JSON-RPC over loopback only.

- Base URL: `http://127.0.0.1:<port>`
- Health: `GET /health`
- RPC: `POST /rpc`
- Session auth header: `X-Session-Token`

## JSON-RPC Envelope

Request:

```json
{
  "jsonrpc": "2.0",
  "id": "req_001",
  "method": "chat.send",
  "params": {}
}
```

Success:

```json
{
  "jsonrpc": "2.0",
  "id": "req_001",
  "result": {}
}
```

Error:

```json
{
  "jsonrpc": "2.0",
  "id": "req_001",
  "error": {
    "code": "AUTH_FAILED",
    "message": "invalid session or token",
    "data": {}
  }
}
```

## Event Schema

Roles (locked):
- `user`
- `assistant`
- `system`
- `error`
- `tool_start`
- `tool_result`
- `reasoning`

Types (locked):
- `message`
- `chunk`
- `state`
- `lifecycle`

Event object:

```json
{
  "seq": 1,
  "ts": 1743637681.123,
  "role": "assistant",
  "type": "chunk",
  "text": "hello",
  "metadata": {"request_id": "req_abc"}
}
```

## Methods

### `session.start`

Params:
- `cwd` (string)
- `ui_mode` (string)
- `client_version` (string)
- `platform` (string)

Result:
- `session_id` (string)
- `session_token` (string)
- `chat_id` (string)
- `capabilities` (object)
- `defaults` (object)

### `session.stop`

Params:
- `session_id` (string)

Result:
- `ok` (bool)

### `chat.send`

Params:
- `session_id` (string)
- `chat_id` (string)
- `text` (string)
- `model` (string)
- `mode` (string)
- `conversation_mode` (`local_first` | `hybrid_resume` | `resume_only`)

Result:
- `request_id` (string)

### `chat.cancel`

Params:
- `session_id` (string)
- `request_id` (string, optional)

Result:
- `ok` (bool)
- `cancelled` (bool)

### `chat.events.poll`

Params:
- `session_id` (string)
- `after_seq` (int >= 0)
- `limit` (int >= 1)

Result:
- `events` (array)
- `last_seq` (int)
- `has_more` (bool)

### `chat.history.list`

Params:
- `session_id` (string)
- `offset` (int >= 0)
- `limit` (int >= 1)

Result:
- `items` (array)

### `settings.get`

Params:
- `session_id` (string)

Result:
- `settings` (object)
- `key_sources` (object)

### `settings.set`

Params:
- `session_id` (string)
- `patch` (object)

Result:
- `ok` (bool)
- `settings` (object)

### `keys.save`

Params:
- `session_id` (string)
- `provider` (string)
- `key` (string)

Result:
- `ok` (bool)
- `source` (string)
- `message` (string)

### `keys.test`

Params:
- `session_id` (string)
- `provider` (string)

Result:
- `ok` (bool)
- `source` (string)
- `message` (string)

### `tool.run_vmd_command` (stub)

Params:
- `session_id` (string)
- `command` (string)
- `cwd` (string, optional)

Result:
- `ok` (bool)
- `stdout` (string)
- `stderr` (string)
- `structured` (object)

### `tool.capture_snapshot` (stub)

Params:
- `session_id` (string)
- `width` (int)
- `height` (int)
- `include_state` (bool)

Result:
- `ok` (bool)
- `image_ref` (nullable string)
- `state_summary` (object)
