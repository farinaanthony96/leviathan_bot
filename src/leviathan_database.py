from datetime import datetime, timedelta

import aiosqlite
import coc
import pytz
from aiosqlite import Connection
from loguru import logger


# =================================== Classes ==================================
class LeviathanSQLiteDatabase:
    sqlite_database: Connection
    
    def __init__(self):
        self.sqlite_database = None
    
    async def start(self):
        # Create and/or connect to the database.
        self.sqlite_database = await aiosqlite.connect('leviathan.db', autocommit=True)
        self.sqlite_database.row_factory = aiosqlite.Row
        
        # Make sure the database has been initialized before.
        async with self.sqlite_database.cursor() as cursor:
            # Assert the player table exists.
            await cursor.execute("""
                CREATE TABLE if NOT EXISTS player (
                    tag TEXT NOT NULL CHECK(tag LIKE "#___%") UNIQUE COLLATE BINARY,
                    name TEXT NOT NULL COLLATE BINARY,
                    townhall_level INTEGER NOT NULL CHECK(townhall_level > 0) COLLATE BINARY,
                    discord_id TEXT UNIQUE COLLATE BINARY,
                PRIMARY KEY(tag) ON CONFLICT IGNORE)"""
            )
            
            # Assert the old_player_names table exists.
            await cursor.execute("""
                CREATE TABLE if NOT EXISTS old_player_names (
                    opn_id INTEGER NOT NULL UNIQUE COLLATE BINARY,
                    player_tag TEXT NOT NULL CHECK(player_tag LIKE "#___%") COLLATE BINARY,
                    old_name TEXT COLLATE BINARY,
                PRIMARY KEY(opn_id AUTOINCREMENT) ON CONFLICT FAIL,
                FOREIGN KEY(player_tag) REFERENCES player(tag))"""
            )
            
            # Assert the raid_weekend_performance table exists.
            await cursor.execute("""
                CREATE TABLE if NOT EXISTS raid_weekend_performance (
                    player_tag TEXT NOT NULL CHECK(player_tag LIKE "#___%") COLLATE BINARY,
                    rwp_id INTEGER NOT NULL UNIQUE COLLATE BINARY,
                    year TEXT NOT NULL COLLATE BINARY,
                    month TEXT NOT NULL COLLATE BINARY,
                    start_day TEXT NOT NULL COLLATE BINARY,
                    attacks_used INTEGER NOT NULL COLLATE BINARY,
                    attacks_available INTEGER NOT NULL COLLATE BINARY,
                    points INTEGER NOT NULL CHECK(points >= 0) COLLATE BINARY,
                PRIMARY KEY(rwp_id AUTOINCREMENT) ON CONFLICT FAIL,
                FOREIGN KEY(player_tag) REFERENCES player(tag))"""
            )
            
            # Assert the clan_games_cache table exists.
            await cursor.execute("""
                CREATE TABLE if NOT EXISTS clan_games_cache (
                    cgp_id INTEGER NOT NULL UNIQUE COLLATE BINARY,
                    player_tag TEXT NOT NULL CHECK(player_tag LIKE "#___%") COLLATE BINARY,
                    year TEXT NOT NULL COLLATE BINARY,
                    month TEXT NOT NULL COLLATE BINARY,
                    cached_points INTEGER NOT NULL DEFAULT 0 CHECK(cached_points >= 0) COLLATE BINARY,
                PRIMARY KEY(cgp_id AUTOINCREMENT) ON CONFLICT FAIL,
                FOREIGN KEY(player_tag) REFERENCES player(tag))"""
            )
    
    async def insert_player(self, new_player: coc.ClanMember, discord_id: str | None):
        async with self.sqlite_database.cursor() as cursor:
            await cursor.execute("""
                SELECT * FROM player
                WHERE tag = ?""",
                (new_player.tag, )
            )
            player = await cursor.fetchone()
            
            # Check if this player does not exist in the database.
            if not player:
                await cursor.execute("""
                    INSERT INTO player (tag, name, townhall_level, discord_id)
                    VALUES (?, ?, ?, ?)""",
                    (new_player.tag, new_player.name, new_player.town_hall, discord_id)
                )
            else:
                # This player is in the database. Check if their name has changed so we can add it to the old_player_names table.
                if new_player.name != player['name']:
                    await cursor.execute("""
                        UPDATE player
                        SET name = ?
                        WHERE tag = ?""",
                        (new_player.name, new_player.tag)
                    )
                    await cursor.execute("""
                        INSERT INTO old_player_names (player_tag, old_name)
                        VALUES (?, ?)""",
                        (player['tag'], player['name'])
                    )
                
                # Also check if their townhall level has changed.
                if new_player.town_hall != player['townhall_level']:
                    await cursor.execute("""
                        UPDATE player
                        SET townhall_level = ?
                        WHERE tag = ?""",
                        (new_player.town_hall, new_player.tag)
                    )
    
    async def update_player_townhall_level(self, player_tag: str, new_townhall_level: int):
        async with self.sqlite_database.cursor() as cursor:
            await cursor.execute("""
                UPDATE player
                SET townhall_level = ?
                WHERE tag = ?""",
                (new_townhall_level, player_tag)
            )
    
    async def update_player_name(self, player_tag: str, new_player_name: str):
        async with self.sqlite_database.cursor() as cursor:
            await cursor.execute("""
                SELECT * FROM player
                WHERE tag = ?""",
                (player_tag, )
            )
            player = await cursor.fetchone()
            
            # Check if this player does not exist in the database.
            if not player:
                logger.warning('Tried to update a non-existent player''s name in the database')
            else:
                await cursor.execute("""
                    INSERT INTO old_player_names (player_tag, old_name)
                    VALUES (?, ?)""",
                    (player['tag'], player['name'])
                )
                await cursor.execute("""
                    UPDATE player
                    SET name = ?
                    WHERE tag = ?""",
                    (new_player_name, player_tag)
                )
    
    async def refresh_players(self, current_clan_members: list[coc.ClanMember]):
        async with self.sqlite_database.cursor() as cursor:
            player_tuples = list[tuple]()
            for player in current_clan_members:
                player_tuples.append((player.tag, player.name, player.town_hall, None))
            
            await cursor.executemany("""
                INSERT OR IGNORE INTO player (tag, name, townhall_level, discord_id)
                VALUES (?, ?, ?, ?)""",
                player_tuples
            )
    
    async def get_player(self, player_tag: str):
        async with self.sqlite_database.cursor() as cursor:
            await cursor.execute("""
                SELECT * FROM player WHERE tag=?""",
                (player_tag,)
            )
            return await cursor.fetchone()
    
    async def get_old_player_names(self, player_tag: str):
        async with self.sqlite_database.cursor() as cursor:
            await cursor.execute("""
                SELECT * FROM old_player_names WHERE tag=?""",
                (player_tag,)
            )
            return await cursor.fetchall()
    
    async def insert_raid_weekend_performances(self, raid_weekend: coc.RaidLogEntry):
        # Get relevant datetimes.
        raid_weekend_start = raid_weekend.start_time.time.replace(tzinfo=pytz.UTC)
        year = raid_weekend_start.strftime('%Y')
        month = raid_weekend_start.strftime('%m')
        start_day = raid_weekend_start.strftime('%d')
        
        # Create the performance payload and insert it into the database.
        raid_weekend_performances = [(raid_member.tag, year, month, start_day, raid_member.attack_count, raid_member.attack_limit + raid_member.bonus_attack_limit, raid_member.capital_resources_looted) for raid_member in raid_weekend.members]
        
        async with self.sqlite_database.cursor() as cursor:
            await cursor.executemany("""
                INSERT INTO raid_weekend_performance (player_tag, year, month, start_day, attacks_used, attacks_available, points)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                raid_weekend_performances
            )
    
    async def get_last_raid_weekend_performances(self) -> dict[str, tuple]:
        # Get relevant datetimes.
        one_week_ago = datetime.now(tz=pytz.UTC) + timedelta(days=-7)
        previous_raid_weekend_start_day = coc.utils.get_raid_weekend_start(one_week_ago)
        cached_year = previous_raid_weekend_start_day.strftime('%Y')
        cached_month = previous_raid_weekend_start_day.strftime('%m')
        cached_start_day = previous_raid_weekend_start_day.strftime('%d')
        
        # Query the database for the cached Raid Weekend performances and store the result.
        async with self.sqlite_database.cursor() as cursor:
            await cursor.execute("""
                SELECT * FROM raid_weekend_performance
                WHERE year=? AND month=? AND start_day=?""",
                (cached_year, cached_month, cached_start_day)
            )
            all_cached_raid_weekend_performances = await cursor.fetchall()
        
        # Return the cached data.
        return {raid_weekend_performance['player_tag']: (raid_weekend_performance['year'], raid_weekend_performance['month'], raid_weekend_performance['start_day'], raid_weekend_performance['attacks_used'], raid_weekend_performance['attacks_available'], raid_weekend_performance['points']) for raid_weekend_performance in all_cached_raid_weekend_performances}
    
    async def get_raid_weekend_performances(self, player_tag: str, limit: int):
        async with self.sqlite_database.cursor() as cursor:
            await cursor.execute("""
                SELECT * FROM raid_weekend_performance
                WHERE player_tag=?
                LIMIT ?
                ORDER BY year DESC, month DESC, start_day DESC""",
                (player_tag, limit)
            )
            return await cursor.fetchall()
    
    async def cache_total_clan_games_points(self, players: list[coc.Player]):
        # Get relevant datetimes.
        now = datetime.now(pytz.UTC)
        
        # Check to make sure we are caching the correct Clan Games year / month.
        next_clan_games = coc.utils.get_clan_games_start().replace(tzinfo=pytz.UTC)
        if now.year == next_clan_games.year and now.month == next_clan_games.month:
            last_month = next_clan_games.replace(day=1) + timedelta(days=-1)
            last_clan_games_year = last_month.strftime('%Y')
            last_clan_games_month = last_month.strftime('%m')
        else:
            last_clan_games_year = now.strftime('%Y')
            last_clan_games_month = now.strftime('%m')
        
        # Get each player's current Clan Games points and curate the data into tuples for the database.
        current_player_clan_games_points = list[tuple]()
        for player in players:
            # Get the current total clan games points this player has.
            clan_games_achievement = player.get_achievement('Games Champion')
            total_clan_games_points = clan_games_achievement.value if clan_games_achievement else 0
            current_player_clan_games_points.append((player.tag, last_clan_games_year, last_clan_games_month, total_clan_games_points))
        
        # Cache the Clan Games points for this month.
        async with self.sqlite_database.cursor() as cursor:
            await cursor.executemany("""
                INSERT INTO clan_games_cache (player_tag, year, month, cached_points)
                VALUES (?, ?, ?, ?)""",
                current_player_clan_games_points
            )
    
    async def get_current_clan_games_points(self, player: coc.Player) -> int:
        # Gather relevent datetimes.
        now = datetime.now(pytz.UTC)
        last_month_dt = now.replace(day=1) + timedelta(days=-1)
        last_month = last_month_dt.strftime('%m')
        year_of_last_month = last_month_dt.strftime('%Y')
        
        # Query the database for how many points they had cached last Clan Games.
        async with self.sqlite_database.cursor() as cursor:
            await cursor.execute("""
                SELECT points FROM clan_games_performance
                WHERE player_tag=? AND year=? AND month=?
                ORDER BY year DESC, month DESC""",
                (player.tag, year_of_last_month, last_month)
            )
            cached_clan_games_points_result = await cursor.fetchone()
        
        # Check if there is no data. It could mean they were not in the clan.
        if not cached_clan_games_points_result:
            return -1
        
        # See how many points they got in Clan Games.
        cached_clan_games_points = cached_clan_games_points_result['cached_points']
        clan_games_achievement = player.get_achievement('Games Champion')
        current_total_clan_games_points = clan_games_achievement.value if clan_games_achievement else 0
        current_clan_games_points = current_total_clan_games_points - cached_clan_games_points
        
        return current_clan_games_points

    async def get_last_clan_games_cached_points(self) -> dict[str, int]:
        # Get relevant datetimes.
        previous_clan_games_month = coc.utils.get_clan_games_end().replace(tzinfo=pytz.UTC, day=1) + timedelta(days=-1)
        cached_year = previous_clan_games_month.strftime('%Y')
        cached_month = previous_clan_games_month.strftime('%m')
        
        # Query the database for the cached clan games points and store the result.
        async with self.sqlite_database.cursor() as cursor:
            await cursor.execute("""
                SELECT * FROM clan_games_cache
                WHERE year=? AND month=?""",
                (cached_year, cached_month)
            )
            all_cached_clan_games_points = await cursor.fetchall()
        
        # Return the cached data.
        return {clan_games_player['player_tag']: clan_games_player['cached_points'] for clan_games_player in all_cached_clan_games_points}
    
    async def close(self) -> None:
        logger.info('Closing connection to database')
        await self.sqlite_database.close()


DATABASE_CLIENT = LeviathanSQLiteDatabase()
