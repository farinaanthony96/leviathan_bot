import asyncio
from datetime import datetime, timedelta

import coc
import pytz
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from coc_client import COC_EVENTS_CLIENT
from leviathan_database import DATABASE_CLIENT
from leviathan_discord import Webhook, COC_PLAYER_TAG_TO_DISCORD_MENTION, MENTION_LEADER, MENTION_CO_LEADER, DISCORD_CLIENT
from leviathan_scheduler import SCHEDULER
from leviathan_utils import CLAN_TAG, CLAN_TIMEZONE, prettify_seconds


# ======================= Environment / Global Variables =======================

# Alert cron triggers
ALERT_CRON_RAID_WEEKEND_FIRST_DAY = CronTrigger(day_of_week='fri', hour=9, minute=0, second=0, timezone=CLAN_TIMEZONE)
ALERT_CRON_RAID_WEEKEND_LAST_DAY = CronTrigger(day_of_week='sun', hour=9, minute=0, second=0, timezone=CLAN_TIMEZONE)

# Reminders
REMINDER_DELTAS_RAID_WEEKEND = [timedelta(hours=-12), timedelta(hours=-8), timedelta(hours=-4), timedelta(hours=-1)]

# Scheduler IDs
SCHEDULER_ID_RAID_WEEKEND_FIRST_DAY = 'raid_weekend_first_day_alert'
SCHEDULER_ID_RAID_WEEKEND_LAST_DAY = 'raid_weekend_last_day_alert'


# ================================== Functions =================================
async def send_raid_weekend_leader_tagging() -> None:
    # Tag leaders to start Raid Weekend in Discord.
    await DISCORD_CLIENT.send_message(f'{MENTION_LEADER} {MENTION_CO_LEADER} Start Raid Weekend!', Webhook.RAID_WEEKEND_REMINDERS)
    logger.info('Tagged the leaders in Discord to start Raid Weekend')


async def get_latest_raid_weekend_participants() -> dict[str, coc.RaidMember]:
    # Get the latest Raid Weekend log entry and extract the participants.
    raid_weekend_log = await COC_EVENTS_CLIENT.get_raid_log(CLAN_TAG, limit=1)
    
    # Check if the clan has never had a Raid Weekend.
    if not raid_weekend_log or len(raid_weekend_log) == 0:
        # Raid Weekend has never happened in this clan before.
        return {}
    
    # Make sure we have a RaidLog and not a ClanWarLogEntry.
    latest_raid_weekend_log_entry = raid_weekend_log[0]
    if not isinstance(latest_raid_weekend_log_entry, coc.RaidLogEntry):
        logger.error('Error receiving Raid Weekend log - a Clan War log entry was received')
        return {}
    
    # Make a dictionary of Raid Weekend participants by player tag.
    latest_raid_weekend_participants = latest_raid_weekend_log_entry.members
    raid_weekend_participants_by_tag = dict[str, coc.RaidMember]()
    for raid_member in latest_raid_weekend_participants:
        raid_weekend_participants_by_tag[raid_member.tag] = raid_member
    
    # Return the dictionary.
    return raid_weekend_participants_by_tag


async def send_raid_weekend_reminder(reminder_td: timedelta) -> None:
    logger.info('Sending Raid Weekend reminders to Discord')
    
    # Make reminder strings.
    reminder_str_plural = prettify_seconds(int(reminder_td.total_seconds()), True)
    reminder_str_singular = prettify_seconds(int(reminder_td.total_seconds()), False)
    
    # Log the reminder.
    logger.info(f'========================= {reminder_str_singular} Raid Weekend Reminder =========================')
    
    # Create a list of players that have participated in Raid Weekend so far and the current members of the clan.
    latest_raid_weekend_participants = await get_latest_raid_weekend_participants()
    current_members = await COC_EVENTS_CLIENT.get_members(CLAN_TAG)
    
    # Build the tagging list for the Discord message.
    discord_mentions = list[str]()
    in_game_mentions = list[str]()
    for member in current_members:
        # Check if this clan member has not done any Raid Weekend attacks.
        if member.tag not in latest_raid_weekend_participants.keys():
            in_game_mention = f'"{member.name}" has not done any Raid Weekend attacks'
            logger.info(in_game_mention)
            
            # Check if we can tag this member in Discord.
            raid_weekend_member_mention = COC_PLAYER_TAG_TO_DISCORD_MENTION.get(member.tag)
            if raid_weekend_member_mention is not None:
                # Add this player's Discord mention to the mention list.
                discord_mentions.append(f'{raid_weekend_member_mention} you have not done any Raid Weekend attacks')
            else:
                # Mention this player's name in plain text in Discord.
                in_game_mentions.append(in_game_mention)
    
    # Check if there is nobody to tag.
    raid_weekend_warning_message = f'Raid Weekend is ending in {reminder_str_plural}'
    if len(discord_mentions) == 0 and len(in_game_mentions) == 0:
        everyone_did_raid_weekend_message = 'Everyone did at least one Raid Weekend attack!'
        raid_weekend_warning_message += f'\n{everyone_did_raid_weekend_message}'
        logger.info(everyone_did_raid_weekend_message)
    else:
        all_mentions = discord_mentions + in_game_mentions
        raid_weekend_warning_message += f'\n{"\n".join(all_mentions)}'
    
    await DISCORD_CLIENT.send_message(raid_weekend_warning_message, Webhook.RAID_WEEKEND_REMINDERS)
    logger.info('Raid Weekend reminders sent to Discord')
    
    
