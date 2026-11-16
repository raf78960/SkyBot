"""
Guide des rôles SkyCommunity — embeds postables.
Chaque poste du guide est lié à un **rôle Discord** : les membres ayant ce rôle
sont listés automatiquement.
"""

from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import database as db

SKY_COLOR = 0x1E90FF
MAX_MENTIONS_PER_SLOT = 40
# Discord : somme des textes de TOUS les embeds d'un message ≤ 6000.
# Guide rôles : pas de footer hébergeur.
_MAX_DESC = 3900
_MAX_MSG_CHARS = 5800

ROLE_SLOTS: dict[str, dict] = {
    "fondateur": {
        "emoji": "👑",
        "label": "Fondateur",
        "section": "direction",
        "desc": (
            "Créateur de SkyCommunity. Il supervise le serveur dans son ensemble "
            "et prend les décisions importantes concernant son fonctionnement et son évolution."
        ),
    },
    "administrateur": {
        "emoji": "🛡️",
        "label": "Administrateur",
        "section": "direction",
        "desc": (
            "Gère l'administration du serveur, veille à son bon fonctionnement "
            "et intervient sur les problèmes importants ou les décisions administratives."
        ),
    },
    "responsable_staff": {
        "emoji": "👥",
        "label": "Responsable Staff",
        "section": "direction",
        "desc": (
            "Gère l'ensemble de l'effectif Staff : helpeurs, modérateurs, administrateurs, "
            "développeurs, marketing et responsables des différents pôles.\n"
            "Pour toute question concernant le Staff ou son organisation, c'est la personne à contacter."
        ),
    },
    "responsable_atc": {
        "emoji": "🎧",
        "label": "Responsable ATC",
        "section": "responsables",
        "desc": (
            "Gère l'équipe des contrôleurs aériens (ATC), leur activité, "
            "leur organisation et le suivi des ouvertures."
        ),
    },
    "responsable_pilotes": {
        "emoji": "✈️",
        "label": "Responsable Pilotes",
        "section": "responsables",
        "desc": "Gère l'effectif des pilotes et veille à leur suivi et à leur activité.",
    },
    "responsable_instructeurs": {
        "emoji": "🎓",
        "label": "Responsable Instructeurs",
        "section": "responsables",
        "desc": (
            "Gère les instructeurs, les formations et l'organisation "
            "des différents parcours de formation."
        ),
    },
    "responsable_ceo": {
        "emoji": "🏢",
        "label": "Responsable CEO",
        "section": "responsables",
        "desc": "Gère les CEO et veille au suivi de leurs activités et de leur organisation.",
    },
    "responsable_evenements": {
        "emoji": "🎉",
        "label": "Responsable Événements",
        "section": "responsables",
        "desc": (
            "Organise et supervise les événements SkyCommunity, "
            "notamment les événements ATC et les vols en groupe."
        ),
    },
    "developpeur": {
        "emoji": "💻",
        "label": "Développeur",
        "section": "equipes",
        "desc": (
            "Travaille sur le développement technique de SkyCommunity, "
            "ses outils, ses sites et ses différentes fonctionnalités."
        ),
    },
    "marketing": {
        "emoji": "📢",
        "label": "Marketing",
        "section": "equipes",
        "desc": (
            "S'occupe de la communication, de la visibilité "
            "et de la création de contenu autour de SkyCommunity."
        ),
    },
    "moderateur": {
        "emoji": "🔨",
        "label": "Modérateur",
        "section": "equipes",
        "desc": (
            "Veille au respect du règlement, intervient en cas de problème "
            "entre membres et assure la modération du serveur."
        ),
    },
    "helpeur": {
        "emoji": "🤝",
        "label": "Helpeur",
        "section": "equipes",
        "desc": (
            "Accompagne les membres, répond à leurs questions "
            "et les aide à utiliser les différents services de SkyCommunity."
        ),
    },
    "instructeur_atc": {
        "emoji": "🎧",
        "label": "Instructeur ATC",
        "section": "formation",
        "desc": "Forme et accompagne les futurs contrôleurs aériens dans leur apprentissage de l'ATC.",
    },
    "instructeur_pilote": {
        "emoji": "✈️",
        "label": "Instructeur Pilote",
        "section": "formation",
        "desc": "Accompagne et forme les pilotes dans leur apprentissage et leur progression.",
    },
    "ceo": {
        "emoji": "🏢",
        "label": "CEO",
        "section": "membres",
        "desc": "Membres occupant une fonction de direction au sein de leur compagnie aérienne virtuelle.",
    },
    "atc": {
        "emoji": "🎧",
        "label": "ATC",
        "section": "membres",
        "desc": "Contrôleurs aériens qui assurent les ouvertures de fréquences et la gestion du trafic aérien.",
    },
    "pilote": {
        "emoji": "🛫",
        "label": "Pilote",
        "section": "membres",
        "desc": "Membres qui participent aux vols et aux différentes activités aéronautiques de SkyCommunity.",
    },
}

