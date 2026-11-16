"""
Gestion des fréquences ATC.
- Panel permanent avec règles + boutons
- Ouverture / pré-ouverture / fermeture
- Annonces formatées dans un salon configurable
- Pré-ouvertures planifiées : salons créés à l'heure annoncée
"""

import logging
import re
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from zoneinfo import ZoneInfo

import database as db
from config import ATC_ROLE_ID, TIMEZONE

log = logging.getLogger(__name__)

# Libellés des positions pour les annonces
SERVICE_LABELS = {
    "APP": "APP - Approche",
    "TWR": "TWR - Tour",
    "GND": "GND - Sol",
    "DEL": "DEL - Clairance",
    "CTR": "CTR - Centre",
    "ATIS": "ATIS",
    "DEP": "DEP - Départ",
}

# Fréquences principales (ICAO → position → MHz)
# Position normalisée : ATIS, DEL, GND, TWR, APP, DEP
FREQ_DB: dict[str, dict[str, str]] = {
    # France
    "LFPG": {"ATIS": "127.125", "DEL": "126.65", "GND": "121.60", "TWR": "119.25", "APP": "121.15", "DEP": "124.35"},
    "LFPO": {"ATIS": "131.35", "DEL": "121.05", "GND": "121.70", "TWR": "118.70", "APP": "123.875", "DEP": "127.75"},
    "LFBO": {"ATIS": "123.125", "DEL": "121.70", "GND": "121.90", "TWR": "118.10", "APP": "125.175"},
    "LFLL": {"ATIS": "126.175", "DEL": "121.65", "GND": "121.825", "TWR": "120.45"},
    "LFML": {"ATIS": "125.35", "DEL": "121.725", "GND": "121.90", "TWR": "118.375", "APP": "120.20"},
    "LFMN": {"ATIS": "129.60", "GND": "121.775", "TWR": "118.70"},
    "LFBD": {"ATIS": "131.15", "GND": "121.90", "TWR": "118.30", "APP": "118.60"},
    "LFRS": {"ATIS": "126.93", "GND": "121.655", "TWR": "118.65", "APP": "124.25"},
    "LFRB": {"ATIS": "129.35", "TWR": "120.10", "APP": "122.40"},
    "LFQQ": {"ATIS": "119.325", "GND": "121.85", "TWR": "118.55", "APP": "120.275"},
    "LFOB": {"ATIS": "118.375", "TWR": "121.40", "APP": "119.90"},
    "LFKJ": {"ATIS": "126.925", "GND": "121.70", "TWR": "118.075", "APP": "121.05"},
    # Europe
    "EGLL": {"ATIS": "128.075", "DEL": "121.975", "GND": "121.70", "TWR": "118.70", "APP": "119.725"},
    "EGKK": {"ATIS": "136.525", "DEL": "121.955", "GND": "121.805", "TWR": "124.23", "APP": "126.825"},
    "EDDF": {"ATIS": "118.03", "DEL": "122.035", "GND": "121.805", "TWR": "119.905"},
    "EDDM": {"ATIS": "123.13", "DEL": "121.73", "GND": "121.83", "TWR": "119.405", "APP": "120.775"},
    "EHAM": {"ATIS": "132.98", "DEL": "121.98", "GND": "121.805", "TWR": "118.105", "APP": "119.055", "DEP": "119.055"},
    "LEMD": {"ATIS": "118.25", "DEL": "130.075", "GND": "121.85", "TWR": "118.15", "APP": "127.50"},
    "LEBL": {"ATIS": "118.65", "DEL": "121.80", "GND": "121.65", "TWR": "118.10", "APP": "119.10"},
    "LEPA": {"ATIS": "119.25", "DEL": "123.88", "GND": "121.705", "TWR": "118.305", "APP": "118.95"},
    "LIRF": {"ATIS": "121.85", "DEL": "121.725", "GND": "121.80", "TWR": "118.70", "APP": "120.175"},
    "LIMC": {"ATIS": "120.025", "DEL": "120.90", "GND": "121.90", "TWR": "119.00", "APP": "132.70", "DEP": "126.75"},
    "LSZH": {"ATIS": "125.725", "DEL": "121.925", "GND": "121.902", "TWR": "118.10", "APP": "125.325", "DEP": "125.95"},
    "LSGG": {"ATIS": "135.575", "GND": "121.675", "TWR": "118.70", "APP": "120.30", "DEP": "119.525"},
    # Outre-mer / Maroc
    "TFFF": {"ATIS": "127.85", "GND": "121.90", "TWR": "118.50", "APP": "121.00"},
    "TFFR": {"ATIS": "127.60", "GND": "121.85", "TWR": "118.40", "APP": "121.30"},
    "FMEE": {"ATIS": "126.80", "GND": "121.90", "TWR": "118.40", "APP": "119.40"},
    "GMMN": {"ATIS": "126.30", "TWR": "118.50", "APP": "119.90"},
    "GMMX": {"TWR": "118.70", "APP": "119.70"},
}


def _normalize_position(position: str) -> str:
    """Retourne la clé courte (TWR, GND, DEL, APP, DEP, ATIS, CTR)."""
    key = (position or "").strip().upper()
    short = key.split("-")[0].split()[0] if key else ""
    aliases = {
        "CLD": "DEL",
        "CLNC": "DEL",
        "CLEARANCE": "DEL",
        "PFLT": "DEL",
        "PREFLIGHT": "DEL",
        "SOL": "GND",
        "GROUND": "GND",
        "TOWER": "TWR",
        "TOUR": "TWR",
        "APPROACH": "APP",
        "APPROCHE": "APP",
        "DEPARTURE": "DEP",
        "DEPART": "DEP",
        "ARR": "APP",
        "DIR": "APP",
        "DIRECTOR": "APP",
    }
    return aliases.get(short, short)


def _lookup_frequency(icao: str, position: str) -> str | None:
    """Retourne la fréquence MHz pour ICAO + position, ou None."""
    icao = (icao or "").upper().strip()
    pos = _normalize_position(position)
    airport = FREQ_DB.get(icao)
    if not airport:
        return None
    return airport.get(pos)


def _is_atc(member: discord.Member) -> bool:
    if not member or member.bot:
        return False
    if ATC_ROLE_ID and any(r.id == ATC_ROLE_ID for r in member.roles):
        return True
    return any("atc" in r.name.lower() for r in member.roles)


async def _is_freq_admin(interaction: discord.Interaction) -> bool:
    """Admin Discord ou Gérant ATC (config) pour le panel admin fréquences."""
    if interaction.guild is None:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    try:
        conf = await db.get_guild_config(member.guild.id) or {}
        allowed = set(db.parse_id_list(conf.get("gerant_atc_role_id")))
        if allowed and any(r.id in allowed for r in member.roles):
            return True
    except Exception:
        pass
    for r in member.roles:
        name = r.name.lower()
        if "gérant atc" in name or "gerant atc" in name:
            return True
    return False


def _extract_icao(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"\b([A-Z]{4})\b", text.upper())
    return m.group(1) if m else None


def _service_label(position: str) -> str:
    key = (position or "").strip().upper()
    short = key.split("-")[0].split()[0] if key else ""
    return SERVICE_LABELS.get(short, position or "—")


def _build_voice_name(position: str, location: str, frequency: str) -> str:
    parts = [p.strip() for p in (location, position, frequency) if p and p.strip()]
    return f"📡 {' '.join(parts)}"[:100]