def schedule_raid_weekend_reminders() -> None:
    # Schedule Raid Weekend reminders in Discord.
    logger.info('Scheduling Raid Weekend reminders')
    
    next_raid_weekend_end = coc.utils.get_raid_weekend_end().replace(tzinfo=pytz.UTC)
    SCHEDULER.schedule_reminders(REMINDER_DELTAS_RAID_WEEKEND, next_raid_weekend_end, send_raid_weekend_reminder)
    
    logger.info('Raid Weekend reminders have been scheduled')


async def raid_weekend_started() -> None:
    await asyncio.sleep(0.1)
    
    # Log that Raid Weekend has started.
    logger.info('Raid Weekend started')


async def raid_weekend_ended() -> None:
    # Log that Raid Weekend has ended.
    logger.info('Raid Weekend ended')
    
    # Check if the clan has never had a Raid Weekend.
    raid_weekend_log = await COC_EVENTS_CLIENT.get_raid_log(CLAN_TAG, limit=1)
    if not raid_weekend_log or len(raid_weekend_log) == 0:
        logger.info('Raid Weekend did not happen this weekend for this clan - No performance data to save')
        return
    
    # Make sure we have a RaidLog and not a ClanWarLogEntry.
    latest_raid_weekend_log_entry = raid_weekend_log[0]
    if not isinstance(latest_raid_weekend_log_entry, coc.RaidLogEntry):
        logger.error('Error receiving Raid Weekend log - a Clan War log entry was received')
        return
    
    # Save all player's Raid Weekend performance to the database.
    logger.info('Caching Raid Weekend performances')
    await DATABASE_CLIENT.insert_raid_weekend_performances(latest_raid_weekend_log_entry)
    logger.info('Raid Weekend performances cached')


async def startup_raid_weekend() -> None:
    # Get relevant event times.
    next_raid_weekend_start = coc.utils.get_raid_weekend_start().replace(tzinfo=pytz.UTC)
    next_raid_weekend_start_alert = next_raid_weekend_start.astimezone(CLAN_TIMEZONE).replace(hour=9, minute=0, second=0)
    next_raid_weekend_end = coc.utils.get_raid_weekend_end().replace(tzinfo=pytz.UTC)
    next_raid_weekend_end_alert = (next_raid_weekend_end + timedelta(days=-1)).astimezone(CLAN_TIMEZONE).replace(hour=9, minute=0, second=0)
    now = datetime.now(tz=pytz.UTC)
    
    # Check if it is not the start of Raid Weekend.
    if now < next_raid_weekend_start:
        logger.info('It is not Raid Weekend')
        
        # Check if we need to cache Raid Weekend performances into the database.
        last_raid_weekend_cached_data = await DATABASE_CLIENT.get_last_raid_weekend_performances()
        if not last_raid_weekend_cached_data or len(last_raid_weekend_cached_data) == 0:
            logger.info('The last Raid Weekend has not been cached. Caching latest Raid Weekend performances for all current players')
            
            # Get the current members in the clan and cache their latest Raid Weekend performances.
            raid_weekend_log = await COC_EVENTS_CLIENT.get_raid_log(CLAN_TAG, limit=1)
            
            # Check if the clan has never had a Raid Weekend.
            if not raid_weekend_log or len(raid_weekend_log) == 0:
                logger.info('This clan has never had Raid Weekend before - there is nothing to cache')
                return
            
            await DATABASE_CLIENT.insert_raid_weekend_performances(raid_weekend_log[0])
        
        return
    
    logger.info('Raid Weekend has been detected')
    
    # Get the latest Raid Weekend log entry.
    raid_weekend_log = await COC_EVENTS_CLIENT.get_raid_log(CLAN_TAG, limit=2)
    
    # Check if the clan has never had a Raid Weekend.
    if not raid_weekend_log or len(raid_weekend_log) == 0:
        # Check if it's before the desired tagging time.
        if now < next_raid_weekend_start_alert:
            logger.info('Not tagging leaders yet since it is before the desired tagging time')
        # Check if it's after the desired tagging time, but before the desired Raid Weekend last day alert time.
        elif now < next_raid_weekend_end_alert:
            await send_raid_weekend_leader_tagging()
        # Check if it's after the desired Raid Weekend last day alert time, but before the end of Raid Weekend.
        elif now < next_raid_weekend_end:
            await send_raid_weekend_leader_tagging()
            schedule_raid_weekend_reminders()
        
        return
    
    # Make sure we have a RaidLog and not a ClanWarLogEntry.
    latest_raid_weekend_log_entry = raid_weekend_log[0]
    if not isinstance(latest_raid_weekend_log_entry, coc.RaidLogEntry):
        logger.error('Error receiving Raid Weekend log - a Clan War log entry was received')
        return
    
    # Check if Raid Weekend has not been started yet.
    if latest_raid_weekend_log_entry.state == 'ended':
        # Check if it's before the desired tagging time.
        if now < next_raid_weekend_start_alert:
            logger.info('Not tagging leaders yet since it is before the desired tagging time')
        # Check if it's after the desired tagging time, but before the desired Raid Weekend last day alert time.
        elif now < next_raid_weekend_end_alert:
            await send_raid_weekend_leader_tagging()
        # Check if it's after the desired Raid Weekend last day alert time, but before the end of Raid Weekend.
        elif now < next_raid_weekend_end:
            await send_raid_weekend_leader_tagging()
            schedule_raid_weekend_reminders()
    # Check if Raid Weekend actually started.
    elif latest_raid_weekend_log_entry.state == 'ongoing':
        # Check if it's after the desired Raid Weekend last day alert time, but before the end of Raid Weekend.
        if next_raid_weekend_end_alert < now < next_raid_weekend_end:
            schedule_raid_weekend_reminders()
    else:
        logger.error(f'Raid Weekend state type of "{latest_raid_weekend_log_entry.state}" is unsupported')


