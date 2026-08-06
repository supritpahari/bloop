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
| `b.help [command]` | `/help` | Shows all commands, or details for one | Anyone             |
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

Plays YouTube audio (URLs or song-name searches) via `yt-dlp` + FFmpeg — no external
music servers needed. Commands: `/play`, `/pause`, `/resume`, `/skip`, `/stop`,
`/queue`, `/nowplaying`, `/volume`, `/shuffle`, `/loop`, `/remove`, `/clear`,
`/join`, `/leave`.

System dependencies on the host (Debian/Ubuntu):

```bash
sudo apt install ffmpeg libopus0
```

Then install the Python extras and restart the bot:

```bash
pip install -r requirements.txt
```

The bot auto-joins your voice channel on `/play`, auto-plays the queue, and leaves
after 5 minutes of inactivity. Grant it **Connect** and **Speak** permissions in
your voice channels.

## Bot permissions

When inviting the bot, grant it at least:
`Send Messages`, `Embed Links`, `Kick Members`, `Ban Members`, `Moderate Members`,
`Connect`, `Speak`.
