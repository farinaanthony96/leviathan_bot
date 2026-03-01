import datetime
from datetime import datetime, time, timedelta

import coc
from loguru import logger
import pytz

import leviathan_cwl_analyzer
from coc_client import COC_EVENTS_CLIENT
from leviathan_discord import Webhook, COC_PLAYER_TAG_TO_DISCORD_MENTION, MENTION_LEADER, MENTION_CO_LEADER, DISCORD_CLIENT
from leviathan_scheduler import SCHEDULER
from leviathan_utils import CLAN_TAG, CLAN_TIMEZONE, prettify_attack_count, prettify_seconds


# ======================= Environment / Global Variables =======================

# Desired war start time and its formatting in the console when logging
DESIRED_WAR_START_TIME = time(hour=21, minute=0, second=0, tzinfo=CLAN_TIMEZONE)
TIME_FORMAT = '%I:%M %p %Z'

# Reminders
WAR_REMINDER_DELTAS = [timedelta(hours=-2), timedelta(hours=-1), timedelta(minutes=-30), timedelta(minutes=-10)]

# Most amount of time to wait to tag leaders after war ends on the same night
WAR_START_THRESHOLD = timedelta(hours=3)


# ================================== Functions =================================
async def get_cwl_war_number(war: coc.ClanWar) -> int:
    # Check if a normal clan war was provided.
    if not war.is_cwl:
        return -1
    
    war_number = 1
    async for cwl_war in war.league_group.get_wars_for_clan(CLAN_TAG):
        # Check if this is the current war.
        if war.war_tag == cwl_war.war_tag:
            return war_number
        war_number += 1


async def send_war_reminder(reminder_td: timedelta) -> None:
    logger.info('Sending war reminders to Discord')
    
    # Get the latest war information.
    war = await COC_EVENTS_CLIENT.get_current_war(CLAN_TAG)
    
    # A very unlikely scenario has occurred.
    if not war:
        logger.error('War reminder could not be sent - A "None" war was provided')
        return
    
    # Make reminder strings.
    reminder_str_plural = prettify_seconds(int(reminder_td.total_seconds()), True)
    reminder_str_singular = prettify_seconds(int(reminder_td.total_seconds()), False)
    
    # Log the reminder.
    logger.info(f'============================= {reminder_str_singular} War Reminder =============================')
    
    # Build the tagging string list for the Discord message.
    discord_mentions = list[str]()
    in_game_mentions = list[str]()
    for war_member in war.members:
        # Check if this war member is in our clan and still has attacks remaining.
        if not war_member.is_opponent and len(war_member.attacks) < war.attacks_per_member:
            # Log how many attacks this player has remaining.
            remaining_attacks = war.attacks_per_member - len(war_member.attacks)
            in_game_mention = f'"{war_member.name}" has {prettify_attack_count(remaining_attacks)} remaining'
            logger.info(in_game_mention)
            
            # Check if we can tag this member in Discord.
            war_member_mention = COC_PLAYER_TAG_TO_DISCORD_MENTION.get(war_member.tag)
            if war_member_mention is not None:
                # Add this player's Discord mention to the mention list.
                discord_mentions.append(f'{war_member_mention} you have {prettify_attack_count(remaining_attacks)} remaining')
            else:
                # Mention this player's name in plain text in Discord.
                in_game_mentions.append(in_game_mention)
    
    # Check if there is nobody to tag.
    war_warning_message = f'War ends in {reminder_str_plural}'
    if len(discord_mentions) == 0 and len(in_game_mentions) == 0:
        everyone_did_war_attacks_message = 'Everyone got their attacks in!'
        war_warning_message += f'\n{everyone_did_war_attacks_message}'
        logger.info(everyone_did_war_attacks_message)
    else:
        all_mentions = discord_mentions + in_game_mentions
        war_warning_message += f'\n{"\n".join(all_mentions)}'
    
    await DISCORD_CLIENT.send_message(war_warning_message, Webhook.CLAN_WAR_REMINDERS)
    logger.info('War reminders sent to Discord')


def schedule_war_reminders(war_end: datetime) -> None:
    # Schedule the war reminders based off the war end time.
    war_end = war_end.replace(tzinfo=pytz.UTC).astimezone(CLAN_TIMEZONE)
    SCHEDULER.schedule_reminders(WAR_REMINDER_DELTAS, war_end, send_war_reminder)
    

