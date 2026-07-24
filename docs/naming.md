# Folder and filename templates

Three independent templates decide where a message lands:

| template | flag | default | applies to |
|---|---|---|---|
| folder | `--folder-format` | `{channel}` | always |
| filename | `--filename-format` | `{date}-{time}-{id}-{slug}` | `--layout per-message` |
| day file | `--dayfile-format` | `{date}` | `--layout per-day` |

Final path is `<out-dir>/<folder>/<filename>.md`. The `.md` suffix is appended
automatically unless the template already ends in it.

## Placeholders

| placeholder | example | notes |
|---|---|---|
| `{date}` | `2026-07-24` | |
| `{time}` | `1430` | |
| `{datetime}` | `2026-07-24-1430` | |
| `{year}` `{month}` `{day}` | `2026` `07` `24` | zero-padded |
| `{hour}` `{minute}` | `14` `30` | zero-padded |
| `{dt}` | — | the datetime itself; use strftime specs: `{dt:%Y/%W}` |
| `{id}` | `1234` | message id, unique per channel |
| `{slug}` | `hello-world` | first line, lowercased and hyphenated, ≤60 chars |
| `{title}` | `Hello, World!` | first line as written, ≤80 chars |
| `{channel}` | `pavel-durov` | channel title, slugified |
| `{channel_title}` | `Pavel Durov` | channel title as written |
| `{channel_id}` | `1006503122` | |
| `{username}` | `durov` | empty for private channels |
| `{author}` | `Pavel Durov` | post author or sender; often empty |
| `{media_type}` | `photo` | empty for text-only messages |

Times are local to the machine running the sync, converted from the UTC
timestamps Telegram sends.

## Examples

```bash
# group by month
--folder-format '{channel}/{year}/{month}'
#   vault/pavel-durov/2026/07/2026-07-24-1430-1234-hello-world.md

# Obsidian-style readable titles
--filename-format '{id} - {title}'
#   vault/pavel-durov/1234 - Hello, World!.md

# ISO week folders via strftime
--folder-format '{dt:%Y/W%W}'
#   vault/2026/W29/...

# one file per day, per channel, named by month folder
--layout per-day --folder-format '{channel}/{year}' --dayfile-format '{date}'
#   vault/pavel-durov/2026/2026-07-24.md
```

## Rules and safety

- Only the **folder** template may contain `/`, which nests directories. A `/`
  produced anywhere else — most often from `{title}` — is folded to `-`.
- Characters illegal in filenames (`< > : " \ | ? *` and control characters) are
  stripped from every path component. Whitespace is collapsed; leading and
  trailing dots and spaces are trimmed.
- A component that ends up empty becomes `untitled`; a template that produces
  nothing at all is an error.
- An unknown placeholder is rejected **at startup**, before any network call,
  with the list of valid names.

## Why you want `{id}` in the filename

When a message is edited, tele-sync re-renders it. If the filename depends on
mutable content — `{slug}`, `{title}` — the new name differs from the old one,
and without a way to find the old file you would end up with two copies.

With `{id}` present, the stale file is located by its id and deleted, so an edit
replaces the note. The id is matched as a whole number, so rewriting message
`274` never touches message `2740`.

Without `{id}`, tele-sync writes the new file and leaves the old one alone. That
is the honest behaviour — it will not guess which unrelated file to delete — but
it means edits can accumulate duplicates.
