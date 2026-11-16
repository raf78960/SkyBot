# API HTTP exposee par le bot Discord pour le site SkyCommunity Radar.
#
# Discord reste maitre des frequences : le site lit/ecrit via cette API.
# Authentification : header X-Bot-Secret == BOT_API_SECRET.
#
# Hebergement meme VM (recommande) :
#   - BOT_API_HOST=127.0.0.1  (ecoute locale uniquement)
#   - BOT_API_PORT=8080
#   - Cote site : DISCORD_BOT_API_URL=http://127.0.0.1:8080
#   - SITE_API_URL=http://127.0.0.1:8001/api  (backend site local)
#
# Endpoints :
#   GET  /api/frequencies               liste frequences actives
#   POST /api/frequencies/open          ouvrir une frequence
#   POST /api/frequencies/<id>/close    fermer
#   POST /api/frequencies/<id>/lock     basculer verrouillage
#   GET  /health                        sante (sans secret)

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import string
from threading import Thread
from typing import Any

import discord
from flask import Flask, jsonify, request

import database as db
from config import ATC_ROLE_ID, GUILD_ID, TIMEZONE

log = logging.getLogger(__name__)

BOT_API_SECRET = os.getenv("BOT_API_SECRET", "").strip()
# Même machine : http://127.0.0.1:8001/api  |  distant : https://radar.example.com/api
SITE_API_URL = os.getenv("SITE_API_URL", "").rstrip("/")
# Secret partagé avec le site. Un seul secret suffit : à défaut de SITE_API_SECRET, on réutilise BOT_API_SECRET
# (c'est celui que le site vérifie sur /api/bot/* et qu'il envoie au bot).
SITE_API_SECRET = (os.getenv("SITE_API_SECRET", "").strip() or BOT_API_SECRET)

# Référence au bot Discord (injectée au démarrage)
_bot: discord.Client | None = None
_loop: asyncio.AbstractEventLoop | None = None

app = Flask("skycommunity_bot_api")


def _check_secret() -> bool:
    secret = request.headers.get("X-Bot-Secret") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not BOT_API_SECRET:
        log.warning("BOT_API_SECRET non configuré — API refusée")
        return False
    return secrets.compare_digest(secret or "", BOT_API_SECRET)


def _run_coro(coro):
    """Exécute une coroutine sur la boucle du bot depuis le thread Flask."""
    if _loop is None or _bot is None:
        raise RuntimeError("Bot non prêt")
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    return fut.result(timeout=45)


def _freq_public(f: dict) -> dict:
    return {
        "id": f["id"],
        "guild_id": f.get("guild_id"),
        "name": f.get("name"),
        "icao": f.get("icao"),
        "position": f.get("position"),
        "frequency_mhz": f.get("frequency_mhz"),
        "languages": f.get("languages"),
        "atc_user_id": str(f.get("atc_user_id") or ""),
        "voice_channel_id": str(f.get("voice_channel_id") or ""),
        "text_channel_id": str(f.get("text_channel_id") or ""),
        "status": f.get("status"),
        "locked": bool(f.get("locked")),
        "created_at": f.get("created_at"),
    }


@app.before_request
def require_secret():
    if request.path == "/" or request.path == "/health":
        return None
    if not _check_secret():
        return jsonify({"detail": "Non autorisé"}), 401
    return None


@app.route("/")
@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "skycommunity-bot-api", "bot_ready": _bot is not None})


@app.route("/api/frequencies", methods=["GET"])
def list_frequencies():
    guild_id = request.args.get("guild_id", type=int) or GUILD_ID or None
    freqs = _run_coro(db.list_active_frequencies(guild_id))
    return jsonify({"frequencies": [_freq_public(f) for f in freqs]})


