import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
from dotenv import load_dotenv
import random
import re
import json

# Optional: Miku GIF responses module
# To disable this feature, comment out the import and the message handler below
try:
    import miku_responses
    MIKU_RESPONSES_ENABLED = True
except ImportError:
    MIKU_RESPONSES_ENABLED = False
    print("Note: miku_responses module not found. GIF responses disabled.")

load_dotenv()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Spotify setup
spotify_client_id = os.getenv('SPOTIFY_CLIENT_ID')
spotify_client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
spotify = None
if spotify_client_id and spotify_client_secret:
    client_credentials_manager = SpotifyClientCredentials(
        client_id=spotify_client_id,
        client_secret=spotify_client_secret
    )
    spotify = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

# yt-dlp options
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False,
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# Fast playlist extraction (flat mode - no full video info)
playlist_ytdl_options = ytdl_format_options.copy()
playlist_ytdl_options['extract_flat'] = True
playlist_ytdl = yt_dlp.YoutubeDL(playlist_ytdl_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # Playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class MusicPlayer:
    def __init__(self, guild_id=None):
        self.guild_id = guild_id
        self.queue = []
        self.original_queue = []  # Store original queue for looping
        self.current = None
        self.voice_client = None
        self.loop_song = False
        self.loop_queue = False
        self.is_paused = False
        self.paused_position = None
        
        # Load saved queue if guild_id is provided
        if guild_id:
            self.load_queue()
    
    def save_queue(self):
        """Save queue state to JSON file"""
        if not self.guild_id:
            return
        
        try:
            queue_data = {
                'queue': [self._serialize_track(track) for track in self.queue],
                'original_queue': [self._serialize_track(track) for track in self.original_queue],
                'current': self._serialize_track(self.current) if self.current else None,
                'loop_song': self.loop_song,
                'loop_queue': self.loop_queue
            }
            
            # Load existing data
            try:
                with open('queue_data.json', 'r') as f:
                    all_data = json.load(f)
            except FileNotFoundError:
                all_data = {}
            
            # Update this guild's data
            all_data[str(self.guild_id)] = queue_data
            
            # Save back to file
            with open('queue_data.json', 'w') as f:
                json.dump(all_data, f, indent=2)
        except Exception as e:
            print(f"Error saving queue for guild {self.guild_id}: {e}")
    
    def load_queue(self):
        """Load queue state from JSON file"""
        if not self.guild_id:
            return
        
        try:
            with open('queue_data.json', 'r') as f:
                all_data = json.load(f)
            
            guild_data = all_data.get(str(self.guild_id))
            if not guild_data:
                return
            
            # Restore queue
            self.queue = [self._deserialize_track(track) for track in guild_data.get('queue', [])]
            self.original_queue = [self._deserialize_track(track) for track in guild_data.get('original_queue', [])]
            
            current = guild_data.get('current')
            if current:
                self.current = self._deserialize_track(current)
            
            self.loop_song = guild_data.get('loop_song', False)
            self.loop_queue = guild_data.get('loop_queue', False)
        except FileNotFoundError:
            # File doesn't exist yet, that's okay
            pass
        except Exception as e:
            print(f"Error loading queue for guild {self.guild_id}: {e}")
    
    def _serialize_track(self, track):
        """Convert track dict to JSON-serializable format"""
        if not track:
            return None
        
        serialized = {
            'url': track.get('url'),
            'title': track.get('title', 'Unknown'),
            'duration': track.get('duration', 0),
            'thumbnail': track.get('thumbnail'),
            'requester_id': track.get('requester').id if track.get('requester') else None
        }
        return serialized
    
    def _deserialize_track(self, track_data):
        """Convert serialized track back to track dict"""
        if not track_data:
            return None
        
        track = {
            'url': track_data.get('url'),
            'title': track_data.get('title', 'Unknown'),
            'duration': track_data.get('duration', 0),
            'thumbnail': track_data.get('thumbnail'),
            'requester': None  # Will be set when needed, user objects can't be stored
        }
        return track

    async def add_to_queue(self, url, ctx):
        """Add a song or playlist to the queue"""
        try:
            added_tracks = []
            if 'youtube.com/playlist' in url or 'youtu.be/playlist' in url:
                # Handle playlist - use fast flat extraction
                data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: playlist_ytdl.extract_info(url, download=False)
                )
                if 'entries' in data:
                    for entry in data['entries']:
                        if entry:
                            # Build URL from video ID
                            video_id = entry.get('id') or entry.get('url', '').split('watch?v=')[-1].split('&')[0]
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                            
                            track = {
                                'url': video_url,
                                'title': entry.get('title', 'Unknown'),
                                'duration': entry.get('duration', 0),
                                'thumbnail': entry.get('thumbnail'),
                                'requester': ctx.user
                            }
                            self.queue.append(track)
                            added_tracks.append(track)
                    # Update original queue if loop is enabled
                    if self.loop_queue:
                        self.original_queue.extend(added_tracks)
                    self.save_queue()  # Save after adding
                    return len(added_tracks)
            else:
                # Handle single song
                data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ytdl.extract_info(url, download=False)
                )
                if 'entries' in data:
                    data = data['entries'][0]
                
                track = {
                    'url': url,
                    'title': data.get('title', 'Unknown'),
                    'duration': data.get('duration', 0),
                    'thumbnail': data.get('thumbnail'),
                    'requester': ctx.user
                }
                self.queue.append(track)
                # Update original queue if loop is enabled
                if self.loop_queue:
                    self.original_queue.append(track)
                self.save_queue()  # Save after adding
                return 1
        except Exception as e:
            raise Exception(f"Error adding to queue: {str(e)}")

    async def play_next(self, ctx):
        """Play the next song in the queue"""
        if self.voice_client is None:
            return

        if self.loop_song and self.current:
            # Loop current song
            await self.play_song(self.current['url'], ctx)
            return

        if len(self.queue) == 0:
            if self.loop_queue and len(self.original_queue) > 0:
                # Restore original queue for looping
                # If current song is in original_queue, start from after it
                if self.current:
                    current_url = self.current.get('url')
                    found = False
                    for track in self.original_queue:
                        if not found and track.get('url') == current_url:
                            found = True
                            continue
                        if found or not current_url:
                            self.queue.append(track.copy())
                    # If current wasn't found or we need to loop from start
                    if not found or len(self.queue) == 0:
                        self.queue = [track.copy() for track in self.original_queue]
                else:
                    self.queue = [track.copy() for track in self.original_queue]
            else:
                self.current = None
                return

        # Get next song
        if len(self.queue) > 0:
            self.current = self.queue.pop(0)
            self.save_queue()  # Save after changing current
            await self.play_song(self.current['url'], ctx)

    async def play_song(self, url, ctx):
        """Play a specific song"""
        try:
            player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
            self.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                self.play_next(ctx), bot.loop
            ))
            self.is_paused = False
            self.paused_position = None
        except Exception as e:
            await ctx.response.send_message(f"Error playing song: {str(e)}", ephemeral=True)
            await self.play_next(ctx)

    def skip(self):
        """Skip current song"""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()

    def pause(self):
        """Pause current song"""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.is_paused = True

    def resume(self):
        """Resume current song"""
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            self.is_paused = False

    def shuffle_queue(self):
        """Shuffle the queue"""
        if len(self.queue) <= 1:
            raise ValueError("Need at least 2 tracks in queue to shuffle")
        random.shuffle(self.queue)
        # If loop is enabled, update original_queue to reflect shuffled order
        if self.loop_queue:
            # Rebuild original_queue with current song (if any) + shuffled queue
            if self.current:
                self.original_queue = [self.current.copy()] + [track.copy() for track in self.queue]
            else:
                self.original_queue = [track.copy() for track in self.queue]
        self.save_queue()  # Save after shuffling

    def clear_queue(self):
        """Clear the queue"""
        self.queue = []
        self.original_queue = []
        self.save_queue()  # Save after clearing

    def get_queue_page(self, page=0, per_page=15):
        """Get a specific page of the queue"""
        if not self.queue:
            return [], 0, 1  # Return empty list, page 0, 1 total page (for empty state)
        
        total_pages = max(1, (len(self.queue) + per_page - 1) // per_page)
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, len(self.queue))
        
        page_tracks = self.queue[start_idx:end_idx]
        
        return page_tracks, page, total_pages
    
    def get_queue_display_text(self, page=0, per_page=15):
        """Get formatted queue display text for a specific page"""
        lines = []
        
        # Header
        if self.current:
            lines.append(f"**Now Playing:** {self.current['title']}")
        
        # Show loop status
        loop_status = []
        if self.loop_song:
            loop_status.append("🔁 Song Loop")
        if self.loop_queue:
            loop_status.append("🔁 Queue Loop")
        if loop_status:
            lines.append(f"**Status:** {', '.join(loop_status)}")
        
        if self.queue:
            page_tracks, current_page, total_pages = self.get_queue_page(page, per_page)
            lines.append(f"\n**Queue:** ({len(self.queue)} tracks)")
            lines.append(f"**Page {current_page + 1}/{total_pages}**\n")
            
            start_num = page * per_page + 1
            for i, track in enumerate(page_tracks, start_num):
                lines.append(f"{i}. {track['title']}")
        else:
            lines.append("\n**Queue is empty**")
        
        return "\n".join(lines)


