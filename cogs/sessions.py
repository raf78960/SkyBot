import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
from zoneinfo import ZoneInfo

import database as db
from config import TIMEZONE
from cogs.views import SessionView, build_session_embed


# Types de formation prédéfinis (options 1-3)
SESSION_TYPES = {
    "avion": {
        "label": "Formation Avion",
        "title": "Formation Avion",
        "emoji": "✈️",
        "ping_field": "session_ping_avion_role_id",
    },
    "pilote": {
        "label": "Formation Pilote",
        "title": "Formation Pilote",
        "emoji": "👨‍✈️",
        "ping_field": "session_ping_pilote_role_id",
    },
    "atc": {
        "label": "Formation ATC",
        "title": "Formation ATC",
        "emoji": "📡",
        "ping_field": "session_ping_atc_role_id",
    },
    "site_atc": {
        "label": "Formation Site ATC",
        "title": "Formation Site ATC",
        "emoji": "🖥️",
        "ping_field": "session_ping_site_atc_role_id",
    },
    "site_pilote": {
        "label": "Formation Site Pilote",
        "title": "Formation Site Pilote",
        "emoji": "🌐",
        "ping_field": "session_ping_site_pilote_role_id",
    },
    "autre": {
        "label": "Autre",
        "title": None,  # demandé via modal
        "emoji": "📝",
        "ping_field": None,
    },
}


