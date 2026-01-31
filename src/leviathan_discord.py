import json
import os
from enum import Enum

import aiohttp
import dotenv
from loguru import logger


# ======================= Environment / Global Variables =======================
dotenv.load_dotenv(override=True)

# Clash of Clans player tag to Discord ID mapping
COC_PLAYER_TAG_TO_DISCORD_MENTION = dict(json.loads(os.getenv('COC_PLAYER_TAG_TO_DISCORD_MENTION')))

# Mention strings for Discord
MENTION_CO_LEADER = os.getenv('DISCORD_CO_LEADER_MENTION')
MENTION_LEADER = os.getenv('DISCORD_LEADER_MENTION')


# ================================ Enumerations ================================
class Webhook(Enum):
    BOT_TEST = os.getenv('DISCORD_BOT_TEST_WEBHOOK')
    CLAN_CHAT = os.getenv('DISCORD_CLAN_CHAT_WEBHOOK')
    CLAN_GAMES_REMINDERS = os.getenv('DISCORD_CLAN_GAMES_REMINDERS_WEBHOOK')
    CLAN_WAR_REMINDERS = os.getenv('DISCORD_CLAN_WAR_REMINDERS_WEBHOOK')
    RAID_WEEKEND_REMINDERS = os.getenv('DISCORD_RAID_WEEKEND_REMINDERS_WEBHOOK')
    RECRUITMENT = os.getenv('DISCORD_RECRUITMENT_WEBHOOK')
    WELCOME = os.getenv('DISCORD_WELCOME_WEBHOOK')


# =================================== Classes ==================================
class LeviathanDiscordClient:
    session: aiohttp.ClientSession
    
    def __init__(self):
        self.session = None
        
    def start(self):
        self.session = aiohttp.ClientSession()
    
    async def send_message(self, message: str, webhook: Webhook):
        if not self.session:
            raise AttributeError('Discord client was not started first! Use start() first before sending a message')
        
        async with self.session.post(url=webhook.value, json={'content': message}) as response:
            return await response.json(content_type='text/html; charset=utf-8')
    
    async def close(self):
        logger.info('Closing connection to Discord')
        await self.session.close()


DISCORD_CLIENT = LeviathanDiscordClient()
