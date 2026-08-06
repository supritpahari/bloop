"""Music system: YouTube playback via yt-dlp + FFmpeg, per-guild player state.

No Lavalink/Wavelink — every track is extracted directly with yt-dlp and
streamed to the voice channel with FFmpeg. Requires `ffmpeg` and `libopus`
on the host, plus the `yt-dlp` and `PyNaCl` pip packages.
"""

import asyncio
import random
import shutil
import time
from dataclasses import dataclass
from typing import Optional

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from economy import utils as u

INACTIVITY_TIMEOUT = 300.0  # seconds idle before leaving the voice channel
EXTRACT_TIMEOUT = 20.0  # max seconds a yt-dlp extraction may take
MAX_QUEUE_LIST = 10  # tracks shown in the /queue embed before "+N more"

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


class MusicError(Exception):
    """A user-facing music failure with a ready-to-display message."""


# --------------------------------------------------------------------- data


@dataclass
class Song:
    title: str
    url: str
    stream_url: str
    duration: Optional[int]
    thumbnail: Optional[str]
    uploader: str
    requester: discord.Member


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
        self.volume: float = 1.0
        self.loop_mode: str = "none"  # none | one | all
        self.shuffle_on: bool = False
        self._started_at: float = 0.0
        self._elapsed: float = 0.0
        self._paused: bool = False
        self._stopping: bool = False
        self._idle_task: Optional[asyncio.Task] = None
        self._now_message: Optional[discord.Message] = None
        self._retry_count: int = 0

    # ------------------------------------------------------------ helpers

    def position(self) -> float:
        """Seconds elapsed in the current track (accounts for pauses)."""
        if not self.current:
            return 0.0
        if self._paused:
            return self._elapsed
        return self._elapsed + (time.monotonic() - self._started_at)

    async def _notify(self, embed: Optional[discord.Embed] = None, content: str = None):
        if self.text_channel is None:
            return
        try:
            await self.text_channel.send(content=content, embed=embed)
        except discord.HTTPException:
            pass

    def cancel_idle(self):
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

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

    # --------------------------------------------------------- playback

    def _source(self, stream_url: str) -> discord.AudioSource:
        return discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(
                stream_url,
                before_options=FFMPEG_BEFORE_OPTIONS,
                options=FFMPEG_OPTIONS,
            ),
            volume=self.volume,
        )

    def _start_playback(self, song: Song, announce: bool = True):
        if not self.voice or not self.voice.is_connected():
            raise MusicError("I'm not connected to a voice channel anymore.")
        if not discord.opus.is_loaded():
            for lib in ("libopus.so.0", "libopus.so", "opus.dll", "libopus.0.dylib"):
                try:
                    discord.opus.load_opus(lib)
                    break
                except OSError:
                    continue
        self._stopping = False
        self.current = song
        self._elapsed = 0.0
        self._paused = False
        self._started_at = time.monotonic()
        source = self._source(song.stream_url)
        self.voice.play(source, after=self._on_ffmpeg_done)
        asyncio.create_task(self.bot.change_presence(
            activity=discord.Activity(name=song.title, type=discord.ActivityType.listening)
        ))
        if announce:
            asyncio.create_task(self._send_now_playing())

    def _on_ffmpeg_done(self, error: Optional[Exception]):
        """Runs on the FFmpeg thread — hop back onto the bot loop."""
        asyncio.run_coroutine_threadsafe(self._handle_track_end(error), self.bot.loop)

    async def _handle_track_end(self, error: Optional[Exception]):
        if self._stopping or not self.voice or not self.voice.is_connected():
            return
        if error and self.current and self._retry_count < 1:
            # One retry with a freshly extracted stream (URLs expire).
            self._retry_count += 1
            await self._notify(content=f"⚠️ Stream hiccup, retrying **{self.current.title}**…")
            try:
                info = await asyncio.wait_for(asyncio.to_thread(_extract, self.current.url), EXTRACT_TIMEOUT)
                self.current.stream_url = info["url"]
                self._start_playback(self.current)
                return
            except Exception:
                pass
        self._retry_count = 0
        if self.loop_mode == "one" and self.current:
            self._start_playback(self.current)
            return
        if self.loop_mode == "all" and self.current:
            self.queue.append(self.current)
        if self.queue:
            next_song = self.queue.pop(0)
            self._start_playback(next_song)
            return
        self.current = None
        await self.bot.change_presence(activity=None)
        await self.schedule_idle()

    # -------------------------------------------------------- embeds

    async def _send_now_playing(self):
        embed = self.now_playing_embed()
        if self._now_message:
            try:
                await self._now_message.edit(embed=embed)
                return
            except discord.HTTPException:
                pass
        await self._notify(embed=embed)
        self._now_message = None

    def now_playing_embed(self) -> discord.Embed:
        song = self.current
        embed = discord.Embed(title="🎵 Now Playing", color=COLOR_NOW_PLAYING)
        embed.description = f"[**{song.title}**]({song.url})"
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        embed.add_field(name="Uploader", value=song.uploader or "Unknown")
        embed.add_field(name="Duration", value=f"`{_progress_bar(self.position(), song.duration)}`\n`{_fmt_duration(int(self.position()))} / {_fmt_duration(song.duration)}`", inline=True)
        embed.add_field(name="Requested by", value=song.requester.mention, inline=True)
        embed.add_field(name="Volume", value=f"{int(self.volume * 100)}%", inline=True)
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
        embed.set_footer(text=f"{len(self.queue)} track(s) in queue")
        return embed

    def queue_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🎶 Music Queue", color=COLOR_NOW_PLAYING)
        if self.current:
            embed.description = f"▶ **{self.current.title}** — {_fmt_duration(self.current.duration)} (now playing)"
        if not self.queue:
            embed.add_field(name="Up next", value="Empty — use `/play` to add tracks.", inline=False)
        else:
            lines = [
                f"`{i}.` **{s.title}** — {_fmt_duration(s.duration)} · {s.requester.mention}"
                for i, s in enumerate(self.queue[:MAX_QUEUE_LIST], 1)
            ]
            if len(self.queue) > MAX_QUEUE_LIST:
                lines.append(f"…and {len(self.queue) - MAX_QUEUE_LIST} more")
            embed.add_field(name=f"Up next ({len(self.queue)})", value="\n".join(lines), inline=False)
        embed.set_footer(
            text=f"Loop: {_loop_label(self.loop_mode)} | Shuffle: {'On' if self.shuffle_on else 'Off'} | Total: {_fmt_queue_duration(self.queue)}"
        )
        return embed

    # --------------------------------------------------------- teardown

    def shutdown(self, disconnect: bool = True):
        """Stop playback and drop state; optionally leave the voice channel."""
        self.cancel_idle()
        self._stopping = True
        self.queue.clear()
        self.current = None
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
    """Play YouTube audio in voice channels via yt-dlp + FFmpeg."""

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
        player = self._player(guild.id)
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

    async def _resolve_song(self, query: str, requester: discord.Member) -> Song:
        try:
            info = await asyncio.wait_for(asyncio.to_thread(_extract, query), timeout=EXTRACT_TIMEOUT)
        except asyncio.TimeoutError:
            raise MusicError("⏱️ That took too long — try again in a moment.") from None
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc).lower()
            if "no video results" in message or "no results" in message:
                raise MusicError(f"No search results for `{query}`.") from exc
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
        return Song(
            title=info.get("title") or "Unknown",
            url=info.get("webpage_url") or query,
            stream_url=stream_url,
            duration=info.get("duration"),
            thumbnail=info.get("thumbnail"),
            uploader=info.get("uploader") or info.get("channel") or "Unknown",
            requester=requester,
        )

    async def _safe(self, ctx, action):
        try:
            await action()
        except MusicError as exc:
            await u.reply(ctx, embed=discord.Embed(description=f"❌ {exc}", color=COLOR_ERROR))

    @staticmethod
    async def _defer(ctx):
        if isinstance(ctx, discord.Interaction) and not ctx.response.is_done():
            await ctx.response.defer()

    # ------------------------------------------------------------- play

    async def _play(self, ctx, query: str):
        query = (query or "").strip()
        if not query:
            raise MusicError("Give me a song name or a YouTube URL to play.")
        if not shutil.which("ffmpeg"):
            raise MusicError("**FFmpeg isn't installed** on this machine. Install it and restart the bot.")
        await self._defer(ctx)
        player = await self._connect(ctx)
        player.cancel_idle()
        song = await self._resolve_song(query, u.author_of(ctx))
        if player.current is not None or (player.voice and player.voice.is_playing()):
            player.queue.append(song)
            embed = discord.Embed(
                title="✅ Added to queue",
                description=f"[**{song.title}**]({song.url}) — position **#{len(player.queue)}**",
                color=COLOR_NOW_PLAYING,
            )
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
            embed.set_footer(text=f"{len(player.queue)} track(s) queued")
            await u.reply(ctx, embed=embed)
            return
        player._start_playback(song, announce=False)
        await u.reply(ctx, embed=player.now_playing_embed())

    @commands.command(name="play", aliases=["p"], help="Play a song from a YouTube URL or search by name.", usage="b.play <url or song name>")
    async def play(self, ctx: commands.Context, *, query: str):
        await self._safe(ctx, lambda: self._play(ctx, query))

    @app_commands.command(name="play", description="Play a YouTube URL or search a song by name.")
    @app_commands.describe(query="A YouTube URL or a song name to search")
    async def slash_play(self, interaction: discord.Interaction, query: str):
        await self._safe(interaction, lambda: self._play(interaction, query))

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
        await u.reply(ctx, embed=discord.Embed(description="⏸️ Paused — use `/resume` to continue.", color=COLOR_NOW_PLAYING))

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
        await u.reply(ctx, embed=discord.Embed(description="▶️ Resumed.", color=COLOR_NOW_PLAYING))

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
        await u.reply(ctx, embed=discord.Embed(
            description=f"⏭️ Skipped **{skipped.title}**." if skipped else "⏭️ Skipped.",
            color=COLOR_NOW_PLAYING,
        ))

    @commands.command(name="skip", aliases=["next", "s"], help="Skip the current track.", usage="b.skip")
    async def skip(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._skip(ctx))

    @app_commands.command(name="skip", description="Skip the current track.")
    async def slash_skip(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._skip(interaction))

    # -------------------------------------------------------------- stop

    async def _stop(self, ctx):
        player = self._active_player(ctx)
        channel = player.voice.channel
        player.shutdown(disconnect=False)
        await player.schedule_idle()
        await u.reply(ctx, embed=discord.Embed(
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
        await u.reply(ctx, embed=player.queue_embed())

    @commands.command(name="queue", aliases=["q"], help="Show the current queue.", usage="b.queue")
    async def queue(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._queue(ctx))

    @app_commands.command(name="queue", description="Show the current queue.")
    async def slash_queue(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._queue(interaction))

    # -------------------------------------------------------- nowplaying

    async def _nowplaying(self, ctx):
        player = self._active_player(ctx)
        if player.current is None:
            raise MusicError("Nothing is playing right now.")
        await u.reply(ctx, embed=player.now_playing_embed())

    @commands.command(name="nowplaying", aliases=["np"], help="Show the current track and progress.", usage="b.nowplaying")
    async def nowplaying(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._nowplaying(ctx))

    @app_commands.command(name="nowplaying", description="Show the current track and progress.")
    async def slash_nowplaying(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._nowplaying(interaction))

    # ------------------------------------------------------------ volume

    async def _volume(self, ctx, volume: int):
        player = self._active_player(ctx)
        volume = max(1, min(100, volume))
        player.volume = volume / 100
        if isinstance(player.voice.source, discord.PCMVolumeTransformer):
            player.voice.source.volume = player.volume
        await u.reply(ctx, embed=discord.Embed(
            description=f"🔊 Volume set to **{volume}%**.", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="volume", aliases=["vol"], help="Set playback volume from 1 to 100.", usage="b.volume <1-100>")
    async def volume(self, ctx: commands.Context, volume: int):
        await self._safe(ctx, lambda: self._volume(ctx, volume))

    @app_commands.command(name="volume", description="Set playback volume from 1 to 100.")
    async def slash_volume(self, interaction: discord.Interaction, volume: int):
        await self._safe(interaction, lambda: self._volume(interaction, volume))

    # ------------------------------------------------------------ shuffle

    async def _shuffle(self, ctx):
        player = self._active_player(ctx)
        if len(player.queue) < 2:
            raise MusicError("Need at least 2 queued tracks to shuffle.")
        random.shuffle(player.queue)
        await u.reply(ctx, embed=discord.Embed(
            description=f"🔀 Shuffled **{len(player.queue)}** queued tracks.", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="shuffle", help="Shuffle the queued tracks.", usage="b.shuffle")
    async def shuffle(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._shuffle(ctx))

    @app_commands.command(name="shuffle", description="Shuffle the queued tracks.")
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
        await u.reply(ctx, embed=discord.Embed(
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
        await u.reply(ctx, embed=discord.Embed(
            description=f"🗑️ Removed **{song.title}** (was #**{index}**).", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="remove", help="Remove a track from the queue by position.", usage="b.remove <position>")
    async def remove(self, ctx: commands.Context, index: int):
        await self._safe(ctx, lambda: self._remove(ctx, index))

    @app_commands.command(name="remove", description="Remove a track from the queue by position.")
    async def slash_remove(self, interaction: discord.Interaction, index: int):
        await self._safe(interaction, lambda: self._remove(interaction, index))

    # -------------------------------------------------------------- clear

    async def _clear(self, ctx):
        player = self._active_player(ctx)
        if not player.queue:
            raise MusicError("The queue is already empty.")
        count = len(player.queue)
        player.queue.clear()
        await u.reply(ctx, embed=discord.Embed(
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
        await u.reply(ctx, embed=discord.Embed(
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
        await u.reply(ctx, embed=discord.Embed(
            description=f"👋 Left **{channel.name}** and cleared the queue.", color=COLOR_NOW_PLAYING
        ))

    @commands.command(name="leave", aliases=["dc", "disconnect"], help="Make the bot leave the voice channel.", usage="b.leave")
    async def leave(self, ctx: commands.Context):
        await self._safe(ctx, lambda: self._leave(ctx))

    @app_commands.command(name="leave", description="Make the bot leave the voice channel.")
    async def slash_leave(self, interaction: discord.Interaction):
        await self._safe(interaction, lambda: self._leave(interaction))

    # ------------------------------------------------------------ events

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id != self.bot.user.id:
            return
        player = self.players.get(member.guild.id)
        if player is None:
            return
        if after.channel is None or (before.channel and before.channel.id != after.channel.id):
            player.shutdown(disconnect=False)
            self.players.pop(member.guild.id, None)

    async def cog_unload(self):
        for player in list(self.players.values()):
            player.shutdown(disconnect=True)
        self.players.clear()


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