# ================================= Triggers ==================================
@SCHEDULER.scheduler.scheduled_job(ALERT_CRON_RAID_WEEKEND_FIRST_DAY, id=SCHEDULER_ID_RAID_WEEKEND_FIRST_DAY)
async def send_raid_weekend_first_day_alert() -> None:
    # Prepare and send the message.
    raid_weekend_started_message = 'Raid Weekend has begun! Be sure to get your 6 raids in. Good luck and have fun!'
    await DISCORD_CLIENT.send_message(raid_weekend_started_message, Webhook.RAID_WEEKEND_REMINDERS)
    logger.info('Sent the Raid Weekend first day alert to Discord')
    
    # Get the latest Raid Weekend log entry so we can tag the leaders if Raid Weekend still has not started.
    raid_weekend_log = await COC_EVENTS_CLIENT.get_raid_log(CLAN_TAG, limit=1)
    
    # Check if the clan has never had a Raid Weekend.
    if not raid_weekend_log or len(raid_weekend_log) == 0:
        # Tag the leaders to start the first Raid Weekend.
        await send_raid_weekend_leader_tagging()
        return
    
    # Make sure we have a RaidLog and not a ClanWarLogEntry.
    latest_raid_weekend_log_entry = raid_weekend_log[0]
    if not isinstance(latest_raid_weekend_log_entry, coc.RaidLogEntry):
        logger.error('Error receiving Raid Weekend log - a Clan War log entry was received')
        return
    
    # Check if Raid Weekend started.
    if latest_raid_weekend_log_entry.state == 'ended':
        # Tag the leaders to start Raid Weekend.
        await send_raid_weekend_leader_tagging()
        return


@SCHEDULER.scheduler.scheduled_job(ALERT_CRON_RAID_WEEKEND_LAST_DAY, id=SCHEDULER_ID_RAID_WEEKEND_LAST_DAY)
async def send_raid_weekend_last_day_alert() -> None:
    # Prepare and send the message.
    raid_weekend_last_day_message = 'Today is the last day of Raid Weekend! Be sure to complete all 6 of your raids if you haven''t done so already.'
    await DISCORD_CLIENT.send_message(raid_weekend_last_day_message, Webhook.RAID_WEEKEND_REMINDERS)
    logger.info('Sent the Raid Weekend last day alert to Discord')
    
    # Get the latest Raid Weekend log entry.
    raid_weekend_log = await COC_EVENTS_CLIENT.get_raid_log(CLAN_TAG, limit=1)
    
    # Check if the clan has never had a Raid Weekend.
    if not raid_weekend_log or len(raid_weekend_log) == 0:
        # The leaders still have not started Raid Weekend.
        return
    
    # Make sure we have a RaidLog and not a ClanWarLogEntry.
    latest_raid_weekend_log_entry = raid_weekend_log[0]
    if not isinstance(latest_raid_weekend_log_entry, coc.RaidLogEntry):
        logger.error('Error receiving Raid Weekend log - a Clan War log entry was received')
        return
    
    # Check if Raid Weekend never started.
    if latest_raid_weekend_log_entry.state == 'ended':
        # The leaders still have not started Raid Weekend.
        return
    # Check if Raid Weekend actually started.
    elif latest_raid_weekend_log_entry.state == 'ongoing':
        schedule_raid_weekend_reminders()
    else:
        logger.error(f'Raid Weekend state type of "{latest_raid_weekend_log_entry.state}" is unsupported')
