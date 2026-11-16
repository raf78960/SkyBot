"""
Système de concours photo SkyCommunity.
- Un seul concours actif à la fois
- Photos dans un salon existant
- Réaction ❤️ automatique
- Fin automatique → top 3, points, suppression des autres photos
- Points cumulatifs + classement global
- /concours-retirer : le staff retire la participation d'un membre (et la photo)
"""

from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from config import TIMEZONE

log = logging.getLogger(__name__)

HEART = "❤️"
TZ = ZoneInfo(TIMEZONE or "Europe/Paris")


def _parse_dt(s: str) -> datetime:
    """Parse une date ISO (avec ou sans timezone) → aware UTC."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Interprété comme heure locale du serveur
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)


def _fmt_local(iso_utc: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso_utc


async def _is_staff_or_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    conf = await db.get_guild_config(interaction.guild_id)
    if not conf:
        return False
    staff_id = conf.get("staff_role_id")
    if staff_id and any(r.id == staff_id for r in interaction.user.roles):
        return True
    return False


class ClassementView(discord.ui.View):
    """Pagination top points (10 par page)."""

    def __init__(self, guild_id: int, rows: list[dict], page: int = 0):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.rows = rows
        self.page = page
        self.per_page = 10
        self._update_buttons()

    def _max_page(self) -> int:
        return max(0, (len(self.rows) - 1) // self.per_page)

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= self._max_page()

    def build_embed(self, guild: discord.Guild) -> discord.Embed:
        start = self.page * self.per_page
        chunk = self.rows[start : start + self.per_page]
        lines = []
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        for i, row in enumerate(chunk):
            rank = start + i + 1
            medal = medals.get(rank - 1, f"**#{rank}**")
            member = guild.get_member(row["user_id"])
            name = member.display_name if member else f"<@{row['user_id']}>"
            lines.append(f"{medal} {name} — **{row['total_points']}** pts")
        desc = "\n".join(lines) if lines else "_Aucun point pour le moment._"
        embed = discord.Embed(
            title="🏆 Classement des points",
            description=desc,
            color=discord.Color.gold(),
        )
        embed.set_footer(
            text=f"Page {self.page + 1}/{self._max_page() + 1} • Total {len(self.rows)} joueurs"
        )
        return embed

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.build_embed(interaction.guild), view=self
        )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self._max_page(), self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.build_embed(interaction.guild), view=self
        )


class Concours(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_contests.start()

    def cog_unload(self):
        self.check_contests.cancel()

    # ------------------------------------------------------------------
    # Création
    # ------------------------------------------------------------------

    @app_commands.command(
        name="concours-creer",
        description="Créer un concours photo (Staff / Admin uniquement)",
    )
    @app_commands.describe(
        nom="Nom du concours",
        date_debut="Date de début (JJ/MM/AAAA HH:MM) heure de Paris",
        date_fin="Date de fin (JJ/MM/AAAA HH:MM) heure de Paris",
        max_photos="Nombre max de photos par personne (défaut 1)",
        salon="Salon où les photos seront postées",
    )
    async def concours_creer(
        self,
        interaction: discord.Interaction,
        nom: str,
        date_debut: str,
        date_fin: str,
        salon: discord.TextChannel,
        max_photos: app_commands.Range[int, 1, 10] = 1,
    ):
        if not await _is_staff_or_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé au staff / administrateurs.", ephemeral=True
            )
            return

        existing = await db.get_active_contest(interaction.guild_id)
        if existing:
            await interaction.response.send_message(
                f"⚠️ Un concours est déjà en cours : **{existing['name']}** "
                f"(fin le {_fmt_local(existing['end_at'])}).\n"
                "Attends sa fin automatique avant d’en créer un autre.",
                ephemeral=True,
            )
            return

        try:
            start_dt = self._parse_user_date(date_debut)
            end_dt = self._parse_user_date(date_fin)
        except ValueError as e:
            await interaction.response.send_message(
                f"❌ Format de date invalide.\nUtilise : `JJ/MM/AAAA HH:MM`\nExemple : `25/12/2025 18:00`\n({e})",
                ephemeral=True,
            )
            return

        if end_dt <= start_dt:
            await interaction.response.send_message(
                "❌ La date de fin doit être après la date de début.", ephemeral=True
            )
            return

        now = datetime.now(timezone.utc)
        if end_dt <= now:
            await interaction.response.send_message(
                "❌ La date de fin est déjà passée.", ephemeral=True
            )
            return

        contest_id = await db.create_contest(
            guild_id=interaction.guild_id,
            name=nom.strip(),
            channel_id=salon.id,
            start_at=start_dt.isoformat(),
            end_at=end_dt.isoformat(),
            max_photos=max_photos,
            created_by=interaction.user.id,
        )

        embed = discord.Embed(
            title=f"📸 Concours : {nom.strip()}",
            description=(
                f"**Salon :** {salon.mention}\n"
                f"**Début :** {_fmt_local(start_dt.isoformat())}\n"
                f"**Fin :** {_fmt_local(end_dt.isoformat())}\n"
                f"**Photos max / personne :** {max_photos}\n\n"
                f"Poste ta photo dans {salon.mention} pendant la durée du concours.\n"
                f"Réagis avec {HEART} pour voter !\n\n"
                f"**Points :**\n"
                f"• +1 participation\n"
                f"• +1 par {HEART}\n"
                f"• Classement : 1er = N pts, 2e = N-1 … (N = nb de participants)\n\n"
                f"À la fin : top 3 annoncé, autres photos supprimées."
            ),
            color=discord.Color.magenta(),
        )
        embed.set_footer(text=f"ID concours #{contest_id}")
        await interaction.response.send_message(embed=embed)

        # Annonce dans le salon du concours
        try:
            await salon.send(
                content="@everyone" if salon.permissions_for(interaction.guild.me).mention_everyone else None,
                embed=embed,
            )
        except discord.Forbidden:
            pass

        log.info(
            "Concours créé #%s « %s » par %s (salon %s)",
            contest_id,
            nom,
            interaction.user.id,
            salon.id,
        )

    def _parse_user_date(self, text: str) -> datetime:
        """JJ/MM/AAAA HH:MM → datetime aware UTC."""
        text = text.strip().replace("-", "/")
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(text, fmt)
                dt = dt.replace(tzinfo=TZ)
                return dt.astimezone(timezone.utc)
            except ValueError:
                continue
        raise ValueError(f"Impossible de parser « {text} »")

    # ------------------------------------------------------------------
    # Points / classement
    # ------------------------------------------------------------------

    @app_commands.command(
        name="points",
        description="Voir le détail de mes points et comment je les ai gagnés",
    )
    async def points_cmd(self, interaction: discord.Interaction):
        total = await db.get_user_points(interaction.guild_id, interaction.user.id)
        history = await db.get_user_points_history(
            interaction.guild_id, interaction.user.id, limit=20
        )

        embed = discord.Embed(
            title=f"⭐ Points de {interaction.user.display_name}",
            description=f"**Total : {total} points**",
            color=discord.Color.blurple(),
        )
        if history:
            lines = []
            for h in history:
                sign = "+" if h["amount"] >= 0 else ""
                when = _fmt_local(h["created_at"])
                lines.append(f"`{sign}{h['amount']}` — {h['reason']} _{when}_")
            embed.add_field(
                name="Historique récent",
                value="\n".join(lines[:15]),
                inline=False,
            )
        else:
            embed.add_field(
                name="Historique",
                value="_Aucun point pour le moment. Participe à un concours !_",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="classement",
        description="Top 10 des personnes ayant le plus de points (paginé)",
    )
    async def classement_cmd(self, interaction: discord.Interaction):
        rows = await db.get_leaderboard(interaction.guild_id, limit=100)
        view = ClassementView(interaction.guild_id, rows, page=0)
        embed = view.build_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="points-retirer",
        description="Retirer des points à un membre (Staff / Admin)",
    )
    @app_commands.describe(
        membre="Membre concerné",
        nombre="Nombre de points à retirer",
        raison="Raison (affichée dans l’historique)",
    )
    async def points_retirer(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        nombre: app_commands.Range[int, 1, 99999],
        raison: str = "Retrait manuel par le staff",
    ):
        if not await _is_staff_or_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé au staff / administrateurs.", ephemeral=True
            )
            return

        removed = await db.remove_points(
            interaction.guild_id,
            membre.id,
            nombre,
            f"{raison} (par {interaction.user.display_name})",
        )
        if removed == 0:
            await interaction.response.send_message(
                f"{membre.mention} n’a pas de points à retirer.", ephemeral=True
            )
            return

        new_total = await db.get_user_points(interaction.guild_id, membre.id)
        await interaction.response.send_message(
            f"✅ **{removed}** point(s) retirés à {membre.mention}.\n"
            f"Nouveau total : **{new_total}** pts.\nRaison : {raison}",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # Retirer une participation
    # ------------------------------------------------------------------

    @app_commands.command(
        name="concours-retirer",
        description="Retirer la participation d'un membre au concours en cours (Staff / Admin)",
    )
    @app_commands.describe(
        membre="Membre dont on retire la participation",
        photo="Numéro de la photo à retirer (si le membre en a posté plusieurs)",
        supprimer_message="Supprimer aussi la photo du salon (défaut : oui)",
    )
    async def concours_retirer(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        photo: Optional[app_commands.Range[int, 1, 10]] = None,
        supprimer_message: bool = True,
    ):
        if not await _is_staff_or_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé au staff / administrateurs.", ephemeral=True
            )
            return

        contest = await db.get_active_contest(interaction.guild_id)
        if not contest:
            await interaction.response.send_message(
                "ℹ️ Aucun concours en cours. Une fois le concours terminé, les points sont déjà attribués : "
                "utilise `/points-retirer` pour les corriger.",
                ephemeral=True,
            )
            return

        entries = await db.get_user_contest_entries(contest["id"], membre.id)
        if not entries:
            await interaction.response.send_message(
                f"ℹ️ {membre.mention} n'a aucune participation au concours **{contest['name']}**.",
                ephemeral=True,
            )
            return

        def _link(e: dict) -> str:
            return f"https://discord.com/channels/{interaction.guild_id}/{e['channel_id']}/{e['message_id']}"

        if photo is None and len(entries) > 1:
            lines = [f"**{i}.** [photo du {_fmt_local(e['created_at'])}]({_link(e)})" for i, e in enumerate(entries, 1)]
            await interaction.response.send_message(
                f"{membre.mention} a **{len(entries)}** participations. Relance la commande avec "
                f"`photo:` (numéro) pour en retirer une :\n" + "\n".join(lines),
                ephemeral=True,
            )
            return

        if photo is None:
            targets = entries
        elif photo > len(entries):
            await interaction.response.send_message(
                f"❌ {membre.mention} n'a que **{len(entries)}** photo(s) dans ce concours.",
                ephemeral=True,
            )
            return
        else:
            targets = [entries[photo - 1]]

        await interaction.response.defer(ephemeral=True)

        deleted_msgs = 0
        for e in targets:
            await db.delete_contest_entry(e["id"])
            if supprimer_message:
                channel = interaction.guild.get_channel(e["channel_id"])
                if channel:
                    try:
                        msg = await channel.fetch_message(e["message_id"])
                        await msg.delete()
                        deleted_msgs += 1
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass

        remaining = await db.count_user_entries(contest["id"], membre.id)
        text = (
            f"✅ Participation retirée pour {membre.mention} au concours **{contest['name']}** "
            f"({len(targets)} photo(s)"
            + (f", {deleted_msgs} message(s) supprimé(s)" if supprimer_message else ", message conservé")
            + f").\nIl/elle peut reposter : {remaining}/{contest['max_photos']} photo(s) utilisée(s)."
        )
        await interaction.followup.send(text, ephemeral=True)
        log.info(
            "Participation concours #%s retirée (membre %s, %s photo(s)) par %s",
            contest["id"], membre.id, len(targets), interaction.user.id,
        )

    # ------------------------------------------------------------------
    # Listener photos
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not message.attachments:
            return

        # Uniquement images
        images = [
            a
            for a in message.attachments
            if (a.content_type and a.content_type.startswith("image/"))
            or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
        ]
        if not images:
            return

        contest = await db.get_active_contest(message.guild.id)
        if not contest:
            return
        if message.channel.id != contest["channel_id"]:
            return

        now = datetime.now(timezone.utc)
        start = _parse_dt(contest["start_at"])
        end = _parse_dt(contest["end_at"])
        if now < start:
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention} Le concours **{contest['name']}** "
                    f"n’a pas encore commencé (début {_fmt_local(contest['start_at'])}).",
                    delete_after=15,
                )
            except discord.Forbidden:
                pass
            return
        if now >= end:
            return  # fin gérée par la task

        count = await db.count_user_entries(contest["id"], message.author.id)
        max_p = contest["max_photos"]
        if count >= max_p:
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention} Tu as déjà posté **{max_p}** photo(s) "
                    f"pour ce concours (maximum atteint).",
                    delete_after=15,
                )
            except discord.Forbidden:
                pass
            return

        # Enregistrer + ajouter ❤️
        await db.add_contest_entry(
            contest_id=contest["id"],
            user_id=message.author.id,
            message_id=message.id,
            channel_id=message.channel.id,
        )
        try:
            await message.add_reaction(HEART)
        except (discord.Forbidden, discord.HTTPException):
            log.warning("Impossible d’ajouter ❤️ sur message %s", message.id)

        remaining = max_p - count - 1
        if remaining > 0:
            try:
                await message.reply(
                    f"✅ Photo enregistrée ! Il te reste **{remaining}** photo(s) possible(s).",
                    delete_after=12,
                    mention_author=False,
                )
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Photo supprimée à la main pendant le concours : on libère la participation (sinon elle compte toujours
        dans le maximum). Sans effet une fois le concours terminé (la fin supprime les photos après l'avoir clôturé)."""
        if not payload.guild_id:
            return
        contest = await db.get_active_contest(payload.guild_id)
        if not contest:
            return
        entry = await db.get_contest_entry_by_message(payload.message_id)
        if entry and entry["contest_id"] == contest["id"]:
            await db.delete_contest_entry(entry["id"])

    # ------------------------------------------------------------------
    # Fin automatique
    # ------------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def check_contests(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        due = await db.list_due_contests(now_iso)
        for contest in due:
            try:
                await self._close_contest(contest)
            except Exception:
                log.exception("Erreur fermeture concours #%s", contest.get("id"))

    @check_contests.before_loop
    async def before_check_contests(self):
        await self.bot.wait_until_ready()

    async def _close_contest(self, contest: dict):
        contest_id = contest["id"]
        guild = self.bot.get_guild(contest["guild_id"])
        if not guild:
            await db.end_contest(contest_id)
            return

        channel = guild.get_channel(contest["channel_id"])
        entries = await db.get_contest_entries(contest_id)

        # Compter les ❤️ réels sur chaque message
        for entry in entries:
            likes = 0
            if channel:
                try:
                    msg = await channel.fetch_message(entry["message_id"])
                    for reaction in msg.reactions:
                        if str(reaction.emoji) == HEART:
                            # On retire le bot s’il a réagi
                            users = [u async for u in reaction.users()]
                            likes = sum(1 for u in users if not u.bot)
                            break
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    likes = 0
            await db.update_entry_likes(entry["id"], likes)
            entry["likes"] = likes

        # Re-trier par likes
        entries.sort(key=lambda e: (-e["likes"], e["id"]))
        n = len(entries)

        # Participants uniques (pour le rang : on classe les entrées, pas les users)
        # Si quelqu’un a plusieurs photos, chaque photo est une entrée séparée.
        # Points de rang : 1er (plus de likes) = N, 2e = N-1, etc. (N = nb d’entrées)
        for rank, entry in enumerate(entries, start=1):
            pts_part = 1
            pts_likes = entry["likes"]
            pts_rank = max(0, n - rank + 1)
            total = pts_part + pts_likes + pts_rank

            await db.update_entry_results(
                entry["id"],
                rank=rank,
                points_participation=pts_part,
                points_likes=pts_likes,
                points_rank=pts_rank,
            )
            await db.add_points(
                guild_id=contest["guild_id"],
                user_id=entry["user_id"],
                amount=total,
                reason=(
                    f"Concours « {contest['name']} » — "
                    f"#{rank} ({entry['likes']} ❤️) "
                    f"+{pts_part} part. +{pts_likes} likes +{pts_rank} rang"
                ),
                contest_id=contest_id,
            )
            entry["rank"] = rank
            entry["total_pts"] = total

        await db.end_contest(contest_id)

        # Annonce top 3
        top3 = entries[:3]
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, e in enumerate(top3):
            member = guild.get_member(e["user_id"])
            name = member.mention if member else f"<@{e['user_id']}>"
            lines.append(
                f"{medals[i]} {name} — **{e['likes']}** ❤️ "
                f"(+{e['total_pts']} pts)"
            )
        if not lines:
            lines = ["_Aucune participation._"]

        embed = discord.Embed(
            title=f"🏁 Concours terminé : {contest['name']}",
            description=(
                f"**Top 3 :**\n" + "\n".join(lines) + "\n\n"
                f"Participants (photos) : **{n}**\n"
                f"Les autres photos ont été supprimées.\n"
                f"Utilise `/points` et `/classement` pour voir les scores."
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Concours #{contest_id}")

        if channel:
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                log.warning("Impossible d’annoncer le concours #%s", contest_id)

            # Supprimer toutes les photos sauf top 3
            keep_ids = {e["message_id"] for e in top3}
            for entry in entries:
                if entry["message_id"] in keep_ids:
                    continue
                try:
                    msg = await channel.fetch_message(entry["message_id"])
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        log.info(
            "Concours #%s « %s » terminé — %s entrées, top3 annoncé",
            contest_id,
            contest["name"],
            n,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Concours(bot))