async def send_war_leader_tagging() -> None:
    # Tag leaders to start a war.
    logger.info('Tagging leaders to start the next war')
    await DISCORD_CLIENT.send_message(f'{MENTION_LEADER} {MENTION_CO_LEADER} Start the next war!', Webhook.CLAN_WAR_REMINDERS)


def schedule_war_leader_tagging(war_end: datetime) -> None:
    # Initialize relevant datetimes.
    war_end = war_end.replace(tzinfo=pytz.UTC)
    desired_start_time_today = datetime.now(CLAN_TIMEZONE).replace(
        hour=DESIRED_WAR_START_TIME.hour,
        minute=DESIRED_WAR_START_TIME.minute,
        second=DESIRED_WAR_START_TIME.second
    )
    desired_start_time_tomorrow = desired_start_time_today + timedelta(days=1)
    
    # Check if the war ends between the desired start time and the threshold.
    if war_end < desired_start_time_today:
        SCHEDULER.schedule_generic_job(desired_start_time_today, 'start_war_leader_tagging', send_war_leader_tagging)
        logger.info(f'Scheduled leader tagging for the desired war start time at {DESIRED_WAR_START_TIME.strftime(TIME_FORMAT)}')
    # Check if the war ends between the desired start time and the threshold.
    elif desired_start_time_today <= war_end <= desired_start_time_today + WAR_START_THRESHOLD:
        SCHEDULER.schedule_generic_job(war_end, 'start_war_leader_tagging', send_war_leader_tagging)
        logger.info(f'Scheduled leader tagging for the end of war at {war_end.astimezone(CLAN_TIMEZONE).strftime(TIME_FORMAT)}')
    # The end time is past the tagging threshold, so let's tag tomorrow.
    else:
        SCHEDULER.schedule_generic_job(desired_start_time_tomorrow, 'start_war_leader_tagging', send_war_leader_tagging)
        logger.info(f'Scheduled leader tagging for the end of war at {desired_start_time_tomorrow.strftime(TIME_FORMAT)}')


async def new_war_found(war: coc.ClanWar) -> None:
    # TODO: We may need to look in the "war_state_changed" for a change from normal clan war to CWL.
    
    # Remove leader tagging to start the next war from the scheduler since we just found a new war.
    SCHEDULER.remove_leader_war_tagging()
    
    # Check if this war is a CWL war.
    if war.is_cwl:
        # Check if it is preparation day during CWL.
        if war.league_group.state == 'preparation':
            # Send a message to Discord stating we found a CWL group.
            new_cwl_group_found_message = 'A CWL group has been found! Make sure to donate to the war 1 defensive clan castles. Good luck!'
            logger.info(new_cwl_group_found_message)
            await DISCORD_CLIENT.send_message(new_cwl_group_found_message, Webhook.CLAN_WAR_REMINDERS)
        
            # Run the CWL performance analyzer to prime the CWL Google sheet.
            await leviathan_cwl_analyzer.run()
        else:
            current_cwl_war_number = await get_cwl_war_number(war)
            next_cwl_round_started_message = f'War {current_cwl_war_number} prep day has begun'
            logger.debug(next_cwl_round_started_message)
    # This must be a normal clan war.
    else:
        # Send a Discord message that a new normal clan war has started.
        new_war_message = f'A new clan war has been declared against "{war.opponent.name}"! Make sure to donate to the defensive clan castles. Good luck!'
        logger.info(new_war_message)
        await DISCORD_CLIENT.send_message(new_war_message, Webhook.CLAN_WAR_REMINDERS)


