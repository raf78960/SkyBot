import asyncio
import itertools
import logging

import discord
from discord.ext import commands

import database as db
from config import DISCORD_TOKEN, GUILD_ID
from cogs.views import SessionView

try:
    from config import EMBED_HOSTING_FOOTER
except ImportError:
    EMBED_HOSTING_FOOTER = (
        "Tous les systèmes de SkyCommunity sont hébergés chez M-Heberge | "
        "La puissance au service de vos projets !"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Footer hébergeur sur TOUS les embeds
# Opt-out guide rôles : discord.Embed._sky_skip_hosting_ids.add(id(embed))
# ---------------------------------------------------------------------------
_original_set_footer = discord.Embed.set_footer
_original_to_dict = discord.Embed.to_dict
discord.Embed._sky_skip_hosting_ids = set()  # type: ignore[attr-defined]


def _set_footer_with_hosting(self, *, text=None, icon_url=None):
    skip = getattr(discord.Embed, "_sky_skip_hosting_ids", set())
    if id(self) in skip:
        return _original_set_footer(self, text=text, icon_url=icon_url)
    if not text:
        text = EMBED_HOSTING_FOOTER
    elif EMBED_HOSTING_FOOTER not in text:
        text = f"{text} · {EMBED_HOSTING_FOOTER}"
    return _original_set_footer(self, text=text, icon_url=icon_url)


def _to_dict_with_hosting(self):
    data = _original_to_dict(self)
    skip = getattr(discord.Embed, "_sky_skip_hosting_ids", set())
    if id(self) in skip:
        return data
    footer = data.get("footer") or {}
    text = (footer.get("text") or "").strip()
    if EMBED_HOSTING_FOOTER not in text:
        footer["text"] = f"{text} · {EMBED_HOSTING_FOOTER}" if text else EMBED_HOSTING_FOOTER
        data["footer"] = footer
    return data


discord.Embed.set_footer = _set_footer_with_hosting
discord.Embed.to_dict = _to_dict_with_hosting

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.voice_states = True
INTENTS.message_content = True  # Requis pour détecter les photos du concours
# ⚠️ Active "SERVER MEMBERS INTENT" + "MESSAGE CONTENT INTENT" dans le portail développeur Discord

bot = commands.Bot(command_prefix="!", intents=INTENTS)


async def sync_commands():
    """
    Synchronise les commandes slash SANS doublons.

    Discord affiche les commandes en double si on sync à la fois
    en global ET par serveur. Stratégie :
    1. Sync uniquement par serveur (instantané)
    2. Vider les commandes globales côté API Discord (garde le tree local intact)
    """
    # 1) Sync par serveur (principal + compagnies)
    guilds_to_sync = list(bot.guilds)
    if GUILD_ID and not any(g.id == GUILD_ID for g in guilds_to_sync):
        guilds_to_sync.append(discord.Object(id=GUILD_ID))

    total = 0
    for g in guilds_to_sync:
        try:
            bot.tree.copy_global_to(guild=g)
            synced = await bot.tree.sync(guild=g)
            total = len(synced)
            name = getattr(g, "name", None) or str(getattr(g, "id", g))
            gid = getattr(g, "id", g)
            logging.info(f"✅ {len(synced)} commandes synchronisées sur {name} ({gid})")
        except Exception as e:
            logging.warning(f"Sync échouée sur {getattr(g, 'id', g)} : {e}")

    # 2) Vider les commandes GLOBALES sur Discord (supprime les doublons)
    #    Sans toucher au tree local, pour que copy_global_to continue de marcher.
    try:
        if bot.application_id:
            await bot.http.bulk_upsert_global_commands(bot.application_id, [])
            logging.info("🧹 Commandes globales Discord vidées (anti-doublons)")
    except Exception as e:
        logging.warning(f"Impossible de vider les commandes globales : {e}")

    if total:
        logging.info(f"Commandes prêtes ({total} par serveur, sans doublon)")
    else:
        logging.warning("⚠️ Aucune commande synchronisée — vérifie le chargement des cogs.")


@bot.event
async def setup_hook():
    await db.init_db()

    active_sessions = await db.list_all_active_sessions_all_guilds()
    for session in active_sessions:
        bot.add_view(SessionView(session["id"]))

    for ext in (
        "cogs.sessions",
        "cogs.admin",
        # "cogs.reminders",  # fichier absent
        "cogs.atis",
        "cogs.frequencies",
        "cogs.tickets",
        "cogs.flightplans",
        "cogs.concours",
        "cogs.atc_planning",
        "cogs.company",
        "cogs.config_dashboard",
        "cogs.site_accounts",
        "cogs.absences",
        "cogs.role_guide",
        "cogs.site_outbox",
    ):
        try:
            await bot.load_extension(ext)
            logging.info(f"Extension chargée : {ext}")
        except Exception as e:
            logging.error(f"Échec chargement {ext} : {e}")

    # API HTTP pour le site Radar (fréquences + comptes ATC)
    # Même VM : BOT_API_HOST=127.0.0.1 (défaut) + SITE_API_URL=http://127.0.0.1:8001/api
    try:
        import os as _os
        from cogs.site_api import start_api_server
        _api_host = (_os.getenv("BOT_API_HOST") or "127.0.0.1").strip()
        _api_port = int(_os.getenv("BOT_API_PORT") or "8080")
        start_api_server(bot, host=_api_host, port=_api_port)
        logging.info("API site démarrée sur %s:%s", _api_host, _api_port)
    except Exception as e:
        logging.error(f"Échec démarrage API site : {e}")

    # ⚠️ Ne pas sync ici : bot.guilds est encore vide dans setup_hook.
    # La sync se fait dans on_ready (tous les serveurs compagnies inclus).


STATUSES = [
    "SkyCommunity | Formations",
    "SkyCommunity | Fréquences ATC",
    "SkyCommunity | Plans de vol",
    "SkyCommunity | /atc-planning",
]


async def rotate_status():
    """Fait tourner le statut du bot toutes les 60 secondes."""
    cycle = itertools.cycle(STATUSES)
    while not bot.is_closed():
        text = next(cycle)
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=text,
            ),
            status=discord.Status.online,
        )
        await asyncio.sleep(60)


