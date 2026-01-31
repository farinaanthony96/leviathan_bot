import asyncio
from datetime import datetime, timedelta

import coc
import pytz
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from coc_client import COC_EVENTS_CLIENT
from leviathan_database import DATABASE_CLIENT
from leviathan_discord import Webhook, COC_PLAYER_TAG_TO_DISCORD_MENTION, DISCORD_CLIENT
from leviathan_scheduler import SCHEDULER
from leviathan_utils import CLAN_TAG, CLAN_TIMEZONE, prettify_seconds


# ======================= Environment / Global Variables =======================

# Alert cron triggers
ALERT_CRON_CLAN_GAMES_FIRST_DAY = CronTrigger(day=22, hour=9, minute=0, second=0, timezone=CLAN_TIMEZONE)
ALERT_CRON_CLAN_GAMES_LAST_DAY = CronTrigger(day=27, hour=9, minute=0, second=0, timezone=CLAN_TIMEZONE)

# Reminders
REMINDER_DELTAS_CLAN_GAMES = [timedelta(hours=-12), timedelta(hours=-8), timedelta(hours=-4), timedelta(hours=-1)]

# Scheduler IDs
SCHEDULER_ID_CLAN_GAMES_FIRST_DAY = 'clan_games_first_day_alert'
SCHEDULER_ID_CLAN_GAMES_LAST_DAY = 'clan_games_last_day_alert'


# ================================== Functions =================================
async def get_latest_clan_games_points() -> dict[str, int]:
    # Get the current members of the clan and make a list of their player tags.
    current_members = await COC_EVENTS_CLIENT.get_members(CLAN_TAG)
    current_member_tags = [member.tag for member in current_members]
    
    # Get the player objects associated with the current members of the clan to get
    # each member's total Clan Games points.
    clan_points_data = dict[str, int]()
    async for player in COC_EVENTS_CLIENT.get_players(current_member_tags):
        for achievement in player.achievements:
            if achievement.name == 'Games Champion':
                clan_points_data[player.tag] = achievement.value
    
    return clan_points_data


async def send_clan_games_reminder(reminder_td: timedelta) -> None:
    logger.info('Sending Clan Games reminders to Discord')
    
    # Make reminder strings.
    reminder_str_plural = prettify_seconds(int(reminder_td.total_seconds()), True)
    reminder_str_singular = prettify_seconds(int(reminder_td.total_seconds()), False)
    
    # Log the reminder.
    logger.info(f'========================== {reminder_str_singular} Clan Games Reminder ==========================')
    
    # Create a list of players that we can track Clan Games points for.
    before_clan_games_player_data = await DATABASE_CLIENT.get_last_clan_games_cached_points()
    latest_clan_games_player_data = await get_latest_clan_games_points()
    trackable_clan_games_player_tags = [player_tag for player_tag in before_clan_games_player_data.keys() if player_tag in latest_clan_games_player_data.keys()]
    
    # Get the current members of the clan.
    current_members = await COC_EVENTS_CLIENT.get_members(CLAN_TAG)
    
    # Build the tagging list for the Discord message.
    discord_mentions = list[str]()
    in_game_mentions = list[str]()
    for member in current_members:
        # Check if this clan member is trackable and has not completed any Clan Games challenges.
        if member.tag in trackable_clan_games_player_tags and before_clan_games_player_data[member.tag] == latest_clan_games_player_data[member.tag]:
            in_game_mention = f'"{member.name}" has not completed any Clan Games challenges'
            logger.info(in_game_mention)
            
            # Check if we can tag this member in Discord.
            clan_games_member_mention = COC_PLAYER_TAG_TO_DISCORD_MENTION.get(member.tag)
            if clan_games_member_mention is not None:
                # Add this player's Discord mention to the mention list.
                discord_mentions.append(f'{clan_games_member_mention} you have not completed any Clan Games challenges')
            else:
                # Mention this player's name in plain text in Discord.
                in_game_mentions.append(in_game_mention)
    
    # Check if there is nobody to tag.
    clan_games_warning_message = f'Clan Games is ending in {reminder_str_plural}'
    if len(discord_mentions) == 0 and len(in_game_mentions) == 0:
        everyone_did_clan_games_message = 'Everyone did at least one Clan Games challenge!'
        clan_games_warning_message += f'\n{everyone_did_clan_games_message}'
        logger.info(everyone_did_clan_games_message)
    else:
        all_mentions = discord_mentions + in_game_mentions
        clan_games_warning_message += f'\n{"\n".join(all_mentions)}'
    
    await DISCORD_CLIENT.send_message(clan_games_warning_message, Webhook.CLAN_GAMES_REMINDERS)
    logger.info('Clan Games reminders sent to Discord')