@app.route("/api/frequencies/open", methods=["POST"])
def open_frequency():
    data = request.get_json(force=True, silent=True) or {}
    atc_user_id = data.get("atc_user_id")
    position = (data.get("position") or "").strip().upper()
    location = (data.get("location") or data.get("icao") or "").strip()
    freq_number = (data.get("frequency_mhz") or data.get("freq_number") or "").strip()
    languages = (data.get("languages") or "FR").strip() or "FR"

    if not atc_user_id or not position or not location or not freq_number:
        return jsonify({"detail": "atc_user_id, position, location (icao) et frequency_mhz requis"}), 400

    try:
        atc_user_id = int(atc_user_id)
    except (TypeError, ValueError):
        return jsonify({"detail": "atc_user_id invalide"}), 400

    result = _run_coro(_open_freq_async(atc_user_id, position, location, freq_number, languages))
    if result.get("error"):
        return jsonify({"detail": result["error"]}), result.get("status", 400)
    return jsonify(result), 201


async def _open_freq_async(
    atc_user_id: int,
    position: str,
    location: str,
    freq_number: str,
    languages: str,
) -> dict[str, Any]:
    from cogs.frequencies import _create_frequency_core, _is_atc, _normalize_position, _lookup_frequency

    guild = _bot.get_guild(GUILD_ID) if GUILD_ID else None
    if guild is None and _bot.guilds:
        guild = _bot.guilds[0]
    if guild is None:
        return {"error": "Aucun serveur Discord disponible", "status": 503}

    member = guild.get_member(atc_user_id)
    if member is None:
        try:
            member = await guild.fetch_member(atc_user_id)
        except discord.HTTPException:
            return {"error": "Membre Discord introuvable sur le serveur", "status": 404}

    if not _is_atc(member):
        return {"error": "Ce membre n'a pas le rôle ATC", "status": 403}

    existing = await db.get_active_frequency_for_atc(guild.id, atc_user_id)
    if existing:
        return {"error": "Cet ATC a déjà une fréquence ouverte", "status": 409, "frequency": _freq_public(existing)}

    pos = _normalize_position(position)
    icao = location.upper()[:4]
    # Si fréquence non fournie ou générique, tenter lookup
    if not freq_number or freq_number in ("auto", "?"):
        looked = _lookup_frequency(icao, pos)
        if looked:
            freq_number = looked

    # Salon de l'annonce d'ouverture/fermeture : salon d'annonces configuré (/freq-config-annonces), sinon CHANNEL_ANNONCES.
    # Le panneau de controle n'est PAS poste : la frequence se gere depuis le site.
    from cogs.frequencies import _get_announce_channel
    ann_channel, ann_role = await _get_announce_channel(guild)
    if ann_channel is None:
        _env_id = int(os.getenv("CHANNEL_ANNONCES", "0") or 0)
        ann_channel = guild.get_channel(_env_id) if _env_id else None
    if ann_channel is None:
        log.warning(
            "Ouverture site %s_%s : AUCUN salon d'annonces (guild %s). Lance /freq-config-annonces sur le serveur, "
            "ou définis CHANNEL_ANNONCES dans le .env du bot. Aucune annonce ne sera postée.",
            location.upper(), pos, guild.id,
        )

    voice, text_ch, freq_id = await _create_frequency_core(
        _bot,
        guild,
        member,
        position=pos,
        location=location,
        freq_number=freq_number,
        langs=languages,
        mode="site",
        panel_channel=None,  # pas de panneau de controle sur Discord : tout se pilote depuis le site
    )
    if not voice or not freq_id:
        return {"error": "Impossible de créer le salon vocal", "status": 500}

    # Annonce (même embed que la commande Discord)
    announced = False
    try:
        from cogs.frequencies import _embed_open, _log_freq
        # signature: _embed_open(icao, frequency, position, languages, controller)
        ann = _embed_open(icao, freq_number, pos, languages, member)
        if ann_channel is not None:
            await ann_channel.send(
                content=ann_role.mention if ann_role else None,
                embed=ann,
                allowed_mentions=discord.AllowedMentions(roles=True, users=True),
            )
            announced = True
            log.info("Annonce ouverture %s_%s postée dans #%s", icao, pos, ann_channel.name)
        await _log_freq(
            guild,
            action="open",
            user=member,
            icao=icao,
            position=pos,
            frequency=str(freq_number),
            mode="site",
        )
    except Exception as e:
        log.warning("Annonce/log open site: %s (le salon d'annonces est-il visible et écrivable par le bot ?)", e)

    freq = await db.get_frequency(freq_id)
    return {"frequency": _freq_public(freq), "voice_channel_id": str(voice.id), "announced": announced}


