"""Configuration loading: environment variables + CLI overrides."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .render import (
    DEFAULT_DAYFILE,
    DEFAULT_FILENAME,
    DEFAULT_FOLDER,
    TemplateError,
    validate_template,
)

LAYOUTS = ("per-message", "per-day")


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass
class Config:
    api_id: int | None
    api_hash: str | None
    session: Path
    out_dir: Path
    channels: list[str] = field(default_factory=list)
    channels_from_cli: bool = False
    bot_token: str | None = None
    layout: str = "per-message"
    download_media: bool = False
    media_dir: str = "assets"
    recheck: int = 0
    react: bool = True
    react_emoji: str = "\U0001f984"  # 🦄
    react_edit_emoji: str = "\U0001f47e"  # 👾 — marks a note rewritten after an edit
    folder_template: str = DEFAULT_FOLDER
    filename_template: str = DEFAULT_FILENAME
    dayfile_template: str = DEFAULT_DAYFILE

    @property
    def is_bot(self) -> bool:
        return bool(self.bot_token)

    @property
    def mode(self) -> str:
        """`user` (MTProto), `bot-mtproto`, or `bot-api` (plain HTTP)."""
        if not self.bot_token:
            return "user"
        return "bot-mtproto" if self.api_id and self.api_hash else "bot-api"

    def channel_dir(self, channel_slug: str) -> Path:
        """Each channel gets its own subfolder under the output directory."""
        return self.out_dir / channel_slug


def _split_channels(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [c.strip() for c in raw.replace("\n", ",").split(",") if c.strip()]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_config(args) -> Config:
    """Build a Config from .env / environment, overridden by CLI arguments."""
    load_dotenv(args.env_file if getattr(args, "env_file", None) else None)

    bot_token = (
        getattr(args, "bot_token", None) or os.getenv("TELEGRAM_BOT_TOKEN") or ""
    ).strip() or None
    if bot_token and not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", bot_token):
        raise ConfigError("TELEGRAM_BOT_TOKEN looks malformed (expected `12345:ABC-...`)")

    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    # A bot token alone is enough: that path talks to the HTTP Bot API instead
    # of MTProto, which is the only transport that needs api_id/api_hash.
    if not (api_id and api_hash) and not bot_token:
        raise ConfigError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set.\n"
            "Get them from https://my.telegram.org -> API development tools, "
            "then copy .env.example to .env and fill them in.\n"
            "(Alternatively set TELEGRAM_BOT_TOKEN to run in bot mode.)"
        )
    api_id_int: int | None = None
    if api_id:
        try:
            api_id_int = int(api_id)
        except ValueError as exc:
            raise ConfigError(f"TELEGRAM_API_ID must be an integer, got {api_id!r}") from exc
    if not api_hash:
        api_hash = None

    out_dir = Path(
        getattr(args, "out", None) or os.getenv("TELESYNC_OUT_DIR") or "./vault"
    ).expanduser().resolve()

    # bot and user logins cannot share a session file
    default_session = "./telesync-bot.session" if bot_token else "./telesync.session"
    session = Path(
        getattr(args, "session", None)
        or os.getenv("TELEGRAM_SESSION")
        or default_session
    ).expanduser().resolve()

    cli_channels = list(getattr(args, "channel", None) or [])
    channels = cli_channels or _split_channels(os.getenv("TELEGRAM_CHANNELS"))

    layout = getattr(args, "layout", None) or os.getenv("TELESYNC_LAYOUT") or "per-message"
    if layout not in LAYOUTS:
        raise ConfigError(f"layout must be one of {LAYOUTS}, got {layout!r}")

    download_media = bool(getattr(args, "media", False)) or _env_bool("TELESYNC_MEDIA")

    folder_template = (
        getattr(args, "folder_format", None)
        or os.getenv("TELESYNC_FOLDER_FORMAT")
        or DEFAULT_FOLDER
    )
    filename_template = (
        getattr(args, "filename_format", None)
        or os.getenv("TELESYNC_FILENAME_FORMAT")
        or DEFAULT_FILENAME
    )
    dayfile_template = (
        getattr(args, "dayfile_format", None)
        or os.getenv("TELESYNC_DAYFILE_FORMAT")
        or DEFAULT_DAYFILE
    )
    try:
        validate_template(folder_template, allow_slash=True)
        validate_template(filename_template)
        validate_template(dayfile_template)
    except TemplateError as exc:
        raise ConfigError(str(exc)) from exc

    return Config(
        api_id=api_id_int,
        api_hash=api_hash,
        session=session,
        out_dir=out_dir,
        channels=channels,
        channels_from_cli=bool(cli_channels),
        bot_token=bot_token,
        layout=layout,
        download_media=download_media,
        media_dir=os.getenv("TELESYNC_MEDIA_DIR", "assets"),
        recheck=int(getattr(args, "recheck", 0) or os.getenv("TELESYNC_RECHECK", 0)),
        react=not getattr(args, "no_react", False) and _env_bool("TELESYNC_REACT", True),
        react_emoji=(
            getattr(args, "react_emoji", None)
            or os.getenv("TELESYNC_REACT_EMOJI")
            or "\U0001f984"
        ),
        react_edit_emoji=(
            getattr(args, "react_edit_emoji", None)
            or os.getenv("TELESYNC_REACT_EDIT_EMOJI")
            or "\U0001f47e"
        ),
        folder_template=folder_template,
        filename_template=filename_template,
        dayfile_template=dayfile_template,
    )
