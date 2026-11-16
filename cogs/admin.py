import discord
from discord import app_commands
from discord.ext import commands

import database as db


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="config-role-formateur",
        description="Définir le(s) rôle(s) autorisé(s) à créer des sessions de formation",
    )
    @app_commands.describe(
        role="Rôle formateur principal",
        role_2="Rôle formateur supplémentaire (optionnel)",
        role_3="Rôle formateur supplémentaire (optionnel)",
        role_4="Rôle formateur supplémentaire (optionnel)",
        role_5="Rôle formateur supplémentaire (optionnel)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_role_formateur(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        role_2: discord.Role | None = None,
        role_3: discord.Role | None = None,
        role_4: discord.Role | None = None,
        role_5: discord.Role | None = None,
    ):
        roles = [r for r in (role, role_2, role_3, role_4, role_5) if r is not None]
        # Dédupliquer en gardant l'ordre
        seen = set()
        unique = []
        for r in roles:
            if r.id not in seen:
                seen.add(r.id)
                unique.append(r)

        await db.set_formateur_role(interaction.guild_id, [r.id for r in unique])
        mentions = ", ".join(r.mention for r in unique)
        await interaction.response.send_message(
            f"✅ Rôle(s) formateur configuré(s) : {mentions}\n"
            f"Ces rôles peuvent créer et gérer des sessions.",
            ephemeral=True,
        )

    @app_commands.command(
        name="config-canal-annonce",
        description="Définir le canal par défaut pour les annonces de sessions",
    )
    @app_commands.describe(canal="Salon où publier les annonces de sessions")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_canal_annonce(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        await db.set_announcement_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(
            f"✅ Les annonces de sessions seront publiées dans {canal.mention} par défaut.",
            ephemeral=True,
        )

    @app_commands.command(
        name="config-role-gerant-atc",
        description="Définir les rôles Gérant ATC (peuvent modifier le planning ATC)",
    )
    @app_commands.describe(
        role="Rôle autorisé à gérer le planning ATC",
        role_2="Rôle supplémentaire (optionnel)",
        role_3="Rôle supplémentaire (optionnel)",
        role_4="Rôle supplémentaire (optionnel)",
        role_5="Rôle supplémentaire (optionnel)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_role_gerant_atc(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        role_2: discord.Role | None = None,
        role_3: discord.Role | None = None,
        role_4: discord.Role | None = None,
        role_5: discord.Role | None = None,
    ):
        seen = set()
        unique = []
        for r in (role, role_2, role_3, role_4, role_5):
            if r is not None and r.id not in seen:
                seen.add(r.id)
                unique.append(r)

        await db.set_gerant_atc_role(interaction.guild_id, [r.id for r in unique])
        mentions = ", ".join(r.mention for r in unique)
        await interaction.response.send_message(
            f"✅ Rôle(s) Gérant ATC configuré(s) : {mentions}\n"
            f"Ces rôles peuvent ajouter, annuler et valider les modifs du planning ATC.\n"
            f"ℹ️ La commande **remplace** la liste précédente.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(
        name="roles",
        description="Voir les rôles d'un membre",
    )
    @app_commands.describe(membre="Membre dont afficher les rôles (toi par défaut)")
    async def roles(
        self,
        interaction: discord.Interaction,
        membre: discord.Member | None = None,
    ):
        member = membre or interaction.user
        if not isinstance(member, discord.Member):
            # Fallback si appelé hors serveur
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée sur un serveur.",
                ephemeral=True,
            )
            return

        # Exclure @everyone, trier du plus haut au plus bas
        role_list = [r for r in member.roles if r.name != "@everyone"]
        role_list.sort(key=lambda r: r.position, reverse=True)

        embed = discord.Embed(
            title=f"Rôles de {member.display_name}",
            color=member.color if member.color.value else 0x5865F2,
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if not role_list:
            embed.description = "_Aucun rôle (hors @everyone)._"
        else:
            # Mentions pour cliquer / voir la couleur
            lines = [f"{r.mention} — `{r.name}` (ID: `{r.id}`)" for r in role_list]
            text = "\n".join(lines)
            # Limite Discord embed field / description
            if len(text) > 4000:
                text = text[:3990] + "\n…"
            embed.description = text
            embed.set_footer(text=f"{len(role_list)} rôle(s)")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="say",
        description="Faire parler le bot (annonce / message) dans un salon",
    )
    @app_commands.describe(
        message="Texte à envoyer (le bot parle à ta place)",
        salon="Salon de destination (défaut : salon actuel)",
        embed="Envoyer en embed (titre optionnel via | : Titre | Corps)",
    )
    async def say(
        self,
        interaction: discord.Interaction,
        message: str,
        salon: discord.TextChannel | None = None,
        embed: bool = False,
    ):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("❌ Serveur uniquement.", ephemeral=True)
            return
        if not member.guild_permissions.administrator:
            await interaction.response.send_message(
                "🚫 Réservé aux administrateurs.", ephemeral=True
            )
            return

        channel = salon or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Choisis un salon texte.", ephemeral=True
            )
            return

        # Permissions bot
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.send_messages:
            await interaction.response.send_message(
                f"❌ Je ne peux pas écrire dans {channel.mention}.", ephemeral=True
            )
            return

        try:
            if embed:
                title = None
                body = message
                if "|" in message:
                    left, right = message.split("|", 1)
                    if left.strip() and right.strip():
                        title = left.strip()[:256]
                        body = right.strip()
                emb = discord.Embed(
                    title=title or "📢 Annonce",
                    description=body[:4096],
                    color=0x1E90FF,
                )
                emb.set_footer(text=f"Annonce · {member.display_name}")
                await channel.send(embed=emb)
            else:
                # Mentions de rôles/users autorisées pour les annonces staff
                await channel.send(
                    content=message[:2000],
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, roles=True, users=True
                    ),
                )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Envoi impossible : {e}", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Message envoyé dans {channel.mention}.", ephemeral=True
        )

    @app_commands.command(
        name="salon-prive",
        description="Créer un salon texte privé avec un membre (visible par le staff)",
    )
    @app_commands.describe(
        membre="Membre avec qui ouvrir le salon",
        nom="Nom du salon (optionnel)",
        categorie="Catégorie où créer le salon (optionnel)",
    )
    async def salon_prive(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        nom: str | None = None,
        categorie: discord.CategoryChannel | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            await interaction.response.send_message("❌ Serveur uniquement.", ephemeral=True)
            return

        conf = await db.get_guild_config(interaction.guild_id) or {}
        is_admin = interaction.user.guild_permissions.administrator
        staff_role = None
        if conf.get("staff_role_id"):
            staff_role = interaction.guild.get_role(int(conf["staff_role_id"]))
        is_staff = bool(
            staff_role and staff_role in interaction.user.roles
        )
        if not is_admin and not is_staff:
            await interaction.response.send_message(
                "🚫 Réservé aux **administrateurs** et au **staff**.",
                ephemeral=True,
            )
            return

        if membre.bot:
            await interaction.response.send_message(
                "❌ Impossible de créer un salon avec un bot.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Nom du salon
        safe_name = (nom or f"prive-{membre.display_name}").strip().lower()
        # Discord : caractères limités pour les noms de salon
        for ch in (" ", "_"):
            safe_name = safe_name.replace(ch, "-")
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
        safe_name = "".join(c if c in allowed else "" for c in safe_name)
        safe_name = safe_name.strip("-")[:90] or f"prive-{membre.id}"

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            membre: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                manage_messages=True,
            ),
        }
        # Tout le staff voit le salon
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                manage_messages=True,
            )

        try:
            channel = await interaction.guild.create_text_channel(
                name=safe_name,
                category=categorie,
                overwrites=overwrites,
                reason=f"Salon privé créé par {interaction.user} avec {membre}",
            )
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ Impossible de créer le salon : {e}", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🔒 Salon privé",
            description=(
                f"Salon créé par {interaction.user.mention} avec {membre.mention}.\n\n"
                f"• Visible par **{membre.mention}**\n"
                f"• Visible par tout le **staff**"
                + (f" ({staff_role.mention})" if staff_role else " *(rôle staff non configuré)*")
                + "\n• Invisible pour le reste du serveur"
            ),
            color=0x1E90FF,
        )
        try:
            await channel.send(
                content=f"{membre.mention} {interaction.user.mention}"
                + (f" {staff_role.mention}" if staff_role else ""),
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            f"✅ Salon créé : {channel.mention}\n"
            f"Accessible à {membre.mention} et au staff.",
            ephemeral=True,
        )

    @config_role_formateur.error
    @config_canal_annonce.error
    @config_role_gerant_atc.error
    async def config_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "🚫 Seuls les administrateurs peuvent faire ça.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "🚫 Seuls les administrateurs peuvent faire ça.", ephemeral=True
                )
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))