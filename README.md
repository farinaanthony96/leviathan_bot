# Leviathan Bot

v0.0.1


## Description

Provides services for the Leviathan clan in their Discord server.


## Visuals

TODO


## Installation

TODO


## Usage

TODO


## Support

If you have any questions or comments you can always use GitHub discussions, or email me at farinaanthony96@gmail.com.


## Roadmap

### Design Flaws to Fix
  - Make entire codebase asynchronous
    - leviathan_cwl_analyzer
  - Decrease coupling throughout the code base
  - Increase code abstraction
    - Particularly, find a better way to abstract clan wars, raid weekends, and clan games into some sort of "Event" interface

### Bugs to Fix
  - The bot will break when the coc.py library times out (either due to the official CoC API being down or some other random event)
    - Solution: More try-except blocks to help catch these weird 1-off errors and possibly implement an error handler
  - The bot is unable to detect when a CWL group is found after a normal clan war ends
    - Solution: Trial and error

### Desired Features to Implement
  - Add a "Last Seen" feature to the database of players
  - Scale back war start times to ending at 8 PM, back to 5:30 PM leading up to CWL
  - Let new members connect their player tag with their Discord ID when they join the Discord server
  - Calculate if a war is possible / impossible to win 
  - Show who defended the best after CWL / clan wars
  - Synchronize Raid Weekend participation with Google sheets
  - Synchronize Clan Games participation with Google sheets
  - Synchronize player history (joining / leaving the clan) with Google Sheets
  - Feature: Automate duplicating the CWL template / Player Participation template for each month and for new years in Google Sheets

Any more ideas are welcome!


## Contributing

You are welcome to make contributions to this project.

To contribute, ensure you have set the environment variables inside the ".env.example" file:
  - COC_API_TOKEN: The Clash of Clans API token you get from the Clash of Clans API documentation website
  - COC_CLAN_TAG: The clan tag of the clan you'd like to run the script on (include the "#")
  - GOOGLE_SHEETS_SPREADSHEET_ID: The ID of the Google Spreadsheet that you'd like to push the data to
    - Be sure to have a sheet for each month inside the spreadsheet. The data will push to the appropriate month. (January, February, March, etc.)

Be sure you rename the ".env.example" file to ".env" so the script can find the file!


## Authors and acknowledgment

Anthony Farina (Owner)


## Project status

This project is still pretty new and will be actively worked on for the foreseeable future. However, if things do change, please feel free to fork it!
