"""
Vue persistante attachée à chaque message d'annonce de session.
Persistante = fonctionne même après un redémarrage du bot, tant qu'on la
ré-enregistre au démarrage (voir bot.py -> setup_hook).
"""

import discord
from datetime import datetime
from zoneinfo import ZoneInfo

import database as db
from config import TIMEZONE


# Mapping type de formation → champ config du rôle requis (même que le ping)
SESSION_REQUIRED_ROLE_FIELD = {
    "avion": "session_ping_avion_role_id",
    "pilote": "session_ping_pilote_role_id",
    "atc": "session_ping_atc_role_id",
    "site_atc": "session_ping_site_atc_role_id",
    "site_pilote": "session_ping_site_pilote_role_id",
}

SESSION_TYPE_LABELS = {
    "avion": "Formation Avion",
    "pilote": "Formation Pilote",
    "atc": "Formation ATC",
    "site_atc": "Formation Site ATC",
    "site_pilote": "Formation Site Pilote",
}


def build_session_embed(session: dict, participants_count: int, participant_ids=None):
    dt_utc = datetime.fromisoformat(session["date_time_utc"])
    dt_local = dt_utc.astimezone(ZoneInfo(TIMEZONE))

    status_label = {
        "planned": "📅 Planifiée",
        "cancelled": "❌ Annulée",
        "done": "✅ Terminée",
    }.get(session["status"], session["status"])

    # Rouge si date passée, terminée ou annulée
    now_utc = datetime.now(ZoneInfo("UTC"))
    is_past = dt_utc <= now_utc
    color = discord.Color.blurple()
    if session["status"] == "cancelled":
        color = discord.Color.red()
    elif session["status"] == "done" or is_past:
        color = discord.Color.red()
        if session["status"] == "planned" and is_past:
            status_label = "⏰ Inscriptions terminées"

    embed = discord.Embed(
        title=f"🎓 {session['title']}",
        description=session["description"] or "*Pas de description*",
        color=color,
    )
    embed.add_field(name="Statut", value=status_label, inline=True)
    embed.add_field(
        name="Date & heure",
        value=f"<t:{int(dt_utc.timestamp())}:F>\n(<t:{int(dt_utc.timestamp())}:R>)",
        inline=True,
    )
    embed.add_field(name="Formateur", value=f"<@{session['formateur_id']}>", inline=True)

    duration = session.get("duration_minutes") or 120
    embed.add_field(name="Durée", value=f"{int(duration)} min", inline=True)

    max_p = session["max_participants"]
    capacity = f"{participants_count}/{max_p}" if max_p and max_p > 0 else f"{participants_count}"
    embed.add_field(name="Nombre d'inscrits", value=capacity, inline=True)

    # Liste des participants sous le compteur
    if participant_ids:
        mentions = " ".join(f"<@{uid}>" for uid in participant_ids)
        # Discord field value max 1024
        if len(mentions) > 1000:
            mentions = mentions[:1000] + "…"
        embed.add_field(name="Participants inscrits", value=mentions, inline=False)
    else:
        embed.add_field(
            name="Participants inscrits",
            value="*Aucun inscrit pour le moment.*",
            inline=False,
        )

    embed.set_footer(text=f"ID session : {session['id']}")
    return embed


