import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

import coc
import dotenv
import gspread
import pandas as pd
from gspread_formatting import CellFormat, Color, ColorStyle, TextFormat, batch_updater
from loguru import logger

from coc_client import COC_EVENTS_CLIENT
from leviathan_scheduler import SCHEDULER
from leviathan_utils import CLAN_TAG, COC_MAX_TOWNHALL_LEVEL


# ======================= Environment / Global Variables =======================
dotenv.load_dotenv(override=True)

# Google Sheets variables
GOOGLE_SHEETS_SHEET_NAME = datetime.today().strftime("%B")
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")

# CWL data CSV file name and path
CWL_DATA_FILE_PATH = Path(f"cwl_data/{datetime.today().strftime("%Y_%m")}_cwl_performance_data.csv")

# Output CWL data to the console
DEBUG_MODE = False


# ================================= Enumerations =================================
class AttackRating(Enum):
    """
    Represents the rating of an attack in CWL.
    """
    
    GODLY = "GODLY"
    EXCELLENT = "EXCELLENT"
    ABOVE_AVERAGE = "ABOVE AVERAGE"
    AVERAGE = "AVERAGE"
    BELOW_AVERAGE = "BELOW AVERAGE"
    POOR = "POOR"
    TOO_EASY = "TOO EASY"
    UNKNOWN = "UNKNOWN RATING"
    

class ParticipationState(Enum):
    """
    Represents the state of a player's participation in a CWL war.
    """
    
    PREPARING = "PREPARING"
    AWAITING_ATTACK = "AWAITING ATTACK"
    ATTACKED = "ATTACKED"
    DID_NOT_ATTACK = "DID NOT ATTACK"
    NOT_IN_WAR = "NOT IN WAR"
    NOT_IN_CLAN = "NOT IN CLAN"
    UNKNOWN = "UNKNOWN STATE"


# =================================== Classes ==================================
@dataclass
class AnalyzedCWLAttack:
    stars: int
    destruction_percentage: int
    duration: int
    attacker_map_position: int
    opponent_townhall_level: int
    opponent_map_position: int
    rating: AttackRating
    
    def __str__(self) -> str:
        # Make sure to show if the attacker did not attack their mirror.
        if self.attacker_map_position != self.opponent_map_position:
            return f"{self.destruction_percentage}% {self.stars}* vs a TH{self.opponent_townhall_level} (ATKD {self.opponent_map_position})"
        
        return f"{self.destruction_percentage}% {self.stars}* vs a TH{self.opponent_townhall_level}"
    

@dataclass
class WarParticipation:
    state: ParticipationState
    attack: AnalyzedCWLAttack | None


class PlayerPerformance:
    player: coc.ClanMember
    war_performances: list[WarParticipation]
    total_stars: int
    total_destruction_percentage: int
    total_duration: int
    total_participated_attacks: int
    total_rounds_placed_into: int
    has_participated: bool
    
    def __init__(self, player: coc.ClanMember):
        self.player = player
        self.war_performances = list[WarParticipation]()
        self.total_stars = 0
        self.total_destruction_percentage = 0
        self.total_duration = 0
        self.total_participated_attacks = 0
        self.total_rounds_placed_into = 0
        self.has_participated = False
    
    def add_war_participation(self, war_state: ParticipationState, war_attack: AnalyzedCWLAttack | None) -> None:
        self.war_performances.append(WarParticipation(war_state, war_attack))
        
        # Check if there is no attack.
        if not war_attack:
            # Make sure we update that this clan member has participated in CWL before.
            if war_state is ParticipationState.PREPARING:
                self.has_participated = True
            elif war_state in {ParticipationState.AWAITING_ATTACK, ParticipationState.ATTACKED, ParticipationState.DID_NOT_ATTACK}:
                self.total_rounds_placed_into += 1
                self.has_participated = True
            
            return
        
        # Update totals based off the attack.
        self.total_stars += war_attack.stars
        self.total_destruction_percentage += war_attack.destruction_percentage
        self.total_duration += war_attack.duration
        self.total_participated_attacks += 1
        self.total_rounds_placed_into += 1
        self.has_participated = True


