import functools
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Lock

import pytz
from apscheduler.events import EVENT_JOB_ERROR, SchedulerEvent
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from leviathan_utils import CLAN_TIMEZONE, prettify_seconds


# ================================== Functions =================================
def scheduler_exception_listener(scheduler_exception_event: SchedulerEvent):
        logger.error('A scheduler exception occurred:')
        logger.error(scheduler_exception_event)


# =================================== Classes ==================================
class Cooldown:
    cooldown_duration: timedelta
    cooldown_end: datetime
    
    def __init__(self, cooldown_duration: timedelta):
        self.cooldown_duration = cooldown_duration
        self.cooldown_end = datetime.now(pytz.UTC) + cooldown_duration
        

class LeviathanScheduler:
    scheduler: AsyncIOScheduler
    cooldowns: dict[Callable, Cooldown]
    cooldown_lock: Lock
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.cooldowns = dict[Callable, Cooldown]()
        self.cooldown_lock = threading.Lock()
    
    def start(self):
        self.scheduler.start()
        self.scheduler.add_listener(scheduler_exception_listener, EVENT_JOB_ERROR)
    
    def shutdown(self, wait: bool):
        logger.info('Shutting down scheduler')
        self.scheduler.shutdown(wait)
    
    def schedule_reminders(self, reminder_deltas: list[timedelta], event_datetime: datetime, function: Callable, *function_args, **function_kwargs):
        # Go through each timedelta to schedule each reminder.
        for reminder in reminder_deltas:
            # Get the current time and the relative reminder time.
            now_dt = datetime.now().astimezone(event_datetime.tzinfo)
            reminder_dt = event_datetime + reminder
            
            # Check if the reminder time is in the future.
            if now_dt < reminder_dt:
                self.scheduler.add_job(func=function, args=function_args, kwargs=dict(function_kwargs, reminder_td=reminder), trigger='date', run_date=reminder_dt)
                logger.info(f'{prettify_seconds(int(reminder.total_seconds()), False)} reminder set for {function.__name__} at {reminder_dt.astimezone(CLAN_TIMEZONE).strftime('%m-%d-%Y %I:%M %p %Z')}')
    
    def schedule_generic_job(self, run_time: datetime, scheduler_id: str, function: Callable, *function_args, **function_kwargs):
        self.scheduler.add_job(id=scheduler_id, func=function, args=function_args, kwargs=function_kwargs, trigger='date', run_date=run_time)
    
    def remove_leader_war_tagging(self):
        try:
            self.scheduler.remove_job('start_war_leader_tagging')
        except JobLookupError:
            logger.info('War leader tagging was not removed because it was not scheduled')
        else:
            logger.info('War leader tagging was removed from the scheduler')
    
    def clear_scheduler(self):
        # Remove all jobs from the scheduler.
        logger.info('Clearing scheduler')
        self.scheduler.remove_all_jobs()
        logger.info('Scheduler has been cleared')
    
    def async_cooldown(self, cooldown_duration: timedelta):
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # Acquire the lock before accessing shared state
                with self.cooldown_lock:
                    # Get the next available time for this specific function
                    cooldown_info = self.cooldowns.get(func, None)
                    cooldown_end = cooldown_info.cooldown_end if cooldown_info else datetime.min.replace(tzinfo=pytz.UTC)
                    now = datetime.now(pytz.UTC)

                    if cooldown_end <= now:
                        # If not on cooldown, update the next available time
                        self.cooldowns[func] = Cooldown(cooldown_duration)
                        return await func(*args, **kwargs)
                    else:
                        # If on cooldown, check if we have the function scheduled
                        if not self.scheduler.get_job(job_id=f'{func.__name__}_cooldown'):
                            self.scheduler.add_job(func=func, args=args, kwargs=kwargs, id=f'{func.__name__}_cooldown', trigger='date', run_date=cooldown_end + timedelta(seconds=1))
                        logger.info(f'Cooldown still active for "{func.__name__}" until {cooldown_info.cooldown_end.astimezone(CLAN_TIMEZONE).strftime('%m/%d/%Y %I:%M %p %Z')}')
            return wrapper
        return decorator


SCHEDULER = LeviathanScheduler()