SECTION_TITLES = {
    "direction": "🔹 DIRECTION",
    "responsables": "🔹 RESPONSABLES",
    "equipes": "🔹 ÉQUIPES",
    "formation": "🔹 FORMATION",
    "membres": "🔹 MEMBRES",
}

SECTION_ORDER = ["direction", "responsables", "equipes", "formation", "membres"]

SLOT_CHOICES = [
    app_commands.Choice(name=f"{v['emoji']} {v['label']}", value=k)
    for k, v in ROLE_SLOTS.items()
]


def _members_for_role(guild: discord.Guild, role: discord.Role | None) -> list[discord.Member]:
    if not role:
        return []
    members = [m for m in role.members if not m.bot]
    members.sort(key=lambda m: (m.display_name or m.name).lower())
    return members


def _format_members(members: list[discord.Member], role: discord.Role | None) -> str:
    if role is None:
        return "*Rôle Discord non configuré*"
    if not members:
        return f"{role.mention} — *aucun membre*"
    shown = members[:MAX_MENTIONS_PER_SLOT]
    parts = [m.mention for m in shown]
    extra = len(members) - len(shown)
    text = " · ".join(parts)
    if extra > 0:
        text += f" · *+{extra} autre(s)*"
    text = f"{role.mention} ({len(members)})\n{text}"
    return text


def _mark_no_hosting_footer(embed: discord.Embed) -> discord.Embed:
    """Exclut cet embed du footer M-Heberge (guide rôles uniquement)."""
    # Embed a __slots__ → registre class-level posé par bot.py
    ids = getattr(discord.Embed, "_sky_skip_hosting_ids", None)
    if ids is None:
        discord.Embed._sky_skip_hosting_ids = set()  # type: ignore[attr-defined]
        ids = discord.Embed._sky_skip_hosting_ids  # type: ignore[attr-defined]
    ids.add(id(embed))
    return embed


def _embed_text_size(embed: discord.Embed) -> int:
    """Estimation de la taille texte d'un embed (limites Discord 6000)."""
    n = 0
    if embed.title:
        n += len(embed.title)
    if embed.description:
        n += len(embed.description)
    if embed.footer and embed.footer.text:
        n += len(embed.footer.text)
    if embed.author and embed.author.name:
        n += len(embed.author.name)
    for field in embed.fields:
        n += len(field.name or "") + len(field.value or "")
    return n


def _chunk_embeds_by_size(
    embeds: list[discord.Embed], max_chars: int = _MAX_MSG_CHARS, max_per_msg: int = 10
) -> list[list[discord.Embed]]:
    """Regroupe les embeds sans dépasser la limite globale Discord (6000 car.)."""
    batches: list[list[discord.Embed]] = []
    current: list[discord.Embed] = []
    size = 0
    for emb in embeds:
        cost = _embed_text_size(emb)
        if current and (size + cost > max_chars or len(current) >= max_per_msg):
            batches.append(current)
            current = []
            size = 0
        current.append(emb)
        size += cost
    if current:
        batches.append(current)
    return batches


