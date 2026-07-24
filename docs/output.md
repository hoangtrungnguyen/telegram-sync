# Output format

## Layout on disk

```
vault/
├── .telesync-state.json                 # sync state, see sync-model.md
└── pavel-durov/                         # one folder per channel (configurable)
    ├── assets/                          # only with --media
    │   └── 1234-photo_1234.jpg
    └── 2026-07-24-1430-1234-hello-world.md
```

## `--layout per-message` (default)

One file per message, YAML frontmatter followed by the body:

```markdown
---
id: 1234
channel: Pavel Durov
channel_id: 1006503122
date: '2026-07-24T14:30:00+07:00'
source: telegram
channel_username: '@durov'
author: Pavel Durov
edited: '2026-07-24T15:02:11+07:00'
views: 1200000
forwards: 400
reply_to: 1230
album: '13500000000000'
media_type: photo
media:
  - assets/1234-photo_1234.jpg
url: https://t.me/durov/1234
---

![](assets/1234-photo_1234.jpg)

Hello **world**
```

Every key except `id`, `channel`, `channel_id`, `date` and `source` is omitted
when it does not apply, so a plain text post has short frontmatter.

| key | meaning |
|---|---|
| `id` | message id, unique within the channel |
| `channel`, `channel_id`, `channel_username` | where it came from |
| `date`, `edited` | ISO 8601, local timezone |
| `author` | post signature, or the sender in groups |
| `views`, `forwards` | as reported by Telegram (MTProto only) |
| `reply_to` | id of the message this replies to |
| `album` | shared id for a grouped media post |
| `media_type` | `photo`, `video`, `document`, `poll`, … |
| `media` | relative paths to downloaded files |
| `url` | deep link back to the message |

## `--layout per-day`

One file per calendar day, each message a `## HH:MM` section:

```markdown
---
date: '2026-07-24'
channel: Pavel Durov
channel_id: 1006503122
source: telegram
---

# 2026-07-24

<!-- telesync:1234 -->
## 14:30 · [#1234](https://t.me/durov/1234) · Pavel Durov

Hello **world**

<!-- telesync:1235 -->
## 15:02 · [#1235](https://t.me/durov/1235)

Second post
```

The `<!-- telesync:ID -->` markers are how re-runs merge instead of overwrite:
existing blocks are parsed out, the new message is inserted or replaced by id,
and the file is rewritten in id order. Editing text between markers by hand will
be lost on the next sync of that day; anything you add outside the day file is
safe.

## Text conversion

Telegram formatting entities are converted to CommonMark:

| Telegram | Markdown |
|---|---|
| bold | `**bold**` |
| italic | `*italic*` |
| underline | `<u>underline</u>` |
| strikethrough | `~~strike~~` |
| spoiler | `\|\|spoiler\|\|` |
| inline code | `` `code` `` |
| code block | fenced, with language when set |
| link | `[text](url)` |
| blockquote | `> ` on each line |
| mention of a user | `[name](tg://user?id=…)` |

Entity offsets from Telegram are counted in UTF-16 code units, and tele-sync
slices in that encoding — so emoji and non-BMP characters don't shift the
markup. Nested spans (bold containing italic) survive; unsupported entity types
are left as plain text.

Non-text content renders as:

- **poll** — question in bold, options as an unchecked task list
- **location** — a Google Maps link
- **contact** — name and phone number
- **media with no caption** — a lone `*(photo)*` marker so the file isn't empty

## Media

With `--media`, the attachment is downloaded into `assets/` inside the channel
folder and prefixed with the message id (`1234-photo_1234.jpg`) to avoid
collisions. Images are embedded with `![](…)`; anything else is linked by
filename. Re-runs detect the existing `1234-*` file and skip re-downloading.

Link previews are never downloaded — they are not attachments.

Album posts arrive from Telegram as separate messages sharing a `media_group_id`.
Each becomes its own note, tied together by the `album` frontmatter key; only
the message carrying the caption has body text.
