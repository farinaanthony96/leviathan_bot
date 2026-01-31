import os

import coc
import dotenv


# ======================= Environment / Global Variables =======================
dotenv.load_dotenv(override=True)

# Clash of Clans library client
COC_EVENTS_CLIENT = coc.EventsClient(key_names=os.getenv('COC_API_KEY_NAME'))