def _freq_embed(freq: dict, voice_channel: discord.VoiceChannel | None = None) -> discord.Embed:
    locked = bool(freq.get("locked"))
    status = "🔒 Verrouillée" if locked else "🟢 Ouverte"
    color = discord.Color.red() if locked else discord.Color.green()
    vocal_txt = (
        voice_channel.mention if voice_channel else f"`{freq['voice_channel_id']}`"
    )
    atc_txt = f"<@{freq['atc_user_id']}>" if freq.get("atc_user_id") else "—"
    icao = freq.get("icao") or "—"
    langs = freq.get("languages") or "—"
    position = freq.get("position") or "—"
    mhz = freq.get("frequency_mhz") or "—"
    text_id = freq.get("text_channel_id")
    text_txt = f"<#{text_id}>" if text_id else "—"

    embed = discord.Embed(
        title=f"📡 Fréquence {freq['name']}",
        color=color,
        description=(
            f"**Statut :** {status}\n"
            f"**Aéroport (ICAO) :** `{icao}`\n"
            f"**Service :** {_service_label(str(position))}\n"
            f"**Fréquence :** `{mhz} MHz`\n"
            f"**Langues :** {langs}\n"
            f"**Vocal :** {vocal_txt}\n"
            f"**ATC :** {atc_txt}"
        ),
    )
    embed.add_field(
        name="Actions disponibles",
        value=(
            "✏️ **Renommer** — modifier le nom de la fréquence (et du vocal)\n"
            "✈️ **ICAO** — changer le code aéroport\n"
            "🔒 **Verrouiller** — bloquer les connexions non-ATC\n"
            "🛑 **Fermer** — clôturer, annoncer et **supprimer** vocal + texte"
        ),
        inline=False,
    )
    embed.set_footer(text=f"ID fréquence : {freq['id']}")
    return embed


async def _get_announce_channel(guild: discord.Guild):
    conf = await db.get_guild_config(guild.id) or {}
    ch_id = conf.get("freq_announce_channel_id")
    if not ch_id:
        # Repli : CHANNEL_ANNONCES du .env (même variable que l'outbox du site) pour le serveur principal
        import os
        env_id = int(os.getenv("CHANNEL_ANNONCES", "0") or 0)
        env_ch = guild.get_channel(env_id) if env_id else None
        return env_ch, None
    ch = guild.get_channel(ch_id)
    role_id = conf.get("freq_ping_role_id")
    role = guild.get_role(role_id) if role_id else None
    return ch, role


async def _send_announce(guild: discord.Guild, embed: discord.Embed):
    ch, role = await _get_announce_channel(guild)
    if not ch:
        return False
    mention = role.mention if role else None
    try:
        await ch.send(
            content=mention or None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=True, users=True),
        )
        return True
    except discord.HTTPException:
        return False


async def _log_freq(
    guild: discord.Guild,
    *,
    action: str,
    user: discord.Member | discord.User,
    icao: str = "—",
    position: str = "—",
    frequency: str = "—",
    mode: str = "auto",
    extra: str | None = None,
):
    """Envoie un log dans le salon de logs fréquences (si configuré)."""
    conf = await db.get_guild_config(guild.id) or {}
    ch_id = conf.get("freq_log_channel_id")
    if not ch_id:
        return
    ch = guild.get_channel(ch_id)
    if not ch:
        return

    colors = {
        "open": discord.Color.green(),
        "manual": discord.Color.blue(),
        "preopen": discord.Color.gold(),
        "preclose": discord.Color.orange(),
        "close": discord.Color.red(),
        "fallback": discord.Color.dark_grey(),
    }
    color = colors.get(action, discord.Color.light_grey())
    titles = {
        "open": "🟢 Fréquence ouverte (auto)",
        "manual": "🔵 Fréquence ouverte (manuelle)",
        "preopen": "🟡 Pré-ouverture",
        "preclose": "🟠 Pré-fermeture",
        "close": "🛑 Fréquence fermée",
        "fallback": "⚙️ Fallback manuel demandé",
    }
    embed = discord.Embed(
        title=titles.get(action, f"📡 {action}"),
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="ATC", value=user.mention, inline=True)
    embed.add_field(name="ICAO", value=f"`{icao}`", inline=True)
    embed.add_field(name="Position", value=_service_label(position), inline=True)
    embed.add_field(name="Fréquence", value=f"`{frequency}` MHz" if frequency and frequency != "—" else "—", inline=True)
    embed.add_field(name="Mode", value=mode, inline=True)
    if extra:
        embed.add_field(name="Détail", value=extra[:1024], inline=False)
    embed.set_footer(text=f"User ID: {user.id}")
    try:
        await ch.send(embed=embed)
    except discord.HTTPException:
        pass


def _embed_open(icao, frequency, position, languages, controller):
    embed = discord.Embed(title="🟢 FRÉQUENCE OUVERTE", color=discord.Color.green())
    embed.add_field(name="🛫 Aéroport", value=icao.upper(), inline=True)
    embed.add_field(name="📻 Fréquence", value=f"{frequency} MHz", inline=True)
    embed.add_field(name="📡 Service", value=_service_label(position), inline=False)
    embed.add_field(name="🌐 Langue(s)", value=languages or "—", inline=True)
    embed.add_field(name="👤 Contrôleur", value=controller.mention, inline=True)
    embed.add_field(
        name="\u200b",
        value="⚠️ Merci de consulter l'ATIS et de déposer votre plan de vol avant de contacter le contrôle.",
        inline=False,
    )
    return embed


def _embed_close(icao, position, controller):
    embed = discord.Embed(title="🔴 FRÉQUENCE FERMÉE", color=discord.Color.red())
    embed.add_field(name="🛫 Aéroport", value=(icao or "—").upper(), inline=True)
    embed.add_field(name="📡 Service", value=_service_label(position), inline=True)
    embed.add_field(name="👤 Contrôleur", value=controller.mention, inline=False)
    embed.add_field(name="\u200b", value="⛔ La fréquence est désormais fermée.", inline=False)
    return embed


def _embed_preopen(icao, frequency, position, hour, languages, controller):
    embed = discord.Embed(title="🟡 PRÉ-OUVERTURE", color=discord.Color.gold())
    embed.add_field(name="🛫 Aéroport", value=icao.upper(), inline=True)
    embed.add_field(name="📻 Fréquence", value=f"{frequency} MHz", inline=True)
    embed.add_field(name="📡 Service", value=_service_label(position), inline=False)
    embed.add_field(name="🕑 Heure", value=hour, inline=True)
    embed.add_field(name="🌐 Langue(s)", value=languages or "—", inline=True)
    embed.add_field(name="👤 Contrôleur", value=controller.mention, inline=False)
    embed.add_field(
        name="\u200b",
        value="⚠️ Merci de consulter l'ATIS et de préparer votre plan de vol avant l'ouverture de la fréquence.",
        inline=False,
    )
    return embed


def _embed_preclose(icao, position, hour, controller):
    embed = discord.Embed(title="🟠 PRÉ-FERMETURE", color=discord.Color.orange())
    embed.add_field(name="🛫 Aéroport", value=(icao or "—").upper(), inline=True)
    embed.add_field(name="📡 Service", value=_service_label(position), inline=True)
    embed.add_field(name="🕐 Heure de fermeture", value=hour, inline=False)
    embed.add_field(name="👤 Contrôleur", value=controller.mention, inline=False)
    embed.add_field(
        name="\u200b",
        value=f"⚠️ La fréquence sera fermée à **{hour}**.",
        inline=False,
    )
    return embed


def _parse_hour_to_utc(hour_str: str) -> datetime | None:
    """
    Parse une heure libre (15h00, 15:00, 15h, 15) → datetime UTC
    pour aujourd'hui (Europe/Paris). Si déjà passée, demain.
    """
    s = (hour_str or "").strip().lower().replace(" ", "")
    m = re.match(r"^(\d{1,2})(?:[h:](\d{2}))?$", s)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return None
    tz = ZoneInfo(TIMEZONE)
    now_local = datetime.now(tz)
    target = now_local.replace(hour=h, minute=mi, second=0, microsecond=0)
    if target <= now_local:
        target = target + timedelta(days=1)
    return target.astimezone(ZoneInfo("UTC"))


