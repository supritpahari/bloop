"""Music system: YouTube playback via yt-dlp + FFmpeg, per-guild player state.

No Lavalink/Wavelink — every track is extracted directly with yt-dlp and
streamed to the voice channel with FFmpeg. Requires `ffmpeg` and `libopus`
on the host, plus the `yt-dlp` and `PyNaCl` pip packages.

Highlights:
- URL, search, or playlist playback (playlists queue lazily so adds are fast)
- Interactive player panel + paginated queue with per-track remove buttons
- /find with a dropdown picker, /playnext, /previous, /seek, /jump, /move
- Auto-updating now-playing progress bar, auto-leave on idle or empty channel
"""

import asyncio
import random
import shutil
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select

from economy import utils as u

INACTIVITY_TIMEOUT = 300.0   # seconds idle (no playback) before leaving
ALONE_TIMEOUT = 60.0         # seconds alone in the channel before leaving
EXTRACT_TIMEOUT = 20.0       # max seconds a yt-dlp extraction may take
MAX_QUEUE_LIST = 10          # tracks shown per /queue page (and in embeds)
MAX_QUEUE_SIZE = 500         # hard cap on queued tracks
PLAYLIST_LIMIT = 50          # max tracks pulled from a playlist URL
HISTORY_LIMIT = 20           # how many previous tracks are remembered
SEARCH_LIMIT = 5             # results shown by /find
PROGRESS_UPDATE_INTERVAL = 5.0  # seconds between progress bar updates

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "nocheckcertificate": True,
    "extract_flat": False,
}

FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"

COLOR_NOW_PLAYING = 0x4FD1C5
COLOR_ERROR = 0xF43F5E
COLOR_QUEUE = 0x6366F1

_OPUS_LIBS = ("libopus.so.0", "libopus.so", "opus.dll", "libopus.0.dylib")


class MusicError(Exception):
    """A user-facing music failure with a ready-to-display message."""


# --------------------------------------------------------------------- data


@dataclass
class Song:
    title: str
    url: str
    stream_url: Optional[str]
    duration: Optional[int]
    thumbnail: Optional[str]
    uploader: str
    requester: discord.Member
    video_id: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return bool(self.stream_url)

    async def ensure_resolved(self) -> None:
        """Resolve a lazily-queued song's stream URL just before playback."""
        if self.stream_url:
            return
        try:
            info = await asyncio.wait_for(asyncio.to_thread(_extract, self.url), EXTRACT_TIMEOUT)
        except asyncio.TimeoutError:
            raise MusicError(f"⏱️ Timed out loading **{self.title}**.") from None
        except yt_dlp.utils.DownloadError as exc:
            raise MusicError(f"Couldn't load **{self.title}** ({str(exc).strip()[:120]}).") from exc
        if not info:
            raise MusicError(f"Couldn't load **{self.title}**.")
        stream_url = info.get("url")
        if not stream_url:
            raise MusicError(f"No playable audio stream was found for **{self.title}**.")
        self.stream_url = stream_url
        self.title = info.get("title") or self.title
        self.duration = info.get("duration") or self.duration
        self.thumbnail = info.get("thumbnail") or self.thumbnail
        self.uploader = (info.get("uploader") or info.get("channel") or self.uploader or "Unknown")


def _extract(query: str) -> dict:
    """Run yt-dlp in a worker thread; raises yt_dlp DownloadError on failure."""
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        if query.startswith(("http://", "https://")):
            info = ydl.extract_info(query, download=False)
        else:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if info.get("entries"):
                return info["entries"][0]
            return info
    return info


def _extract_search(query: str, limit: int = SEARCH_LIMIT) -> list:
    """Fast, flat search results (title/duration/channel) for the picker."""
    opts = dict(YTDL_OPTIONS)
    opts["extract_flat"] = "in_playlist"
    opts["noplaylist"] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    if not info:
        return []
    return list(info.get("entries") or [])


def _extract_playlist(url: str, limit: int = PLAYLIST_LIMIT) -> list:
    """Fast, flat playlist entries (resolved lazily one-by-one later)."""
    opts = dict(YTDL_OPTIONS)
    opts["noplaylist"] = False
    opts["extract_flat"] = "in_playlist"
    opts["playlistend"] = limit
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return []
    if info.get("_type") == "playlist" or "entries" in info:
        return list(info.get("entries") or [])
    return [info]


def _best_thumbnail(entry: dict) -> Optional[str]:
    thumbnails = entry.get("thumbnails") or []
    if thumbnails:
        return thumbnails[-1].get("url") or None
    return entry.get("thumbnail")


def _fmt_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "🔴 LIVE"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _progress_bar(elapsed: float, duration: Optional[int], width: int = 14) -> str:
    if not duration:
        return "🔴 LIVE"
    ratio = min(1.0, elapsed / duration)
    filled = int(round(ratio * width))
    return "▬" * filled + "🔘" + "─" * (width - filled)


def _loop_label(mode: str) -> str:
    return {"none": "Off", "one": "🔂 Track", "all": "🔁 Queue"}.get(mode, "Off")


def _fmt_queue_duration(songs: list["Song"]) -> str:
    total = sum(s.duration or 0 for s in songs)
    if not total:
        return "unknown"
    return _fmt_duration(total)


def _parse_position(text: str) -> int:
    """Parse '90', '1:30', or '1:02:03' into seconds."""
    text = (text or "").strip()
    if not text:
        raise MusicError("Give me a time like `90` (seconds) or `1:30`.")
    parts = text.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        raise MusicError("Time must be numbers — like `90` or `1:30`.")
    if len(parts) > 3 or any(p < 0 for p in parts):
        raise MusicError("Invalid time — use `seconds`, `mm:ss`, or `hh:mm:ss`.")
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


# ------------------------------------------------------------------ views