# Global music players per guild
music_players = {}


class QueueView(discord.ui.View):
    """View for paginated queue display"""
    def __init__(self, player, initial_page=0, per_page=15, timeout=300):
        super().__init__(timeout=timeout)
        self.player = player
        self.current_page = initial_page
        self.per_page = per_page
        self.update_buttons()
    
    def update_buttons(self):
        """Update button states based on current page"""
        _, _, total_pages = self.player.get_queue_page(self.current_page, self.per_page)
        
        # Clear existing buttons
        self.clear_items()
        
        # Don't show buttons if queue is empty or only one page
        if not self.player.queue or total_pages <= 1:
            return
        
        # Previous button
        prev_button = discord.ui.Button(
            label="◀ Previous",
            style=discord.ButtonStyle.primary,
            disabled=self.current_page == 0
        )
        prev_button.callback = self.previous_page
        self.add_item(prev_button)
        
        # Page info button (disabled, just for display)
        page_button = discord.ui.Button(
            label=f"Page {self.current_page + 1}/{total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True
        )
        self.add_item(page_button)
        
        # Next button
        next_button = discord.ui.Button(
            label="Next ▶",
            style=discord.ButtonStyle.primary,
            disabled=self.current_page >= total_pages - 1
        )
        next_button.callback = self.next_page
        self.add_item(next_button)
    
    async def previous_page(self, interaction: discord.Interaction):
        """Go to previous page"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            text = self.player.get_queue_display_text(self.current_page, self.per_page)
            await interaction.response.edit_message(content=text, view=self)
        else:
            await interaction.response.defer()
    
    async def next_page(self, interaction: discord.Interaction):
        """Go to next page"""
        _, _, total_pages = self.player.get_queue_page(self.current_page, self.per_page)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            text = self.player.get_queue_display_text(self.current_page, self.per_page)
            await interaction.response.edit_message(content=text, view=self)
        else:
            await interaction.response.defer()
    
    async def on_timeout(self):
        """Disable buttons when view times out"""
        for item in self.children:
            item.disabled = True


def get_music_player(guild_id):
    """Get or create music player for a guild"""
    if guild_id not in music_players:
        music_players[guild_id] = MusicPlayer(guild_id=guild_id)
    return music_players[guild_id]


async def get_spotify_track_info(url):
    """Get track info from Spotify and search on YouTube"""
    if not spotify:
        raise Exception("Spotify credentials not configured")
    
    # Check if it's a playlist
    if 'playlist' in url:
        playlist_id = url.split('playlist/')[-1].split('?')[0]
        if not playlist_id:
            raise Exception("Invalid Spotify playlist URL")
        
        # Get playlist tracks
        results = spotify.playlist_tracks(playlist_id)
        tracks = []
        
        # Handle pagination
        while results:
            for item in results['items']:
                if item['track'] and item['track']['type'] == 'track':
                    track = item['track']
                    artist = track['artists'][0]['name']
                    title = track['name']
                    search_query = f"{artist} {title}"
                    yt_search_url = f"ytsearch:{search_query}"
                    tracks.append((yt_search_url, f"{artist} - {title}"))
            
            # Get next page if available
            if results['next']:
                results = spotify.next(results)
            else:
                break
        
        if not tracks:
            raise Exception("Playlist is empty or contains no valid tracks")
        
        return tracks  # Return list of (yt_url, track_name) tuples
    
    # Handle single track
    track_id = None
    if 'track' in url:
        track_id = url.split('track/')[-1].split('?')[0]
    
    if not track_id:
        raise Exception("Invalid Spotify URL. Please provide a track or playlist URL.")
    
    track = spotify.track(track_id)
    artist = track['artists'][0]['name']
    title = track['name']
    
    # Search on YouTube
    search_query = f"{artist} {title}"
    yt_search_url = f"ytsearch:{search_query}"
    
    return yt_search_url, f"{artist} - {title}"


@bot.event
async def on_ready():
    print(f'{bot.user} has logged in!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.event
async def on_message(message):
    """Handle messages for GIF responses"""
    # Process commands first
    await bot.process_commands(message)
    
    # Handle GIF responses if enabled
    if MIKU_RESPONSES_ENABLED:
        tenor_key = os.getenv('TENOR_API_KEY')
        await miku_responses.handle_message_response(message, bot.user, tenor_key)


@bot.tree.command(name="join", description="Join your voice channel")
@app_commands.describe(channel="The voice channel to join (optional)")
async def join(interaction: discord.Interaction, channel: discord.VoiceChannel = None):
    """Make the bot join your voice channel (admin only)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    player = get_music_player(interaction.guild_id)
    player.clear_queue()
    
    if channel is None:
        if interaction.user.voice is None:
            await interaction.response.send_message("You need to be in a voice channel or specify one.", ephemeral=True)
            return
        channel = interaction.user.voice.channel
    
    if player.voice_client:
        await player.voice_client.move_to(channel)
    else:
        player.voice_client = await channel.connect()
    
    await interaction.response.send_message(f"Joined {channel.name}")