async def _create_frequency_core(
    bot: commands.Bot,
    guild: discord.Guild,
    atc_member: discord.Member,
    *,
    position: str,
    location: str,
    freq_number: str,
    langs: str,
    mode: str = "auto",
    panel_channel: discord.abc.Messageable | None = None,
) -> tuple[discord.VoiceChannel | None, discord.TextChannel | None, int | None]:
    """
    Crée vocal + texte + DB + panel.
    Retourne (voice, text_ch, freq_id) ou (None, None, None) en cas d'échec.
    """
    icao = _extract_icao(location) or location.upper()[:4]
    voice_name = _build_voice_name(position, location, freq_number)
    display_name = f"{location} {position} {freq_number}".strip()

    conf = await db.get_guild_config(guild.id) or {}
    category = None  # catégorie vocaux
    if conf.get("freq_category_id"):
        cat = guild.get_channel(conf["freq_category_id"])
        if isinstance(cat, discord.CategoryChannel):
            category = cat

    text_category = None  # catégorie dédiée aux salons texte (panel)
    if conf.get("freq_text_category_id"):
        tcat = guild.get_channel(conf["freq_text_category_id"])
        if isinstance(tcat, discord.CategoryChannel):
            text_category = tcat
    if text_category is None:
        text_category = category  # fallback : même catégorie que les vocaux

    # Permissions = celles de la catégorie respective + bot / créateur ATC
    if category is not None:
        overwrites = dict(category.overwrites)
    else:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False, connect=False, speak=False
            ),
        }
    if text_category is not None:
        text_overwrites = dict(text_category.overwrites)
    else:
        text_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False, send_messages=False, read_message_history=False
            ),
        }
    overwrites[guild.me] = discord.PermissionOverwrite(
        connect=True, speak=True, manage_channels=True, view_channel=True
    )
    overwrites[atc_member] = discord.PermissionOverwrite(
        connect=True, speak=True, manage_channels=True, view_channel=True
    )
    text_overwrites[guild.me] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_channels=True,
        manage_messages=True, read_message_history=True,
    )
    text_overwrites[atc_member] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_channels=True,
        read_message_history=True,
    )

    try:
        voice = await guild.create_voice_channel(
            name=voice_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ouverture fréquence ATC par {atc_member}",
        )
    except discord.HTTPException as e:
        log.warning("Création vocal échouée: %s", e)
        return None, None, None

    # Plus de salon texte par frequence : le panel est poste dans le salon ou la commande a ete lancee.
    text_ch = None

    freq_id = await db.create_frequency(
        guild_id=guild.id,
        voice_channel_id=voice.id,
        name=display_name,
        atc_user_id=atc_member.id,
        text_channel_id=text_ch.id if text_ch else None,
        icao=icao,
        position=position,
        frequency_mhz=freq_number,
        languages=langs,
    )
    freq = await db.get_frequency(freq_id)
    view = FrequencyView(freq_id)
    bot.add_view(view)
    panel_embed = _freq_embed(freq, voice)

    target_ch = text_ch or panel_channel
    if target_ch is not None:
        try:
            msg = await target_ch.send(
                content=(
                    f"{atc_member.mention} — panel de contrôle de la fréquence.\n"
                    f"Vocal : {voice.mention}"
                ),
                embed=panel_embed,
                view=view,
            )
            await db.update_frequency(
                freq_id,
                message_id=msg.id,
            )
        except discord.HTTPException:
            pass

    return voice, text_ch, freq_id


async def _create_frequency_channels(
    interaction: discord.Interaction,
    bot: commands.Bot,
    *,
    position: str,
    location: str,
    freq_number: str,
    langs: str,
    mode: str = "auto",
) -> bool:
    """
    Crée vocal + salon texte + DB + panel + annonce (flux interactif).
    Prérequis : interaction déjà defer. Retourne True si succès.
    """
    icao = _extract_icao(location) or location.upper()[:4]
    display_name = f"{location} {position} {freq_number}".strip()

    voice, text_ch, freq_id = await _create_frequency_core(
        bot,
        interaction.guild,
        interaction.user,
        position=position,
        location=location,
        freq_number=freq_number,
        langs=langs,
        mode=mode,
        panel_channel=interaction.channel,
    )
    if not voice or not freq_id:
        await interaction.followup.send(
            "❌ Impossible de créer le salon vocal.", ephemeral=True
        )
        return False

    ann = _embed_open(icao, freq_number, position, langs, interaction.user)
    announced = await _send_announce(interaction.guild, ann)
    log_action = "manual" if mode == "manual" else "open"
    await _log_freq(
        interaction.guild,
        action=log_action,
        user=interaction.user,
        icao=icao,
        position=position,
        frequency=freq_number,
        mode=mode,
        extra=f"Vocal : {voice.mention}" + (f" · Texte : {text_ch.mention}" if text_ch else ""),
    )

    extra = f" · Texte : {text_ch.mention}" if text_ch else ""
    await interaction.followup.send(
        f"✅ Fréquence **{display_name}** ouverte → {voice.mention}{extra}"
        + ("" if announced else "\n⚠️ Salon d'annonces non configuré (`/freq-config-annonces`)."),
        ephemeral=True,
    )
    return True


# Options de langue (liste déroulante)
LANG_SELECT_OPTIONS = [
    discord.SelectOption(label="Français", value="🇫🇷 FR", emoji="🇫🇷", description="Langue FR uniquement"),
    discord.SelectOption(label="English", value="🇬🇧 EN", emoji="🇬🇧", description="Langue EN uniquement"),
    discord.SelectOption(label="FR + EN", value="🇫🇷🇬🇧 FR / EN", emoji="🌐", description="Français et Anglais"),
]


class LanguageSelect(discord.ui.Select):
    """Sélecteur de langue avant d'ouvrir le formulaire fréquence."""

    def __init__(self, bot: commands.Bot, mode: str):
        # mode: "open" | "manual" | "preopen"
        super().__init__(
            placeholder="Choisir la/les langue(s)…",
            min_values=1,
            max_values=1,
            options=LANG_SELECT_OPTIONS,
            custom_id=f"freq_lang_select_{mode}",
        )
        self.bot = bot
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        if not _is_atc(interaction.user):
            await interaction.response.send_message("🚫 Réservé aux ATC.", ephemeral=True)
            return
        langs = self.values[0]
        if self.mode == "open":
            await interaction.response.send_modal(OpenFrequencyModal(self.bot, languages=langs))
        elif self.mode == "manual":
            await interaction.response.send_modal(ManualOpenModal(self.bot, languages=langs))
        elif self.mode == "preopen":
            await interaction.response.send_modal(PreOpenModal(self.bot, languages=langs))
        else:
            await interaction.response.send_message("Mode inconnu.", ephemeral=True)


class LanguageSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, mode: str):
        super().__init__(timeout=120)
        self.add_item(LanguageSelect(bot, mode))


class ManualFallbackView(discord.ui.View):
    """Bouton éphémère proposé quand le lookup auto échoue."""

    def __init__(
        self,
        bot: commands.Bot,
        position: str,
        location: str,
        languages: str,
    ):
        super().__init__(timeout=120)
        self.bot = bot
        self.position = position
        self.location = location
        self.languages = languages

    @discord.ui.button(
        label="Saisir la fréquence manuellement",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
    )
    async def manual_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_atc(interaction.user):
            await interaction.response.send_message("🚫 Réservé aux ATC.", ephemeral=True)
            return
        modal = ManualOpenModal(
            self.bot,
            languages=self.languages,
            prefill_position=self.position,
            prefill_location=self.location,
        )
        await interaction.response.send_modal(modal)
        await _log_freq(
            interaction.guild,
            action="fallback",
            user=interaction.user,
            icao=_extract_icao(self.location) or self.location.upper()[:4],
            position=self.position,
            mode="fallback",
            extra="Lookup auto échoué → saisie manuelle demandée",
        )