async def war_state_changed(old_war: coc.ClanWar, new_war: coc.ClanWar) -> None:
    logger.debug(f'War state went from "{old_war.state.value}" to "{new_war.state.value}"')
    
    # Check if it is battle day.
    if new_war.state is coc.WarState.in_war:
        # Send a message to Discord saying battle day has started.
        battle_day_started_message = f'Battle day has started against "{new_war.opponent.name}"!'
        logger.info(battle_day_started_message)
        await DISCORD_CLIENT.send_message(battle_day_started_message, Webhook.CLAN_WAR_REMINDERS)
        
        # Schedule war reminders.
        schedule_war_reminders(new_war.end_time.time)
    # Check if war ended.
    elif new_war.state is coc.WarState.war_ended:
        # Check if this is a CWL war or a normal clan war.
        war_results_message = ''
        if new_war.is_cwl:
            # Update the CWL sheet for the last time.
            if new_war.league_group.state == 'ended':
                await leviathan_cwl_analyzer.run()
                
            current_cwl_war_number = await get_cwl_war_number(new_war)
            war_results_message += f'War {current_cwl_war_number} in CWL has just ended - '
        else:
            war_results_message += 'The war has ended - '
        
        # Add the status to the results message.
        match new_war.status:
            case 'won':
                war_results_message += 'WE WON!'
            case 'lost':
                war_results_message += 'We lost'
            case 'tie':
                war_results_message += 'We tied'
            case _:
                war_results_message += 'The result was unable to be determined'
                
        # Send a message to Discord saying the war has ended and the results.
        logger.info(war_results_message)
        await DISCORD_CLIENT.send_message(war_results_message, Webhook.CLAN_WAR_REMINDERS)
        
        # Make a list of players who did not attack in war.
        members_who_missed_attacks_mentions = list[str]()
        for war_member in new_war.members:
            if len(war_member.attacks) == 0 and not war_member.is_opponent:
                members_who_missed_attacks_mentions.append(f'"{war_member.name}"')
        
        # If there are players who did not attack in war, log it.
        if len(members_who_missed_attacks_mentions) > 0:
            logger.info('Players who did not attack:')
            logger.info(', '.join(members_who_missed_attacks_mentions))
        
        # Schedule leader tagging to start the next war, so long as we are not in the middle of CWL.
        current_cwl_war_number = await get_cwl_war_number(new_war)
        if not new_war.is_cwl or current_cwl_war_number == new_war.league_group.number_of_rounds:
            schedule_war_leader_tagging(new_war.end_time.time)
    # We're not doing anything for any other state of war.
    else:
        pass
        
        # TODO: Check if we go from "war_ended" to "not_in_war" to check if the clan is now looking
        # for another war. If that's correct / logical behavior then we can remove leader tagging
        # from the scheduler here.
        # Note: We can detect if state goes from "war_ended" to "preparation" here
        # Note: For CWL, do we check if a new CWL war started if old_war's status is "war_ended" and the new one is "in_war"???
        

async def war_attack_occurred(attack: coc.WarAttack, war: coc.ClanWar) -> None:
    # Check if this war is CWL so we can run the CWL performance analyzer.
    if war.is_cwl:
        logger.info(f'CWL war attack detected! Updating CWL performance sheet')
        
        # Run the CWL performance analyzer.
        await leviathan_cwl_analyzer.run()


async def startup_cwl_war() -> None:
    # Get the CWL group.
    cwl_group = await COC_EVENTS_CLIENT.get_league_group(CLAN_TAG)
    
    # Check if it's not CWL.
    if not cwl_group:
        logger.info('The clan is not in CWL')
        return
    
    logger.info('CWL detected - Running the CWL analysis')
    await leviathan_cwl_analyzer.run()
    
    # Check if it is prep day.
    if cwl_group.state == 'preparation':
        logger.info('Preparation day has been detected for CWL - Not scheduling war reminders')
        return
    elif cwl_group.state == 'ended':
        logger.info('CWL has ended - Setting up leader tagging to search for a normal clan war')
        schedule_war_leader_tagging(datetime.now(pytz.UTC))
        return
    
    # Get the current war in CWL.
    current_cwl_war = None
    async for war in cwl_group.get_wars_for_clan(CLAN_TAG):
        # Check if this is the current war.
        if war.state is coc.WarState.in_war:
            current_cwl_war = war
            break
    
    # Setup war tagging
    schedule_war_reminders(current_cwl_war.end_time.time)
    

async def startup_war() -> None:
    # Get the latest war.
    latest_war = await COC_EVENTS_CLIENT.get_clan_war(CLAN_TAG)
    
    # Check if the clan is not in war.
    if not latest_war or latest_war.state is coc.WarState.not_in_war:
        # Check if it is CWL.
        logger.info('The clan is not at war - Checking if it is CWL')
        await startup_cwl_war()
        return
    # Check if a clan war has ended recently.
    elif latest_war.state is coc.WarState.war_ended:
        # Schedule leader tagging to start the next war.
        logger.info('A clan war has ended recently')
        schedule_war_leader_tagging(datetime.now(pytz.UTC))
        return
    
    # This must be a normal clan war.
    logger.info('An active clan war has been detected')
    
    logger.debug(f'Current war state: {latest_war.state.in_game_name}')

    # As long as it's not preparation day, schedule leader tagging.
    if latest_war.state is not coc.WarState.preparation:
        schedule_war_reminders(latest_war.end_time.time)