@bot.event
async def on_guild_join(guild: discord.Guild):
    """Quand le bot rejoint un serveur de compagnie, synchronise les commandes immédiatement."""
    logging.info(f"Bot ajouté sur {guild.name} ({guild.id}) — sync des commandes…")
    try:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        logging.info(f"✅ {len(synced)} commandes synchronisées sur {guild.name}")
    except Exception as e:
        logging.error(f"Erreur sync sur {guild.name} : {e}")


_synced_once = False


@bot.event
async def on_ready():
    global _synced_once
    logging.info(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    if not GUILD_ID:
        logging.warning(
            "GUILD_ID non défini dans .env (optionnel). "
            "Les commandes sont synchronisées sur chaque serveur rejoint."
        )
    else:
        logging.info(f"GUILD_ID (serveur principal) : {GUILD_ID}")
    logging.info(f"Serveurs rejoints : {len(bot.guilds)}")
    for g in bot.guilds:
        logging.info(f"  • {g.name} ({g.id})")

    # Sync après connexion : bot.guilds est rempli (principal + compagnies)
    if not _synced_once:
        _synced_once = True
        try:
            await sync_commands()
        except Exception as e:
            logging.error(f"Erreur sync commandes : {e}")

    bot.loop.create_task(rotate_status())
    logging.info("Bot prêt. Tape / dans Discord pour voir les commandes.")


if __name__ == "__main__":
    # L'API Flask (fréquences + health) remplace l'ancien keep_alive minimal.
    # Si BOT_API_SECRET n'est pas défini, les routes /api/* refusent les appels ;
    # /health reste accessible pour UptimeRobot.
    bot.run(DISCORD_TOKEN)