class ManualOpenModal(discord.ui.Modal, title="Ouvrir une fréquence (manuel)"):
    position = discord.ui.TextInput(
        label="Position",
        placeholder="Ex : TWR, APP, GND, DEL, CTR…",
        max_length=30,
        required=True,
    )
    location = discord.ui.TextInput(
        label="Lieu / Aéroport (ICAO)",
        placeholder="Ex : LFML",
        max_length=40,
        required=True,
    )
    frequency = discord.ui.TextInput(
        label="Numéro de fréquence",
        placeholder="Ex : 119.865",
        max_length=20,
        required=True,
    )

    def __init__(
        self,
        bot: commands.Bot,
        *,
        languages: str,
        prefill_position: str | None = None,
        prefill_location: str | None = None,
    ):
        super().__init__()
        self.bot = bot
        self.languages = languages
        if prefill_position:
            self.position.default = prefill_position
        if prefill_location:
            self.location.default = prefill_location

    async def on_submit(self, interaction: discord.Interaction):
        if not _is_atc(interaction.user):
            await interaction.response.send_message("🚫 Réservé aux ATC.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        existing = await db.get_active_frequency_for_atc(
            interaction.guild_id, interaction.user.id
        )
        if existing:
            await interaction.followup.send(
                f"Tu as déjà une fréquence ouverte : **{existing['name']}** "
                f"(<#{existing['voice_channel_id']}>).\n"
                "Ferme-la avant d'en ouvrir une autre.",
                ephemeral=True,
            )
            return

        position = self.position.value.strip()
        location = self.location.value.strip()
        freq_number = self.frequency.value.strip().replace(" MHz", "").replace("MHz", "").strip()
        langs = self.languages

        if not freq_number:
            await interaction.followup.send("❌ Fréquence invalide.", ephemeral=True)
            return

        await _create_frequency_channels(
            interaction,
            self.bot,
            position=position,
            location=location,
            freq_number=freq_number,
            langs=langs,
            mode="manual",
        )


class OpenFrequencyModal(discord.ui.Modal, title="Ouvrir une fréquence"):
    position = discord.ui.TextInput(
        label="Position",
        placeholder="Ex : TWR, APP, GND, DEL, CTR…",
        max_length=30,
        required=True,
    )
    location = discord.ui.TextInput(
        label="Lieu / Aéroport (ICAO)",
        placeholder="Ex : LFML",
        max_length=40,
        required=True,
    )

    def __init__(self, bot: commands.Bot, *, languages: str):
        super().__init__()
        self.bot = bot
        self.languages = languages

    async def on_submit(self, interaction: discord.Interaction):
        if not _is_atc(interaction.user):
            await interaction.response.send_message("🚫 Réservé aux ATC.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        existing = await db.get_active_frequency_for_atc(
            interaction.guild_id, interaction.user.id
        )
        if existing:
            await interaction.followup.send(
                f"Tu as déjà une fréquence ouverte : **{existing['name']}** "
                f"(<#{existing['voice_channel_id']}>).\n"
                "Ferme-la avant d'en ouvrir une autre.",
                ephemeral=True,
            )
            return

        position = self.position.value.strip()
        location = self.location.value.strip()
        langs = self.languages
        icao = _extract_icao(location) or location.upper()[:4]

        freq_number = _lookup_frequency(icao, position)
        if not freq_number:
            known = ", ".join(sorted(FREQ_DB.keys()))
            view = ManualFallbackView(self.bot, position, location, langs)
            await interaction.followup.send(
                f"❌ Aucune fréquence enregistrée pour **{icao}** / **{_normalize_position(position)}**.\n"
                f"Aéroports connus : `{known}`\n\n"
                "Tu peux saisir la fréquence manuellement :",
                view=view,
                ephemeral=True,
            )
            await _log_freq(
                interaction.guild,
                action="fallback",
                user=interaction.user,
                icao=icao,
                position=position,
                mode="fallback",
                extra="Lookup auto échoué — bouton manuel proposé",
            )
            return

        await _create_frequency_channels(
            interaction,
            self.bot,
            position=position,
            location=location,
            freq_number=freq_number,
            langs=langs,
            mode="auto",
        )


class PreOpenModal(discord.ui.Modal, title="Pré-ouverture de fréquence"):
    position = discord.ui.TextInput(
        label="Position",
        placeholder="Ex : TWR, APP, GND…",
        max_length=30,
        required=True,
    )
    location = discord.ui.TextInput(
        label="Lieu / Aéroport (ICAO)",
        placeholder="Ex : LFML",
        max_length=40,
        required=True,
    )
    hour = discord.ui.TextInput(
        label="Heure d'ouverture prévue",
        placeholder="Ex : 15h00",
        max_length=20,
        required=True,
    )

    def __init__(self, bot: commands.Bot, *, languages: str):
        super().__init__()
        self.bot = bot
        self.languages = languages

    async def on_submit(self, interaction: discord.Interaction):
        if not _is_atc(interaction.user):
            await interaction.response.send_message("🚫 Réservé aux ATC.", ephemeral=True)
            return

        position = self.position.value.strip()
        location = self.location.value.strip()
        hour = self.hour.value.strip()
        langs = self.languages
        icao = _extract_icao(location) or location.upper()[:4]

        scheduled_utc = _parse_hour_to_utc(hour)
        if not scheduled_utc:
            await interaction.response.send_message(
                "❌ Heure invalide. Utilise un format comme `15h00`, `15:00` ou `15h`.",
                ephemeral=True,
            )
            return

        freq_number = _lookup_frequency(icao, position)
        if not freq_number:
            known = ", ".join(sorted(FREQ_DB.keys()))
            await interaction.response.send_message(
                f"❌ Aucune fréquence enregistrée pour **{icao}** / **{_normalize_position(position)}**.\n"
                f"Aéroports connus : `{known}`\n"
                "Vérifie l’ICAO et la position (TWR, GND, DEL, APP, DEP, ATIS…).",
                ephemeral=True,
            )
            return

        pending = await db.get_pending_preopen_for_atc(
            interaction.guild_id, interaction.user.id
        )
        if pending:
            await interaction.response.send_message(
                f"Tu as déjà une pré-ouverture planifiée pour **{pending['icao']} {pending['position']}** "
                f"à **{pending['hour_str']}**.\n"
                "Attends qu’elle se déclenche (ou demande à un admin de l’annuler) avant d’en planifier une autre.",
                ephemeral=True,
            )
            return

        existing = await db.get_active_frequency_for_atc(
            interaction.guild_id, interaction.user.id
        )
        if existing:
            await interaction.response.send_message(
                f"Tu as déjà une fréquence ouverte : **{existing['name']}** "
                f"(<#{existing['voice_channel_id']}>).\n"
                "Ferme-la avant de planifier une pré-ouverture.",
                ephemeral=True,
            )
            return

        await db.create_preopen_schedule(
            guild_id=interaction.guild_id,
            atc_user_id=interaction.user.id,
            position=position,
            location=location,
            icao=icao,
            frequency_mhz=freq_number,
            languages=langs,
            hour_str=hour,
            scheduled_at=scheduled_utc.isoformat(),
        )

        ann = _embed_preopen(icao, freq_number, position, hour, langs, interaction.user)
        announced = await _send_announce(interaction.guild, ann)
        await _log_freq(
            interaction.guild,
            action="preopen",
            user=interaction.user,
            icao=icao,
            position=position,
            frequency=freq_number,
            mode="auto",
            extra=f"Heure prévue : {hour} (création auto des salons)",
        )

        local_str = scheduled_utc.astimezone(ZoneInfo(TIMEZONE)).strftime("%H:%M")
        await interaction.response.send_message(
            f"✅ Pré-ouverture planifiée pour **{icao} {position}** (`{freq_number}` MHz).\n"
            f"Les salons vocal + texte seront créés automatiquement vers **{local_str}** ({TIMEZONE})."
            + ("" if announced else "\n⚠️ Salon d'annonces non configuré (`/freq-config-annonces`)."),
            ephemeral=True,
        )


