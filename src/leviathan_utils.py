import os

import dotenv
import pytz
from apscheduler.triggers.cron import CronTrigger


# ======================= Environment / Global Variables =======================
dotenv.load_dotenv(override=True)

# Clan info
CLAN_TAG = os.getenv('COC_CLAN_TAG')
CLAN_TIMEZONE = pytz.timezone(os.getenv('COC_CLAN_TIMEZONE'))

# Clash of Clans info
COC_MAX_TOWNHALL_LEVEL = 18

# New season cron trigger
ALERT_CRON_NEW_SEASON = CronTrigger(day=1, hour=9, minute=0, second=0, timezone=CLAN_TIMEZONE)

# New season Scheduler ID
SCHEDULER_ID_NEW_SEASON = 'new_season_alert'


# ================================== Functions =================================
def prettify_attack_count(attack_count: int) -> str:
    return '1 attack' if attack_count == 1 else f'{attack_count} attacks'


def prettify_seconds(seconds: int, plural_naming: bool) -> str:
    # Check if a negative value was provided and make it positive.
    if seconds < 0:
        seconds *= -1
    
    if seconds == 0:
        return '0 seconds' if plural_naming else '0 second'
    
    # Calculate the hours, minutes, and seconds then setup the return string.
    hours = seconds // 3600
    remaining_seconds = seconds % 3600
    minutes = remaining_seconds // 60
    seconds = remaining_seconds % 60
    prettified_seconds = ''
    
    # Add the hours to the string if applicable.
    if hours == 1:
        prettified_seconds += '1 hour'
    elif hours >= 2:
        prettified_seconds += f'{hours} hours' if plural_naming else f'{hours} hour'
    
    # Add the "and" inbetween the hours and the next value if applicable.
    if prettified_seconds != '' and (minutes != 0 or seconds != 0):
        prettified_seconds += ' and '
    
    # Add the minutes to the string if applicable.
    if minutes == 1:
        prettified_seconds += '1 minute'
    elif minutes >= 2:
        prettified_seconds += f'{minutes} minutes' if plural_naming else f'{minutes} minute'
        
    # Add the "and" inbetween the previous value and the seconds if applicable.
    if prettified_seconds != '' and seconds != 0:
        prettified_seconds += ' and '
    
    # Add the seconds to the string.
    if seconds == 1:
        prettified_seconds += '1 second'
    elif seconds >= 2:
        prettified_seconds += f'{seconds} seconds' if plural_naming else f'{seconds} second'
    
    # Return the prettified seconds string.
    return prettified_seconds