class SessionView(discord.ui.View):
    """Vue persistante : timeout=None + custom_id fixes basés sur l'ID de session."""

    def __init__(self, session_id: int):
        super().__init__(timeout=None)
        self.session_id = int(session_id)
        # On force les custom_id pour qu'ils soient stables après redémarrage
        self.children[0].custom_id = f"session_join_{self.session_id}"
        self.children[1].custom_id = f"session_leave_{self.session_id}"

    @discord.ui.button(label="S'inscrire", style=discord.ButtonStyle.success, emoji="✅")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await db.get_session(self.session_id)
        if not session:
            await interaction.response.send_message(
                "Cette session n'existe plus.", ephemeral=True
            )
            return

        # Date passée ou statut non planifié → inscriptions bloquées
        try:
            dt_utc = datetime.fromisoformat(session["date_time_utc"])
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
        except Exception:
            dt_utc = None

        if session["status"] != "planned" or (
            dt_utc and dt_utc <= datetime.now(ZoneInfo("UTC"))
        ):
            await interaction.response.send_message(
                "⛔ Les inscriptions sont terminées pour cette formation "
                "(date passée ou session clôturée).",
                ephemeral=True,
            )
            return

        # Rôle obligatoire selon le type de formation
        stype = session.get("session_type")
        if stype in SESSION_REQUIRED_ROLE_FIELD and interaction.guild:
            conf = await db.get_guild_config(interaction.guild.id) or {}
            role_id = conf.get(SESSION_REQUIRED_ROLE_FIELD[stype])
            if role_id:
                role = interaction.guild.get_role(role_id)
                member = interaction.user
                if role and isinstance(member, discord.Member) and role not in member.roles:
                    label = SESSION_TYPE_LABELS.get(stype, stype)
                    await interaction.response.send_message(
                        f"🚫 Tu dois avoir le rôle **{role.name}** pour t'inscrire "
                        f"à une **{label}**.",
                        ephemeral=True,
                    )
                    return

        # Une seule formation du même type (pilote / atc / avion) à la fois
        if stype and stype != "autre" and interaction.guild:
            same = await db.list_user_planned_sessions_by_type(
                interaction.guild.id, interaction.user.id, stype
            )
            others = [s for s in same if s["id"] != self.session_id]
            # Ne compter que les sessions encore « en cours » (date non passée)
            now_utc = datetime.now(ZoneInfo("UTC"))
            active_others = []
            for s in others:
                try:
                    sdt = datetime.fromisoformat(s["date_time_utc"])
                    if sdt.tzinfo is None:
                        sdt = sdt.replace(tzinfo=ZoneInfo("UTC"))
                    if sdt > now_utc:
                        active_others.append(s)
                except Exception:
                    active_others.append(s)
            if active_others:
                label = SESSION_TYPE_LABELS.get(stype, stype)
                titles = ", ".join(f"**{s['title']}**" for s in active_others[:3])
                await interaction.response.send_message(
                    f"🚫 Tu es déjà inscrit(e) à une **{label}** en cours ({titles}).\n"
                    "Désinscris-toi d'abord avant de rejoindre une autre formation "
                    "du même type.\n"
                    "Tu peux cumuler **Pilote + ATC** si leurs horaires ne se chevauchent pas.",
                    ephemeral=True,
                )
                return

            # Chevauchement horaire avec une autre formation (type différent)
            try:
                this_start = datetime.fromisoformat(session["date_time_utc"])
                if this_start.tzinfo is None:
                    this_start = this_start.replace(tzinfo=ZoneInfo("UTC"))
            except Exception:
                this_start = None
            this_dur = int(session.get("duration_minutes") or 120)
            if this_start:
                from datetime import timedelta
                this_end = this_start + timedelta(minutes=this_dur)
                all_planned = await db.list_user_planned_sessions(
                    interaction.guild.id, interaction.user.id
                )
                for other in all_planned:
                    if other["id"] == self.session_id:
                        continue
                    try:
                        o_start = datetime.fromisoformat(other["date_time_utc"])
                        if o_start.tzinfo is None:
                            o_start = o_start.replace(tzinfo=ZoneInfo("UTC"))
                    except Exception:
                        continue
                    o_dur = int(other.get("duration_minutes") or 120)
                    o_end = o_start + timedelta(minutes=o_dur)
                    # Chevauchement strict
                    if this_start < o_end and o_start < this_end:
                        o_label = SESSION_TYPE_LABELS.get(
                            other.get("session_type"), other.get("title", "formation")
                        )
                        await interaction.response.send_message(
                            f"🚫 Cette formation chevauche **{other['title']}** "
                            f"({o_label}) à laquelle tu es déjà inscrit(e).\n"
                            "Les horaires ne doivent pas se superposer.",
                            ephemeral=True,
                        )
                        return

        max_p = session["max_participants"]
        if max_p and max_p > 0:
            current = await db.count_participants(self.session_id)
            if current >= max_p:
                await interaction.response.send_message(
                    "Désolé, cette session est déjà complète.", ephemeral=True
                )
                return

        added = await db.register_user(self.session_id, interaction.user.id)
        if not added:
            await interaction.response.send_message(
                "Tu es déjà inscrit(e) à cette session.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Inscription confirmée pour **{session['title']}** !", ephemeral=True
        )
        await self._refresh_embed(interaction)

    @discord.ui.button(label="Se désinscrire", style=discord.ButtonStyle.danger, emoji="🚫")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await db.get_session(self.session_id)
        if not session:
            await interaction.response.send_message("Session introuvable.", ephemeral=True)
            return

        # Conversion explicite des IDs (évite les soucis str/int côté SQLite)
        removed = await db.unregister_user(int(self.session_id), int(interaction.user.id))
        if not removed:
            await interaction.response.send_message(
                "Tu n'étais pas inscrit(e) à cette session.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"🚫 Désinscription confirmée pour **{session['title']}**.", ephemeral=True
        )
        await self._refresh_embed(interaction)

    async def _refresh_embed(self, interaction: discord.Interaction):
        session = await db.get_session(self.session_id)
        if not session:
            return
        participants = await db.get_participants(self.session_id)
        count = len(participants)
        embed = build_session_embed(session, count, participants)
        try:
            message = interaction.message
            await message.edit(embed=embed, view=self)
        except (discord.NotFound, discord.HTTPException):
            pass