class RenameFreqModal(discord.ui.Modal, title="Renommer la fréquence"):
    new_name = discord.ui.TextInput(
        label="Nouveau nom",
        placeholder="Ex : LFML TWR 118.700",
        max_length=80,
    )

    def __init__(self, freq_id: int, parent_view: "FrequencyView"):
        super().__init__()
        self.freq_id = freq_id
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        name = self.new_name.value.strip()
        if not name:
            await interaction.response.send_message("Nom invalide.", ephemeral=True)
            return
        fields = {"name": name}
        icao = _extract_icao(name)
        if icao:
            fields["icao"] = icao
        await db.update_frequency(self.freq_id, **fields)
        freq = await db.get_frequency(self.freq_id)
        voice = interaction.guild.get_channel(freq["voice_channel_id"])
        if voice and isinstance(voice, discord.VoiceChannel):
            try:
                await voice.edit(name=f"📡 {name}"[:100])
            except discord.HTTPException:
                pass
        embed = _freq_embed(
            freq, voice if isinstance(voice, discord.VoiceChannel) else None
        )
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class SetIcaoModal(discord.ui.Modal, title="Aéroport de la fréquence"):
    icao_input = discord.ui.TextInput(
        label="Code ICAO",
        placeholder="Ex : LFML",
        max_length=4,
        min_length=4,
    )

    def __init__(self, freq_id: int, parent_view: "FrequencyView"):
        super().__init__()
        self.freq_id = freq_id
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        icao = self.icao_input.value.strip().upper()
        if len(icao) != 4 or not icao.isalpha():
            await interaction.response.send_message(
                "❌ ICAO invalide (4 lettres).", ephemeral=True
            )
            return
        await db.update_frequency(self.freq_id, icao=icao)
        freq = await db.get_frequency(self.freq_id)
        voice = interaction.guild.get_channel(freq["voice_channel_id"])
        embed = _freq_embed(
            freq, voice if isinstance(voice, discord.VoiceChannel) else None
        )
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


async def _close_frequency_full(
    guild: discord.Guild,
    user: discord.abc.User,
    freq: dict,
) -> tuple[bool, bool]:
    """Ferme une fréquence : DB, annonce, log, suppression salons.
    Retourne (deleted_voice, deleted_text).
    """
    await db.close_frequency(freq["id"])

    voice = guild.get_channel(freq["voice_channel_id"])
    text_ch = None
    if freq.get("text_channel_id"):
        text_ch = guild.get_channel(freq["text_channel_id"])

    deleted_voice = False
    deleted_text = False
    if voice and isinstance(voice, discord.VoiceChannel):
        try:
            await voice.delete(reason=f"Fréquence fermée par {user}")
            deleted_voice = True
        except discord.HTTPException:
            pass

    icao = freq.get("icao") or "—"
    position = freq.get("position") or freq.get("name") or "—"
    freq_mhz = freq.get("frequency_mhz") or "—"
    ann = _embed_close(icao, position, user)
    await _send_announce(guild, ann)
    await _log_freq(
        guild,
        action="close",
        user=user,
        icao=icao,
        position=position,
        frequency=str(freq_mhz),
        mode="—",
        extra=f"Nom : {freq.get('name', '—')}",
    )

    if text_ch and isinstance(text_ch, discord.TextChannel):
        try:
            await text_ch.delete(reason=f"Fréquence fermée par {user}")
            deleted_text = True
        except discord.HTTPException:
            pass

    return deleted_voice, deleted_text


async def _toggle_lock_frequency(guild: discord.Guild, freq: dict) -> dict | None:
    """Bascule verrouillage d'une fréquence active. Retourne le dict mis à jour.

    Verrouillé :
    - rôles configurés (freq_lock_deny_role_ids) : view+connect = False sur le vocal
    - salon texte : visible uniquement créateur + staff (+ bot)
    - ATC / staff / créateur restent autorisés
    """
    if not freq or freq.get("status") != "active":
        return None
    new_locked = 0 if freq.get("locked") else 1
    await db.update_frequency(freq["id"], locked=new_locked)
    freq = await db.get_frequency(freq["id"])
    if not freq:
        return None

    conf = await db.get_guild_config(guild.id) or {}
    deny_ids = db.parse_id_list(conf.get("freq_lock_deny_role_ids"))
    staff_role = None
    if conf.get("staff_role_id"):
        staff_role = guild.get_role(conf["staff_role_id"])
    atc_role = guild.get_role(ATC_ROLE_ID) if ATC_ROLE_ID else None
    creator = guild.get_member(freq["atc_user_id"]) if freq.get("atc_user_id") else None

    voice = guild.get_channel(freq["voice_channel_id"])
    if voice and isinstance(voice, discord.VoiceChannel):
        try:
            overwrites = dict(voice.overwrites)
            default = overwrites.get(guild.default_role) or discord.PermissionOverwrite()
            if new_locked:
                default.connect = False
                overwrites[guild.default_role] = default
                for rid in deny_ids:
                    role = guild.get_role(rid)
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(
                            view_channel=False, connect=False
                        )
                if atc_role:
                    overwrites[atc_role] = discord.PermissionOverwrite(
                        view_channel=True, connect=True, speak=True
                    )
                if staff_role:
                    overwrites[staff_role] = discord.PermissionOverwrite(
                        view_channel=True, connect=True, speak=True
                    )
                if creator:
                    overwrites[creator] = discord.PermissionOverwrite(
                        view_channel=True, connect=True, speak=True, manage_channels=True
                    )
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True, connect=True, speak=True, manage_channels=True
                )
            else:
                default.connect = True
                overwrites[guild.default_role] = default
                for rid in deny_ids:
                    role = guild.get_role(rid)
                    if role and role in overwrites:
                        # Retirer le deny explicite au déverrouillage
                        try:
                            del overwrites[role]
                        except KeyError:
                            pass
            await voice.edit(overwrites=overwrites)
        except discord.HTTPException:
            pass

    # Salon texte : verrouillé → visible seulement créateur + staff (+ bot)
    text_ch = None
    if freq.get("text_channel_id"):
        text_ch = guild.get_channel(freq["text_channel_id"])
    if text_ch and isinstance(text_ch, discord.TextChannel):
        try:
            text_ow = dict(text_ch.overwrites)
            if new_locked:
                text_ow[guild.default_role] = discord.PermissionOverwrite(
                    view_channel=False
                )
                for rid in deny_ids:
                    role = guild.get_role(rid)
                    if role:
                        text_ow[role] = discord.PermissionOverwrite(view_channel=False)
                if staff_role:
                    text_ow[staff_role] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    )
                if creator:
                    text_ow[creator] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True,
                        manage_channels=True,
                    )
                text_ow[guild.me] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_channels=True,
                    manage_messages=True, read_message_history=True,
                )
                # Les ATC gardent l'accès texte si rôle ATC configuré
                if atc_role:
                    text_ow[atc_role] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    )
            else:
                # Restaurer une visibilité plus ouverte (default view True si catégorie le permet)
                text_ow[guild.default_role] = discord.PermissionOverwrite(
                    view_channel=True
                )
                for rid in deny_ids:
                    role = guild.get_role(rid)
                    if role and role in text_ow:
                        try:
                            del text_ow[role]
                        except KeyError:
                            pass
            await text_ch.edit(overwrites=text_ow)
        except discord.HTTPException:
            pass
    return freq


