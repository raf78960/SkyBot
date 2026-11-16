"""
Dashboard de configuration permanent du bot SkyCommunity.

Salon dédié (#config-bot) avec embed permanent + bouton Rafraîchir
+ menus pour configurer rôles / salons / catégories sans commandes éparpillées.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable, Awaitable

import discord
from discord import app_commands
from discord.ext import commands

import database as db

# Couleur SkyCommunity (bleu ciel, alignée planning ATC)
SKY_COLOR = 0x1E90FF
SKYCOMMUNITY_LOGO_URL = os.getenv("SKYCOMMUNITY_LOGO_URL", "")

# ---------- Helpers affichage ----------

def _mention_role(guild: discord.Guild, role_id) -> str:
    if not role_id:
        return "❌ *non configuré*"
    ids = db.parse_id_list(role_id)
    if not ids:
        return "❌ *non configuré*"
    parts = []
    for rid in ids:
        role = guild.get_role(rid)
        parts.append(role.mention if role else f"`{rid}` *(introuvable)*")
    return " · ".join(parts)


def _mention_channel(guild: discord.Guild, channel_id) -> str:
    if not channel_id:
        return "❌ *non configuré*"
    try:
        cid = int(channel_id)
    except (TypeError, ValueError):
        return "❌ *non configuré*"
    ch = guild.get_channel(cid)
    if ch is None:
        return f"`{cid}` *(introuvable)*"
    return ch.mention


def _ok(value) -> str:
    if value is None or value == "" or value == 0:
        return "❌"
    if isinstance(value, str) and not value.strip():
        return "❌"
    return "✅"


async def build_config_embed(guild: discord.Guild) -> discord.Embed:
    conf = await db.get_guild_config(guild.id) or {}

    embed = discord.Embed(
        title="⚙️ CONFIGURATION SKYCOMMUNITY",
        description=(
            "Panneau de configuration central du bot.\n"
            "Choisis une **section** ci-dessous pour modifier un rôle, un salon ou une catégorie.\n"
            "Utilise **Rafraîchir** pour mettre à jour l’affichage."
        ),
        color=SKY_COLOR,
        timestamp=datetime.now(timezone.utc),
    )

    # --- Général ---
    gen_lines = [
        f"{_ok(conf.get('formateur_role_id'))} **Rôle(s) formateur** : {_mention_role(guild, conf.get('formateur_role_id'))}",
        f"{_ok(conf.get('staff_role_id'))} **Rôle staff** : {_mention_role(guild, conf.get('staff_role_id'))}",
        f"{_ok(conf.get('announcement_channel_id'))} **Canal annonces sessions** : {_mention_channel(guild, conf.get('announcement_channel_id'))}",
    ]
    embed.add_field(name="📌 Général", value="\n".join(gen_lines), inline=False)

    # --- Tickets ---
    ticket_lines = [
        f"{_ok(conf.get('ticket_access_category_id'))} **Catégorie Accès** : {_mention_channel(guild, conf.get('ticket_access_category_id'))}",
        f"{_ok(conf.get('ticket_support_category_id'))} **Catégorie Support** : {_mention_channel(guild, conf.get('ticket_support_category_id'))}",
        f"{_ok(conf.get('ticket_ping_role_id'))} **Rôle mention tickets (Accès)** : {_mention_role(guild, conf.get('ticket_ping_role_id'))}",
        f"{_ok(conf.get('ticket_support_ping_role_id'))} **Rôle mention Support** : {_mention_role(guild, conf.get('ticket_support_ping_role_id'))}",
        f"{_ok(conf.get('ticket_log_channel_id'))} **Logs tickets (général)** : {_mention_channel(guild, conf.get('ticket_log_channel_id'))}",
        f"{_ok(conf.get('ticket_access_log_channel_id'))} **Logs Accès** : {_mention_channel(guild, conf.get('ticket_access_log_channel_id'))}",
        f"{_ok(conf.get('ticket_support_log_channel_id'))} **Logs Support** : {_mention_channel(guild, conf.get('ticket_support_log_channel_id'))}",
        f"{_ok(conf.get('disponibilites_channel_id'))} **Canal disponibilités** : {_mention_channel(guild, conf.get('disponibilites_channel_id'))}",
    ]
    embed.add_field(name="🎫 Tickets", value="\n".join(ticket_lines), inline=False)

    # --- Fréquences ---
    freq_lines = [
        f"{_ok(conf.get('freq_category_id'))} **Catégorie fréquences** : {_mention_channel(guild, conf.get('freq_category_id'))}",
        f"{_ok(conf.get('freq_announce_channel_id'))} **Canal annonces freq** : {_mention_channel(guild, conf.get('freq_announce_channel_id'))}",
        f"{_ok(conf.get('freq_ping_role_id'))} **Rôle ping freq** : {_mention_role(guild, conf.get('freq_ping_role_id'))}",
        f"{_ok(conf.get('freq_log_channel_id'))} **Logs fréquences** : {_mention_channel(guild, conf.get('freq_log_channel_id'))}",
        f"{_ok(conf.get('gerant_atc_role_id'))} **Rôle Gérant ATC** : {_mention_role(guild, conf.get('gerant_atc_role_id'))}",
        f"{_ok(conf.get('freq_lock_deny_role_ids'))} **Rôles bloqués au verrouillage** : {_mention_role(guild, conf.get('freq_lock_deny_role_ids'))}",
        f"{_ok(conf.get('atc_planning_mod_channel_id'))} **Salon validation modifs planning** : {_mention_channel(guild, conf.get('atc_planning_mod_channel_id'))}",
    ]
    embed.add_field(name="📡 Fréquences ATC", value="\n".join(freq_lines), inline=False)

    # --- Plans de vol ---
    fp_lines = [
        f"{_ok(conf.get('flightplan_channel_id'))} **Canal plans de vol** : {_mention_channel(guild, conf.get('flightplan_channel_id'))}",
        f"{_ok(conf.get('flightplan_log_channel_id'))} **Logs plans de vol** : {_mention_channel(guild, conf.get('flightplan_log_channel_id'))}",
    ]
    embed.add_field(name="🗺️ Plans de vol", value="\n".join(fp_lines), inline=False)

    # --- Sessions ---
    sess_lines = [
        f"{_ok(conf.get('session_ping_avion_role_id'))} **Ping rôle avion** : {_mention_role(guild, conf.get('session_ping_avion_role_id'))}",
        f"{_ok(conf.get('session_ping_pilote_role_id'))} **Ping rôle pilote** : {_mention_role(guild, conf.get('session_ping_pilote_role_id'))}",
        f"{_ok(conf.get('session_ping_atc_role_id'))} **Ping rôle ATC** : {_mention_role(guild, conf.get('session_ping_atc_role_id'))}",
        f"{_ok(conf.get('session_ping_site_atc_role_id'))} **Ping rôle Site ATC** : {_mention_role(guild, conf.get('session_ping_site_atc_role_id'))}",
        f"{_ok(conf.get('session_ping_site_pilote_role_id'))} **Ping rôle Site pilote** : {_mention_role(guild, conf.get('session_ping_site_pilote_role_id'))}",
    ]
    embed.add_field(name="🎓 Sessions / Formations", value="\n".join(sess_lines), inline=False)

    # --- Compagnie ---
    company_lines = [
        f"{_ok(conf.get('pilot_role_id'))} **Rôle pilotes compagnie** : {_mention_role(guild, conf.get('pilot_role_id'))}",
        f"{_ok(conf.get('callsign_manager_role_id'))} **Rôle gestion callsigns** : {_mention_role(guild, conf.get('callsign_manager_role_id'))}",
    ]
    embed.add_field(name="✈️ Compagnie", value="\n".join(company_lines), inline=False)

    # --- Absences ---
    abs_lines = [
        f"{_ok(conf.get('absence_role_ids'))} **Rôles autorisés (max 8)** : {_mention_role(guild, conf.get('absence_role_ids'))}",
        f"{_ok(conf.get('absence_temp_role_id'))} **Rôle temporaire Absent** : {_mention_role(guild, conf.get('absence_temp_role_id'))}",
        f"{_ok(conf.get('absence_log_channel_id'))} **Salon logs / annonces absences** : {_mention_channel(guild, conf.get('absence_log_channel_id'))}",
        f"{_ok(conf.get('absence_ping_role_ids'))} **Rôles mentionnés (nouvelle absence)** : {_mention_role(guild, conf.get('absence_ping_role_ids'))}",
        f"{_ok(conf.get('absence_panel_channel_id'))} **Salon panel absences** : {_mention_channel(guild, conf.get('absence_panel_channel_id'))}",
    ]
    embed.add_field(name="🏖️ Absences", value="\n".join(abs_lines), inline=False)

    missing = sum(
        1
        for k in (
            "formateur_role_id",
            "staff_role_id",
            "announcement_channel_id",
            "ticket_access_category_id",
            "ticket_support_category_id",
            "freq_category_id",
            "flightplan_channel_id",
        )
        if not conf.get(k)
    )
    footer = f"SkyCommunity • Config bot"
    if missing:
        footer += f" • {missing} paramètre(s) important(s) manquant(s)"
    embed.set_footer(text=footer)

    if SKYCOMMUNITY_LOGO_URL:
        embed.set_thumbnail(url=SKYCOMMUNITY_LOGO_URL)
        embed.set_image(url=SKYCOMMUNITY_LOGO_URL)

    return embed


async def _refresh_panel_message(guild: discord.Guild) -> bool:
    """Met à jour le message permanent s’il existe. Retourne True si ok."""
    conf = await db.get_guild_config(guild.id) or {}
    ch_id = conf.get("config_panel_channel_id")
    msg_id = conf.get("config_panel_message_id")
    if not ch_id or not msg_id:
        return False
    channel = guild.get_channel(int(ch_id))
    if channel is None or not isinstance(channel, discord.TextChannel):
        return False
    try:
        msg = await channel.fetch_message(int(msg_id))
    except (discord.NotFound, discord.HTTPException):
        return False
    embed = await build_config_embed(guild)
    try:
        await msg.edit(embed=embed, view=ConfigPanelView())
        return True
    except discord.HTTPException:
        return False


def _is_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_guild


# ---------- Vues de configuration (éphémères) ----------

class _RoleConfigView(discord.ui.View):
    """Sélecteur de rôle pour un champ donné."""

    def __init__(
        self,
        field_label: str,
        setter: Callable[[int, int], Awaitable[None]],
        multi: bool = False,
        max_roles: int = 5,
    ):
        super().__init__(timeout=180)
        self.field_label = field_label
        self.setter = setter
        self.multi = multi

        select = discord.ui.RoleSelect(
            placeholder=f"Choisir : {field_label}",
            min_values=1,
            max_values=max(1, min(25, max_roles if multi else 1)),
            custom_id="cfg_role_select",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux administrateurs.", ephemeral=True
            )
            return
        select: discord.ui.RoleSelect = self.children[0]  # type: ignore
        roles = select.values
        if self.multi:
            await self.setter(interaction.guild_id, [r.id for r in roles])
            mentions = ", ".join(r.mention for r in roles)
        else:
            await self.setter(interaction.guild_id, roles[0].id)
            mentions = roles[0].mention
        await interaction.response.send_message(
            f"✅ **{self.field_label}** → {mentions}", ephemeral=True
        )
        await _refresh_panel_message(interaction.guild)


class _ChannelConfigView(discord.ui.View):
    """Sélecteur de salon / catégorie pour un champ donné."""

    def __init__(
        self,
        field_label: str,
        setter: Callable[[int, int], Awaitable[None]],
        channel_types: list[discord.ChannelType] | None = None,
    ):
        super().__init__(timeout=180)
        self.field_label = field_label
        self.setter = setter
        types = channel_types or [
            discord.ChannelType.text,
            discord.ChannelType.news,
        ]
        select = discord.ui.ChannelSelect(
            placeholder=f"Choisir : {field_label}",
            channel_types=types,
            min_values=1,
            max_values=1,
            custom_id="cfg_channel_select",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux administrateurs.", ephemeral=True
            )
            return
        select: discord.ui.ChannelSelect = self.children[0]  # type: ignore
        ch = select.values[0]
        await self.setter(interaction.guild_id, ch.id)
        await interaction.response.send_message(
            f"✅ **{self.field_label}** → {ch.mention}", ephemeral=True
        )
        await _refresh_panel_message(interaction.guild)


# Mapping section → options (label, type, setter, extra)
# type: "role" | "role_multi" | "channel" | "category"

SECTION_OPTIONS: dict[str, list[tuple]] = {
    "general": [
        ("Rôle(s) formateur", "role_multi", db.set_formateur_role, None),
        ("Rôle staff", "role", db.set_staff_role, None),
        ("Canal annonces sessions", "channel", db.set_announcement_channel, None),
    ],
    "tickets": [
        ("Catégorie Accès", "category", db.set_ticket_access_category, None),
        ("Catégorie Support", "category", db.set_ticket_support_category, None),
        ("Rôle mention tickets (Accès)", "role", db.set_ticket_ping_role, None),
        ("Rôle mention Support", "role", db.set_ticket_support_ping_role, None),
        ("Logs tickets (général)", "channel", db.set_ticket_log_channel, None),
        ("Logs Accès", "channel", db.set_ticket_access_log_channel, None),
        ("Logs Support", "channel", db.set_ticket_support_log_channel, None),
        ("Canal disponibilités", "channel", db.set_disponibilites_channel, None),
    ],
    "frequencies": [
        ("Catégorie fréquences", "category", db.set_freq_category, None),
        ("Canal annonces freq", "channel", db.set_freq_announce_channel, None),
        ("Rôle ping freq", "role", db.set_freq_ping_role, None),
        ("Logs fréquences", "channel", db.set_freq_log_channel, None),
        ("Rôle(s) Gérant ATC", "role_multi", db.set_gerant_atc_role, None),
        ("Rôles bloqués au verrouillage", "role_multi", db.set_freq_lock_deny_roles, None),
        ("Salon validation modifs planning", "channel", db.set_atc_planning_mod_channel, None),
    ],
    "flightplans": [
        ("Canal plans de vol", "channel", db.set_flightplan_channel, None),
        ("Logs plans de vol", "channel", db.set_flightplan_log_channel, None),
    ],
    "sessions": [
        ("Ping rôle avion", "role", db.set_session_ping_avion_role, None),
        ("Ping rôle pilote", "role", db.set_session_ping_pilote_role, None),
        ("Ping rôle ATC", "role", db.set_session_ping_atc_role, None),
        ("Ping rôle Site ATC", "role", db.set_session_ping_site_atc_role, None),
        ("Ping rôle Site pilote", "role", db.set_session_ping_site_pilote_role, None),
    ],
    "company": [
        ("Rôle pilotes compagnie", "role", db.set_pilot_role, None),
        ("Rôle gestion callsigns", "role", db.set_callsign_manager_role, None),
    ],
    "absences": [
        ("Rôles autorisés absences (max 8)", "role_multi8", db.set_absence_roles, None),
        ("Rôle temporaire Absent", "role", db.set_absence_temp_role, None),
        ("Salon logs / annonces absences", "channel", db.set_absence_log_channel, None),
        ("Rôles mentionnés (nouvelle absence)", "role_multi", db.set_absence_ping_roles, None),
    ],
}

SECTION_LABELS = {
    "general": "📌 Général",
    "tickets": "🎫 Tickets",
    "frequencies": "📡 Fréquences ATC",
    "flightplans": "🗺️ Plans de vol",
    "sessions": "🎓 Sessions / Formations",
    "company": "✈️ Compagnie",
    "absences": "🏖️ Absences",
}


class SectionFieldSelect(discord.ui.Select):
    """Choix du champ à configurer dans une section."""

    def __init__(self, section_key: str):
        self.section_key = section_key
        options = []
        for i, (label, kind, _setter, _) in enumerate(SECTION_OPTIONS[section_key]):
            emoji = "👤" if kind.startswith("role") else ("📁" if kind == "category" else "#️⃣")
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(i),
                    emoji=emoji,
                )
            )
        super().__init__(
            placeholder="Quel paramètre modifier ?",
            options=options,
            min_values=1,
            max_values=1,
            custom_id=f"cfg_field_{section_key}",
        )

    async def callback(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux administrateurs.", ephemeral=True
            )
            return
        idx = int(self.values[0])
        label, kind, setter, _ = SECTION_OPTIONS[self.section_key][idx]
        if kind == "role":
            view = _RoleConfigView(label, setter, multi=False)
        elif kind == "role_multi":
            view = _RoleConfigView(label, setter, multi=True, max_roles=25)
        elif kind == "role_multi8":
            view = _RoleConfigView(label, setter, multi=True, max_roles=8)
        elif kind == "category":
            view = _ChannelConfigView(
                label,
                setter,
                channel_types=[discord.ChannelType.category],
            )
        else:
            view = _ChannelConfigView(label, setter)
        await interaction.response.send_message(
            f"Sélectionne la valeur pour **{label}** :",
            view=view,
            ephemeral=True,
        )


class SectionPickView(discord.ui.View):
    def __init__(self, section_key: str):
        super().__init__(timeout=180)
        self.add_item(SectionFieldSelect(section_key))


class ConfigPanelView(discord.ui.View):
    """Vue permanente sous le panneau de config."""

    def __init__(self):
        super().__init__(timeout=None)

        section_select = discord.ui.Select(
            placeholder="Configurer une section…",
            custom_id="config_dashboard:section",
            options=[
                discord.SelectOption(
                    label="Général",
                    value="general",
                    emoji="📌",
                    description="Formateur, staff, annonces",
                ),
                discord.SelectOption(
                    label="Tickets",
                    value="tickets",
                    emoji="🎫",
                    description="Catégories, logs, dispos",
                ),
                discord.SelectOption(
                    label="Fréquences ATC",
                    value="frequencies",
                    emoji="📡",
                    description="Catégorie, annonces, logs",
                ),
                discord.SelectOption(
                    label="Plans de vol",
                    value="flightplans",
                    emoji="🗺️",
                    description="Canal + logs",
                ),
                discord.SelectOption(
                    label="Sessions / Formations",
                    value="sessions",
                    emoji="🎓",
                    description="Rôles de ping",
                ),
                discord.SelectOption(
                    label="Absences",
                    value="absences",
                    emoji="🏖️",
                    description="Rôles, rôle Absent, logs",
                ),
                discord.SelectOption(
                    label="Compagnie",
                    value="company",
                    emoji="✈️",
                    description="Rôle pilotes",
                ),
            ],
            min_values=1,
            max_values=1,
        )
        section_select.callback = self._on_section
        self.add_item(section_select)

        refresh = discord.ui.Button(
            label="Rafraîchir",
            style=discord.ButtonStyle.secondary,
            emoji="🔄",
            custom_id="config_dashboard:refresh",
        )
        refresh.callback = self._on_refresh
        self.add_item(refresh)

    async def _on_section(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux administrateurs.", ephemeral=True
            )
            return
        select: discord.ui.Select = self.children[0]  # type: ignore
        key = select.values[0]
        title = SECTION_LABELS.get(key, key)
        await interaction.response.send_message(
            f"**{title}** — choisis le paramètre à modifier :",
            view=SectionPickView(key),
            ephemeral=True,
        )

    async def _on_refresh(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux administrateurs.", ephemeral=True
            )
            return
        embed = await build_config_embed(interaction.guild)
        try:
            await interaction.response.edit_message(embed=embed, view=ConfigPanelView())
        except discord.HTTPException:
            # Message peut ne plus être éditable depuis cette interaction
            ok = await _refresh_panel_message(interaction.guild)
            if ok:
                await interaction.response.send_message(
                    "✅ Panneau rafraîchi.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "⚠️ Impossible de rafraîchir le panneau.", ephemeral=True
                )


# ---------- Cog ----------

class ConfigDashboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ConfigPanelView())

    @app_commands.command(
        name="config-panel",
        description="Publier le panneau de configuration permanent dans ce salon",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_panel(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ À utiliser dans un salon texte du serveur.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        embed = await build_config_embed(interaction.guild)
        view = ConfigPanelView()
        msg = await interaction.channel.send(embed=embed, view=view)
        await db.set_config_panel_message(
            interaction.guild.id, interaction.channel.id, msg.id
        )
        await interaction.followup.send(
            f"✅ Panneau de configuration publié ici ({msg.jump_url}).\n"
            f"Conseil : renomme le salon en `#config-bot` et limite l’écriture aux admins.",
            ephemeral=True,
        )

    @app_commands.command(
        name="config-voir",
        description="Afficher l’état actuel de la configuration (éphémère)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_voir(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Serveur uniquement.", ephemeral=True
            )
            return
        embed = await build_config_embed(interaction.guild)
        # Pas de logo en grand pour la version éphémère (plus léger)
        embed.set_image(url=None)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_panel.error
    @config_voir.error
    async def _admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "🚫 Seuls les administrateurs peuvent faire ça."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(ConfigDashboard(bot))