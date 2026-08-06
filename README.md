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

| Prefix (`b.`) | Slash (`/`) | What it does        |
| ------------- | ----------- | ------------------- |
| `b.ping`      | `/ping`     | Bot latency in ms   |
| `b.echo ...`  | `/echo`     | Repeats your message |