def build_admin_freq_embed(guild: discord.Guild, freqs: list[dict]) -> discord.Embed:
    """Embed du panel admin fréquences ouvertes."""
    embed = discord.Embed(
        title="🛠️ ADMIN — Fréquences ouvertes",
        description=(
            "Gère les fréquences **actives** : fermer ou verrouiller.\n"
            "Utilise les menus ci-dessous puis **Rafraîchir** pour mettre à jour la liste."
        ),
        color=discord.Color.dark_red(),
        timestamp=datetime.now(ZoneInfo(TIMEZONE)),
    )
    if not freqs:
        embed.add_field(
            name="État",
            value="_Aucune fréquence ouverte actuellement._",
            inline=False,
        )
    else:
        lines = []
        for f in freqs:
            lock = "🔒" if f.get("locked") else "🟢"
            icao = f.get("icao") or "—"
            pos = f.get("position") or "—"
            mhz = f.get("frequency_mhz") or "—"
            atc_id = f.get("atc_user_id")
            voice_id = f.get("voice_channel_id")
            lines.append(
                f"{lock} **#{f['id']}** `{icao}` **{pos}** `{mhz}` — {f.get('name', '—')}\n"
                f"  ATC <@{atc_id}> · <#{voice_id}>"
            )
        text = "\n".join(lines)
        if len(text) > 1000:
            text = text[:990] + "\n…"
        embed.add_field(
            name=f"📡 {len(freqs)} fréquence(s) active(s)",
            value=text,
            inline=False,
        )
    embed.set_footer(text="Réservé aux administrateurs et Gérants ATC")
    return embed


class FrequencyView(discord.ui.View):
    def __init__(self, freq_id: int):
        super().__init__(timeout=None)
        self.freq_id = freq_id
        labels = ["rename", "icao", "lock", "close"]
        for i, child in enumerate(self.children):
            if isinstance(child, discord.ui.Button) and i < len(labels):
                child.custom_id = f"freq_{labels[i]}_{freq_id}"

    async def _require_owner_atc(self, interaction: discord.Interaction) -> bool:
        """Seul l'ATC qui a ouvert la fréquence (ou un admin) peut utiliser les boutons."""
        if interaction.user.guild_permissions.administrator:
            return True
        if not _is_atc(interaction.user):
            await interaction.response.send_message(
                "🚫 Réservé à l'ATC qui a ouvert cette fréquence.", ephemeral=True
            )
            return False
        freq = await db.get_frequency(self.freq_id)
        if not freq:
            await interaction.response.send_message(
                "Fréquence introuvable.", ephemeral=True
            )
            return False
        owner_id = freq.get("atc_user_id")
        if owner_id and interaction.user.id != owner_id:
            await interaction.response.send_message(
                "🚫 Seul l'ATC qui a **ouvert** cette fréquence peut utiliser ces boutons.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Renommer", style=discord.ButtonStyle.primary, emoji="✏️")
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_owner_atc(interaction):
            return
        await interaction.response.send_modal(RenameFreqModal(self.freq_id, self))

    @discord.ui.button(label="ICAO", style=discord.ButtonStyle.primary, emoji="✈️")
    async def icao_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_owner_atc(interaction):
            return
        await interaction.response.send_modal(SetIcaoModal(self.freq_id, self))

    @discord.ui.button(label="Verrouiller", style=discord.ButtonStyle.secondary, emoji="🔒")
    async def lock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_owner_atc(interaction):
            return
        freq = await db.get_frequency(self.freq_id)
        if not freq or freq["status"] != "active":
            await interaction.response.send_message("Fréquence inactive.", ephemeral=True)
            return

        freq = await _toggle_lock_frequency(interaction.guild, freq)
        if not freq:
            await interaction.response.send_message("Fréquence inactive.", ephemeral=True)
            return
        new_locked = bool(freq.get("locked"))
        voice = interaction.guild.get_channel(freq["voice_channel_id"])
        button.label = "Déverrouiller" if new_locked else "Verrouiller"
        button.emoji = "🔓" if new_locked else "🔒"
        embed = _freq_embed(
            freq, voice if isinstance(voice, discord.VoiceChannel) else None
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger, emoji="🛑")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_owner_atc(interaction):
            return
        freq = await db.get_frequency(self.freq_id)
        if not freq:
            await interaction.response.send_message(
                "Fréquence introuvable.", ephemeral=True
            )
            return

        text_ch = None
        if freq.get("text_channel_id"):
            text_ch = interaction.guild.get_channel(freq["text_channel_id"])
        in_linked_text = (
            text_ch
            and isinstance(text_ch, discord.TextChannel)
            and interaction.channel_id == text_ch.id
        )

        # Ne pas supprimer le salon texte tout de suite si on y est
        text_id_backup = freq.get("text_channel_id")
        if in_linked_text:
            freq = dict(freq)
            freq["text_channel_id"] = None

        deleted_voice, _ = await _close_frequency_full(
            interaction.guild, interaction.user, freq
        )

        for child in self.children:
            child.disabled = True

        parts = ["Cette fréquence a été clôturée."]
        if deleted_voice:
            parts.append("Le salon **vocal** a été supprimé.")

        embed = discord.Embed(
            title=f"📡 Fréquence {freq['name']} — Fermée",
            color=discord.Color.dark_grey(),
            description="\n".join(parts),
        )

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.HTTPException:
            pass

        if in_linked_text and text_id_backup:
            try:
                import asyncio
                await asyncio.sleep(3)
                ch = interaction.guild.get_channel(text_id_backup)
                if ch and isinstance(ch, discord.TextChannel):
                    await ch.delete(reason=f"Fréquence fermée par {interaction.user}")
            except discord.HTTPException:
                pass
        elif text_id_backup and not in_linked_text:
            # déjà géré dans _close_frequency_full si text_channel_id était présent
            pass


# ---------- Panel admin fréquences (ouvertes / fermer / verrouiller) ----------

async def refresh_admin_freq_panel(bot: commands.Bot, guild_id: int):
    """Met à jour le message du panel admin fréquences s'il est enregistré."""
    conf = await db.get_guild_config(guild_id) or {}
    ch_id = conf.get("freq_admin_panel_channel_id")
    msg_id = conf.get("freq_admin_panel_message_id")
    if not ch_id or not msg_id:
        return
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    channel = guild.get_channel(ch_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        msg = await channel.fetch_message(msg_id)
    except (discord.NotFound, discord.HTTPException):
        return
    freqs = await db.list_active_frequencies(guild_id)
    embed = build_admin_freq_embed(guild, freqs)
    view = AdminFreqPanelView(freqs)
    try:
        await msg.edit(embed=embed, view=view)
    except discord.HTTPException as e:
        log.warning("Refresh panel admin freq échoué: %s", e)


class AdminCloseFreqSelect(discord.ui.Select):
    def __init__(self, freqs: list[dict]):
        options = []
        for f in freqs[:25]:
            lock = "🔒" if f.get("locked") else "🟢"
            label = f"{lock} #{f['id']} {f.get('icao') or ''} {f.get('position') or f.get('name') or ''}".strip()
            desc = f"{f.get('frequency_mhz') or '—'} MHz · ATC {f.get('atc_user_id')}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(f["id"]),
                    description=desc[:100],
                )
            )
        if not options:
            options = [
                discord.SelectOption(
                    label="Aucune fréquence ouverte",
                    value="0",
                    description="Rien à fermer",
                )
            ]
        super().__init__(
            placeholder="🛑 Fermer une fréquence…",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="freq_admin:close",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not await _is_freq_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux administrateurs et Gérants ATC.", ephemeral=True
            )
            return
        if self.values[0] == "0":
            await interaction.response.send_message(
                "Aucune fréquence à fermer.", ephemeral=True
            )
            return
        freq_id = int(self.values[0])
        freq = await db.get_frequency(freq_id)
        if not freq or freq.get("status") != "active":
            await interaction.response.send_message(
                "❌ Fréquence introuvable ou déjà fermée.", ephemeral=True
            )
            await refresh_admin_freq_panel(interaction.client, interaction.guild_id)
            return
        name = freq.get("name") or f"#{freq_id}"
        deleted_voice, deleted_text = await _close_frequency_full(
            interaction.guild, interaction.user, freq
        )
        parts = [f"✅ **{name}** fermée."]
        if deleted_voice:
            parts.append("Vocal supprimé.")
        if deleted_text:
            parts.append("Salon texte supprimé.")
        await interaction.response.send_message(" ".join(parts), ephemeral=True)
        await refresh_admin_freq_panel(interaction.client, interaction.guild_id)