class CWLAnalysis:
    performances: dict[str, PlayerPerformance]
    cwl_group: coc.ClanWarLeagueGroup
    
    def __init__(self, cwl_roster: list[coc.ClanMember], cwl_group: coc.ClanWarLeagueGroup):
        self.performances = dict[str, PlayerPerformance]()
        self.cwl_group = cwl_group
        
        # Populate the performances with all players in the clan.
        for player in cwl_roster:
            self.performances[player.tag] = PlayerPerformance(player)
    
    def add_player_war_performance(self, player_tag: str, war_attack: AnalyzedCWLAttack) -> None:
        self.performances[player_tag].add_war_participation(ParticipationState.ATTACKED, war_attack)
    
    def add_player_war_state(self, player_tag: str, war_state: ParticipationState) -> None:
        self.performances[player_tag].add_war_participation(war_state, None)
    
    def sorted_performances(self) -> list[PlayerPerformance]:
        return sorted(self.performances.values(), key=lambda player_performance: (player_performance.total_participated_attacks, player_performance.total_stars, player_performance.total_destruction_percentage, player_performance.player.name), reverse=True)
        
    async def create_data_headers(self) -> list[str]:
        headers = ["Participating Roster", "Townhall Level"]
        
        # Add the appropriate number of rounds to the sheet.
        rounds_remaining = self.cwl_group.number_of_rounds
        round_index = 0
        async for round_war in self.cwl_group.get_wars_for_clan(CLAN_TAG):
            round_index += 1
            if round_war.state is coc.WarState.preparation:
                headers.append(f"War {round_index} Performance\n"
                            f"00* 00.00%   |   00* 00.00%\n"
                            f"0/{round_war.team_size}                 0/{round_war.team_size}")
                rounds_remaining -= 1
                break
            
            headers.append(f"War {round_index} Performance\n{round_war.clan.stars}* {round(round_war.clan.destruction, 2)}%"
                        f"   |   {round_war.opponent.stars}* {round(round_war.opponent.destruction, 2)}%\n"
                        f"{round_war.clan.attacks_used}/{round_war.team_size}                 {round_war.opponent.attacks_used}/{round_war.team_size}")
            rounds_remaining -= 1
        
        for round_index in range(round_index, round_index + rounds_remaining):
            headers.append(f"War {round_index + 1} Performance\n"
                        f"00* 00.00%   |   00* 00.00%\n"
                        f"0/{round_war.team_size}                 0/{round_war.team_size}")
            
            
        headers.append("Attacks Used")
        headers.append("Overall Stars")
        headers.append("Overall Destruction (%)")
        
        return headers
    
    def create_performance_table(self) -> list[list[str]]:
        # Get a sorted list of players by performance (or by name if there are no performances).
        sorted_analysis = self.sorted_performances()
        
        # Iterate over each clan member to record their performance into a 2D list.
        performance_data_table = list[list[str]]()
        for participant_performance in sorted_analysis:
            # Check if this clan member participated in CWL.
            if not participant_performance.has_participated:
                continue
            
            # Start with the participant's name and townhall level.
            row = list[str]()
            row.append(participant_performance.player.name)
            row.append(f"TH{participant_performance.player.town_hall}")
            
            # Iterate over each of the participant's round performance to add to the row.
            for round_performance in participant_performance.war_performances:
                if not round_performance.attack:
                    row.append(round_performance.state.value)
                    continue
                
                row.append(str(round_performance.attack))
            
            # Add how many times the participant attacked over how many rounds they were in.
            row.append(f"{participant_performance.total_participated_attacks}/{participant_performance.total_rounds_placed_into}")
            
            # Add how many total stars the participant earned.
            row.append(f"{participant_performance.total_stars}")
            
            # Add how much total destruction % the participant got.
            row.append(f"{participant_performance.total_destruction_percentage}")
            
            performance_data_table.append(row)
        
        return performance_data_table


