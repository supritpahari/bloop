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
| `b.embed`      | `/embed`    | Builds and posts a custom embed (`b.embed` asks for `Title | Text | Footer | Color | Channel` in chat, `/embed` opens a form) | Manage Messages |
| `b.kick @user [reason]` | `/kick` | Kicks a member              | Kick Members        |
| `b.ban @user [reason]` | `/ban`   | Bans a member               | Ban Members         |
| `b.mute @user 10m [reason]` | `/mute` | Timeouts a member        | Moderate Members    |
| `b.unmute @user` | `/unmute`   | Removes a timeout              | Moderate Members    |
| `b.clear`      | `/clear`    | Bulk-deletes every recent message in this channel (messages older than 14 days are left alone — Discord limit) | Administrator |
| `b.lock`       | `/lock`     | Locks the channel so only admins can send messages | Administrator |
| `b.unlock`     | `/unlock`   | Unlocks a channel locked with `b.lock` / `/lock` | Administrator |

Moderation commands can be used by anyone with **Administrator** or the specific
permission listed. They also respect role hierarchy (you can't kick/ban/mute someone
above you, the server owner, or yourself).

## AI moderation

The server owner can configure automatic message scanning with `b.aimod` or
`/aimod`. Confirmed violations create strikes that reset after seven
violation-free days. Punishments escalate even when the AI model keeps suggesting
only a warning:

- **Strict:** 10-minute timeout → 1-hour timeout → kick → ban
- **Moderate:** warning → 10-minute timeout → 1-hour timeout → kick → ban
- **Lenient:** two warnings → 10-minute timeout → 1-hour timeout → kick → ban

Use `b.aimodreset @member` or `/aimodreset` to clear a member's strikes. For every
automatic action to work, grant the bot **Moderate Members**, **Kick Members**, and
**Ban Members**, then place its highest role above the members it should moderate.
If Discord denies an action, the bot posts the missing permission or role problem
instead of failing silently.

## Tickets

One admin command, a click-to-open panel, and approval-based closing with an AI
summary.

| Prefix (`b.`) | Slash (`/`) | What it does | Who can use it |
| -------------- | ----------- | ------------ | -------------- |
| `b.ticket` | `/ticket` | Opens a setup form: pick the panel channel and the roles to add to tickets, then **Save** — posts the panel message with the **Open Ticket** button | Administrator |
| — | 🎫 **Open Ticket** button | Opens a private `ticket-0042` channel with the configured roles added (one open ticket per user) | Anyone |
| `b.closeticket` | `/closeticket` | Request closing the ticket you're in — the other side must approve: staff approve if the creator asks, the creator approves if staff ask | Ticket creator or staff |

Setup needs the bot to have **Manage Channels** and **Manage Roles**; ticket
channels are created under an auto-created hidden 🎫 Tickets category. On close,
the ticket creator is DM'd a short AI summary of the conversation, generated
with the same AI configured via `/aichat` (no AI configured → the DM says so).
State is stored in `bloop_tickets.db`, and the panel button survives bot
restarts.

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
| `/clearqueue` | Clear the queue (keeps the current track) |
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