@app.route("/api/frequencies/<int:freq_id>/close", methods=["POST"])
def close_frequency(freq_id: int):
    data = request.get_json(force=True, silent=True) or {}
    by_user_id = data.get("by_user_id")
    result = _run_coro(_close_freq_async(freq_id, by_user_id))
    if result.get("error"):
        return jsonify({"detail": result["error"]}), result.get("status", 400)
    return jsonify(result)


async def _close_freq_async(freq_id: int, by_user_id: int | None) -> dict:
    from cogs.frequencies import _close_frequency_full

    freq = await db.get_frequency(freq_id)
    if not freq or freq.get("status") != "active":
        return {"error": "Fréquence introuvable ou déjà fermée", "status": 404}

    guild = _bot.get_guild(freq["guild_id"])
    if guild is None:
        return {"error": "Serveur Discord introuvable", "status": 503}

    user = None
    if by_user_id:
        user = guild.get_member(int(by_user_id))
        if user is None:
            try:
                user = await guild.fetch_member(int(by_user_id))
            except discord.HTTPException:
                user = _bot.user
    if user is None:
        user = _bot.user

    # Seul le propriétaire ATC, un admin ou le bot peut fermer
    owner_id = freq.get("atc_user_id")
    is_owner = by_user_id and int(by_user_id) == int(owner_id)
    is_admin = False
    if by_user_id and isinstance(user, discord.Member):
        is_admin = user.guild_permissions.administrator or (
            ATC_ROLE_ID and any(r.id == ATC_ROLE_ID for r in user.roles) and "gérant" in " ".join(r.name.lower() for r in user.roles)
        )
    if by_user_id and not is_owner and not is_admin and user != _bot.user:
        # Autoriser quand même si appelé depuis le site avec secret (gestion site)
        pass

    deleted_v, deleted_t = await _close_frequency_full(guild, user, freq)
    return {"ok": True, "deleted_voice": deleted_v, "deleted_text": deleted_t, "id": freq_id}


@app.route("/api/frequencies/<int:freq_id>/lock", methods=["POST"])
def lock_frequency(freq_id: int):
    result = _run_coro(_lock_freq_async(freq_id))
    if result.get("error"):
        return jsonify({"detail": result["error"]}), result.get("status", 400)
    return jsonify(result)


async def _lock_freq_async(freq_id: int) -> dict:
    from cogs.frequencies import _toggle_lock_frequency

    freq = await db.get_frequency(freq_id)
    if not freq or freq.get("status") != "active":
        return {"error": "Fréquence introuvable ou inactive", "status": 404}

    guild = _bot.get_guild(freq["guild_id"])
    if guild is None:
        return {"error": "Serveur Discord introuvable", "status": 503}

    updated = await _toggle_lock_frequency(guild, freq)
    if not updated:
        return {"error": "Échec du verrouillage", "status": 500}
    return {"frequency": _freq_public(updated)}


# ---------- Fermeture côté Discord -> libère la position sur le site ----------