@bot.tree.command(name="play", description="Play a song from YouTube or Spotify")
@app_commands.describe(url="YouTube or Spotify URL")
async def play(interaction: discord.Interaction, url: str):
    """Play a song from YouTube or Spotify"""
    player = get_music_player(interaction.guild_id)
    
    # Check if user is in voice channel
    if interaction.user.voice is None:
        await interaction.response.send_message("You need to be in a voice channel!", ephemeral=True)
        return
    
    # Connect to voice channel if not connected
    if player.voice_client is None:
        player.voice_client = await interaction.user.voice.channel.connect()
    elif player.voice_client.channel != interaction.user.voice.channel:
        await interaction.response.send_message("I'm already in a different voice channel!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    try:
        # Check if it's Spotify or YouTube
        if 'spotify.com' in url or 'open.spotify.com' in url:
            # Handle Spotify
            spotify_result = await get_spotify_track_info(url)
            
            # Check if it's a playlist (returns list) or single track (returns tuple)
            if isinstance(spotify_result, list):
                # Playlist - add first batch and start playing, then continue in background
                total_tracks = len(spotify_result)
                await interaction.followup.send(f"Processing **{total_tracks} tracks** from Spotify playlist...")
                
                # Process in batches of 5 for better performance
                batch_size = 5
                total_added = 0
                started_playing = False
                
                async def add_track_to_queue(yt_url, track_name):
                    """Helper to add track and handle errors"""
                    nonlocal total_added
                    try:
                        await player.add_to_queue(yt_url, interaction)
                        total_added += 1
                        return True
                    except Exception as e:
                        print(f"Error adding track {track_name}: {e}")
                        return False
                
                # Add first batch and start playing immediately
                first_batch = spotify_result[:batch_size]
                first_batch_tasks = [
                    asyncio.create_task(add_track_to_queue(yt_url, track_name))
                    for yt_url, track_name in first_batch
                ]
                
                # Wait for first batch to complete
                await asyncio.gather(*first_batch_tasks, return_exceptions=True)
                
                # Start playing if nothing is playing
                if not player.voice_client.is_playing() and not player.voice_client.is_paused():
                    await player.play_next(interaction)
                    started_playing = True
                
                # Continue adding rest in background
                async def add_remaining_tracks():
                    nonlocal total_added
                    for i in range(batch_size, total_tracks, batch_size):
                        batch = spotify_result[i:i + batch_size]
                        batch_tasks = [
                            asyncio.create_task(add_track_to_queue(yt_url, track_name))
                            for yt_url, track_name in batch
                        ]
                        await asyncio.gather(*batch_tasks, return_exceptions=True)
                    
                    # Send final update
                    await interaction.followup.send(
                        f"✅ Finished! Added **{total_added}/{total_tracks} tracks** from Spotify playlist to queue!",
                        ephemeral=False
                    )
                
                # Start background task for remaining tracks
                asyncio.create_task(add_remaining_tracks())
                
                # Send immediate feedback
                if started_playing:
                    await interaction.followup.send(
                        f"🎵 Started playing! Adding remaining **{total_tracks - batch_size} tracks** in background...",
                        ephemeral=False
                    )
            else:
                # Single track
                yt_url, track_name = spotify_result
                count = await player.add_to_queue(yt_url, interaction)
                await interaction.followup.send(f"Added **{track_name}** to queue!")
        elif 'youtube.com' in url or 'youtu.be' in url:
            # Handle YouTube
            count = await player.add_to_queue(url, interaction)
            if count > 1:
                await interaction.followup.send(f"Added {count} songs to queue!")
            else:
                track_title = player.queue[-1]['title'] if player.queue else "Unknown"
                await interaction.followup.send(f"Added **{track_title}** to queue!")
        else:
            await interaction.followup.send("Please provide a valid YouTube or Spotify URL.", ephemeral=True)
            return
        
        # Start playing if nothing is playing
        if not player.voice_client.is_playing() and not player.voice_client.is_paused():
            await player.play_next(interaction)
    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)


