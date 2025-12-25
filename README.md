# MikuBot - Discord Music Bot

A Discord music bot that plays music from YouTube and Spotify, with support for playlists, queue management, and looping features.

## Features

- **Play from YouTube or Spotify** - Automatically detects the platform and plays accordingly
- **24/7 Hatsune Miku Playlist** - Dedicated command for continuous Miku music
- **Queue Management** - View, clear, and shuffle your queue
- **Looping** - Loop individual songs or entire playlists
- **Playback Controls** - Pause, resume, skip, and more

## Setup

### Prerequisites

- Python 3.8 or higher
- FFmpeg installed on your system
- Discord Bot Token
- (Optional) Spotify API credentials for Spotify support

### Installation

1. Clone or download this repository

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Install FFmpeg:
   - **Linux**: `sudo apt install ffmpeg` (or your package manager)
   - **macOS**: `brew install ffmpeg`
   - **Windows**: Download from [FFmpeg website](https://ffmpeg.org/download.html)

4. Create a `.env` file in the project root:
```env
DISCORD_TOKEN=your_discord_bot_token_here
SPOTIFY_CLIENT_ID=your_spotify_client_id_here
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret_here
```

### Getting Credentials

#### Discord Bot Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" section and create a bot
4. Copy the token and add it to `.env`
5. Enable "Message Content Intent" and "Server Members Intent" in the Bot section
6. Invite the bot to your server with the following permissions:
   - Connect
   - Speak
   - Use Voice Activity

#### Spotify API Credentials (Optional)
1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Copy the Client ID and Client Secret
4. Add them to `.env`

### Running the Bot

```bash
python main.py
```

## Commands

- `/join` - Make the bot join your voice channel (Admin only)
- `/play <url>` - Play a song from YouTube or Spotify
- `/playmiku` - Play a 24/7 playlist with only Hatsune Miku songs
- `/skip` - Skip the current song (must be in VC)
- `/leave` - Disconnect from voice and clear queue
- `/queue` - View current queue
- `/clearqueue` - Clear all tracks from the queue
- `/shuffle` - Shuffle the current queue (needs 2+ tracks)
- `/loop` - Loop the currently playing song
- `/loopplaylist` - Loop the current queue
- `/pause` - Pause the currently playing song
- `/resume` - Resume currently playing song
- `/help` - Show all commands

## Notes

- Spotify tracks are automatically searched and played from YouTube
- The bot supports YouTube playlists and single tracks
- Queue loop will repeat the entire queue in order
- Song loop will repeat only the current song
- Queue is stored in memory (will be cleared on bot restart)

## Troubleshooting

- **Bot doesn't join voice channel**: Make sure the bot has "Connect" and "Speak" permissions
- **No sound**: Check that FFmpeg is installed and in your PATH
- **Spotify not working**: Verify your Spotify API credentials are correct in `.env`
- **Commands not showing**: Wait a few minutes after starting the bot for commands to sync

