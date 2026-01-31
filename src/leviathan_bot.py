import asyncio
import os
from datetime import datetime

import coc
import dotenv
import pytz
from loguru import logger

import leviathan_clan_games
import leviathan_raid_weekend
import leviathan_reddit
import leviathan_war
from coc_client import COC_EVENTS_CLIENT
from leviathan_database import DATABASE_CLIENT
from leviathan_discord import Webhook, COC_PLAYER_TAG_TO_DISCORD_MENTION, DISCORD_CLIENT
from leviathan_scheduler import SCHEDULER
from leviathan_utils import CLAN_TAG, prettify_seconds


# ======================= Environment / Global Variables =======================
dotenv.load_dotenv(override=True)

# Asyncio debug mode
DEBUG_MODE = False


# =============================== Event Listeners ==============================
@COC_EVENTS_CLIENT.event
@coc.WarEvents.new_war()
async def new_war_found(new_war: coc.ClanWar) -> None:
    await leviathan_war.new_war_found(new_war)


@COC_EVENTS_CLIENT.event
@coc.WarEvents.state()
async def war_state_changed(old_war: coc.ClanWar, new_war: coc.ClanWar) -> None:
    await leviathan_war.war_state_changed(old_war, new_war)


@COC_EVENTS_CLIENT.event
@coc.WarEvents.war_attack()
async def war_attack_occurred(attack: coc.WarAttack, war: coc.ClanWar) -> None:
    await leviathan_war.war_attack_occurred(attack, war)


@COC_EVENTS_CLIENT.event
@coc.ClientEvents.raid_weekend_start()
async def raid_weekend_started() -> None:
    await leviathan_raid_weekend.raid_weekend_started()


@COC_EVENTS_CLIENT.event
@coc.ClientEvents.raid_weekend_end()
async def raid_weekend_ended() -> None:
    await leviathan_raid_weekend.raid_weekend_ended()


@COC_EVENTS_CLIENT.event
@coc.ClientEvents.clan_games_start()
async def clan_games_started() -> None:
    await leviathan_clan_games.clan_games_started()


@COC_EVENTS_CLIENT.event
@coc.ClientEvents.clan_games_end()
async def clan_games_ended() -> None:
    await leviathan_clan_games.clan_games_ended()


@COC_EVENTS_CLIENT.event
@coc.ClientEvents.new_season_start()
async def new_season_started() -> None:
    logger.info('A new season has started')
    await asyncio.sleep(0.1)


@COC_EVENTS_CLIENT.event
@coc.ClanEvents.member_join()
async def player_joined_clan(new_member: coc.ClanMember, clan: coc.Clan) -> None:
    logger.info(f'"{new_member.name}" has joined the clan')
    await DATABASE_CLIENT.insert_player(new_member, None)
    COC_EVENTS_CLIENT.add_player_updates(new_member.tag)


@COC_EVENTS_CLIENT.event
@coc.ClanEvents.member_leave()
async def member_left_clan(old_member: coc.ClanMember, clan: coc.Clan) -> None:
    logger.info(f'"{old_member.name}" has left the clan')
    COC_EVENTS_CLIENT.remove_player_updates(old_member.tag)
    await asyncio.sleep(0.1)


@COC_EVENTS_CLIENT.event
@coc.PlayerEvents.name()
async def member_changed_name(old_player: coc.Player, new_player: coc.Player) -> None:
    logger.info(f'"{old_player.name}" changed their name to "{new_player.name}"')
    await DISCORD_CLIENT.send_message(f'"{old_player.name}" has changed their name to "{new_player.name}"!', Webhook.CLAN_CHAT)
    await DATABASE_CLIENT.update_player_name(new_player.tag, new_player.name)


@COC_EVENTS_CLIENT.event
@coc.PlayerEvents.town_hall()
async def member_upgraded_townhall(old_player: coc.Player, new_player: coc.Player) -> None:
    logger.info(f'"{new_player.name}" upgraded to Townhall {new_player.town_hall}!')
    
    # Tag the player in Discord if possible.
    player_discord_mention = COC_PLAYER_TAG_TO_DISCORD_MENTION.get(new_player.tag)
    if player_discord_mention:
        await DISCORD_CLIENT.send_message(f'Congratulations to "{player_discord_mention}" for upgrading to Townhall {new_player.town_hall}!', Webhook.CLAN_CHAT)
    else:
        await DISCORD_CLIENT.send_message(f'Congratulations to "{new_player.name}" for upgrading to Townhall {new_player.town_hall}!', Webhook.CLAN_CHAT)
    
    await DATABASE_CLIENT.update_player_townhall_level(new_player.tag, new_player.town_hall)


@COC_EVENTS_CLIENT.event
@coc.ClientEvents.maintenance_start()
async def maintenance_started() -> None:
    logger.info('Maintenance has started')
    
    # Tell Discord that maintenance has begun.
    logger.info('Sending maintenance began message to Discord')
    await DISCORD_CLIENT.send_message('Clash of Clans maintenance has begun', Webhook.CLAN_CHAT)
    
    # Clear the scheduler since it has coc.py-related requests in there.
    SCHEDULER.clear_scheduler()


