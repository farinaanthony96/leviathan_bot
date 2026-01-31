import asyncio
import os
from datetime import datetime, timedelta

import asyncpraw
import dotenv
import pytz
from asyncpraw.exceptions import AsyncPRAWException
from loguru import logger

from leviathan_discord import Webhook, DISCORD_CLIENT
from leviathan_utils import COC_MAX_TOWNHALL_LEVEL


# ======================= Environment / Global Variables =======================
dotenv.load_dotenv(override=True)

# Clash of Clans recruitment subreddit naming and labeling
COC_RECRUIT_SUBREDDIT = 'ClashOfClansRecruit'
SEARCHING_STRING = '[searching]'

# Initialize list of many combinations of townhall strings
TOWNHALL_RECRUITMENT_LEVELS = [COC_MAX_TOWNHALL_LEVEL]
TOWNHALL_SUBSTRINGS = [
    f'th{th_level},th {th_level},t h{th_level},t h {th_level},townhall{th_level},townhall {th_level},town hall {th_level},town hall{th_level}'.split(',') 
    for th_level in TOWNHALL_RECRUITMENT_LEVELS
]
ALL_DESIRED_TOWNHALL_SUBSTRINGS = []
[ALL_DESIRED_TOWNHALL_SUBSTRINGS.extend(th_level_ss_list) for th_level_ss_list in TOWNHALL_SUBSTRINGS]


# ================================== Functions =================================
async def stream_recruitment_subreddit():
    # Stream forever.
    while True:
        try:
            logger.info('Streaming recruitment posts from Reddit')
            
            # Create the Reddit client and the context manager.
            reddit_client = asyncpraw.Reddit(
                client_id=os.getenv('REDDIT_CLIENT_ID'),
                client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
                user_agent=os.getenv('REDDIT_USER_AGENT'),
                username=os.getenv('REDDIT_USERNAME'),
                password=os.getenv('REDDIT_PASSWORD')
            )
            
            async with reddit_client as reddit:
                # Get an instance of the recruitment subreddit.
                coc_recruit_sub = await reddit.subreddit(COC_RECRUIT_SUBREDDIT)
                
                # Indefinitely stream the submissions on the recruitment subreddit until there is a submission that is a desired townhall level searching.
                async for submission in coc_recruit_sub.stream.submissions(skip_existing=True):
                    # Check if this submission was made in the last 5 minutes.
                    submission_creation = datetime.fromtimestamp(submission.created_utc, pytz.UTC)
                    five_mins_ago = datetime.now(pytz.UTC) + timedelta(minutes=-5)
                    if submission_creation < five_mins_ago:
                        # Compensate for weird spam bug in asyncpraw.
                        continue
                    
                    normalized_title = submission.title.lower()
                    
                    # Check if this is a desired townhall level searching for a new clan.
                    if SEARCHING_STRING in normalized_title and any(desired_townhall_substring in normalized_title for desired_townhall_substring in ALL_DESIRED_TOWNHALL_SUBSTRINGS):
                        # Send the recruitment submission to Discord.
                        logger.info(f'Recruitment post found: {submission.url}')
                        await DISCORD_CLIENT.send_message(submission.url, Webhook.RECRUITMENT)
        except AsyncPRAWException as praw_error:
            logger.error('Reddit library has thrown an exception while streaming Reddit recruitment posts:')
            logger.error(praw_error)
            
            logger.info('Waiting 15 seconds before starting the Reddit recruitment service again')
            await asyncio.sleep(15)
            logger.info('Restarting the Reddit recruitment task...')
        except asyncio.CancelledError as e:
            logger.info('Reddit recruitment stream is shutting down')
            raise
        except Exception as e:
            logger.error('An unknown exception occurred while streaming Reddit recruitment posts:')
            logger.error(e)
            
            logger.info('Waiting 15 seconds before starting the Reddit recruitment service again')
            await asyncio.sleep(15)
            logger.info('Restarting the Reddit recruitment task...')