def schedule_clan_games_reminders() -> None:
    # Schedule Clan Games reminders in Discord.
    logger.info('Scheduling Clan Games reminders')
    
    next_clan_games_end = coc.utils.get_clan_games_end().replace(tzinfo=pytz.UTC)
    SCHEDULER.schedule_reminders(REMINDER_DELTAS_CLAN_GAMES, next_clan_games_end, send_clan_games_reminder)
    
    logger.info('Clan Games reminders have been scheduled')


async def clan_games_started() -> None:
    # Log that Clan Games has started.
    logger.info('Clan Games started')
    await asyncio.sleep(0.1)


async def clan_games_ended() -> None:
    # Log that Clan Games has ended.
    logger.info('Clan Games ended')
    
    # Get the current members of the clan and make a list of their player tags.
    current_members = await COC_EVENTS_CLIENT.get_members(CLAN_TAG)
    current_member_tags = [member.tag for member in current_members]
    
    # Get the player objects associated with the current members of the clan.
    current_players = list[coc.Player]()
    async for player in COC_EVENTS_CLIENT.get_players(current_member_tags):
        current_players.append(player)
        
    # Cache all player's Clan Games points to the database.
    logger.info('Caching Clan Games performances')
    await DATABASE_CLIENT.cache_total_clan_games_points(current_players)
    logger.info('Clan Games performances cached')


async def startup_clan_games() -> None:
    # Get relevant event times.
    next_clan_games_start = coc.utils.get_clan_games_start().replace(tzinfo=pytz.UTC)
    next_clan_games_end = coc.utils.get_clan_games_end().replace(tzinfo=pytz.UTC)
    next_clan_games_end_alert = (next_clan_games_end + timedelta(days=-1)).astimezone(CLAN_TIMEZONE).replace(hour=9, minute=0, second=0)
    now = datetime.now(tz=pytz.UTC)
    
    # Check if it is not the start of Clan Games.
    if now < next_clan_games_start:
        logger.info('It is not Clan Games')
        
        # Check if we need to cache clan games points into the database.
        last_clan_games_cached_data = await DATABASE_CLIENT.get_last_clan_games_cached_points()
        if not last_clan_games_cached_data or len(last_clan_games_cached_data) == 0:
            logger.info('The last Clan Games has not been cached. Caching latest Clan Games points for all current players')
            
            # Get the current members in the clan and cache their latest Clan Games points.
            current_clan_members = await COC_EVENTS_CLIENT.get_members(CLAN_TAG)
            current_clan_members_tags = [current_clan_member.tag for current_clan_member in current_clan_members]
            current_players_in_clan = [player async for player in COC_EVENTS_CLIENT.get_players(current_clan_members_tags)]
            await DATABASE_CLIENT.cache_total_clan_games_points(current_players_in_clan)
        
        return
    
    logger.info('Clan Games has been detected')
    
    # Check if it's after the desired Clan Games last day alert time, but before the end of Clan Games.
    if next_clan_games_end_alert < now:
        schedule_clan_games_reminders()


# ================================== Triggers ==================================
@SCHEDULER.scheduler.scheduled_job(ALERT_CRON_CLAN_GAMES_FIRST_DAY, id=SCHEDULER_ID_CLAN_GAMES_FIRST_DAY)
async def send_clan_games_first_day_alert() -> None:
    # Prepare and send the message.
    clan_games_started_message = 'Clan Games has begun! Be sure to get some challenges done. Good luck and have fun!'
    await DISCORD_CLIENT.send_message(clan_games_started_message, Webhook.CLAN_GAMES_REMINDERS)
    logger.info('Sent the Clan Games first day alert to Discord')


@SCHEDULER.scheduler.scheduled_job(ALERT_CRON_CLAN_GAMES_LAST_DAY, id=SCHEDULER_ID_CLAN_GAMES_LAST_DAY)
async def send_clan_games_last_day_alert() -> None:
    # Prepare and send the message.
    clan_games_last_day_message = 'Today is the last day of Clan Games! Be sure to get some challenges done if you haven''t done so already.'
    await DISCORD_CLIENT.send_message(clan_games_last_day_message, Webhook.CLAN_GAMES_REMINDERS)
    logger.info('Sent the Clan Games last day alert to Discord')
    
    schedule_clan_games_reminders()