@bot.tree.command(name="playmiku", description="Play a 24/7 playlist with only Hatsune Miku songs")
async def playmiku(interaction: discord.Interaction):
    """Play the Hatsune Miku playlist"""
    player = get_music_player(interaction.guild_id)
    
    if interaction.user.voice is None:
        await interaction.response.send_message("You need to be in a voice channel!", ephemeral=True)
        return
    
    if player.voice_client is None:
        player.voice_client = await interaction.user.voice.channel.connect()
    elif player.voice_client.channel != interaction.user.voice.channel:
        await interaction.response.send_message("I'm already in a different voice channel!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    playlist_url = "https://youtube.com/playlist?list=PLn79jv6mDuar0LS9n6o6JH6ZA5unZZ3x7&si=pu4wmmxL-NkeRVMx"
    
    try:
        count = await player.add_to_queue(playlist_url, interaction)
        # Enable queue loop and save the playlist as original queue
        player.loop_queue = True
        player.original_queue = [track.copy() for track in player.queue]
        player.save_queue()  # Save loop state and original queue
        await interaction.followup.send(f"Added Hatsune Miku playlist ({count} songs) to queue! Queue looping enabled.")
        
        if not player.voice_client.is_playing() and not player.voice_client.is_paused():
            await player.play_next(interaction)
    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)


