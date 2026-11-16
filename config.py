import os
from dotenv import load_dotenv

load_dotenv()

# ---------- Discord / général ----------
# Sur Replit : onglet Secrets. En local : fichier .env
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("DB_PATH", "training_bot.db")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Paris")

# Délais avant une session pour lesquels un rappel est envoyé (en heures)
REMINDER_HOURS_BEFORE = [24, 1]

# Footer affiché sur tous les embeds postés par le bot
EMBED_HOSTING_FOOTER = (
    "Tous les systèmes de SkyCommunity sont hébergés chez M-Heberge | "
    "La puissance au service de vos projets !"
)

# ---------- ATIS / aviation ----------
CHECKWX_API_KEY = os.getenv("CHECKWX_API_KEY", "")
AIRPORT_DB_TOKEN = os.getenv("AIRPORT_DB_TOKEN", "")
# ID du serveur Discord (optionnel : laisse vide pour sync global)
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
# Rôle ATC autorisé pour les commandes admin ATIS
ATC_ROLE_ID = int(os.getenv("ATC_ROLE_ID", "0") or 0)
# Rôle Gérant ATC — peut modifier le planning ATC (ajouter / annuler créneaux)
GERANT_ATC_ROLE_ID = int(os.getenv("GERANT_ATC_ROLE_ID", "0") or 0)

if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN manquant. Sur Replit : onglet Secrets -> ajoute "
        "DISCORD_TOKEN. En local : crée un fichier .env (voir .env.example)."
    )