async def user_is_admin(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    member = interaction.user
    if isinstance(member, discord.Member):
        perms = member.guild_permissions
        if perms.administrator or perms.manage_guild:
            return True
    return False


async def user_is_admin_or_formateur(interaction: discord.Interaction) -> bool:
    if await user_is_admin(interaction):
        return True
    conf = await db.get_guild_config(interaction.guild_id)
    if not conf:
        return False
    role_ids = db.parse_id_list(conf.get("formateur_role_id"))
    user_role_ids = {r.id for r in interaction.user.roles}
    return any(rid in user_role_ids for rid in role_ids)


async def _get_session_ping_role(guild: discord.Guild, session_type: str | None):
    """Retourne le rôle à ping pour le type de session (ou None)."""
    if not session_type or session_type == "autre":
        return None
    info = SESSION_TYPES.get(session_type)
    if not info or not info.get("ping_field"):
        return None
    conf = await db.get_guild_config(guild.id) or {}
    role_id = conf.get(info["ping_field"])
    if not role_id:
        return None
    return guild.get_role(role_id)


class SessionCreateModal(discord.ui.Modal, title="Créer une session de formation"):
    def __init__(
        self,
        formateur: discord.Member,
        announcement_channel: discord.TextChannel,
        session_type: str,
        titre: str | None = None,
    ):
        super().__init__()
        self.formateur = formateur
        self.announcement_channel = announcement_channel
        self.session_type = session_type
        self.fixed_titre = titre
        self.titre_input = None

        # Si type "autre", demander le titre en premier
        if session_type == "autre":
            self.titre_input = discord.ui.TextInput(
                label="Titre de la session",
                placeholder="Ex : Briefing IFR avancé",
                max_length=100,
                required=True,
            )
            self.add_item(self.titre_input)

        self.description = None
        if session_type != "autre":
            self.description = discord.ui.TextInput(
                label="Description",
                style=discord.TextStyle.paragraph,
                required=False,
                max_length=500,
            )
            self.add_item(self.description)
        self.date_str = discord.ui.TextInput(
            label="Date (JJ/MM/AAAA)",
            placeholder="Ex : 15/09/2026",
            max_length=10,
        )
        self.heure_str = discord.ui.TextInput(
            label="Heure (HH:MM, 24h)",
            placeholder="Ex : 14:30",
            max_length=5,
        )
        self.duration_str = discord.ui.TextInput(
            label="Durée (minutes, défaut 120)",
            placeholder="Ex : 120",
            required=False,
            max_length=4,
            default="120",
        )
        self.max_participants = discord.ui.TextInput(
            label="Places max (0 ou vide = illimité)",
            required=False,
            max_length=4,
        )
        self.add_item(self.date_str)
        self.add_item(self.heure_str)
        self.add_item(self.duration_str)
        self.add_item(self.max_participants)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            naive_dt = datetime.strptime(
                f"{self.date_str.value} {self.heure_str.value}", "%d/%m/%Y %H:%M"
            )
            local_dt = naive_dt.replace(tzinfo=ZoneInfo(TIMEZONE))
            utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
        except ValueError:
            await interaction.response.send_message(
                "❌ Format de date/heure invalide. Utilise JJ/MM/AAAA et HH:MM.",
                ephemeral=True,
            )
            return

        if utc_dt <= datetime.now(ZoneInfo("UTC")):
            await interaction.response.send_message(
                "❌ La date de la session doit être dans le futur.", ephemeral=True
            )
            return

        try:
            max_p = int(self.max_participants.value) if self.max_participants.value else 0
        except ValueError:
            max_p = 0

        try:
            duration_minutes = int(self.duration_str.value) if self.duration_str.value else 120
        except ValueError:
            duration_minutes = 120
        if duration_minutes <= 0:
            duration_minutes = 120
        if duration_minutes > 12 * 60:
            await interaction.response.send_message(
                "❌ Durée max : 12 heures (720 minutes).", ephemeral=True
            )
            return

        if self.session_type == "autre":
            titre = self.titre_input.value.strip()
            if not titre:
                await interaction.response.send_message(
                    "❌ Le titre est obligatoire pour une session « Autre ».",
                    ephemeral=True,
                )
                return
            description = ""
        else:
            titre = self.fixed_titre or SESSION_TYPES[self.session_type]["title"]
            description = self.description.value if self.description else ""

        session_id = await db.create_session(
            guild_id=interaction.guild_id,
            title=titre,
            description=description,
            formateur_id=self.formateur.id,
            date_time_utc=utc_dt,
            max_participants=max_p,
            created_by=interaction.user.id,
            session_type=self.session_type,
            duration_minutes=duration_minutes,
        )

        session = await db.get_session(session_id)
        embed = build_session_embed(session, 0, [])
        view = SessionView(session_id)

        ping_role = await _get_session_ping_role(interaction.guild, self.session_type)
        content = ping_role.mention if ping_role else None

        message = await self.announcement_channel.send(
            content=content,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await db.set_session_message(session_id, self.announcement_channel.id, message.id)

        type_label = SESSION_TYPES.get(self.session_type, {}).get("label", self.session_type)
        await interaction.response.send_message(
            f"✅ Session **{titre}** ({type_label}) créée et annoncée dans "
            f"{self.announcement_channel.mention} (ID : {session_id})."
            + (f"\n🔔 Ping : {ping_role.mention}" if ping_role else ""),
            ephemeral=True,
        )


class SessionTypeSelect(discord.ui.Select):
    def __init__(
        self,
        formateur: discord.Member,
        announcement_channel: discord.TextChannel,
    ):
        options = [
            discord.SelectOption(
                label="Formation Avion",
                value="avion",
                emoji="✈️",
                description="Session type Formation Avion",
            ),
            discord.SelectOption(
                label="Formation Pilote",
                value="pilote",
                emoji="👨‍✈️",
                description="Session type Formation Pilote",
            ),
            discord.SelectOption(
                label="Formation ATC",
                value="atc",
                emoji="📡",
                description="Session type Formation ATC",
            ),
            discord.SelectOption(
                label="Formation Site ATC",
                value="site_atc",
                emoji="🖥️",
                description="Session type Formation Site ATC",
            ),
            discord.SelectOption(
                label="Formation Site Pilote",
                value="site_pilote",
                emoji="🌐",
                description="Session type Formation Site Pilote",
            ),
            discord.SelectOption(
                label="Autre",
                value="autre",
                emoji="📝",
                description="Titre personnalisé (demandé ensuite)",
            ),
        ]
        super().__init__(
            placeholder="Choisir le type de formation…",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.formateur = formateur
        self.announcement_channel = announcement_channel

    async def callback(self, interaction: discord.Interaction):
        stype = self.values[0]
        info = SESSION_TYPES[stype]
        titre = info["title"]  # None pour "autre"
        modal = SessionCreateModal(
            self.formateur,
            self.announcement_channel,
            session_type=stype,
            titre=titre,
        )
        await interaction.response.send_modal(modal)


class SessionTypeSelectView(discord.ui.View):
    def __init__(
        self,
        formateur: discord.Member,
        announcement_channel: discord.TextChannel,
    ):
        super().__init__(timeout=120)
        self.add_item(SessionTypeSelect(formateur, announcement_channel))


class SessionIdTransformer(app_commands.Transformer):
    async def transform(self, interaction: discord.Interaction, value: str) -> int:
        try:
            return int(value)
        except ValueError:
            raise app_commands.AppCommandError("L'ID de session doit être un nombre.")


class Sessions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._past_sessions_task.start()

    def cog_unload(self):
        self._past_sessions_task.cancel()

    @tasks.loop(minutes=5)
    async def _past_sessions_task(self):
        """Passe en rouge / status done les formations dont la date est passée."""
        try:
            past = await db.list_past_planned_sessions()
            for session in past:
                await db.mark_session_done(session["id"])
                ch_id = session.get("channel_id")
                msg_id = session.get("message_id")
                if not ch_id or not msg_id:
                    continue
                channel = self.bot.get_channel(ch_id)
                if not channel:
                    continue
                try:
                    msg = await channel.fetch_message(msg_id)
                    participants = await db.get_participants(session["id"])
                    updated = await db.get_session(session["id"])
                    embed = build_session_embed(
                        updated, len(participants), participants
                    )
                    # Garder la vue mais les inscriptions seront refusées
                    view = SessionView(session["id"])
                    self.bot.add_view(view)
                    await msg.edit(embed=embed, view=view)
                except (discord.NotFound, discord.HTTPException):
                    pass
        except Exception:
            pass

    @_past_sessions_task.before_loop
    async def _before_past_sessions(self):
        await self.bot.wait_until_ready()

    async def session_autocomplete(self, interaction: discord.Interaction, current: str):
        sessions = await db.list_upcoming_sessions(interaction.guild_id)
        choices = []
        for s in sessions:
            label = f"#{s['id']} — {s['title']}"
            if current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=str(s["id"])))
        return choices[:25]

    @app_commands.command(name="session-create", description="Créer une nouvelle session de formation")
    @app_commands.describe(
        formateur="La personne qui animera la session",
        canal_annonce="Le canal où publier l'annonce (par défaut : canal configuré ou canal actuel)",
    )
    async def session_create(
        self,
        interaction: discord.Interaction,
        formateur: discord.Member,
        canal_annonce: discord.TextChannel = None,
    ):
        if not await user_is_admin_or_formateur(interaction):
            await interaction.response.send_message(
                "🚫 Tu n'as pas la permission de créer une session "
                "(réservé aux admins et au rôle formateur configuré).",
                ephemeral=True,
            )
            return

        channel = canal_annonce
        if channel is None:
            conf = await db.get_guild_config(interaction.guild_id)
            if conf and conf.get("announcement_channel_id"):
                channel = interaction.guild.get_channel(conf["announcement_channel_id"])
            if channel is None:
                channel = interaction.channel

        await interaction.response.send_message(
            "🎓 **Choisis le type de formation :**",
            view=SessionTypeSelectView(formateur, channel),
            ephemeral=True,
        )

    @app_commands.command(
        name="session-config-ping-avion",
        description="Rôle à mentionner pour les sessions Formation Avion",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def session_config_ping_avion(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await db.set_session_ping_avion_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle ping **Formation Avion** : {role.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="session-config-ping-pilote",
        description="Rôle à mentionner pour les sessions Formation Pilote",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def session_config_ping_pilote(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await db.set_session_ping_pilote_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle ping **Formation Pilote** : {role.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="session-config-ping-atc",
        description="Rôle à mentionner pour les sessions Formation ATC",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def session_config_ping_atc(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await db.set_session_ping_atc_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle ping **Formation ATC** : {role.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="session-config-ping-site-atc",
        description="Rôle à mentionner pour les sessions Formation Site ATC",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def session_config_ping_site_atc(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await db.set_session_ping_site_atc_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle ping **Formation Site ATC** : {role.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="session-config-ping-site-pilote",
        description="Rôle à mentionner pour les sessions Formation Site Pilote",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def session_config_ping_site_pilote(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await db.set_session_ping_site_pilote_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle ping **Formation Site Pilote** : {role.mention}",
            ephemeral=True,
        )

    @app_commands.command(name="planning", description="Voir le planning des sessions à venir")
    async def planning(self, interaction: discord.Interaction):
        sessions = await db.list_upcoming_sessions(interaction.guild_id)
        if not sessions:
            await interaction.response.send_message(
                "📭 Aucune session de formation planifiée pour le moment.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📅 Planning des formations à venir",
            color=discord.Color.blurple(),
        )
        for s in sessions[:20]:
            dt_utc = datetime.fromisoformat(s["date_time_utc"])
            count = await db.count_participants(s["id"])
            max_p = s["max_participants"]
            capacity = f"{count}/{max_p}" if max_p else f"{count} inscrit(s)"
            stype = s.get("session_type")
            type_txt = ""
            if stype and stype in SESSION_TYPES:
                type_txt = f" · {SESSION_TYPES[stype]['emoji']} {SESSION_TYPES[stype]['label']}"
            embed.add_field(
                name=f"#{s['id']} — {s['title']}",
                value=(
                    f"<t:{int(dt_utc.timestamp())}:F> · Formateur : <@{s['formateur_id']}> · "
                    f"{capacity}{type_txt}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mes-sessions", description="Voir les sessions auxquelles tu es inscrit(e)")
    async def mes_sessions(self, interaction: discord.Interaction):
        sessions = await db.list_user_sessions(interaction.guild_id, interaction.user.id)
        if not sessions:
            await interaction.response.send_message(
                "Tu n'es inscrit(e) à aucune session pour le moment.", ephemeral=True
            )
            return

        embed = discord.Embed(title="🎓 Tes sessions", color=discord.Color.green())
        for s in sessions:
            dt_utc = datetime.fromisoformat(s["date_time_utc"])
            embed.add_field(
                name=f"#{s['id']} — {s['title']}",
                value=f"<t:{int(dt_utc.timestamp())}:F>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="session-inscrits",
        description="Voir qui est inscrit à une session de formation",
    )
    @app_commands.describe(session_id="ID de la session (voir /planning)")
    @app_commands.autocomplete(session_id=session_autocomplete)
    async def session_inscrits(self, interaction: discord.Interaction, session_id: str):
        if not await user_is_admin_or_formateur(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux formateurs et administrateurs.", ephemeral=True
            )
            return

        session = await db.get_session(int(session_id))
        if not session or session["guild_id"] != interaction.guild_id:
            await interaction.response.send_message(
                "Session introuvable.", ephemeral=True
            )
            return

        participants = await db.get_participants(session["id"])
        count = len(participants)
        max_p = session.get("max_participants") or 0
        capacity = f"{count}/{max_p}" if max_p else str(count)

        dt_utc = datetime.fromisoformat(session["date_time_utc"])
        embed = discord.Embed(
            title=f"👥 Inscrits — #{session['id']} {session['title']}",
            description=(
                f"**Date :** <t:{int(dt_utc.timestamp())}:F>\n"
                f"**Formateur :** <@{session['formateur_id']}>\n"
                f"**Places :** {capacity}"
            ),
            color=discord.Color.blue(),
        )

        if not participants:
            embed.add_field(
                name="Participants",
                value="*Aucun inscrit pour le moment.*",
                inline=False,
            )
        else:
            # Mentions par paquets pour rester sous la limite Discord
            lines = []
            for i, uid in enumerate(participants, start=1):
                lines.append(f"`{i}.` <@{uid}>")
            chunk = []
            chunk_len = 0
            field_i = 1
            for line in lines:
                if chunk_len + len(line) + 1 > 1000:
                    embed.add_field(
                        name=f"Participants ({field_i})",
                        value="\n".join(chunk),
                        inline=False,
                    )
                    field_i += 1
                    chunk = [line]
                    chunk_len = len(line) + 1
                else:
                    chunk.append(line)
                    chunk_len += len(line) + 1
            if chunk:
                name = "Participants" if field_i == 1 else f"Participants ({field_i})"
                embed.add_field(name=name, value="\n".join(chunk), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="session-annuler", description="Annuler une session (garde l'historique)")
    @app_commands.describe(session_id="ID de la session à annuler")
    @app_commands.autocomplete(session_id=session_autocomplete)
    async def session_annuler(self, interaction: discord.Interaction, session_id: str):
        if not await user_is_admin_or_formateur(interaction):
            await interaction.response.send_message("🚫 Permission refusée.", ephemeral=True)
            return

        session = await db.get_session(int(session_id))
        if not session or session["guild_id"] != interaction.guild_id:
            await interaction.response.send_message("Session introuvable.", ephemeral=True)
            return

        await db.cancel_session(session["id"])

        if session["channel_id"] and session["message_id"]:
            try:
                channel = interaction.guild.get_channel(session["channel_id"])
                message = await channel.fetch_message(session["message_id"])
                participants = await db.get_participants(session["id"])
                updated_session = await db.get_session(session["id"])
                embed = build_session_embed(
                    updated_session, len(participants), participants
                )
                await message.edit(embed=embed, view=None)
            except (discord.NotFound, discord.HTTPException):
                pass

        participants = await db.get_participants(session["id"])
        for user_id in participants:
            member = interaction.guild.get_member(user_id)
            if member:
                try:
                    await member.send(
                        f"❌ La session **{session['title']}** prévue a été annulée."
                    )
                except discord.Forbidden:
                    pass

        await interaction.response.send_message(
            f"✅ Session #{session['id']} annulée, participants notifiés.", ephemeral=True
        )

    @app_commands.command(name="session-supprimer", description="Supprimer définitivement une session")
    @app_commands.describe(session_id="ID de la session à supprimer")
    @app_commands.autocomplete(session_id=session_autocomplete)
    async def session_supprimer(self, interaction: discord.Interaction, session_id: str):
        if not await user_is_admin(interaction):
            await interaction.response.send_message(
                "🚫 Seuls les admins du serveur peuvent supprimer définitivement une session.",
                ephemeral=True,
            )
            return

        session = await db.get_session(int(session_id))
        if not session or session["guild_id"] != interaction.guild_id:
            await interaction.response.send_message("Session introuvable.", ephemeral=True)
            return

        if session["channel_id"] and session["message_id"]:
            try:
                channel = interaction.guild.get_channel(session["channel_id"])
                message = await channel.fetch_message(session["message_id"])
                await message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

        await db.delete_session(session["id"])
        await interaction.response.send_message(
            f"🗑️ Session #{session_id} supprimée définitivement.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Sessions(bot))