class PlayerView(View):
    """Interactive control panel for the music player."""

    def __init__(self, player: "GuildPlayer"):
        super().__init__(timeout=None)
        self.player = player
        self._update_buttons()

    def _update_buttons(self):
        """Keep button labels/disabled states in sync with the player."""
        p = self.player
        playing = bool(p.voice and (p.voice.is_playing() or p.voice.is_paused()))
        connected = bool(p.voice and p.voice.is_connected())

        self.previous.disabled = not p.history

        self.pause_resume.disabled = not playing
        self.pause_resume.label = "▶️ Resume" if p._paused else "⏸️ Pause"
        self.pause_resume.style = discord.ButtonStyle.success if p._paused else discord.ButtonStyle.secondary

        self.skip.disabled = not playing
        self.stop.disabled = not connected

        self.loop.label = _loop_label(p.loop_mode)
        self.loop.style = discord.ButtonStyle.primary if p.loop_mode != "none" else discord.ButtonStyle.secondary

        self.shuffle.disabled = len(p.queue) < 2
        self.shuffle.style = discord.ButtonStyle.primary if p.shuffle_on else discord.ButtonStyle.secondary

        self.volume.disabled = not playing
        self.clear.disabled = not p.queue
        self.queue.disabled = not p.queue and not p.current

    @staticmethod
    async def _safe_reply(interaction: discord.Interaction, message: str):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    async def _guard(self, interaction: discord.Interaction, action):
        try:
            await action
        except MusicError as exc:
            await self._safe_reply(interaction, f"❌ {exc}")
        except discord.HTTPException:
            pass
        except Exception as exc:
            await self._safe_reply(interaction, f"❌ Unexpected error: {str(exc)[:200]}")

    # ------------------------------------------------------- button actions

    async def _previous_action(self, interaction):
        player = self.player
        if not player.history:
            await self._safe_reply(interaction, "There's no previous track to go back to.")
            return
        prev = player.history.pop()
        if player.current:
            player.queue.insert(0, player.current)
        if player.voice and (player.voice.is_playing() or player.voice.is_paused()):
            player._force_next = prev
            player.voice.stop()
            self._update_buttons()
            await interaction.response.edit_message(
                embed=discord.Embed(description=f"⏮️ Going back to **{prev.title}**…", color=COLOR_NOW_PLAYING),
                view=self,
            )
        else:
            await player._start_playback(prev)
            self._update_buttons()
            await interaction.response.edit_message(embed=player.now_playing_embed(), view=self)

    async def _pause_resume_action(self, interaction):
        player = self.player
        if not player.voice or not (player.voice.is_playing() or player.voice.is_paused()):
            await self._safe_reply(interaction, "Nothing is playing.")
            return
        if player._paused:
            player._paused = False
            player._started_at = time.monotonic()
            player.voice.resume()
        else:
            player._elapsed += time.monotonic() - player._started_at
            player._paused = True
            player.voice.pause()
        self._update_buttons()
        await interaction.response.edit_message(embed=player.now_playing_embed(), view=self)

    async def _stop_action(self, interaction):
        player = self.player
        if not player.voice or not player.voice.is_connected():
            await self._safe_reply(interaction, "Not connected.")
            return
        channel = player.voice.channel
        player.shutdown(disconnect=False)
        await player.schedule_idle()
        embed = discord.Embed(
            description=f"⏹️ Stopped playback and cleared the queue. I'll leave **{channel.name}** after {int(INACTIVITY_TIMEOUT)}s of inactivity.",
            color=COLOR_NOW_PLAYING,
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def _skip_action(self, interaction):
        player = self.player
        if not player.voice or not (player.voice.is_playing() or player.voice.is_paused()):
            await self._safe_reply(interaction, "Nothing is playing.")
            return
        skipped = player.current
        player.voice.stop()
        self._update_buttons()
        embed = discord.Embed(
            description=f"⏭️ Skipped **{skipped.title}**." if skipped else "⏭️ Skipped.",
            color=COLOR_NOW_PLAYING,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def _loop_action(self, interaction):
        player = self.player
        cycle = {"none": "one", "one": "all", "all": "none"}
        player.loop_mode = cycle.get(player.loop_mode, "none")
        self._update_buttons()
        await interaction.response.edit_message(embed=player.now_playing_embed(), view=self)

    async def _shuffle_action(self, interaction):
        player = self.player
        if len(player.queue) < 2:
            await self._safe_reply(interaction, "Need at least 2 queued tracks to shuffle.")
            return
        player.shuffle_on = not player.shuffle_on
        if player.shuffle_on:
            random.shuffle(player.queue)
        self._update_buttons()
        await interaction.response.edit_message(embed=player.now_playing_embed(), view=self)

    async def _volume_action(self, interaction):
        await interaction.response.send_modal(VolumeModal(self.player, self))

    async def _queue_action(self, interaction):
        view = QueueView(self.player)
        await interaction.response.send_message(embed=view._get_page_embed(), view=view, ephemeral=True)

    async def _clear_action(self, interaction):
        player = self.player
        if not player.queue:
            await self._safe_reply(interaction, "Queue is already empty.")
            return
        count = len(player.queue)
        player.queue.clear()
        self._update_buttons()
        await interaction.response.edit_message(embed=player.now_playing_embed(), view=self)
        await interaction.followup.send(f"🧹 Cleared **{count}** track(s) from the queue.", ephemeral=True)

    # ---------------------------------------------------------- button defs

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="music_prev", row=0)
    async def previous(self, interaction: discord.Interaction, button: Button):
        await self._guard(interaction, self._previous_action(interaction))

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, custom_id="music_pause_resume", row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: Button):
        await self._guard(interaction, self._pause_resume_action(interaction))

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music_stop", row=0)
    async def stop(self, interaction: discord.Interaction, button: Button):
        await self._guard(interaction, self._stop_action(interaction))

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="music_skip", row=0)
    async def skip(self, interaction: discord.Interaction, button: Button):
        await self._guard(interaction, self._skip_action(interaction))

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="music_loop", row=1)
    async def loop(self, interaction: discord.Interaction, button: Button):
        await self._guard(interaction, self._loop_action(interaction))

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="music_shuffle", row=1)
    async def shuffle(self, interaction: discord.Interaction, button: Button):
        await self._guard(interaction, self._shuffle_action(interaction))

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="music_volume", row=1)
    async def volume(self, interaction: discord.Interaction, button: Button):
        await self._guard(interaction, self._volume_action(interaction))

    @discord.ui.button(emoji="📋", style=discord.ButtonStyle.secondary, custom_id="music_queue", row=1)
    async def queue(self, interaction: discord.Interaction, button: Button):
        await self._guard(interaction, self._queue_action(interaction))

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="music_clear", row=1)
    async def clear(self, interaction: discord.Interaction, button: Button):
        await self._guard(interaction, self._clear_action(interaction))


class VolumeModal(discord.ui.Modal, title="🔊 Volume Control"):
    volume_input = discord.ui.TextInput(
        label="Volume (1-100)",
        placeholder="50",
        min_length=1,
        max_length=3,
        required=True,
    )

    def __init__(self, player: "GuildPlayer", view: PlayerView):
        super().__init__()
        self.player = player
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            volume = int(self.volume_input.value)
        except ValueError:
            await interaction.response.send_message("Please enter a number 1-100.", ephemeral=True)
            return
        volume = max(1, min(100, volume))
        self.player.volume = volume / 100
        if self.player.voice and isinstance(self.player.voice.source, discord.PCMVolumeTransformer):
            self.player.voice.source.volume = self.player.volume
        try:
            await interaction.response.edit_message(embed=self.player.now_playing_embed(), view=self.view)
        except discord.HTTPException:
            pass
        await interaction.followup.send(f"🔊 Volume set to **{volume}%**.", ephemeral=True)