# ================================== Functions =================================
def rate_attack(attacker: coc.ClanWarMember, defender: coc.ClanWarMember) -> AttackRating:
    # Default rating.
    rating = AttackRating.UNKNOWN
    
    # Check if the attacker provided does not have any attacks to rate.
    if len(attacker.attacks) == 0:
        return rating

    # Rate the attack.
    attack = attacker.attacks[0]
    if attack.stars == 0:
        rating = AttackRating.POOR
    elif defender.town_hall == COC_MAX_TOWNHALL_LEVEL:
        if attacker.town_hall == COC_MAX_TOWNHALL_LEVEL:
            match attack.stars:
                case 1:
                    rating = AttackRating.BELOW_AVERAGE
                case 2:
                    if 85 <= int(attack.destruction) <= 99:
                        rating = AttackRating.EXCELLENT
                    elif 70 <= int(attack.destruction) < 85:
                        rating = AttackRating.ABOVE_AVERAGE
                    else:
                        rating = AttackRating.AVERAGE
                case 3:
                    rating = AttackRating.GODLY
        elif attacker.town_hall == COC_MAX_TOWNHALL_LEVEL - 1:
            match attack.stars:
                case 1:
                    rating = AttackRating.AVERAGE
                case 2:
                    if 70 <= int(attack.destruction) <= 99:
                        rating = AttackRating.EXCELLENT
                    else:
                        rating = AttackRating.ABOVE_AVERAGE
                case 3:
                    rating = AttackRating.GODLY
        elif attacker.town_hall <= COC_MAX_TOWNHALL_LEVEL - 2:
            match attack.stars:
                case 1:
                    rating = AttackRating.ABOVE_AVERAGE
                case 2:
                    rating = AttackRating.EXCELLENT
                case 3:
                    rating = AttackRating.GODLY
    elif attacker.town_hall == defender.town_hall:
        match attack.stars:
            case 1:
                rating = AttackRating.BELOW_AVERAGE
            case 2:
                if 70 <= int(attack.destruction) <= 99:
                    rating = AttackRating.ABOVE_AVERAGE
                else:
                    rating = AttackRating.AVERAGE
            case 3:
                rating = AttackRating.EXCELLENT
    elif attacker.town_hall == defender.town_hall + 1:
        match attack.stars:
            case 1:
                rating = AttackRating.POOR
            case 2:
                rating = AttackRating.BELOW_AVERAGE
            case 3:
                rating = AttackRating.AVERAGE
    elif attacker.town_hall >= defender.town_hall + 2:
        match attack.stars:
            case 3:
                rating = AttackRating.TOO_EASY
            case _:
                rating = AttackRating.POOR
    elif attacker.town_hall + 1 == defender.town_hall:
        match attack.stars:
            case 1:
                rating = AttackRating.AVERAGE
            case 2:
                if 70 <= int(attack.destruction) <= 99:
                    rating = AttackRating.EXCELLENT
                else:
                    rating = AttackRating.ABOVE_AVERAGE
            case 3:
                rating = AttackRating.GODLY
    elif attacker.town_hall + 2 <= defender.town_hall:
        match attack.stars:
            case 1:
                rating = AttackRating.ABOVE_AVERAGE
            case 2:
                rating = AttackRating.EXCELLENT
            case 3:
                rating = AttackRating.GODLY
        
    return rating


async def analyze_cwl_performance() -> CWLAnalysis:
    # Get the CWL group and all the clan members in the clan.
    cwl_group = await COC_EVENTS_CLIENT.get_league_group(CLAN_TAG)
    clan_members = await COC_EVENTS_CLIENT.get_members(CLAN_TAG)
    cwl_analysis = CWLAnalysis(clan_members, cwl_group)
    
    # Iterate through each available war so far during CWL for the clan.
    round_number = 0
    async for war in cwl_group.get_wars_for_clan(CLAN_TAG):
        round_number += 1
        
        # Iterate through each clan member in the clan.
        for clan_member in clan_members:
            # Check if this clan member is in the war.
            war_member = war.get_member(clan_member.tag)
            if not war_member:
                # Member is not in this war.
                if DEBUG_MODE:
                    logger.debug(f"[{war.clan.name}] [Round {round_number}]: {clan_member.name} {ParticipationState.NOT_IN_WAR.value}")
                cwl_analysis.add_player_war_state(clan_member.tag, ParticipationState.NOT_IN_WAR)
                continue
            
            # Check if this war member did not attack in this war.
            war_member_attacks = war_member.attacks
            if len(war_member_attacks) == 0:
                player_participation_state = ParticipationState.UNKNOWN
                
                # Check if the war has already ended.
                if war.state is coc.WarState.war_ended:
                    player_participation_state = ParticipationState.DID_NOT_ATTACK
                # Check if the war is in the preparation period.
                elif war.state is coc.WarState.preparation:
                    player_participation_state = ParticipationState.PREPARING
                # Check if the war is going on right now.
                elif war.state is coc.WarState.in_war:
                    player_participation_state = ParticipationState.AWAITING_ATTACK
                
                # Print this player's performance if debug mode is on.
                if DEBUG_MODE:
                    logger.debug(f"[{war.clan.name}] [Round {round_number}]: {war_member.name} {player_participation_state.value}")
                
                # Add this player's performance and continue.
                cwl_analysis.add_player_war_state(war_member.tag, player_participation_state)
                continue
            
            # Analyze the war member's performance!
            war_member_attack = war_member_attacks[0]
            opponent = war.opponent.get_member(war_member_attack.defender_tag)
            attack_rating = rate_attack(war_member, opponent)
            war_member_attack = AnalyzedCWLAttack(war_member_attack.stars, int(war_member_attack.destruction), int(war_member_attack.duration),
                            war_member.map_position, opponent.town_hall, opponent.map_position, attack_rating)
            
            # Add the war member's performance to the analysis.
            cwl_analysis.add_player_war_performance(war_member.tag, war_member_attack)
            
            # Print this player's performance if debug mode is on.
            if DEBUG_MODE:
                logger.debug(f"[{war.clan.name}] [Round {round_number}]: {war_member.name} " \
                      f"(TH{war_member.town_hall}) got a {str(war_member_attack)}")
            
        # Debug mode console formatting.
        if DEBUG_MODE:
            logger.debug("============================================================================")
    
    # Add the "not in war" state to all the wars where there is no data yet.
    remaining_wars = cwl_group.number_of_rounds - len(cwl_group.rounds)
    for _ in range(0, remaining_wars):
        # Add the "not in war" state to all members of the clan.
        for clan_member in clan_members:
            cwl_analysis.add_player_war_state(clan_member.tag, ParticipationState.NOT_IN_WAR)
    
    return cwl_analysis