class AdminLockFreqSelect(discord.ui.Select):
    def __init__(self, freqs: list[dict]):
        options = []
        for f in freqs[:25]:
            lock = "🔒" if f.get("locked") else "🟢"
            action = "Déverrouiller" if f.get("locked") else "Verrouiller"
            label = f"{lock} #{f['id']} {f.get('icao') or ''} {f.get('position') or f.get('name') or ''}".strip()
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(f["id"]),
                    description=f"{action} · {f.get('frequency_mhz') or '—'} MHz"[:100],
                )
            )
        if not options:
            options = [
                discord.SelectOption(
                    label="Aucune fréquence ouverte",
                    value="0",
                    description="Rien à verrouiller",
                )
            ]
        super().__init__(
            placeholder="🔒 Verrouiller / déverrouiller…",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="freq_admin:lock",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not await _is_freq_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux administrateurs et Gérants ATC.", ephemeral=True
            )
            return
        if self.values[0] == "0":
            await interaction.response.send_message(
                "Aucune fréquence active.", ephemeral=True
            )
            return
        freq_id = int(self.values[0])
        freq = await db.get_frequency(freq_id)
        if not freq or freq.get("status") != "active":
            await interaction.response.send_message(
                "❌ Fréquence introuvable ou inactive.", ephemeral=True
            )
            await refresh_admin_freq_panel(interaction.client, interaction.guild_id)
            return
        updated = await _toggle_lock_frequency(interaction.guild, freq)
        if not updated:
            await interaction.response.send_message(
                "❌ Impossible de modifier le verrouillage.", ephemeral=True
            )
            return
        state = "🔒 verrouillée" if updated.get("locked") else "🟢 déverrouillée"
        await interaction.response.send_message(
            f"✅ **{updated.get('name', freq_id)}** est maintenant {state}.",
            ephemeral=True,
        )
        await refresh_admin_freq_panel(interaction.client, interaction.guild_id)


class AdminFreqPanelView(discord.ui.View):
    """Panel permanent admin : liste + fermer / verrouiller / rafraîchir."""

    def __init__(self, freqs: list[dict] | None = None):
        super().__init__(timeout=None)
        freqs = freqs or []
        self.add_item(AdminCloseFreqSelect(freqs))
        self.add_item(AdminLockFreqSelect(freqs))

    @discord.ui.button(
        label="Rafraîchir",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="freq_admin:refresh",
        row=2,
    )
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _is_freq_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux administrateurs et Gérants ATC.", ephemeral=True
            )
            return
        freqs = await db.list_active_frequencies(interaction.guild_id)
        embed = build_admin_freq_embed(interaction.guild, freqs)
        view = AdminFreqPanelView(freqs)
        await interaction.response.edit_message(embed=embed, view=view)


PANEL_DESCRIPTION = (
    "Ce salon est dédié à l'ouverture et à la fermeture des fréquences.\n\n"
    "**Priorité d'ouverture**\n"
    "APP → TWR → GND\n\n"
    "Le Centre peut prendre en charge toute position non occupée située dans sa zone.\n\n"
    "**Ouverture**\n"
    "• **Ouvrir une fréquence** — la fréquence est attribuée automatiquement selon l'ICAO et la position\n"
    "• **Fréquence manuelle** — à utiliser si l'aéroport / la position n'est pas dans la base (ou pour une fréquence temporaire)\n"
    "• **Pré-ouverture** — annonce min. 1h à l'avance (le jour même) ; les salons vocal + texte sont créés **automatiquement à l'heure indiquée**\n"
    "• Pas besoin de cliquer « Ouvrir » après une pré-ouverture planifiée\n\n"
    "**Fermeture**\n"
    "• Vous pouvez prévoir une fermeture (~10 min avant)\n"
    "• Puis effectuer la fermeture une fois hors ligne\n\n"
    "**Règles**\n"
    "• Minimum 30 min d'ouverture (si aucun trafic)\n"
    "• Minimum 1h si trafic présent\n"
    "• Évitez les ouvertures/fermetures répétées (les annonces notifient les membres)\n\n"
    "Tout abus du système pourra entraîner des sanctions."
)


class FrequencyPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot | None = None):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Ouvrir une fréquence",
        style=discord.ButtonStyle.success,
        emoji="🟢",
        custom_id="freq_panel_open",
        row=0,
    )
    async def open_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_atc(interaction.user):
            await interaction.response.send_message("🚫 Réservé aux ATC.", ephemeral=True)
            return
        existing = await db.get_active_frequency_for_atc(
            interaction.guild_id, interaction.user.id
        )
        if existing:
            await interaction.response.send_message(
                f"Tu as déjà une fréquence ouverte : **{existing['name']}** "
                f"(<#{existing['voice_channel_id']}>).",
                ephemeral=True,
            )
            return
        bot = self.bot or interaction.client
        await interaction.response.send_message(
            "🌐 **Choisis la langue de la fréquence :**",
            view=LanguageSelectView(bot, "open"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Fréquence manuelle",
        style=discord.ButtonStyle.secondary,
        emoji="✏️",
        custom_id="freq_panel_manual",
        row=0,
    )
    async def manual_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_atc(interaction.user):
            await interaction.response.send_message("🚫 Réservé aux ATC.", ephemeral=True)
            return
        existing = await db.get_active_frequency_for_atc(
            interaction.guild_id, interaction.user.id
        )
        if existing:
            await interaction.response.send_message(
                f"Tu as déjà une fréquence ouverte : **{existing['name']}** "
                f"(<#{existing['voice_channel_id']}>).",
                ephemeral=True,
            )
            return
        bot = self.bot or interaction.client
        await interaction.response.send_message(
            "🌐 **Choisis la langue de la fréquence :**",
            view=LanguageSelectView(bot, "manual"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Pré-ouverture",
        style=discord.ButtonStyle.primary,
        emoji="🟡",
        custom_id="freq_panel_preopen",
        row=1,
    )
    async def preopen_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_atc(interaction.user):
            await interaction.response.send_message("🚫 Réservé aux ATC.", ephemeral=True)
            return
        bot = self.bot or interaction.client
        await interaction.response.send_message(
            "🌐 **Choisis la langue de la fréquence :**",
            view=LanguageSelectView(bot, "preopen"),
            ephemeral=True,
        )

class Frequencies(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(FrequencyPanelView(self.bot))
        # Panel admin (options rechargées au Rafraîchir après redémarrage)
        self.bot.add_view(AdminFreqPanelView([]))
        for freq in await db.list_active_frequencies():
            self.bot.add_view(FrequencyView(freq["id"]))
        if not self.process_preopens.is_running():
            self.process_preopens.start()

    def cog_unload(self):
        self.process_preopens.cancel()

    @tasks.loop(seconds=30)
    async def process_preopens(self):
        """Crée les salons des pré-ouvertures dont l'heure est atteinte."""
        from datetime import timezone as tz_utc

        now_iso = datetime.now(tz_utc.utc).isoformat()
        due = await db.list_due_preopen_schedules(now_iso)
        for sched in due:
            await self._execute_preopen(sched)

    @process_preopens.before_loop
    async def before_process_preopens(self):
        await self.bot.wait_until_ready()

    async def _execute_preopen(self, sched: dict):
        schedule_id = sched["id"]
        guild = self.bot.get_guild(sched["guild_id"])
        if not guild:
            await db.mark_preopen_done(schedule_id)
            return

        member = guild.get_member(sched["atc_user_id"])
        if not member:
            try:
                member = await guild.fetch_member(sched["atc_user_id"])
            except discord.HTTPException:
                member = None
        if not member:
            log.warning("Pré-ouverture %s : ATC introuvable, annulation", schedule_id)
            await db.cancel_preopen_schedule(schedule_id)
            return

        existing = await db.get_active_frequency_for_atc(guild.id, member.id)
        if existing:
            log.info(
                "Pré-ouverture %s : ATC a déjà une fréquence active, skip", schedule_id
            )
            await db.mark_preopen_done(schedule_id)
            try:
                await member.send(
                    f"⚠️ Ta pré-ouverture **{sched.get('icao')} {sched.get('position')}** "
                    f"prévue à **{sched.get('hour_str')}** n'a pas créé de nouveaux salons : "
                    f"tu as déjà **{existing['name']}** ouverte."
                )
            except discord.HTTPException:
                pass
            return

        position = sched["position"]
        location = sched["location"]
        freq_number = sched["frequency_mhz"]
        langs = sched.get("languages") or "🇫🇷 FR"
        icao = sched.get("icao") or _extract_icao(location) or location.upper()[:4]

        voice, text_ch, freq_id = await _create_frequency_core(
            self.bot,
            guild,
            member,
            position=position,
            location=location,
            freq_number=freq_number,
            langs=langs,
            mode="auto",
            panel_channel=None,
        )
        if not voice or not freq_id:
            log.warning("Pré-ouverture %s : échec création salons", schedule_id)
            # Ne pas marquer done pour retenter au prochain cycle ? Ou cancel.
            # On marque done pour éviter une boucle d'erreurs.
            await db.mark_preopen_done(schedule_id)
            try:
                await member.send(
                    f"❌ Impossible de créer les salons pour ta pré-ouverture "
                    f"**{icao} {position}**. Réessaie via le panel."
                )
            except discord.HTTPException:
                pass
            return

        # Annonce d'ouverture effective (les salons existent maintenant)
        ann = _embed_open(icao, freq_number, position, langs, member)
        await _send_announce(guild, ann)
        await _log_freq(
            guild,
            action="open",
            user=member,
            icao=icao,
            position=position,
            frequency=freq_number,
            mode="scheduled",
            extra=(
                f"Pré-ouverture auto · Vocal : {voice.mention}"
                + (f" · Texte : {text_ch.mention}" if text_ch else "")
            ),
        )
        await db.mark_preopen_done(schedule_id)

        display = f"{location} {position} {freq_number}".strip()
        try:
            await member.send(
                f"✅ Ta pré-ouverture **{display}** est active.\n"
                f"Vocal : {voice.mention}"
                + (f"\nTexte : {text_ch.mention}" if text_ch else "")
            )
        except discord.HTTPException:
            pass

        log.info(
            "Pré-ouverture %s exécutée : %s → vocal %s",
            schedule_id,
            display,
            voice.id,
        )

    @app_commands.command(
        name="freq-panel",
        description="Publier le panneau COMMANDES ATC (ouverture / fermeture)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def freq_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="COMMANDES ATC",
            description=PANEL_DESCRIPTION,
            color=discord.Color.dark_blue(),
        )
        await interaction.channel.send(
            embed=embed, view=FrequencyPanelView(self.bot)
        )
        await interaction.response.send_message("✅ Panneau publié.", ephemeral=True)

    @app_commands.command(
        name="freq-admin-panel",
        description="Publier le panneau ADMIN des fréquences ouvertes (fermer / verrouiller)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def freq_admin_panel(self, interaction: discord.Interaction):
        freqs = await db.list_active_frequencies(interaction.guild_id)
        embed = build_admin_freq_embed(interaction.guild, freqs)
        view = AdminFreqPanelView(freqs)
        msg = await interaction.channel.send(embed=embed, view=view)
        await db.set_freq_admin_panel(interaction.guild_id, interaction.channel_id, msg.id)
        await interaction.response.send_message(
            "✅ Panel admin fréquences publié.\n"
            "Les admins et Gérants ATC peuvent fermer ou verrouiller les fréquences ouvertes.",
            ephemeral=True,
        )

    @app_commands.command(
        name="freq-config-categorie",
        description="Catégorie où créer les salons VOCAUX de fréquences",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def freq_config_category(
        self, interaction: discord.Interaction, categorie: discord.CategoryChannel
    ):
        await db.set_freq_category(interaction.guild_id, categorie.id)
        await interaction.response.send_message(
            f"✅ Catégorie salons **vocaux** fréquences : **{categorie.name}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="freq-config-annonces",
        description="Salon où poster les annonces d'ouverture / fermeture",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def freq_config_annonces(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        await db.set_freq_announce_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(
            f"✅ Salon annonces fréquences : {canal.mention}", ephemeral=True
        )

    @app_commands.command(
        name="freq-config-role",
        description="Rôle à mentionner dans les annonces de fréquences",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def freq_config_role(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await db.set_freq_ping_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle ping annonces : {role.mention}", ephemeral=True
        )

    @app_commands.command(
        name="freq-config-logs",
        description="Salon de logs des actions fréquences (ouvertures, manuels, fermetures…)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def freq_config_logs(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        await db.set_freq_log_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(
            f"✅ Salon logs fréquences : {canal.mention}", ephemeral=True
        )

    @app_commands.command(
        name="freq-config-categorie-texte",
        description="Catégorie où créer les salons TEXTE (panel) des fréquences",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def freq_config_text_category(
        self, interaction: discord.Interaction, categorie: discord.CategoryChannel
    ):
        await db.set_freq_text_category(interaction.guild_id, categorie.id)
        await interaction.response.send_message(
            f"✅ Catégorie salons **texte** fréquences : **{categorie.name}**.\n"
            f"Les prochaines ouvertures y placeront le panel.\n"
            f"Utilise `/freq-deplacer-texte` pour y déplacer tous les salons texte déjà ouverts.",
            ephemeral=True,
        )

    @app_commands.command(
        name="freq-deplacer-texte",
        description="Déplacer TOUS les salons texte (panel) des fréquences actives vers une catégorie",
    )
    @app_commands.describe(
        categorie="Catégorie de destination (enregistrée aussi pour les prochaines ouvertures)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def freq_deplacer_texte(
        self,
        interaction: discord.Interaction,
        categorie: discord.CategoryChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        await db.set_freq_text_category(interaction.guild_id, categorie.id)

        freqs = await db.list_active_frequencies(interaction.guild_id)
        moved = 0
        failed = 0
        already = 0
        for f in freqs:
            tid = f.get("text_channel_id")
            if not tid:
                continue
            ch = interaction.guild.get_channel(tid)
            if not isinstance(ch, discord.TextChannel):
                failed += 1
                continue
            if ch.category_id == categorie.id:
                already += 1
                continue
            try:
                await ch.edit(
                    category=categorie,
                    reason=f"Déplacement massif panels fréquences par {interaction.user}",
                )
                moved += 1
            except discord.HTTPException:
                failed += 1

        await interaction.followup.send(
            f"✅ Catégorie texte fréquences : **{categorie.name}**\n"
            f"• Déplacés : **{moved}**\n"
            f"• Déjà au bon endroit : **{already}**\n"
            f"• Échecs / introuvables : **{failed}**\n\n"
            f"Les **prochaines** ouvertures créeront le salon texte directement dans cette catégorie.",
            ephemeral=True,
        )

    @app_commands.command(
        name="freq-liste",
        description="Lister les fréquences actives",
    )
    async def freq_liste(self, interaction: discord.Interaction):
        freqs = await db.list_active_frequencies(interaction.guild_id)
        if not freqs:
            await interaction.response.send_message(
                "Aucune fréquence active.", ephemeral=True
            )
            return
        lines = []
        for f in freqs:
            lock = "🔒" if f.get("locked") else "🟢"
            lines.append(
                f"{lock} **{f['name']}** — <#{f['voice_channel_id']}> · ATC <@{f['atc_user_id']}>"
            )
        embed = discord.Embed(
            title="📡 Fréquences actives",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Frequencies(bot))