class QueueView(View):
    """Paginated queue view with per-track remove buttons."""

    def __init__(self, player: "GuildPlayer", page: int = 0):
        super().__init__(timeout=None)
        self.player = player
        self.page = page
        self._build()

    @property
    def max_page(self) -> int:
        return max(0, (len(self.player.queue) - 1) // MAX_QUEUE_LIST)

    def _build(self):
        self.clear_items()
        self.page = max(0, min(self.page, self.max_page))

        self.prev_btn = Button(emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
        self.prev_btn.callback = self._prev
        self.add_item(self.prev_btn)

        self.next_btn = Button(emoji="➡️", style=discord.ButtonStyle.secondary, row=0)
        self.next_btn.callback = self._next
        self.add_item(self.next_btn)

        start = self.page * MAX_QUEUE_LIST
        end = min(start + MAX_QUEUE_LIST, len(self.player.queue))
        for index in range(start, end):
            btn = Button(label=f"Remove #{index + 1}", style=discord.ButtonStyle.danger, row=1)
            btn.callback = self._make_remove(index)
            self.add_item(btn)

        self._update_states()

    def _update_states(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.max_page

    def _get_page_embed(self) -> discord.Embed:
        player = self.player
        embed = discord.Embed(title="🎶 Music Queue", color=COLOR_QUEUE)

        if player.current:
            embed.description = f"▶ Now playing: **{player.current.title}** — {_fmt_duration(player.current.duration)}"

        start = self.page * MAX_QUEUE_LIST
        end = min(start + MAX_QUEUE_LIST, len(player.queue))
        page_queue = player.queue[start:end]

        if not player.queue:
            embed.add_field(name="Up next", value="Empty — use `/play` to add tracks.", inline=False)
        else:
            lines = [
                f"`{i + start + 1}.` **{s.title}** — {_fmt_duration(s.duration)} · {s.requester.mention}"
                for i, s in enumerate(page_queue)
            ]
            if len(player.queue) > MAX_QUEUE_LIST:
                lines.append(f"…and {len(player.queue) - end} more on later pages")
            embed.add_field(name=f"Up next ({len(player.queue)})", value="\n".join(lines), inline=False)

        embed.set_footer(
            text=f"Page {self.page + 1}/{self.max_page + 1} | Loop: {_loop_label(player.loop_mode)} | Shuffle: {'On' if player.shuffle_on else 'Off'} | Total: {_fmt_queue_duration(player.queue)}"
        )
        return embed

    async def _prev(self, interaction: discord.Interaction):
        self.page -= 1
        self._build()
        await interaction.response.edit_message(embed=self._get_page_embed(), view=self)

    async def _next(self, interaction: discord.Interaction):
        self.page += 1
        self._build()
        await interaction.response.edit_message(embed=self._get_page_embed(), view=self)

    def _make_remove(self, index: int):
        async def callback(interaction: discord.Interaction):
            player = self.player
            if index < 0 or index >= len(player.queue):
                await interaction.response.send_message("That track is no longer in the queue.", ephemeral=True)
                return
            song = player.queue.pop(index)
            self._build()
            await interaction.response.edit_message(embed=self._get_page_embed(), view=self)
            await interaction.followup.send(f"🗑️ Removed **{song.title}**.", ephemeral=True)
        return callback


class SearchSelect(Select):
    def __init__(self, cog: "Music", entries: list):
        options = []
        for i, entry in enumerate(entries):
            title = (entry.get("title") or "Unknown")
            uploader = entry.get("uploader") or entry.get("channel") or "Unknown"
            duration = _fmt_duration(entry.get("duration"))
            options.append(
                discord.SelectOption(
                    label=f"{i + 1}. {title}"[:100],
                    value=str(i),
                    description=f"{uploader} · {duration}"[:100] or None,
                )
            )
        super().__init__(placeholder="🎵 Choose a track to play…", min_values=1, max_values=1, options=options)
        self.cog = cog
        self.entries = entries

    async def callback(self, interaction: discord.Interaction):
        entry = self.entries[int(self.values[0])]
        url = entry.get("webpage_url") or entry.get("url") or f"https://www.youtube.com/watch?v={entry['id']}"
        await interaction.response.defer(thinking=True)
        requester = interaction.user
        try:
            song = await self.cog._resolve_song(url, requester)
            player = await self.cog._connect(interaction)
            player.cancel_idle()
            await self.cog._start_or_queue(interaction, player, [song])
        except MusicError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"❌ Unexpected error: {str(exc)[:200]}", ephemeral=True)


class SearchView(View):
    def __init__(self, cog: "Music", entries: list):
        super().__init__(timeout=None)
        self.add_item(SearchSelect(cog, entries))


# ------------------------------------------------------------------ player


class GuildPlayer:
    """Owns one guild's voice client, queue and playback state."""

    def __init__(self, bot: commands.Bot, guild_id: int, text_channel: Optional[discord.TextChannel] = None):
        self.bot = bot
        self.guild_id = guild_id
        self.text_channel = text_channel
        self.voice: Optional[discord.VoiceClient] = None
        self.queue: list[Song] = []
        self.current: Optional[Song] = None
        self.history: list[Song] = []
        self.volume: float = 1.0
        self.loop_mode: str = "none"  # none | one | all
        self.shuffle_on: bool = False
        self._started_at: float = 0.0
        self._elapsed: float = 0.0
        self._paused: bool = False
        self._stopping: bool = False
        self._seek_offset: float = 0.0
        self._seek_pending: Optional[float] = None
        self._force_next: Optional[Song] = None
        self._retry_count: int = 0
        self._idle_task: Optional[asyncio.Task] = None
        self._alone_task: Optional[asyncio.Task] = None
        self._now_message: Optional[discord.Message] = None
        self._progress_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------ helpers

    def position(self) -> float:
        """Seconds elapsed in the current track (accounts for pauses)."""
        if not self.current:
            return 0.0
        if self._paused:
            return self._elapsed
        return self._elapsed + (time.monotonic() - self._started_at)

    async def _notify(self, embed: Optional[discord.Embed] = None, content: str = None, view: Optional[discord.ui.View] = None) -> Optional[discord.Message]:
        if self.text_channel is None:
            return None
        try:
            return await self.text_channel.send(content=content, embed=embed, view=view)
        except discord.HTTPException:
            return None

    def cancel_idle(self):
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    def cancel_alone(self):
        if self._alone_task and not self._alone_task.done():
            self._alone_task.cancel()
        self._alone_task = None

    async def schedule_idle(self):
        self.cancel_idle()
        self._idle_task = asyncio.create_task(self._idle_worker())

    async def _idle_worker(self):
        await asyncio.sleep(INACTIVITY_TIMEOUT)
        if self._stopping or self.queue or self.current:
            return
        if self.voice and self.voice.is_connected() and not self.voice.is_playing():
            channel = self.voice.channel
            await self._notify(content=f"⏏️ Left **{channel.name}** after {int(INACTIVITY_TIMEOUT)}s of inactivity.")
            try:
                await self.voice.disconnect()
            except Exception:
                pass

    def _add_history(self, song: Optional[Song]):
        if song is None:
            return
        self.history.append(song)
        if len(self.history) > HISTORY_LIMIT:
            self.history.pop(0)

    def _pop_next(self) -> Song:
        if self.shuffle_on and len(self.queue) > 1:
            return self.queue.pop(random.randrange(len(self.queue)))
        return self.queue.pop(0)

    # --------------------------------------------------------- playback

    def _source(self, stream_url: str, start_seconds: float = 0.0) -> discord.AudioSource:
        before = FFMPEG_BEFORE_OPTIONS
        if start_seconds and start_seconds > 0:
            before += f" -ss {start_seconds}"
        return discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(
                stream_url,
                before_options=before,
                options=FFMPEG_OPTIONS,
            ),
            volume=self.volume,
        )

    async def _start_playback(self, song: Song, *, announce: bool = True, start_seconds: Optional[float] = None):
        if not self.voice or not self.voice.is_connected():
            raise MusicError("I'm not connected to a voice channel anymore.")
        if not discord.opus.is_loaded():
            for lib in _OPUS_LIBS:
                try:
                    discord.opus.load_opus(lib)
                    break
                except OSError:
                    continue

        await song.ensure_resolved()

        if self._stopping or not self.voice or not self.voice.is_connected():
            raise MusicError("Playback was stopped before I could start that track.")

        self._stopping = False
        is_new = song is not self.current
        if is_new:
            self._seek_offset = 0.0
        if start_seconds is None:
            start_seconds = self._seek_offset
        if song.duration:
            start_seconds = min(max(0.0, start_seconds), max(0, song.duration - 1))
        else:
            start_seconds = 0.0

        self.current = song
        self._elapsed = start_seconds
        self._paused = False
        self._started_at = time.monotonic()
        source = self._source(song.stream_url, start_seconds)
        self.voice.play(source, after=self._on_ffmpeg_done)
        asyncio.create_task(self.bot.change_presence(
            activity=discord.Activity(name=song.title, type=discord.ActivityType.listening)
        ))
        if announce:
            asyncio.create_task(self._send_now_playing())
        self._start_progress_updater()

    def _start_progress_updater(self):
        """Start background task to update the now-playing embed progress bar."""
        if self._progress_task and not self._progress_task.done():
            self._progress_task.cancel()
        self._progress_task = asyncio.create_task(self._progress_updater())

    async def _progress_updater(self):
        """Periodically update the now-playing embed with current progress."""
        while True:
            await asyncio.sleep(PROGRESS_UPDATE_INTERVAL)
            if self._stopping or not self.current or not self.voice:
                break
            if not self.voice.is_connected():
                break
            if not (self.voice.is_playing() or self.voice.is_paused()):
                continue
            if self._now_message:
                try:
                    await self._now_message.edit(embed=self.now_playing_embed(), view=PlayerView(self))
                except (discord.HTTPException, discord.NotFound):
                    self._now_message = None

    def _on_ffmpeg_done(self, error: Optional[Exception]):
        """Runs on the FFmpeg thread — hop back onto the bot loop."""
        asyncio.run_coroutine_threadsafe(self._handle_track_end(error), self.bot.loop)

    async def _handle_track_end(self, error: Optional[Exception]):
        if self._stopping or not self.voice or not self.voice.is_connected():
            return

        # A /previous or /jump asked us to switch to a specific track.
        if self._force_next is not None:
            song = self._force_next
            self._force_next = None
            try:
                await self._start_playback(song)
                return
            except MusicError as exc:
                await self._notify(content=f"⚠️ {exc} — skipping.")
                # Fall through and continue with the queue.

        # A /seek asked us to restart the current track at an offset.
        if self._seek_pending is not None and self.current:
            offset = self._seek_pending
            self._seek_pending = None
            self._seek_offset = offset
            await self._start_playback(self.current, announce=False, start_seconds=offset)
            return

        # One retry with a freshly extracted stream (URLs expire).
        if error and self.current and self._retry_count < 1:
            self._retry_count += 1
            await self._notify(content=f"⚠️ Stream hiccup, retrying **{self.current.title}**…")
            try:
                self.current.stream_url = None
                await self._start_playback(self.current, announce=False, start_seconds=self._seek_offset)
                return
            except Exception:
                pass

        self._retry_count = 0
        self._seek_offset = 0.0

        if self.loop_mode == "one" and self.current:
            await self._start_playback(self.current)
            return

        if self.loop_mode == "all" and self.current:
            self.queue.append(self.current)
        else:
            self._add_history(self.current)

        # Advance, skipping any track that fails to resolve.
        while self.queue:
            next_song = self._pop_next()
            try:
                await self._start_playback(next_song)
                return
            except MusicError as exc:
                await self._notify(content=f"⚠️ {exc} — skipping.")
                continue

        self.current = None
        await self.bot.change_presence(activity=None)
        await self.schedule_idle()

    # -------------------------------------------------------- embeds

    async def _send_now_playing(self):
        if self.current is None:
            return
        embed = self.now_playing_embed()
        view = PlayerView(self)
        if self._now_message:
            try:
                await self._now_message.edit(embed=embed, view=view)
                return
            except (discord.HTTPException, discord.NotFound):
                self._now_message = None
        self._now_message = await self._notify(embed=embed, view=view)

    def now_playing_embed(self) -> discord.Embed:
        song = self.current
        embed = discord.Embed(title="🎵 Now Playing", color=COLOR_NOW_PLAYING)
        embed.description = f"[**{song.title}**]({song.url})"
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        embed.add_field(name="Channel", value=song.uploader or "Unknown", inline=True)
        embed.add_field(
            name="Progress",
            value=f"`{_progress_bar(self.position(), song.duration)}`\n`{_fmt_duration(int(self.position()))} / {_fmt_duration(song.duration)}`",
            inline=True,
        )
        embed.add_field(name="Requested by", value=song.requester.mention, inline=True)
        embed.add_field(name="Volume", value=f"🔊 {int(self.volume * 100)}%", inline=True)
        embed.add_field(name="Loop", value=_loop_label(self.loop_mode), inline=True)
        embed.add_field(name="Shuffle", value="✅ On" if self.shuffle_on else "Off", inline=True)
        if self.queue:
            embed.add_field(
                name="Up next",
                value="\n".join(f"`{i}.` **{s.title}** — {_fmt_duration(s.duration)}" for i, s in enumerate(self.queue[:3], 1)),
                inline=False,
            )
        else:
            embed.add_field(name="Up next", value="Nothing queued — use `/play`", inline=False)
        embed.set_footer(text=f"{len(self.queue)} track(s) in queue · use the buttons or /seek, /jump, /move")
        return embed

    # --------------------------------------------------------- teardown

    @staticmethod
    async def _clear_view(message: discord.Message):
        try:
            await message.edit(view=None)
        except (discord.HTTPException, discord.NotFound):
            pass

    def shutdown(self, disconnect: bool = True):
        """Stop playback and drop state; optionally leave the voice channel."""
        self.cancel_idle()
        self.cancel_alone()
        if self._progress_task and not self._progress_task.done():
            self._progress_task.cancel()
        self._stopping = True
        self._force_next = None
        self._seek_pending = None
        self.queue.clear()
        self.current = None
        if self._now_message:
            asyncio.create_task(self._clear_view(self._now_message))
        self._now_message = None
        if self.voice:
            try:
                if self.voice.is_playing() or self.voice.is_paused():
                    self.voice.stop()
                if disconnect and self.voice.is_connected():
                    asyncio.create_task(self.voice.disconnect())
            except Exception:
                pass
        self.voice = None
        asyncio.create_task(self.bot.change_presence(activity=None))


# -------------------------------------------------------------------- cog


class Music(commands.Cog):
    """Play YouTube audio in voice channels via yt-dlp + FFmpeg.

    **Commands:**
    • `/play <query>` — Play a URL, search a name, or queue a whole playlist
    • `/playnext <query>` — Queue a track (or playlist) at the front of the queue
    • `/find <query>` — Search YouTube and pick from the top results
    • `/pause` / `/resume` — Pause and resume the current track
    • `/skip` — Skip the current track
    • `/previous` — Go back to the previous track
    • `/seek <time>` — Jump to a timestamp (e.g. `90` or `1:30`)
    • `/jump <position>` — Play a queued track immediately
    • `/move <from> <to>` — Move a track within the queue
    • `/stop` — Stop playback and clear the queue
    • `/queue` — Show the queue (interactive paginated view)
    • `/nowplaying` — Show current track with progress (interactive controls)
    • `/volume <1-100>` — Set playback volume
    • `/shuffle` — Toggle shuffle mode
    • `/loop [none|one|all]` — Set loop mode
    • `/remove <position>` — Remove a track from queue
    • `/clear` — Clear the queue
    • `/join` — Make the bot join your voice channel
    • `/leave` — Make the bot leave the voice channel
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildPlayer] = {}

    # ------------------------------------------------------------ helpers

    def _player(self, guild_id: int, text_channel: Optional[discord.TextChannel] = None) -> GuildPlayer:
        player = self.players.get(guild_id)
        if player is None:
            player = GuildPlayer(self.bot, guild_id, text_channel)
            self.players[guild_id] = player
        if text_channel is not None:
            player.text_channel = text_channel
        return player

    def _active_player(self, ctx) -> GuildPlayer:
        guild = ctx.guild
        if guild is None:
            raise MusicError("This command only works inside a server.")
        player = self.players.get(guild.id)
        if player is None or not player.voice or not player.voice.is_connected():
            raise MusicError("I'm not in a voice channel. Use `/play` to start some music.")
        return player

    async def _connect(self, ctx) -> GuildPlayer:
        """Join the caller's channel (or reuse the existing connection)."""
        author = u.author_of(ctx)
        guild = ctx.guild
        if guild is None:
            raise MusicError("This command only works inside a server.")
        voice_state = author.voice
        if voice_state is None or voice_state.channel is None:
            raise MusicError("You must be in a voice channel first.")
        channel = voice_state.channel
        if not channel.permissions_for(guild.me).connect:
            raise MusicError(f"I don't have permission to **connect** to {channel.mention}.")
        if not channel.permissions_for(guild.me).speak:
            raise MusicError(f"I don't have permission to **speak** in {channel.mention}.")
        player = self._player(guild.id, text_channel=getattr(ctx, "channel", None))
        if player.voice and player.voice.is_connected():
            if player.voice.channel.id != channel.id:
                raise MusicError("I'm already playing in another voice channel — join me there or use `/leave` first.")
            return player
        try:
            player.voice = await channel.connect()
        except discord.ClientException as exc:
            player.voice = None
            raise MusicError(f"Couldn't join {channel.mention}: {exc}") from exc
        return player

    @staticmethod
    def _looks_like_playlist(query: str) -> bool:
        """Heuristic: a YouTube playlist URL has `list=` but no single `v=`."""
        if not query.startswith(("http://", "https://")):
            return False
        try:
            parsed = urllib.parse.urlparse(query)
            qs = urllib.parse.parse_qs(parsed.query)
        except ValueError:
            return False
        return "list" in qs and "v" not in qs

    async def _resolve_song(self, query: str, requester: discord.Member) -> Song:
        try:
            info = await asyncio.wait_for(asyncio.to_thread(_extract, query), timeout=EXTRACT_TIMEOUT)
        except asyncio.TimeoutError:
            raise MusicError("⏱️ That took too long — try again in a moment.") from None
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc).lower()
            if "no video results" in message or "no results" in message:
                raise MusicError(f"No search results for `{query}`.") from exc
            if "age" in message or "sign in" in message:
                raise MusicError("That video is age-restricted and can't be played.") from exc
            if "video unavailable" in message or "not available" in message or "private" in message:
                raise MusicError("That video is unavailable — private, deleted, or region-locked.") from exc
            raise MusicError(f"Couldn't load that: {str(exc).strip()[:200]}") from exc
        if not info:
            raise MusicError(f"No results for `{query}`.")
        if info.get("_type") == "playlist" or "entries" in info:
            raise MusicError("Playlist links aren't supported — give me a single video or a song name.")
        stream_url = info.get("url")
        if not stream_url:
            raise MusicError("No playable audio stream was found for that video.")
        try:
            return Song(
                title=info.get("title") or "Unknown",
                url=info.get("webpage_url") or query,
                stream_url=stream_url,
                duration=info.get("duration"),
                thumbnail=info.get("thumbnail"),
                uploader=info.get("uploader") or info.get("channel") or "Unknown",
                requester=requester,
                video_id=info.get("id"),
            )
        except Exception as exc:
            raise MusicError(f"Couldn't load that: {str(exc).strip()[:200]}") from exc

    async def _resolve_playlist(self, url: str, requester: discord.Member) -> list[Song]:
        try:
            entries = await asyncio.wait_for(asyncio.to_thread(_extract_playlist, url, PLAYLIST_LIMIT), EXTRACT_TIMEOUT)
        except asyncio.TimeoutError:
            raise MusicError("⏱️ That playlist took too long to read — try again.") from None
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc).lower()
            if "no results" in message or "not found" in message:
                raise MusicError("I couldn't find that playlist.") from exc
            raise MusicError(f"Couldn't read that playlist: {str(exc).strip()[:200]}") from exc

        songs: list[Song] = []
        for entry in entries:
            if not entry or not entry.get("id"):
                continue
            songs.append(
                Song(
                    title=entry.get("title") or "Unknown",
                    url=entry.get("webpage_url") or entry.get("url") or f"https://www.youtube.com/watch?v={entry['id']}",
                    stream_url=None,  # resolved lazily right before playback
                    duration=entry.get("duration"),
                    thumbnail=_best_thumbnail(entry),
                    uploader=entry.get("uploader") or entry.get("channel") or "Unknown",
                    requester=requester,
                    video_id=entry.get("id"),
                )
            )
        return songs

    async def _safe(self, ctx, action):
        try:
            await action()
        except MusicError as exc:
            await u.reply(ctx, embed=discord.Embed(description=f"❌ {exc}", color=COLOR_ERROR))
        except Exception as exc:
            await u.reply(ctx, embed=discord.Embed(description=f"❌ Unexpected error: {str(exc)[:200]}", color=COLOR_ERROR))

    @staticmethod
    async def _defer(ctx):
        if isinstance(ctx, discord.Interaction) and not ctx.response.is_done():
            await ctx.response.defer()

    async def _send(self, ctx, *, content: str = None, embed: discord.Embed = None, view=None, ephemeral: bool = False) -> Optional[discord.Message]:
        """Reply to either a prefix or slash context, returning the message."""
        if ctx is None:
            return None
        if isinstance(ctx, commands.Context):
            return await ctx.send(content=content, embed=embed, view=view)
        if not ctx.response.is_done():
            await ctx.response.send_message(content=content, embed=embed, view=view, ephemeral=ephemeral)
            return await ctx.original_response()
        return await ctx.followup.send(content=content, embed=embed, view=view, ephemeral=ephemeral)

    # ------------------------------------------------------- add / play

    def _added_embed(self, songs: list[Song], start: int) -> discord.Embed:
        if len(songs) == 1:
            s = songs[0]
            embed = discord.Embed(title="✅ Added to queue", description=f"[**{s.title}**]({s.url})", color=COLOR_NOW_PLAYING)
            if s.thumbnail:
                embed.set_thumbnail(url=s.thumbnail)
            embed.add_field(name="Position", value=f"**#{start}**", inline=True)
            embed.add_field(name="Duration", value=_fmt_duration(s.duration), inline=True)
            embed.add_field(name="Requested by", value=s.requester.mention, inline=True)
            embed.set_footer(text=f"{start} track(s) queued")
            return embed

        first = songs[0]
        embed = discord.Embed(
            title="✅ Added to queue",
            description=f"Queued **{len(songs)}** tracks (positions **#{start}–#{start + len(songs) - 1}**).",
            color=COLOR_NOW_PLAYING,
        )
        if first.thumbnail:
            embed.set_thumbnail(url=first.thumbnail)
        lines = [f"`{i}.` **{s.title}** — {_fmt_duration(s.duration)}" for i, s in enumerate(songs[:5], 1)]
        if len(songs) > 5:
            lines.append(f"…and {len(songs) - 5} more")
        embed.add_field(name="Includes", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Requested by {first.requester.display_name}")
        return embed

    async def _start_or_queue(self, ctx, player: GuildPlayer, songs: list[Song]):
        """Start playback with the first song, or append the rest to the queue."""
        if not songs:
            raise MusicError("Nothing to play.")
        playing_now = player.current is None and not (player.voice and (player.voice.is_playing() or player.voice.is_paused()))
        queued_count = len(songs) - (1 if playing_now else 0)
        if len(player.queue) + queued_count > MAX_QUEUE_SIZE:
            raise MusicError(f"The queue is limited to **{MAX_QUEUE_SIZE}** tracks — I can't add {len(songs)} more.")
        try:
            if playing_now:
                first = songs.pop(0)
                await player._start_playback(first, announce=False)
                player.queue.extend(songs)
                embed = player.now_playing_embed()
                if songs:
                    embed.add_field(name="Also queued", value=f"Added **{len(songs)}** more track(s).", inline=False)
                msg = await self._send(ctx, embed=embed, view=PlayerView(player))
                player._now_message = msg
                return
            start = len(player.queue) + 1
            player.queue.extend(songs)
            await self._send(ctx, embed=self._added_embed(songs, start))
        except MusicError:
            if player.current is None and not (player.voice and (player.voice.is_playing() or player.voice.is_paused())):
                await player.schedule_idle()
            raise

    async def _play(self, ctx, query: str):
        query = (query or "").strip()
        if not query:
            raise MusicError("Give me a song name, YouTube URL, or playlist URL to play.")
        if not shutil.which("ffmpeg"):
            raise MusicError("**FFmpeg isn't installed** on this machine. Install it and restart the bot.")
        await self._defer(ctx)
        requester = u.author_of(ctx)
        if self._looks_like_playlist(query):
            songs = await self._resolve_playlist(query, requester)
            if not songs:
                raise MusicError("That playlist is empty or I couldn't read it.")
        else:
            songs = [await self._resolve_song(query, requester)]
        player = await self._connect(ctx)
        player.cancel_idle()
        await self._start_or_queue(ctx, player, songs)

    async def _playnext(self, ctx, query: str):
        query = (query or "").strip()
        if not query:
            raise MusicError("Give me a song name or URL to play next.")
        if not shutil.which("ffmpeg"):
            raise MusicError("**FFmpeg isn't installed** on this machine. Install it and restart the bot.")
        await self._defer(ctx)
        requester = u.author_of(ctx)
        if self._looks_like_playlist(query):
            songs = await self._resolve_playlist(query, requester)
            if not songs:
                raise MusicError("That playlist is empty or I couldn't read it.")
        else:
            songs = [await self._resolve_song(query, requester)]
        player = await self._connect(ctx)
        player.cancel_idle()
        if len(player.queue) + len(songs) > MAX_QUEUE_SIZE:
            raise MusicError(f"The queue is limited to **{MAX_QUEUE_SIZE}** tracks.")
        playing_now = player.current is None and not (player.voice and (player.voice.is_playing() or player.voice.is_paused()))
        if playing_now:
            await self._start_or_queue(ctx, player, songs)
            return
        for s in reversed(songs):
            player.queue.insert(0, s)
        if len(songs) == 1:
            await self._send(ctx, embed=discord.Embed(description=f"⏭️ **{songs[0].title}** will play next.", color=COLOR_NOW_PLAYING))
        else:
            await self._send(ctx, embed=discord.Embed(description=f"⏭️ Queued **{len(songs)}** track(s) to play next.", color=COLOR_NOW_PLAYING))

    async def _search(self, ctx, query: str):
        query = (query or "").strip()
        if not query:
            raise MusicError("Give me something to search for.")
        await self._defer(ctx)
        try:
            entries = await asyncio.wait_for(asyncio.to_thread(_extract_search, query, SEARCH_LIMIT), EXTRACT_TIMEOUT)
        except asyncio.TimeoutError:
            raise MusicError("⏱️ Search timed out — try again in a moment.") from None
        except yt_dlp.utils.DownloadError as exc:
            raise MusicError(f"Search failed: {str(exc).strip()[:200]}") from exc
        entries = [e for e in (entries or []) if e.get("id")]
        if not entries:
            raise MusicError(f"No results found for `{query}`.")
        await self._send(ctx, embed=self._search_embed(query, entries), view=SearchView(self, entries))

    def _search_embed(self, query: str, entries: list) -> discord.Embed:
        embed = discord.Embed(title="🔎 Search Results", description=f"Pick a track for **{query}**:", color=COLOR_QUEUE)
        for i, entry in enumerate(entries, 1):
            title = entry.get("title") or "Unknown"
            uploader = entry.get("uploader") or entry.get("channel") or "Unknown"
            embed.add_field(name=f"{i}. {title}", value=f"`{_fmt_duration(entry.get('duration'))}` · {uploader}", inline=False)
        embed.set_footer(text="Choose from the dropdown below to play a track.")
        return embed

    async def _reply_now_playing(self, ctx):
        player = self._active_player(ctx)
        if player.current is None:
            raise MusicError("Nothing is playing right now.")
        msg = await self._send(ctx, embed=player.now_playing_embed(), view=PlayerView(player))
        player._now_message = msg

    # ------------------------------------------------------------- play

    @commands.command(name="play", aliases=["p"], help="Play a YouTube URL, search a name, or queue a playlist.", usage="b.play <url, playlist, or song name>")
    async def play(self, ctx: commands.Context, *, query: str):
        await self._safe(ctx, lambda: self._play(ctx, query))

    @app_commands.command(name="play", description="Play a YouTube URL, search a name, or queue a playlist.")
    @app_commands.describe(query="A YouTube URL, playlist URL, or a song name to search")
    async def slash_play(self, interaction: discord.Interaction, query: str):
        await self._safe(interaction, lambda: self._play(interaction, query))

    # ---------------------------------------------------------- playnext

    @commands.command(name="playnext", aliases=["pn", "nextup"], help="Queue a track (or playlist) at the front of the queue.", usage="b.playnext <url or song name>")
    async def playnext(self, ctx: commands.Context, *, query: str):
        await self._safe(ctx, lambda: self._playnext(ctx, query))

    @app_commands.command(name="playnext", description="Queue a track (or playlist) at the front of the queue.")
    @app_commands.describe(query="A YouTube URL, playlist URL, or a song name to search")
    async def slash_playnext(self, interaction: discord.Interaction, query: str):
        await self._safe(interaction, lambda: self._playnext(interaction, query))

    # --------------------------------------------------------------- find

    @commands.command(name="find", aliases=["song"], help="Search YouTube for a song and pick from the top results.", usage="b.find <song name>")
    async def find(self, ctx: commands.Context, *, query: str):
        await self._safe(ctx, lambda: self._search(ctx, query))

    @app_commands.command(name="find", description="Search YouTube for a song and pick from the top results.")
    @app_commands.describe(query="What to search for")
    async def slash_find(self, interaction: discord.Interaction, query: str):
        await self._safe(interaction, lambda: self._search(interaction, query))

    # ------------------------------------------------------------ pause

    async def _pause(self, ctx):
        player = self._active_player(ctx)
        if player.voice.is_paused():
            raise MusicError("Playback is already paused.")
        if not player.voice.is_playing():
            raise MusicError("Nothing is playing right now.")
        player._elapsed += time.monotonic() - player._started_at
        player._paused = True
        player.voice.pause()
        await self._reply_now_playing(ctx)

    @commands.command(name="pause", help="Pause the current track.", usage="b.pause")
    async def pause(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._pause(ctx))

    @app_commands.command(name="pause", description="Pause the current track.")
    async def slash_pause(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._pause(interaction))

    # ------------------------------------------------------------ resume

    async def _resume(self, ctx):
        player = self._active_player(ctx)
        if not player.voice.is_paused():
            raise MusicError("Playback isn't paused.")
        player._paused = False
        player._started_at = time.monotonic()
        player.voice.resume()
        await self._reply_now_playing(ctx)

    @commands.command(name="resume", help="Resume the paused track.", usage="b.resume")
    async def resume(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._resume(ctx))

    @app_commands.command(name="resume", description="Resume the paused track.")
    async def slash_resume(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._resume(interaction))

    # -------------------------------------------------------------- skip

    async def _skip(self, ctx):
        player = self._active_player(ctx)
        if not player.voice.is_playing() and not player.voice.is_paused():
            raise MusicError("Nothing is playing right now.")
        skipped = player.current
        player.voice.stop()
        await self._send(ctx, embed=discord.Embed(
            description=f"⏭️ Skipped **{skipped.title}**." if skipped else "⏭️ Skipped.",
            color=COLOR_NOW_PLAYING,
        ))

    @commands.command(name="skip", aliases=["next", "s"], help="Skip the current track.", usage="b.skip")
    async def skip(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._skip(ctx))

    @app_commands.command(name="skip", description="Skip the current track.")
    async def slash_skip(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._skip(interaction))

    # ----------------------------------------------------------- previous

    async def _previous(self, ctx):
        player = self._active_player(ctx)
        if not player.history:
            raise MusicError("There's no previous track to go back to.")
        prev = player.history.pop()
        if player.current:
            player.queue.insert(0, player.current)
        if player.voice and (player.voice.is_playing() or player.voice.is_paused()):
            player._force_next = prev
            player.voice.stop()
        else:
            await player._start_playback(prev)
        await self._send(ctx, embed=discord.Embed(
            description=f"⏮️ Going back to **{prev.title}**.",
            color=COLOR_NOW_PLAYING,
        ))

    @commands.command(name="previous", aliases=["prev", "back"], help="Go back to the previous track.", usage="b.previous")
    async def previous(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._previous(ctx))

    @app_commands.command(name="previous", description="Go back to the previous track.")
    async def slash_previous(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._previous(interaction))

    # --------------------------------------------------------------- seek

    async def _seek(self, ctx, position: str):
        player = self._active_player(ctx)
        if not player.voice.is_playing() and not player.voice.is_paused():
            raise MusicError("Nothing is playing right now.")
        song = player.current
        if song is None:
            raise MusicError("Nothing is playing right now.")
        if not song.duration:
            raise MusicError("Can't seek in a live stream.")
        seconds = _parse_position(position)
        seconds = max(0, min(seconds, song.duration - 1))
        player._seek_pending = seconds
        player.voice.stop()
        await self._send(ctx, embed=discord.Embed(
            description=f"⏩ Seeking to **{_fmt_duration(seconds)}** in **{song.title}**.",
            color=COLOR_NOW_PLAYING,
        ))

    @commands.command(name="seek", help="Jump to a timestamp in the current track.", usage="b.seek <90 or 1:30>")
    async def seek(self, ctx: commands.Context, *, position: str):
        await self._safe(ctx, lambda: self._seek(ctx, position))

    @app_commands.command(name="seek", description="Jump to a timestamp in the current track.")
    @app_commands.describe(position="Timestamp like 90 (seconds) or 1:30")
    async def slash_seek(self, interaction: discord.Interaction, position: str):
        await self._safe(interaction, lambda: self._seek(interaction, position))

    # --------------------------------------------------------------- jump

    async def _jump(self, ctx, index: int):
        player = self._active_player(ctx)
        if index < 1 or index > len(player.queue):
            raise MusicError(f"Invalid position. The queue has {len(player.queue)} track(s).")
        song = player.queue.pop(index - 1)
        if player.current:
            player.queue.insert(0, player.current)
        if player.voice and (player.voice.is_playing() or player.voice.is_paused()):
            player._force_next = song
            player.voice.stop()
        else:
            await player._start_playback(song)
        await self._send(ctx, embed=discord.Embed(
            description=f"⏭️ Jumping to **{song.title}**.",
            color=COLOR_NOW_PLAYING,
        ))

    @commands.command(name="jump", aliases=["jumpto"], help="Play a queued track immediately.", usage="b.jump <position>")
    async def jump(self, ctx: commands.Context, index: int):
        await self._safe(ctx, lambda: self._jump(ctx, index))

    @app_commands.command(name="jump", description="Play a queued track immediately.")
    @app_commands.describe(index="Queue position of the track to play")
    async def slash_jump(self, interaction: discord.Interaction, index: app_commands.Range[int, 1, MAX_QUEUE_SIZE]):
        await self._safe(interaction, lambda: self._jump(interaction, index))

    # --------------------------------------------------------------- move

    async def _move(self, ctx, from_pos: int, to_pos: int):
        player = self._active_player(ctx)
        n = len(player.queue)
        if n < 2:
            raise MusicError("Need at least 2 queued tracks to move things around.")
        if from_pos < 1 or from_pos > n:
            raise MusicError(f"`from` must be between 1 and {n}.")
        if to_pos < 1 or to_pos > n:
            raise MusicError(f"`to` must be between 1 and {n}.")
        song = player.queue.pop(from_pos - 1)
        player.queue.insert(to_pos - 1, song)
        await self._send(ctx, embed=discord.Embed(
            description=f"↕️ Moved **{song.title}** from #**{from_pos}** to #**{to_pos}**.",
            color=COLOR_NOW_PLAYING,
        ))

    @commands.command(name="move", aliases=["mv"], help="Move a track within the queue.", usage="b.move <from> <to>")
    async def move(self, ctx: commands.Context, from_pos: int, to_pos: int):
        await self._safe(ctx, lambda: self._move(ctx, from_pos, to_pos))

    @app_commands.command(name="move", description="Move a track within the queue.")
    @app_commands.describe(from_pos="Current position", to_pos="New position")
    async def slash_move(self, interaction: discord.Interaction, from_pos: app_commands.Range[int, 1, MAX_QUEUE_SIZE], to_pos: app_commands.Range[int, 1, MAX_QUEUE_SIZE]):
        await self._safe(interaction, lambda: self._move(interaction, from_pos, to_pos))

    # -------------------------------------------------------------- stop

    async def _stop(self, ctx):
        player = self._active_player(ctx)
        channel = player.voice.channel
        player.shutdown(disconnect=False)
        await player.schedule_idle()
        await self._send(ctx, embed=discord.Embed(
            description=f"⏹️ Stopped playback and cleared the queue. I'll leave **{channel.name}** after {int(INACTIVITY_TIMEOUT)}s of inactivity.",
            color=COLOR_NOW_PLAYING,
        ))

    @commands.command(name="stop", help="Stop playback, clear the queue, and schedule leaving.", usage="b.stop")
    async def stop(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._stop(ctx))

    @app_commands.command(name="stop", description="Stop playback and clear the queue.")
    async def slash_stop(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._stop(interaction))

    # ------------------------------------------------------------- queue

    async def _queue(self, ctx):
        player = self._active_player(ctx)
        view = QueueView(player)
        await self._send(ctx, embed=view._get_page_embed(), view=view)

    @commands.command(name="queue", aliases=["q"], help="Show the current queue (interactive).", usage="b.queue")
    async def queue(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._queue(ctx))

    @app_commands.command(name="queue", description="Show the current queue (interactive).")
    async def slash_queue(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._queue(interaction))

    # -------------------------------------------------------- nowplaying

    @commands.command(name="nowplaying", aliases=["np"], help="Show the current track and progress (interactive).", usage="b.nowplaying")
    async def nowplaying(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._reply_now_playing(ctx))

    @app_commands.command(name="nowplaying", description="Show the current track and progress (interactive).")
    async def slash_nowplaying(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._reply_now_playing(interaction))

    # ------------------------------------------------------------ volume

    async def _volume(self, ctx, volume: int):
        player = self._active_player(ctx)
        clamped = max(1, min(100, volume))
        player.volume = clamped / 100
        if isinstance(player.voice.source, discord.PCMVolumeTransformer):
            player.voice.source.volume = player.volume
        note = f" (clamped from {volume})" if volume != clamped else ""
        await self._send(ctx, embed=discord.Embed(
            description=f"🔊 Volume set to **{clamped}%**{note}.", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="volume", aliases=["vol"], help="Set playback volume from 1 to 100.", usage="b.volume <1-100>")
    async def volume(self, ctx: commands.Context, volume: int):
        await self._safe(ctx, lambda: self._volume(ctx, volume))

    @app_commands.command(name="volume", description="Set playback volume from 1 to 100.")
    @app_commands.describe(volume="New volume (1-100)")
    async def slash_volume(self, interaction: discord.Interaction, volume: app_commands.Range[int, 1, 100]):
        await self._safe(interaction, lambda: self._volume(interaction, volume))

    # ------------------------------------------------------------ shuffle

    async def _shuffle(self, ctx):
        player = self._active_player(ctx)
        if len(player.queue) < 2:
            raise MusicError("Need at least 2 queued tracks to shuffle.")
        player.shuffle_on = not player.shuffle_on
        if player.shuffle_on:
            random.shuffle(player.queue)
        state = "✅ On" if player.shuffle_on else "Off"
        await self._send(ctx, embed=discord.Embed(
            description=f"🔀 Shuffle mode: **{state}**.", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="shuffle", help="Toggle shuffle mode on or off.", usage="b.shuffle")
    async def shuffle(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._shuffle(ctx))

    @app_commands.command(name="shuffle", description="Toggle shuffle mode on or off.")
    async def slash_shuffle(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._shuffle(interaction))

    # --------------------------------------------------------------- loop

    async def _loop(self, ctx, mode: Optional[str] = None):
        player = self._active_player(ctx)
        if mode in ("none", "one", "all"):
            player.loop_mode = mode
        else:
            cycle = {"none": "one", "one": "all", "all": "none"}
            player.loop_mode = cycle.get(player.loop_mode, "none")
        await self._send(ctx, embed=discord.Embed(
            description=f"🔁 Loop mode: **{_loop_label(player.loop_mode)}**", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="loop", help="Toggle loop: none, one (track), or all (queue).", usage="b.loop [none|one|all]")
    async def loop(self, ctx: commands.Context, mode: str = None):
        await self._safe(ctx, lambda: self._loop(ctx, mode))

    @app_commands.command(name="loop", description="Set loop mode: none, one (track) or all (queue).")
    @app_commands.choices(mode=[
        app_commands.Choice(name="None", value="none"),
        app_commands.Choice(name="One (track)", value="one"),
        app_commands.Choice(name="All (queue)", value="all"),
    ])
    async def slash_loop(self, interaction: discord.Interaction, mode: str = None):
        await self._safe(interaction, lambda: self._loop(interaction, mode))

    # ------------------------------------------------------------- remove

    async def _remove(self, ctx, index: int):
        player = self._active_player(ctx)
        if index < 1 or index > len(player.queue):
            raise MusicError(f"Invalid position. Use `/queue` — there are {len(player.queue)} queued track(s).")
        song = player.queue.pop(index - 1)
        await self._send(ctx, embed=discord.Embed(
            description=f"🗑️ Removed **{song.title}** (was #**{index}**).", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="remove", help="Remove a track from the queue by position.", usage="b.remove <position>")
    async def remove(self, ctx: commands.Context, index: int):
        await self._safe(ctx, lambda: self._remove(ctx, index))

    @app_commands.command(name="remove", description="Remove a track from the queue by position.")
    @app_commands.describe(index="Queue position of the track to remove")
    async def slash_remove(self, interaction: discord.Interaction, index: app_commands.Range[int, 1, MAX_QUEUE_SIZE]):
        await self._safe(interaction, lambda: self._remove(interaction, index))

    # -------------------------------------------------------------- clear

    async def _clear(self, ctx):
        player = self._active_player(ctx)
        if not player.queue:
            raise MusicError("The queue is already empty.")
        count = len(player.queue)
        player.queue.clear()
        await self._send(ctx, embed=discord.Embed(
            description=f"🧹 Cleared **{count}** track(s) from the queue.", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="clear", help="Clear the queue (keeps the current track).", usage="b.clear")
    async def clear(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._clear(ctx))

    @app_commands.command(name="clear", description="Clear the queue (keeps the current track).")
    async def slash_clear(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._clear(interaction))

    # --------------------------------------------------------------- join

    async def _join(self, ctx):
        player = await self._connect(ctx)
        channel = player.voice.channel
        await self._send(ctx, embed=discord.Embed(
            description=f"🔊 Joined **{channel.name}**. Use `/play` to start some music!", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="join", help="Make the bot join your voice channel.", usage="b.join")
    async def join(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._join(ctx))

    @app_commands.command(name="join", description="Make the bot join your voice channel.")
    async def slash_join(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._join(interaction))

    # -------------------------------------------------------------- leave

    async def _leave(self, ctx):
        guild = ctx.guild
        if guild is None:
            raise MusicError("This command only works inside a server.")
        player = self.players.get(guild.id)
        if player is None or not player.voice or not player.voice.is_connected():
            raise MusicError("I'm not in a voice channel.")
        channel = player.voice.channel
        player.shutdown(disconnect=True)
        self.players.pop(guild.id, None)
        await self._send(ctx, embed=discord.Embed(
            description=f"👋 Left **{channel.name}** and cleared the queue.", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="leave", aliases=["dc", "disconnect"], help="Make the bot leave the voice channel.", usage="b.leave")
    async def leave(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._leave(ctx))

    @app_commands.command(name="leave", description="Make the bot leave the voice channel.")
    async def slash_leave(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._leave(interaction))

    # ------------------------------------------------------------ events

    async def _leave_when_alone(self, player: GuildPlayer):
        await asyncio.sleep(ALONE_TIMEOUT)
        if not player.voice or not player.voice.is_connected():
            return
        channel = player.voice.channel
        humans = [m for m in channel.members if not m.bot]
        if humans:
            return
        await player._notify(content=f"👋 Nobody is in **{channel.name}** anymore, so I'm leaving. Use `/play` to bring me back!")
        player.shutdown(disconnect=True)
        self.players.pop(player.guild_id, None)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id == self.bot.user.id:
            # The bot was disconnected or moved externally.
            player = self.players.get(member.guild.id)
            if player is None:
                return
            if after.channel is None:
                # Disconnected — clean up but don't try to reconnect.
                player.shutdown(disconnect=False)
                self.players.pop(member.guild.id, None)
            elif before.channel and before.channel.id != after.channel.id:
                # Moved to another channel — leave gracefully.
                player.shutdown(disconnect=True)
                self.players.pop(member.guild.id, None)
            return

        # Track whether the bot has been left alone in its channel.
        player = self.players.get(member.guild.id)
        if player is None or not player.voice or not player.voice.is_connected():
            return
        channel = player.voice.channel
        if before.channel and before.channel.id == channel.id and after.channel != channel:
            humans = [m for m in channel.members if not m.bot]
            if not humans:
                player.cancel_alone()
                player._alone_task = asyncio.create_task(self._leave_when_alone(player))
        elif after.channel == channel and before.channel != channel:
            player.cancel_alone()

    async def cog_unload(self):
        for player in list(self.players.values()):
            player.shutdown(disconnect=True)
        self.players.clear()


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