@bot.tree.command(name="skip", description="Skip the current song")
async def skip(interaction: discord.Interaction):
    """Skip the current song"""
    player = get_music_player(interaction.guild_id)
    
    if player.voice_client is None or not player.voice_client.is_connected():
        await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)
        return
    
    if interaction.user.voice is None or interaction.user.voice.channel != player.voice_client.channel:
        await interaction.response.send_message("You need to be in the same voice channel as the bot!", ephemeral=True)
        return
    
    if not player.voice_client.is_playing() and not player.voice_client.is_paused():
        await interaction.response.send_message("Nothing is playing!", ephemeral=True)
        return
    
    player.skip()
    await interaction.response.send_message("Skipped!")


@bot.tree.command(name="stop", description="Stop playing and leave voice channel")
async def stop(interaction: discord.Interaction):
    """Stop playing and disconnect from voice channel"""
    player = get_music_player(interaction.guild_id)
    
    if player.voice_client is None or not player.voice_client.is_connected():
        await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)
        return
    
    # Stop playback
    if player.voice_client.is_playing() or player.voice_client.is_paused():
        player.voice_client.stop()
    
    # Clear queue and disconnect
    player.clear_queue()
    player.current = None
    player.loop_song = False
    player.loop_queue = False
    player.original_queue = []
    player.save_queue()
    await player.voice_client.disconnect()
    player.voice_client = None
    
    await interaction.response.send_message("Stopped playing and left the voice channel!")