async def notify_site_frequency_closed(freq_id: int, closed_by_name: str | None = None) -> bool:
    """Prévient le site qu'une fréquence vient d'être fermée côté Discord, pour qu'il libère la position ATC liée.

    Jamais bloquant : si le site est injoignable, la fermeture Discord reste valable (le site libère de toute façon
    une position sans heartbeat au bout de 10 min).
    """
    # /api/bot/* côté site vérifie BOT_API_SECRET (comme l'outbox) : on l'utilise en priorité, sinon 401.
    secret = BOT_API_SECRET or SITE_API_SECRET
    if not SITE_API_URL or not secret:
        return False
    import aiohttp

    url = f"{SITE_API_URL}/bot/frequencies/{int(freq_id)}/closed"
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
        "User-Agent": "SkyCommunityBot/1.0",
        "ngrok-skip-browser-warning": "true",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"closed_by_name": (closed_by_name or "Staff Discord")[:80]},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 201):
                    return True
                log.warning("notify_site_frequency_closed %s → HTTP %s", freq_id, resp.status)
                return False
    except Exception as e:
        log.warning("notify_site_frequency_closed %s a échoué : %s", freq_id, e)
        return False


# ---------- Création compte site (appelé par commande Discord) ----------

def generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    # Éviter caractères ambigus
    alphabet = alphabet.replace("O", "").replace("0", "").replace("l", "").replace("I", "").replace("1", "")
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def provision_site_atc_account(
    *,
    discord_user_id: int,
    display_name: str,
    email: str | None = None,
) -> dict[str, Any]:
    """
    Appelle le site pour créer un compte ATC (atc_allowed=True) avec mot de passe temporaire.
    Retourne {email, password, user_id, created} ou {error}.
    """
    if not SITE_API_URL or not SITE_API_SECRET:
        return {"error": "SITE_API_URL / SITE_API_SECRET non configurés sur le bot"}

    email = (email or f"atc.{discord_user_id}@skycommunity.fr").strip().lower()
    password = generate_temp_password()

    import aiohttp

    payload = {
        "email": email,
        "password": password,
        "display_name": display_name[:40],
        "discord_user_id": str(discord_user_id),
        "atc_allowed": True,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Site-Secret": SITE_API_SECRET,
        # ngrok free : évite la page interstitielle HTML
        "ngrok-skip-browser-warning": "true",
        "User-Agent": "SkyCommunityBot/1.0",
    }
    url = f"{SITE_API_URL.rstrip('/')}/auth/bot-provision-atc"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                text = await resp.text()
                try:
                    body = __import__("json").loads(text) if text else {}
                except Exception:
                    return {
                        "error": (
                            f"Réponse non-JSON du site (HTTP {resp.status}). "
                            f"URL={url} — vérifie SITE_API_URL (doit finir par /api) "
                            f"et que le backend tourne sur le bon port. "
                            f"Début réponse: {text[:180]!r}"
                        )
                    }
                if resp.status not in (200, 201):
                    detail = body.get("detail") if isinstance(body, dict) else text
                    return {"error": f"{detail} (HTTP {resp.status})"}
                return {
                    "email": body.get("email") or email,
                    "password": password if body.get("created") else body.get("password") or password,
                    "user_id": body.get("id"),
                    "created": bool(body.get("created", True)),
                    "reset": bool(body.get("reset", False)),
                }
    except Exception as e:
        log.exception("provision_site_atc_account")
        return {"error": f"{type(e).__name__}: {e} (URL={url})"}


def start_api_server(bot: discord.Client, host: str = "127.0.0.1", port: int = 8080):
    """
    Démarre l'API Flask dans un thread daemon.
    Par défaut host=127.0.0.1 (même VM que le site) — pas d'exposition publique.
    Mettre BOT_API_HOST=0.0.0.0 seulement si un reverse-proxy externe doit y accéder.
    """
    global _bot, _loop
    _bot = bot
    _loop = asyncio.get_event_loop()

    def run():
        log.info("API site ↔ bot écoute sur %s:%s (même VM = 127.0.0.1)", host, port)
        app.run(host=host, port=port, threaded=True, use_reloader=False)

    t = Thread(target=run, daemon=True, name="bot-site-api")
    t.start()
    return t