def _build_guide_embeds(
    guild: discord.Guild, role_map: dict[str, int]
) -> list[discord.Embed]:
    embeds: list[discord.Embed] = []

    intro = discord.Embed(
        title="📖 GUIDE DES RÔLES — SKYCOMMUNITY",
        description=(
            "Bienvenue dans le guide des rôles de SkyCommunity !\n"
            "Tu trouveras ici les **missions** de chaque rôle et **à qui t'adresser** "
            "selon ta question ou ton problème.\n\n"
            "Les personnes listées sont celles qui ont le **rôle Discord** correspondant "
            "(mis à jour à chaque republication du guide)."
        ),
        color=SKY_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embeds.append(intro)

    for section in SECTION_ORDER:
        lines: list[str] = []
        for key, meta in ROLE_SLOTS.items():
            if meta["section"] != section:
                continue
            rid = role_map.get(key)
            role = guild.get_role(rid) if rid else None
            members = _members_for_role(guild, role)
            holders = _format_members(members, role)
            lines.append(
                f"**{meta['emoji']} {meta['label']}** — {holders}\n"
                f"{meta['desc']}"
            )
        if not lines:
            continue
        body = "\n\n".join(lines)
        if len(body) <= _MAX_DESC:
            embeds.append(
                discord.Embed(
                    title=SECTION_TITLES[section],
                    description=body,
                    color=SKY_COLOR,
                )
            )
        else:
            chunk: list[str] = []
            size = 0
            part = 1
            for line in lines:
                add = len(line) + 2
                if chunk and size + add > _MAX_DESC:
                    embeds.append(
                        discord.Embed(
                            title=f"{SECTION_TITLES[section]} ({part})",
                            description="\n\n".join(chunk),
                            color=SKY_COLOR,
                        )
                    )
                    chunk = []
                    size = 0
                    part += 1
                chunk.append(line)
                size += add
            if chunk:
                title = SECTION_TITLES[section] if part == 1 else f"{SECTION_TITLES[section]} ({part})"
                embeds.append(
                    discord.Embed(title=title, description="\n\n".join(chunk), color=SKY_COLOR)
                )

    embeds.append(
        discord.Embed(
            title="🔹 AUTRES RÔLES",
            description=(
                "**🤖 Agent**\n"
                "Bot officiel de SkyCommunity. Il permet d'assurer certaines "
                "fonctionnalités et automatisations du serveur.\n\n"
                "**⭐ Staff**\n"
                "Rôle regroupant les helpeurs, les modérateurs, les administrateurs "
                "ainsi que le fondateur."
            ),
            color=SKY_COLOR,
        )
    )

    contact = discord.Embed(
        title="❓ QUI CONTACTER SELON MON PROBLÈME ?",
        description=(
            "• **Problème avec un membre / modération** → Helpeur ou Modérateur\n"
            "• **Question concernant le Staff** → Responsable Staff\n"
            "• **Ouvertures ATC** → Responsable ATC\n"
            "• **Pilotes** → Responsable Pilotes\n"
            "• **Formation** → Responsable Instructeurs\n"
            "• **Compagnie virtuelle** → Responsable CEO\n"
            "• **Événement** → Responsable Événements\n"
            "• **Problème technique / bug** → Développeur\n"
            "• **Communication** → Marketing\n"
            "• **Problème important / administratif** → Administrateur ou Fondateur\n\n"
            "**Merci de vous adresser directement aux personnes concernées "
            "afin de faciliter le suivi de vos demandes !**"
        ),
        color=SKY_COLOR,
    )
    contact.set_footer(text="SkyCommunity • Guide des rôles")
    embeds.append(contact)

    # Pas de footer M-Heberge sur le guide (trop d'embeds / limite 6000)
    return [_mark_no_hosting_footer(e) for e in embeds]


async def _is_admin_or_staff(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    conf = await db.get_guild_config(interaction.guild_id) or {}
    rid = conf.get("staff_role_id")
    if not rid:
        return False
    role = interaction.guild.get_role(int(rid))
    return bool(role and role in interaction.user.roles)


class RoleGuide(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="guide-roles-set",
        description="Lier un poste du guide à un rôle Discord (membres listés auto)",
    )
    @app_commands.describe(
        poste="Poste affiché dans le guide",
        role_discord="Rôle Discord dont les membres seront listés",
    )
    @app_commands.choices(poste=SLOT_CHOICES)
    async def guide_roles_set(
        self,
        interaction: discord.Interaction,
        poste: app_commands.Choice[str],
        role_discord: discord.Role,
    ):
        if not await _is_admin_or_staff(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux admins et au staff.", ephemeral=True
            )
            return

        await db.set_role_guide_discord_role(
            interaction.guild_id, poste.value, role_discord.id
        )
        members = _members_for_role(interaction.guild, role_discord)
        meta = ROLE_SLOTS[poste.value]
        preview = _format_members(members, role_discord)
        await interaction.response.send_message(
            f"✅ **{meta['emoji']} {meta['label']}** lié à {role_discord.mention}\n"
            f"{preview}\n\n"
            f"_Relance `/guide-roles-poster` pour actualiser le guide public._",
            ephemeral=True,
        )

    @app_commands.command(
        name="guide-roles-clear",
        description="Retirer le rôle Discord d'un poste du guide",
    )
    @app_commands.describe(poste="Poste à réinitialiser")
    @app_commands.choices(poste=SLOT_CHOICES)
    async def guide_roles_clear(
        self,
        interaction: discord.Interaction,
        poste: app_commands.Choice[str],
    ):
        if not await _is_admin_or_staff(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux admins et au staff.", ephemeral=True
            )
            return
        await db.clear_role_guide_assignment(interaction.guild_id, poste.value)
        meta = ROLE_SLOTS[poste.value]
        await interaction.response.send_message(
            f"✅ **{meta['emoji']} {meta['label']}** : plus de rôle Discord lié.",
            ephemeral=True,
        )

    @app_commands.command(
        name="guide-roles-voir",
        description="Aperçu du guide des rôles (éphémère)",
    )
    async def guide_roles_voir(self, interaction: discord.Interaction):
        if not await _is_admin_or_staff(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux admins et au staff.", ephemeral=True
            )
            return
        role_map = await db.get_all_role_guide_discord_roles(interaction.guild_id)
        embeds = _build_guide_embeds(interaction.guild, role_map)
        # Ephemeral : max 10 embeds, et total ≤ 6000 car. → lots par taille
        batches = _chunk_embeds_by_size(embeds)
        first, *rest = batches
        await interaction.response.send_message(embeds=first, ephemeral=True)
        for batch in rest:
            await interaction.followup.send(embeds=batch, ephemeral=True)

    @app_commands.command(
        name="guide-roles-poster",
        description="Publier (ou republier) le guide des rôles dans ce salon",
    )
    async def guide_roles_poster(self, interaction: discord.Interaction):
        if not await _is_admin_or_staff(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux admins et au staff.", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ À utiliser dans un salon texte.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        role_map = await db.get_all_role_guide_discord_roles(interaction.guild_id)
        embeds = _build_guide_embeds(interaction.guild, role_map)

        conf = await db.get_guild_config(interaction.guild_id) or {}
        old_channel_id = conf.get("role_guide_channel_id")
        old_msg_ids = db.parse_id_list(conf.get("role_guide_message_ids"))

        if old_channel_id and old_msg_ids:
            old_ch = interaction.guild.get_channel(int(old_channel_id))
            if old_ch:
                for mid in old_msg_ids:
                    try:
                        msg = await old_ch.fetch_message(mid)
                        await msg.delete()
                    except Exception:
                        pass

        sent_ids: list[int] = []
        for chunk in _chunk_embeds_by_size(embeds):
            msg = await interaction.channel.send(embeds=chunk)
            sent_ids.append(msg.id)

        await db.set_role_guide_panel(
            interaction.guild_id, interaction.channel.id, sent_ids
        )
        await interaction.followup.send(
            f"✅ Guide publié dans {interaction.channel.mention} "
            f"({len(embeds)} embeds, {len(sent_ids)} message(s)).\n"
            f"Les membres sont ceux qui ont le rôle Discord lié à chaque poste.\n"
            f"Après un changement de rôles Discord, relance `/guide-roles-poster` "
            f"pour rafraîchir la liste.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleGuide(bot))