@bot.tree.command(name="leave", description="Disconnect from voice")
async def leave(interaction: discord.Interaction):
    """Disconnect from voice channel"""
    player = get_music_player(interaction.guild_id)
    
    if player.voice_client is None or not player.voice_client.is_connected():
        await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)
        return
    
    player.clear_queue()  # This already saves
    player.current = None
    player.loop_song = False
    player.loop_queue = False
    player.original_queue = []
    player.save_queue()  # Save after clearing everything
    await player.voice_client.disconnect()
    player.voice_client = None
    
    await interaction.response.send_message("Left the voice channel!")


@bot.tree.command(name="queue", description="View current queue")
async def queue(interaction: discord.Interaction):
    """View the current queue with pagination"""
    player = get_music_player(interaction.guild_id)
    
    # Get queue display text for first page
    queue_text = player.get_queue_display_text(page=0, per_page=15)
    
    # Create view with pagination buttons
    view = QueueView(player, initial_page=0, per_page=15)
    
    await interaction.response.send_message(queue_text, view=view)


@bot.tree.command(name="clearqueue", description="Clear all tracks from the queue")
async def clearqueue(interaction: discord.Interaction):
    """Clear the queue"""
    player = get_music_player(interaction.guild_id)
    
    player.clear_queue()
    await interaction.response.send_message("Queue cleared!")


@bot.tree.command(name="shuffle", description="Shuffle the current queue")
async def shuffle(interaction: discord.Interaction):
    """Shuffle the queue"""
    player = get_music_player(interaction.guild_id)
    
    try:
        player.shuffle_queue()
        await interaction.response.send_message("Queue shuffled!")
    except ValueError as e:
        await interaction.response.send_message(str(e), ephemeral=True)


@bot.tree.command(name="loop", description="Loop the currently playing song")
async def loop(interaction: discord.Interaction):
    """Toggle loop for current song"""
    player = get_music_player(interaction.guild_id)
    
    player.loop_song = not player.loop_song
    player.loop_queue = False  # Disable queue loop when song loop is enabled
    player.save_queue()  # Save loop state
    
    status = "enabled" if player.loop_song else "disabled"
    await interaction.response.send_message(f"Song loop {status}!")


@bot.tree.command(name="loopplaylist", description="Loop current queue")
async def loopplaylist(interaction: discord.Interaction):
    """Toggle loop for current queue"""
    player = get_music_player(interaction.guild_id)
    
    player.loop_queue = not player.loop_queue
    player.loop_song = False  # Disable song loop when queue loop is enabled
    
    # When enabling loop, save current queue + current song as original
    if player.loop_queue:
        player.original_queue = []
        if player.current:
            player.original_queue.append(player.current.copy())
        player.original_queue.extend([track.copy() for track in player.queue])
    else:
        player.original_queue = []
    
    player.save_queue()  # Save loop state and original queue
    status = "enabled" if player.loop_queue else "disabled"
    await interaction.response.send_message(f"Queue loop {status}!")


@bot.tree.command(name="pause", description="Pause the currently playing song")
async def pause(interaction: discord.Interaction):
    """Pause the current song"""
    player = get_music_player(interaction.guild_id)
    
    if player.voice_client is None or not player.voice_client.is_connected():
        await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)
        return
    
    if not player.voice_client.is_playing():
        await interaction.response.send_message("Nothing is playing!", ephemeral=True)
        return
    
    player.pause()
    await interaction.response.send_message("Paused!")


@bot.tree.command(name="resume", description="Resume currently playing song")
async def resume(interaction: discord.Interaction):
    """Resume the current song"""
    player = get_music_player(interaction.guild_id)
    
    if player.voice_client is None or not player.voice_client.is_connected():
        await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)
        return
    
    if not player.voice_client.is_paused():
        await interaction.response.send_message("Nothing is paused!", ephemeral=True)
        return
    
    player.resume()
    await interaction.response.send_message("Resumed!")


