# Bloop Bot

A Discord bot in Python with both prefix commands (`b.`) and slash commands.

## Setup

1. Create a bot at https://discord.com/developers/applications
2. Enable **Message Content Intent** in the bot settings (required for prefix commands)
3. Invite the bot with the `applications.commands` and `bot` scopes
4. Install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
5. Set your token:
   ```bash
   cp .env.example .env
   # edit .env and paste your bot token
   ```

## Run

```bash
python bot.py
```

## Commands

| Prefix (`b.`) | Slash (`/`) | What it does                    | Required permission |
| -------------- | ----------- | ------------------------------- | ------------------- |
| `b.help [command]` | `/help` | Browse all commands by category, or get details for one | Anyone |
| `b.ping`       | `/ping`     | Bot latency in ms               | Anyone              |
| `b.echo ...`   | `/echo`     | Repeats your message            | Anyone              |
| `b.avatar [@user]` | `/avatar`  | Shows a big profile picture     | Anyone              |
| `b.userinfo [@user]` | `/userinfo` | Shows user details (ID, joined, roles, ...) | Anyone    |
| `b.kick @user [reason]` | `/kick` | Kicks a member              | Kick Members        |
| `b.ban @user [reason]` | `/ban`   | Bans a member               | Ban Members         |
| `b.mute @user 10m [reason]` | `/mute` | Timeouts a member        | Moderate Members    |
| `b.unmute @user` | `/unmute`   | Removes a timeout              | Moderate Members    |

Moderation commands can be used by anyone with **Administrator** or the specific
permission listed. They also respect role hierarchy (you can't kick/ban/mute someone
above you, the server owner, or yourself).

## Music

Plays YouTube audio (URLs, song-name searches, or whole playlists) via `yt-dlp` +
FFmpeg — no external music servers needed. Every command works as a slash command
and with the `b.` prefix.

| Command | What it does |
| ------- | ------------ |
| `/play <query>` | Play a URL, search a name, or queue a whole playlist |
| `/playnext <query>` | Queue a track (or playlist) at the front of the queue |
| `/find <query>` | Search YouTube and pick from the top results |
| `/pause` / `/resume` | Pause / resume the current track |
| `/skip` | Skip the current track |
| `/previous` | Go back to the previous track |
| `/seek <time>` | Jump to a timestamp (e.g. `90` or `1:30`) |
| `/jump <position>` | Play a queued track immediately |
| `/move <from> <to>` | Move a track within the queue |
| `/stop` | Stop playback and clear the queue |
| `/queue` | Show the queue (paginated, with per-track remove buttons) |
| `/nowplaying` | Show the current track with a live progress bar and controls |
| `/volume <1-100>` | Set playback volume |
| `/shuffle` | Toggle shuffle mode |
| `/loop [none\|one\|all]` | Loop off, the track, or the whole queue |
| `/remove <position>` | Remove a track from the queue |
| `/clear` | Clear the queue (keeps the current track) |
| `/join` / `/leave` | Make the bot join / leave your voice channel |

The now-playing message has an interactive control panel (previous, pause/resume,
skip, stop, loop, shuffle, volume, queue, clear) that updates its progress bar
automatically.

System dependencies on the host (Debian/Ubuntu):

```bash
sudo apt install ffmpeg libopus0
```

Then install the Python extras and restart the bot:

```bash
pip install -r requirements.txt
```

The bot auto-joins your voice channel on `/play`, auto-plays the queue, and leaves
after 5 minutes of inactivity — or 60 seconds after everyone else leaves the
channel. Grant it **Connect** and **Speak** permissions in your voice channels.

## Bot permissions

When inviting the bot, grant it at least:
`Send Messages`, `Embed Links`, `Kick Members`, `Ban Members`, `Moderate Members`,
`Connect`, `Speak`.