@COC_EVENTS_CLIENT.event
@coc.ClientEvents.maintenance_completion()
async def maintenance_ended(maintenance_start_time: datetime) -> None:
    logger.info('Maintenance has ended')
    
    # Sending message to Discord stating that the maintenance has ended.
    logger.info('Sending maintenance ended message to Discord')
    maintenance_length = int((datetime.now(pytz.UTC) - maintenance_start_time.replace(tzinfo=pytz.UTC)).total_seconds())
    await DISCORD_CLIENT.send_message(f'Clash of Clans maintenance has ended - total length: {prettify_seconds(maintenance_length, True)}', Webhook.CLAN_CHAT)
    
    # Start the coc.py library again to re-populate the scheduler again.
    logger.info('Repopulating the scheduler')
    await get_clan_status()


@COC_EVENTS_CLIENT.event
@coc.ClientEvents.event_error()
async def coc_py_error_occurred(coc_py_exception: Exception) -> None:
    logger.error('The coc.py library encountered an error:')
    logger.error(coc_py_exception)


# ================================== Functions =================================
async def get_clan_status() -> None:
    # Check the current status of war.
    logger.info('Determining the current status of war')
    await leviathan_war.startup_war()
    logger.info('The current status of war has been determined')
    
    # Check the current status of Raid Weekend.
    logger.info('Determining the current status of Raid Weekend')
    await leviathan_raid_weekend.startup_raid_weekend()
    logger.info('The current status of Raid Weekend has been determined')
    
    # Check the current status of Clan Games.
    logger.info('Determining the current status of Clan Games')
    await leviathan_clan_games.startup_clan_games()
    logger.info('The current status of Clan Games has been determined')


async def startup() -> None:
    # Configure the logger.
    logger.add("./logs/{time:YYYY-MM-DD}_leviathan_bot.log", rotation="00:00", enqueue=True)
    
    logger.info('========================== Initializing Leviathan Bot ==========================')
    
    # Connect to the database.
    logger.info('Connecting to the database')
    await DATABASE_CLIENT.start()
    logger.info('Connected to the database')
    
    # Connect to Discord.
    logger.info('Connecting to Discord')
    DISCORD_CLIENT.start()
    logger.info('Connected to Discord')
    
    # Start the scheduler.
    logger.info('Starting the scheduler')
    SCHEDULER.start()
    logger.info('Scheduler started')
    
    # Log into the Clash of Clans API client.
    logger.info('Logging into the Clash of Clans API client')
    await COC_EVENTS_CLIENT.login(email=os.getenv('COC_API_EMAIL'), password=os.getenv('COC_API_PASSWORD'))
    logger.info('Logged into the Clash of Clans API client')
    
    # Register all clan updates.
    logger.info('Registering all clan updates')
    COC_EVENTS_CLIENT.add_clan_updates(CLAN_TAG)
    logger.info('All clan updates registered')
    
    # Register all clan war updates.
    logger.info('Registering all clan war updates')
    COC_EVENTS_CLIENT.add_war_updates(CLAN_TAG)
    logger.info('All clan war updates registered')
    
    # Register player updates for all current members of the clan.
    logger.info('Getting all current members of the clan and registering player updates')
    current_members = await COC_EVENTS_CLIENT.get_members(clan_tag=CLAN_TAG)
    COC_EVENTS_CLIENT.add_player_updates(*[member.tag for member in current_members])
    logger.info('All player updates have been registered')
    
    # Add the current clan members to the database, if needed.
    logger.info('Refreshing player database table with new members')
    await DATABASE_CLIENT.refresh_players(current_members)
    logger.info('Player database table refreshed')
    
    # Get the overall status of the clan to populate the scheduler with reminders.
    await get_clan_status()
    
    # Start the Reddit recruitment task.
    loop = asyncio.get_event_loop()
    loop.create_task(coro=leviathan_reddit.stream_recruitment_subreddit(), name='stream_reddit_recruitment')
    
    logger.info('============================ Initialization Complete ===========================')


# ================================= Main Method ================================
if __name__ == '__main__':
    # Setup debugging, if enabled.
    loop = asyncio.get_event_loop()
    loop.set_debug(DEBUG_MODE)
    
    # Run the main event loop forever.
    try:
        loop.run_until_complete(startup())
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        # Ctrl-C to end the loop.
        logger.info('========================== Terminating Leviathan Bot ===========================')
        
        # Cancel the Reddit recruitment task in the main event loop.
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            if task.get_name() == 'stream_reddit_recruitment':
                task.cancel()
                try:
                    loop.run_until_complete(task)
                except asyncio.CancelledError as e:
                    logger.info(f'Task "{task.get_name()}" has been stopped')
                    break
        
        # Close all I/O connections / singletons.
        SCHEDULER.shutdown(True)
        loop.run_until_complete(DISCORD_CLIENT.close())
        loop.run_until_complete(DATABASE_CLIENT.close())
        
        # Stop the main event loop and finish shutting down the bot.
        loop.stop()
        logger.info('========================== Leviathan Bot Terminated ============================')
