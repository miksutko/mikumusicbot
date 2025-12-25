"""
MikuBot GIF Response Module
Handles automatic GIF responses when Miku is mentioned or certain keywords are detected.
Can be easily disabled by not importing this module in main.py
"""

import discord
import aiohttp
import random
import re
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Tenor API key (free tier available at https://developers.google.com/tenor)
# You can also use a simple list of GIF URLs if you prefer
TENOR_API_KEY = os.getenv('TENOR_API_KEY')  # Set in .env as TENOR_API_KEY (optional)

# Fallback GIF URLs if Tenor is not configured
# Use direct GIF URLs (not page URLs) for best compatibility
# You can find direct GIF URLs from:
# - Giphy: Right-click GIF > Copy image address
# - Tenor: Use the API or find direct URLs
# - Or use any direct .gif URL
FALLBACK_GIFS = {
    'miku': [
        'https://tenor.com/view/hatsune-miku-miku-spin-gif-2039974444974717565',
        # Add more GIF URLs here (direct .gif URLs work best)
        # Example: 'https://media.giphy.com/media/example.gif',
    ],
    'greeting': [
        # Add greeting GIF URLs here
        # Example: 'https://media.giphy.com/media/greeting-example.gif',
    ],
    'christmas': [
        # Add Christmas GIF URLs here
        # Example: 'https://media.giphy.com/media/christmas-example.gif',
    ]
}

# Keyword triggers and their search terms
# To add a new trigger, just add a new entry here!
TRIGGERS = {
    # Miku mentions and keywords
    'miku': {
        'keywords': ['miku', 'hatsune miku', '初音ミク'],
        'search_term': 'hatsune miku',
        'probability': 0.3  # 30% chance to respond
    },
    # Greetings
    'greeting': {
        'keywords': ['good morning', 'good evening', 'good night', 'good afternoon', 
                     'morning', 'evening', 'night', 'hello', 'hi', 'hey'],
        'search_term': 'hatsune miku greeting',
        'probability': 0.2  # 20% chance to respond
    },
    # Christmas
    'christmas': {
        'keywords': ['merry christmas', 'christmas', 'xmas'],
        'search_term': 'hatsune miku christmas',
        'probability': 0.5  # 50% chance to respond
    },
    # Add more triggers here easily! Just copy the format below:
    # 'birthday': {
    #     'keywords': ['happy birthday', 'birthday', 'bday'],
    #     'search_term': 'hatsune miku birthday',
    #     'probability': 0.4  # 40% chance to respond
    # },
    # 'newyear': {
    #     'keywords': ['happy new year', 'new year', 'newyear'],
    #     'search_term': 'hatsune miku new year',
    #     'probability': 0.5
    # },
}


async def get_tenor_gif(search_term: str, api_key: str = None) -> str:
    """Get a random GIF from Tenor API"""
    if not api_key:
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://tenor.googleapis.com/v2/search"
            params = {
                'q': search_term,
                'key': api_key,
                'client_key': 'mikubot',
                'limit': 20,
                'media_filter': 'gif'
            }
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get('results', [])
                    if results:
                        gif = random.choice(results)
                        return gif.get('media_formats', {}).get('gif', {}).get('url')
    except Exception as e:
        print(f"Error fetching Tenor GIF: {e}")
    
    return None


# Removed convert_tenor_page_to_gif_url - just use URLs directly


async def get_fallback_gif(trigger_type: str) -> str:
    """Get a fallback GIF from the fallback list"""
    gifs = FALLBACK_GIFS.get(trigger_type, FALLBACK_GIFS.get('miku', []))
    if not gifs:
        return None
    
    # Return random GIF from the list
    # Note: Direct .gif URLs work best, but Discord can also handle some page URLs
    return random.choice(gifs)


async def get_gif_for_trigger(trigger_type: str, search_term: str, api_key: str = None) -> str:
    """Get a GIF for a specific trigger, trying Tenor API first, then fallback"""
    # Only try Tenor API if key is provided
    if api_key:
        gif_url = await get_tenor_gif(search_term, api_key)
        if gif_url:
            return gif_url
    
    # Always use fallback if no API key or API failed
    return await get_fallback_gif(trigger_type)


def check_message_triggers(message_content: str, bot_user: discord.User) -> dict:
    """
    Check if message contains any triggers
    Returns trigger info if found, None otherwise
    """
    content_lower = message_content.lower()
    
    # Check for bot mention first (highest priority)
    if f'<@{bot_user.id}>' in message_content or f'<@!{bot_user.id}>' in message_content:
        return {
            'type': 'miku',
            'trigger': TRIGGERS['miku'],
            'probability': 1.0  # Always respond to direct mentions
        }
    
    # Check other triggers
    for trigger_type, trigger_data in TRIGGERS.items():
        for keyword in trigger_data['keywords']:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, content_lower, re.IGNORECASE):
                return {
                    'type': trigger_type,
                    'trigger': trigger_data,
                    'probability': trigger_data['probability']
                }
    
    return None


async def handle_message_response(message: discord.Message, bot_user: discord.User, tenor_key: str = None):
    """
    Handle message and send GIF response if triggered
    Returns True if a GIF was sent, False otherwise
    """
    # Don't respond to bot messages
    if message.author.bot:
        return False
    
    # Check for triggers
    trigger_info = check_message_triggers(message.content, bot_user)
    if not trigger_info:
        return False
    
    # Check probability
    if random.random() > trigger_info['probability']:
        return False
    
    # Get GIF
    gif_url = await get_gif_for_trigger(
        trigger_info['type'],
        trigger_info['trigger']['search_term'],
        tenor_key
    )
    
    if not gif_url:
        return False
    
    # Check if it's a direct mention/ping
    is_mention = f'<@{bot_user.id}>' in message.content or f'<@!{bot_user.id}>' in message.content
    
    # Send GIF - reply if pinged, regular message otherwise
    try:
        if is_mention:
            await message.reply(gif_url)
        else:
            await message.channel.send(gif_url)
        return True
    except Exception as e:
        print(f"Error sending GIF response: {e}")
        return False

