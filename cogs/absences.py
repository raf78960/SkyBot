"""
Système d'absences SkyCommunity.
- Panel permanent : déposer / annuler une absence
- Formulaire : motif + date début + date fin
- Rôles autorisés configurables (max 8)
- Rôle temporaire « Absent » + logs / annonces
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from config import TIMEZONE

log = logging.getLogger(__name__)
SKY_COLOR = 0x1E90FF


def _tz() -> ZoneInfo:
    return ZoneInfo(TIMEZONE)


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip().replace("-", "/")
    parts = raw.split("/")
    if len(parts) != 3:
        return None
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
        return date(y, m, d)
    except Exception:
        return None


async def _member_can_declare(member: discord.Member, conf: dict) -> bool:
    role_ids = db.parse_id_list(conf.get("absence_role_ids"))
    if not role_ids:
        return False
    member_ids = {r.id for r in member.roles}
    return any(rid in member_ids for rid in role_ids)


async def _apply_temp_role(guild: discord.Guild, user_id: int, conf: dict, add: bool):
    rid = conf.get("absence_temp_role_id")
    if not rid:
        return
    role = guild.get_role(int(rid))
    member = guild.get_member(user_id)
    if not role or not member:
        return
    try:
        if add and role not in member.roles:
            await member.add_roles(role, reason="Absence déclarée")
        elif not add and role in member.roles:
            await member.remove_roles(role, reason="Absence terminée / annulée")
    except discord.HTTPException as e:
        log.warning("Impossible de gérer le rôle Absent pour %s: %s", user_id, e)


def _absence_embed(absence: dict, member: discord.Member | None = None) -> discord.Embed:
    status = absence.get("status") or "active"
    colors = {
        "active": discord.Color.orange(),
        "cancelled": discord.Color.dark_grey(),
        "expired": discord.Color.green(),
    }
    title = {
        "active": "🏖️ Absence déclarée",
        "cancelled": "❌ Absence annulée",
        "expired": "✅ Absence terminée",
    }.get(status, "Absence")
    who = member.mention if member else f"<@{absence['user_id']}>"
    embed = discord.Embed(
        title=title,
        color=colors.get(status, SKY_COLOR),
        timestamp=datetime.now(_tz()),
    )
    embed.add_field(name="Membre", value=who, inline=True)
    embed.add_field(
        name="Période",
        value=f"**{absence['start_date']}** → **{absence['end_date']}**",
        inline=True,
    )
    embed.add_field(name="Motif", value=absence.get("motif") or "—", inline=False)
    embed.set_footer(text=f"absence_id={absence['id']}")
    return embed


class AbsenceDeclareModal(discord.ui.Modal, title="Déposer une absence"):
    motif = discord.ui.TextInput(
        label="Motif",
        style=discord.TextStyle.paragraph,
        placeholder="Ex : vacances, examens, indisponibilité…",
        max_length=500,
        required=True,
    )
    start_str = discord.ui.TextInput(
        label="Date de début (JJ/MM/AAAA)",
        placeholder="Ex : 10/11/2026",
        max_length=10,
        required=True,
    )
    end_str = discord.ui.TextInput(
        label="Date de fin (JJ/MM/AAAA)",
        placeholder="Ex : 20/11/2026",
        max_length=10,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Membres uniquement.", ephemeral=True)
            return
        conf = await db.get_guild_config(interaction.guild_id) or {}
        if not await _member_can_declare(interaction.user, conf):
            await interaction.response.send_message(
                "🚫 Tu n'as pas un des rôles autorisés à déposer une absence.",
                ephemeral=True,
            )
            return

        existing = await db.get_active_absence_for_user(
            interaction.guild_id, interaction.user.id
        )
        if existing:
            await interaction.response.send_message(
                f"⚠️ Tu as déjà une absence active (`{existing['start_date']}` → `{existing['end_date']}`).\n"
                "Annule-la d'abord si tu veux en déposer une nouvelle.",
                ephemeral=True,
            )
            return

        start_d = _parse_date(self.start_str.value)
        end_d = _parse_date(self.end_str.value)
        if not start_d or not end_d:
            await interaction.response.send_message(
                "❌ Dates invalides. Format : JJ/MM/AAAA", ephemeral=True
            )
            return
        if end_d < start_d:
            await interaction.response.send_message(
                "❌ La date de fin doit être après (ou égale) la date de début.",
                ephemeral=True,
            )
            return
        today = datetime.now(_tz()).date()
        if end_d < today:
            await interaction.response.send_message(
                "❌ La période d'absence est déjà terminée.", ephemeral=True
            )
            return

        motif = self.motif.value.strip()
        absence_id = await db.create_absence(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            motif=motif,
            start_date=str(start_d),
            end_date=str(end_d),
        )
        absence = await db.get_absence(absence_id)

        # Rôle temporaire dès le dépôt (si période déjà commencée ou à venir)
        if start_d <= today:
            await _apply_temp_role(interaction.guild, interaction.user.id, conf, add=True)

        # Log / annonce (+ mentions multi-rôles configurés)
        log_ch_id = conf.get("absence_log_channel_id")
        if log_ch_id:
            ch = interaction.guild.get_channel(int(log_ch_id))
            if ch:
                try:
                    mentions = [interaction.user.mention]
                    for rid in db.parse_id_list(conf.get("absence_ping_role_ids")):
                        role = interaction.guild.get_role(rid)
                        if role:
                            mentions.append(role.mention)
                    msg = await ch.send(
                        content=" ".join(mentions),
                        embed=_absence_embed(absence, interaction.user),
                        allowed_mentions=discord.AllowedMentions(users=True, roles=True),
                    )
                    await db.set_absence_log_message(absence_id, ch.id, msg.id)
                except discord.HTTPException:
                    pass

        await interaction.response.send_message(
            f"✅ Absence enregistrée du **{start_d.strftime('%d/%m/%Y')}** "
            f"au **{end_d.strftime('%d/%m/%Y')}**.\n"
            f"Motif : {motif}",
            ephemeral=True,
        )


class AbsencePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Déposer une absence",
        style=discord.ButtonStyle.primary,
        emoji="📝",
        custom_id="absence_panel:declare",
    )
    async def declare(self, interaction: discord.Interaction, button: discord.ui.Button):
        conf = await db.get_guild_config(interaction.guild_id) or {}
        if not isinstance(interaction.user, discord.Member) or not await _member_can_declare(
            interaction.user, conf
        ):
            await interaction.response.send_message(
                "🚫 Tu n'as pas un des rôles autorisés à déposer une absence.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(AbsenceDeclareModal())

    @discord.ui.button(
        label="Annuler mon absence",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="absence_panel:cancel",
    )
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        absence = await db.get_active_absence_for_user(
            interaction.guild_id, interaction.user.id
        )
        if not absence:
            await interaction.response.send_message(
                "ℹ️ Tu n'as pas d'absence active.", ephemeral=True
            )
            return
        await db.cancel_absence(absence["id"])
        conf = await db.get_guild_config(interaction.guild_id) or {}
        await _apply_temp_role(interaction.guild, interaction.user.id, conf, add=False)

        # Log
        log_ch_id = conf.get("absence_log_channel_id")
        if log_ch_id:
            ch = interaction.guild.get_channel(int(log_ch_id))
            if ch:
                absence["status"] = "cancelled"
                try:
                    await ch.send(
                        embed=_absence_embed(
                            absence,
                            interaction.user if isinstance(interaction.user, discord.Member) else None,
                        )
                    )
                except discord.HTTPException:
                    pass

        await interaction.response.send_message(
            "✅ Ton absence a été annulée. Le rôle temporaire a été retiré.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Mon absence",
        style=discord.ButtonStyle.secondary,
        emoji="ℹ️",
        custom_id="absence_panel:status",
    )
    async def status(self, interaction: discord.Interaction, button: discord.ui.Button):
        absence = await db.get_active_absence_for_user(
            interaction.guild_id, interaction.user.id
        )
        if not absence:
            await interaction.response.send_message(
                "ℹ️ Tu n'as pas d'absence active.", ephemeral=True
            )
            return
        embed = _absence_embed(
            absence,
            interaction.user if isinstance(interaction.user, discord.Member) else None,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class Absences(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(AbsencePanelView())
        if not self.process_absences.is_running():
            self.process_absences.start()

    def cog_unload(self):
        self.process_absences.cancel()

    @tasks.loop(minutes=30)
    async def process_absences(self):
        """Applique / retire le rôle Absent selon les dates, expire les absences passées."""
        today = datetime.now(_tz()).date()
        try:
            absences = await db.list_active_absences()
        except Exception as e:
            log.warning("Lecture absences: %s", e)
            return
        for absence in absences:
            try:
                start_d = date.fromisoformat(absence["start_date"])
                end_d = date.fromisoformat(absence["end_date"])
            except Exception:
                continue
            guild = self.bot.get_guild(absence["guild_id"])
            if not guild:
                continue
            conf = await db.get_guild_config(guild.id) or {}
            if end_d < today:
                await db.expire_absence(absence["id"])
                await _apply_temp_role(guild, absence["user_id"], conf, add=False)
                log_ch_id = conf.get("absence_log_channel_id")
                if log_ch_id:
                    ch = guild.get_channel(int(log_ch_id))
                    if ch:
                        absence["status"] = "expired"
                        try:
                            await ch.send(embed=_absence_embed(absence))
                        except discord.HTTPException:
                            pass
            elif start_d <= today <= end_d:
                await _apply_temp_role(guild, absence["user_id"], conf, add=True)

    @process_absences.before_loop
    async def _before_absences(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="absence-panel",
        description="Publier le panneau permanent des absences dans ce salon",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def absence_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏖️ Absences — SkyCommunity",
            description=(
                "Dépose une absence si tu as un des **rôles autorisés**.\n\n"
                "• **Déposer** — motif + date début + date fin\n"
                "• **Annuler** — termine ton absence active (retrait du rôle)\n"
                "• **Mon absence** — voir ta période en cours\n\n"
                "Un rôle temporaire **Absent** te sera attribué pendant la période, "
                "et une annonce sera postée dans le salon de logs configuré."
            ),
            color=SKY_COLOR,
            timestamp=datetime.now(_tz()),
        )
        view = AbsencePanelView()
        self.bot.add_view(view)
        msg = await interaction.channel.send(embed=embed, view=view)
        await db.set_absence_panel(interaction.guild_id, interaction.channel.id, msg.id)
        await interaction.response.send_message(
            f"✅ Panel absences publié dans {interaction.channel.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Absences(bot))