@bot.tree.command(name="testtenor", description="Test Tenor API connection (Admin only)")
async def test_tenor(interaction: discord.Interaction):
    """Test if Tenor API is working (Admin only)"""
    # Check for admin permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "You need administrator permissions to use this command.",
            ephemeral=True
        )
        return
    
    tenor_key = os.getenv('TENOR_API_KEY')
    
    if not tenor_key or tenor_key == "your_tenor_api_key_here":
        await interaction.response.send_message(
            "❌ Tenor API key not configured!\n"
            "Please add `TENOR_API_KEY` to your `.env` file.\n"
            "Get a free key at: https://developers.google.com/tenor",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    # Test with a simple search
    try:
        import miku_responses
        gif_url = await miku_responses.get_tenor_gif("hatsune miku", tenor_key)
        
        if gif_url:
            await interaction.followup.send(
                f"✅ Tenor API is working!\n"
                f"Found GIF: {gif_url}\n\n"
                f"Here's a test GIF:",
                ephemeral=True
            )
            await interaction.followup.send(gif_url, ephemeral=True)
        else:
            await interaction.followup.send(
                "⚠️ Tenor API key is set but no GIFs were returned.\n"
                "This might be a temporary issue or the search term returned no results.",
                ephemeral=True
            )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error testing Tenor API:\n```{str(e)}```\n\n"
            "Check your API key and try again.",
            ephemeral=True
        )


@bot.tree.command(name="help", description="Show all the commands")
async def help_command(interaction: discord.Interaction):
    """Show help message with all commands"""
    # Replace with your actual GitHub repository URL
    github_url = "https://github.com/miksutko/mikumusicbot"  # Update this!
    
    help_text = f"""
**MikuBot Commands:**

`/join` - Make the bot join your voice channel (Admin only)
`/play <url>` - Play a song from YouTube or Spotify
`/playmiku` - Play a 24/7 playlist with only Hatsune Miku songs
`/skip` - Skip the current song (must be in VC)
`/stop` - Stop playing and leave voice channel
`/leave` - Disconnect from voice and clear queue
`/queue` - View current queue
`/clearqueue` - Clear all tracks from the queue
`/shuffle` - Shuffle the current queue (needs 2+ tracks)
`/loop` - Loop the currently playing song
`/loopplaylist` - Loop the current queue
`/pause` - Pause the currently playing song
`/resume` - Resume currently playing song
`/help` - Show this help message

**Notes:**
- Spotify tracks are automatically searched and played from YouTube
- The bot supports YouTube playlists and single tracks
- Queue loop will repeat the entire queue in order
- Song loop will repeat only the current song

🔗 [GitHub Repository]({github_url})
"""
    await interaction.response.send_message(help_text)

if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("Error: DISCORD_TOKEN not found in environment variables!")
        print("Please set DISCORD_TOKEN in your .env file.")
        exit(1)
    
    # Strip whitespace and remove quotes if present
    token = token.strip().strip('"').strip("'")
    
    # Check if token is still the placeholder
    if token == "your_discord_bot_token_here":
        print("Error: DISCORD_TOKEN is still set to placeholder value!")
        print("Please replace 'your_discord_bot_token_here' with your actual Discord bot token in the .env file.")
        print("\nTo get your token:")
        print("1. Go to https://discord.com/developers/applications")
        print("2. Select your application (or create a new one)")
        print("3. Go to the 'Bot' section")
        print("4. Copy the token and paste it in your .env file")
        print("\nNote: You can use quotes around the token if needed: DISCORD_TOKEN=\"your_token_here\"")
        exit(1)
    
    try:
        bot.run(token)
    except discord.errors.LoginFailure as e:
        print(f"Error: Failed to login to Discord!")
        print(f"Reason: {str(e)}")
        print("\nPossible causes:")
        print("- Invalid or expired Discord bot token")
        print("- Token was copied incorrectly (may have extra spaces)")
        print("- Bot token was reset in Discord Developer Portal")
        print("\nPlease check your DISCORD_TOKEN in the .env file and try again.")
        exit(1)
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        exit(1)