async def cwl_analysis_to_google_sheets(cwl_analysis: CWLAnalysis, analysis_header: list[str]) -> None:
    gs = gspread.service_account()
    
    cwl_spreadsheet = gs.open_by_key(GOOGLE_SHEETS_SPREADSHEET_ID)
    cwl_worksheet = cwl_spreadsheet.worksheet(GOOGLE_SHEETS_SHEET_NAME)
    format_batch = batch_updater(cwl_spreadsheet)
    
    title_format = CellFormat(textFormat=TextFormat(bold=True), horizontalAlignment='CENTER', verticalAlignment='MIDDLE')
    light_orange_3_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(0.988, 0.898, 0.804))).to_props()  # Player Name background
    white_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(1.0, 1.0, 1.0))).to_props()  # Awaiting
    gray_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(0.8, 0.8, 0.8))).to_props()  # Not in war / preparing / war stats
    light_green_2_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(0.714, 0.843, 0.659))).to_props()  # Victory
    light_red_2_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(0.918, 0.6, 0.6))).to_props()  # Defeat
    magenta_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(1.0, 0.0, 1.0))).to_props()  # Godly
    green_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(0.0, 1.0, 0.0))).to_props()  # Excellent
    dark_green_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(0.204, 0.659, 0.325))).to_props()  # Above average
    yellow_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(1.0, 1.0, 0.0))).to_props()  # Average
    orange_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(1.0, 0.6, 0.0))).to_props()  # Below average
    red_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(1.0, 0.0, 0.0))).to_props()  # Poor
    cyan_bg_format = CellFormat(backgroundColorStyle=ColorStyle(rgbColor=Color(0.0, 1.0, 1.0))).to_props()  # Too easy
    format_batch.format_cell_range(cwl_worksheet, "1:2", title_format)
    
    # cwl_worksheet.update_cell(1, 1, f"{cwl_analysis.available_wars[0].clan.name} CWL")
    # cwl_worksheet.update_cell(1, 2, "Opposing Clans =>")
    
    available_wars = list[coc.ClanWar]()
    async for war in cwl_analysis.cwl_group.get_wars_for_clan(CLAN_TAG):
        available_wars.append(war)
    
    opponent_clan_names = [war.opponent.name for war in available_wars]
    opponent_clan_names.extend(["?" for _ in range(0, cwl_analysis.cwl_group.number_of_rounds - len(opponent_clan_names))])
    cwl_worksheet.update(values=[opponent_clan_names], range_name="C1")
    
    # Attack performance formatting.
    sorted_analysis = cwl_analysis.sorted_performances()
    attack_formatting = list()
    row_num = 3
    for performance in sorted_analysis:
        if not performance.has_participated:
            continue
        
        col_num = 3
        for war_participation in performance.war_performances:
            match war_participation.state:
                case ParticipationState.ATTACKED:
                    match war_participation.attack.rating:
                        case AttackRating.GODLY:
                            attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": magenta_bg_format})
                        case AttackRating.EXCELLENT:
                            attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": green_bg_format})
                        case AttackRating.ABOVE_AVERAGE:
                            attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": dark_green_bg_format})
                        case AttackRating.AVERAGE:
                            attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": yellow_bg_format})
                        case AttackRating.BELOW_AVERAGE:
                            attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": orange_bg_format})
                        case AttackRating.POOR:
                            attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": red_bg_format})
                        case AttackRating.TOO_EASY:
                            attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": cyan_bg_format})
                        case _:
                            attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": gray_bg_format})
                case ParticipationState.AWAITING_ATTACK:
                    attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": white_bg_format})
                case ParticipationState.DID_NOT_ATTACK:
                    attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": red_bg_format})
                case _:
                    attack_formatting.append({"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": gray_bg_format})
            
            col_num += 1
        
        row_num += 1
    
    # Create filler rows beneath the data to clear any residual data.
    filler_data = list[list[str]]()
    for _ in range(0, 50 - len(sorted_analysis)):
        filler_data_row = ["", ""]
        for _ in range(0, cwl_analysis.cwl_group.number_of_rounds + 3):
            filler_data_row.append("")
        filler_data.append(filler_data_row)
    
    filler_row = 3 + len(sorted_analysis)
    filler_formatting = list[list[dict]]()
    for _ in range(0, 50 - len(sorted_analysis)):
        filler_col = 1
        filler_formatting_row = [{"range": gspread.utils.rowcol_to_a1(row_num, col_num), "format": light_orange_3_bg_format}]
        for _ in range(0, 1 + cwl_analysis.cwl_group.number_of_rounds + 3):
            filler_formatting_row.append({"range": gspread.utils.rowcol_to_a1(filler_row, filler_col), "format": white_bg_format})
            filler_col += 1
        filler_formatting.append(filler_formatting_row)
        filler_row += 1
    
    # War performance formatting.
    war_performance_formatting = list()
    round_index = -1
    async for round_war in cwl_analysis.cwl_group.get_wars_for_clan(CLAN_TAG):
        round_index += 1
        if round_war.state == "preparation":
            continue
        
        if round_war.clan.stars > round_war.opponent.stars:
            war_performance_formatting.append({"range": gspread.utils.rowcol_to_a1(2, round_index + 3), "format": light_green_2_bg_format})
        elif round_war.clan.stars < round_war.opponent.stars:
            war_performance_formatting.append({"range": gspread.utils.rowcol_to_a1(2, round_index + 3), "format": light_red_2_bg_format})
        elif round_war.clan.destruction > round_war.opponent.destruction:
            war_performance_formatting.append({"range": gspread.utils.rowcol_to_a1(2, round_index + 3), "format": light_green_2_bg_format})
        elif round_war.clan.destruction < round_war.opponent.destruction:
            war_performance_formatting.append({"range": gspread.utils.rowcol_to_a1(2, round_index + 3), "format": light_red_2_bg_format})
        else:
            war_performance_formatting.append({"range": gspread.utils.rowcol_to_a1(2, round_index + 3), "format": white_bg_format})
    
    # Send the filler data and filler formatting to Google sheets.
    cwl_worksheet.update(values=filler_data, range_name=gspread.utils.rowcol_to_a1(3 + len(sorted_analysis), 1))
    cwl_worksheet.batch_format(filler_formatting)
    
    # Send the war headers to Google sheets.
    cwl_worksheet.update(values=[analysis_header], range_name="A2")
    
    # Make a 2D list of strings of the attack data and send it to Google sheets.
    cwl_worksheet.update(values=sorted_analysis, range_name="A3")
    
    # Send formatting data for the whole sheet to Google sheets.
    format_batch.execute()
    cwl_worksheet.batch_format(attack_formatting)
    
    if len(war_performance_formatting) > 0:
        cwl_worksheet.batch_format(war_performance_formatting)


@SCHEDULER.cooldown(timedelta(minutes=5))
async def run():
    """
    This function will analyze the performance of a clan based off the provided clan tag
    and output the data to a .CSV file and a Google Sheet.
    """
    
    # Analyze player performances.
    cwl_analysis = await analyze_cwl_performance()
    
    # Create the headers for the CWL analysis data.
    headers = await cwl_analysis.create_data_headers()
    
    # Create a 2D list of performance data and place it in a dataframe.
    df = pd.DataFrame(cwl_analysis.create_performance_table(), columns=headers)
    
    # Print the performance data to the console if debug mode is on.
    if DEBUG_MODE:
        logger.debug(df)
    
    # Send performance data to a CSV file.
    CWL_DATA_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CWL_DATA_FILE_PATH, index=False)
    
    # Push the performance data to Google sheets.
    await cwl_analysis_to_google_sheets(cwl_analysis, headers)
