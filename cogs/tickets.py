"""
Système de tickets multi-serveurs :
- Serveur principal : Accès + Support (+ disponibilités entretiens)
- Serveurs compagnies : Candidature / Formation / Support
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import database as db


TICKET_TYPES = {
    "access": {
        "label": "Ticket Accès",
        "emoji": "🔑",
        "color": discord.Color.blurple(),
        "prefix": "acces",
    },
    "support": {
        "label": "Ticket Support",
        "emoji": "🛠️",
        "color": discord.Color.blue(),  # même bleu que les embeds ATIS
        "prefix": "support",
    },
    # Types pour les serveurs de compagnies (SkyAirlines)
    "candidature": {
        "label": "Ticket Candidature",
        "emoji": "📩",
        "color": discord.Color.green(),
        "prefix": "candidature",
    },
    "formation": {
        "label": "Ticket Formation",
        "emoji": "🎓",
        "color": discord.Color.gold(),
        "prefix": "formation",
    },
}

# Motifs tickets Support (menu déroulant)
SUPPORT_MOTIFS = [
    {
        "value": "signalement",
        "label": "Signalement",
        "description": "Signaler un comportement ou un problème sur le serveur.",
        "emoji": "🚨",
    },
    {
        "value": "formation",
        "label": "Formation",
        "description": "Pour toute question concernant les formations.",
        "emoji": "🎓",
    },
    {
        "value": "candidature",
        "label": "Candidature",
        "description": "Pour rejoindre le staff ou proposer sa candidature.",
        "emoji": "📝",
    },
    {
        "value": "partenariat",
        "label": "Partenariat",
        "description": "Pour toute demande de partenariat.",
        "emoji": "🤝",
    },
    {
        "value": "autre",
        "label": "Autre demande",
        "description": "Toute demande qui ne correspond pas aux autres catégories.",
        "emoji": "💬",
    },
]

SUPPORT_MOTIF_LABELS = {m["value"]: m["label"] for m in SUPPORT_MOTIFS}


# Logo SkyCommunity (bas de l'embed panneau Accès). Définir via .env si besoin.
import os
SKYCOMMUNITY_LOGO_URL = os.getenv(
    "SKYCOMMUNITY_LOGO_URL",
    "",
)


def _sanitize_channel_part(text: str) -> str:
    """Nettoie un pseudo pour un nom de salon Discord."""
    text = (text or "user").lower().replace(" ", "-")
    # Garder lettres, chiffres, tirets, underscores
    cleaned = "".join(c for c in text if c.isalnum() or c in "-_")
    return cleaned[:20] or "user"


def _ticket_channel_name(
    ticket_type: str,
    user_name: str,
    staff_name: str | None = None,
    *,
    has_dispos: bool = False,
) -> str:
    """
    🔴-acces-pseudo     → pas de disponibilités données
    🟠-acces-pseudo     → dispos données, pas encore pris en charge
    🟢-acces-nomstaff   → dispos données + pris en charge (nom du staff)
    """
    meta = TICKET_TYPES.get(ticket_type, TICKET_TYPES["support"])
    prefix = meta["prefix"]
    if staff_name:
        staff_part = _sanitize_channel_part(staff_name)
        return f"🟢-{prefix}-{staff_part}"[:100]
    user_part = _sanitize_channel_part(user_name)
    if has_dispos:
        return f"🟠-{prefix}-{user_part}"[:100]
    return f"🔴-{prefix}-{user_part}"[:100]


async def _send_ticket_log(
    guild: discord.Guild,
    *,
    action: str,
    ticket: dict,
    actor: discord.abc.User,
    extra: str | None = None,
):
    """Log ticket dans le salon dédié au type (accès / support), avec repli sur le log global."""
    conf = await db.get_guild_config(guild.id) or {}
    ticket_type = ticket.get("ticket_type")
    if ticket_type == "access":
        log_ch_id = conf.get("ticket_access_log_channel_id") or conf.get(
            "ticket_log_channel_id"
        )
    elif ticket_type == "support":
        log_ch_id = conf.get("ticket_support_log_channel_id") or conf.get(
            "ticket_log_channel_id"
        )
    else:
        log_ch_id = conf.get("ticket_log_channel_id")
    if not log_ch_id:
        return
    log_ch = guild.get_channel(log_ch_id)
    if not log_ch:
        return

    meta = TICKET_TYPES.get(ticket_type, {})
    type_label = meta.get("label", ticket_type or "?")
    type_emoji = meta.get("emoji", "🎫")

    tid = ticket.get("id")
    uid = ticket.get("user_id")
    cid = ticket.get("channel_id")

    if action == "open":
        title = "🗂️ Logs — Ticket ouvert"
        color = discord.Color.green()
        lines = [
            f"{type_emoji} **{type_label}** `#{tid}`",
            f"**Créateur :** <@{uid}>",
            f"**Salon :** <#{cid}>",
        ]
        if ticket.get("motif"):
            motif_label = SUPPORT_MOTIF_LABELS.get(ticket["motif"], ticket["motif"])
            lines.append(f"**Motif :** {motif_label}")
    elif action == "claim":
        title = "🗂️ Logs — Ticket pris en charge"
        color = discord.Color.gold()
        lines = [
            f"{type_emoji} **{type_label}** `#{tid}`",
            f"**Créateur :** <@{uid}>",
            f"**Pris en charge par :** {actor.mention}",
            f"**Salon :** <#{cid}>",
        ]
    elif action == "close":
        title = "🗂️ Logs — Ticket fermé"
        color = discord.Color.dark_grey()
        claimed = f"<@{ticket['claimed_by']}>" if ticket.get("claimed_by") else "Personne"
        lines = [
            f"{type_emoji} **{type_label}** `#{tid}`",
            f"**Créateur :** <@{uid}>",
            f"**Fermé par :** {actor.mention}",
            f"**Avait été pris en charge par :** {claimed}",
        ]
        if ticket.get("close_reason"):
            lines.append(f"**Motif de fermeture :** {ticket['close_reason']}")
        if ticket.get("motif"):
            motif_label = SUPPORT_MOTIF_LABELS.get(ticket["motif"], ticket["motif"])
            lines.append(f"**Motif d'ouverture :** {motif_label}")
    else:
        title = "🗂️ Logs — Ticket"
        color = discord.Color.dark_grey()
        lines = [f"Ticket `#{tid}` — action `{action}` par {actor.mention}"]

    if extra:
        lines.append(extra)

    embed = discord.Embed(
        title=title,
        description=chr(10).join(lines),
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=f"ID ticket : {tid}")
    try:
        await log_ch.send(embed=embed)
    except discord.HTTPException:
        pass


ACCESS_PANEL_TITLE = "✈️ ACCÈS À SKYCOMMUNITY"
ACCESS_PANEL_DESCRIPTION = (
    "Bienvenue sur **SkyCommunity**, une communauté dédiée à la simulation aérienne "
    "sur Microsoft Flight Simulator et au contrôle aérien.\n\n"
    "Avant d’accéder à l’ensemble du serveur, chaque nouveau membre passe par une "
    "courte étape d’accueil afin que nous puissions mieux connaître votre expérience "
    "et vous orienter vers le parcours adapté à votre niveau.\n\n"
    "**📋 Comment ça fonctionne ?**\n\n"
    "**1️⃣ Répondez aux questions d’arrivée**\n"
    "Elles permettent de nous renseigner sur votre plateforme, votre simulateur "
    "et les langues que vous utilisez.\n\n"
    "**2️⃣ Ouvrez votre ticket d’accès**\n"
    "Cliquez sur le bouton ci-dessous afin de contacter notre équipe.\n\n"
    "**3️⃣ Passez un court entretien**\n"
    "Indiquez vos disponibilités **directement dans le ticket d’accès**, puis un membre "
    "du staff échangera avec vous pendant quelques minutes afin d’évaluer votre expérience "
    "sur le simulateur et vos connaissances.\n\n"
    "**4️⃣ Accédez au parcours adapté**\n"
    "Selon votre niveau, vous pourrez :\n"
    "✈️ être orienté vers une Formation Avion ;\n"
    "🎙️ suivre une Formation Pilote ;\n"
    "📡 suivre une Formation ATC ;\n"
    "✅ ou obtenir directement l’accès au serveur si vous avez déjà le niveau requis.\n\n"
    "**🚀 Envie de commencer ?**\n"
    "Cliquez sur le bouton ci-dessous pour commencer votre parcours d’arrivée.\n\n"
    "Pas besoin d’avoir un niveau particulier pour rejoindre SkyCommunity. "
    "Que vous soyez débutant ou expérimenté, notre équipe vous orientera simplement "
    "vers le parcours correspondant à votre niveau."
)


async def _is_staff(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    conf = await db.get_guild_config(interaction.guild_id)
    if conf and conf.get("staff_role_id"):
        role = interaction.guild.get_role(conf["staff_role_id"])
        if role and role in interaction.user.roles:
            return True
    return False


def _require_admin_or_staff():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        if interaction.guild is None:
            return False
        conf = await db.get_guild_config(interaction.guild_id)
        if conf and conf.get("staff_role_id"):
            role = interaction.guild.get_role(conf["staff_role_id"])
            if role and role in interaction.user.roles:
                return True
        raise app_commands.MissingPermissions(["Administrator or staff role"])

    return app_commands.check(predicate)


async def _resolve_ticket_status_for_dispos(dispos: dict) -> str:
    """Retourne 'open' ou 'closed' selon le ticket lié (défaut open si inconnu)."""
    ch_id = dispos.get("ticket_channel_id")
    if not ch_id:
        return "open"
    ticket = await db.get_ticket_by_channel(ch_id)
    if not ticket:
        return "closed"
    return ticket.get("status") or "open"


async def _build_dispos_embed(dispos: dict, ticket_status: str | None = None) -> discord.Embed:
    """
    Couleurs :
      - Vert  : ticket ouvert et entretien pas encore pris en charge
      - Orange: ticket pris en charge, toujours ouvert
      - Rouge : ticket fermé
    """
    status = dispos.get("status", "pending")
    if ticket_status is None:
        ticket_status = await _resolve_ticket_status_for_dispos(dispos)

    if ticket_status == "closed":
        color = discord.Color.red()
    elif status == "taken":
        color = discord.Color.orange()
    else:
        color = discord.Color.green()

    embed = discord.Embed(
        title="📅 Disponibilités entretien",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="Membre",
        value=f"<@{dispos['target_user_id']}>",
        inline=True,
    )
    embed.add_field(
        name="Demandé par",
        value=f"<@{dispos['requested_by']}>",
        inline=True,
    )
    embed.add_field(
        name="Disponibilités",
        value=dispos["dispos_text"] or "—",
        inline=False,
    )
    if dispos.get("commentaire"):
        embed.add_field(
            name="Commentaire",
            value=dispos["commentaire"],
            inline=False,
        )
    if dispos.get("ticket_channel_id"):
        embed.add_field(
            name="Ticket",
            value=f"<#{dispos['ticket_channel_id']}>",
            inline=False,
        )

    if status == "taken" and dispos.get("taken_by"):
        entretien_txt = f"✅ **Pris en charge par** <@{dispos['taken_by']}>"
    else:
        entretien_txt = "⏳ En attente de prise en charge"
    embed.add_field(name="Statut de l'entretien", value=entretien_txt, inline=False)

    ticket_txt = "🔴 **Fermé**" if ticket_status == "closed" else "🟢 **Ouvert**"
    embed.add_field(name="Statut du ticket", value=ticket_txt, inline=False)

    embed.set_footer(text=f"ID dispos : {dispos['id']}")
    return embed


async def _refresh_dispos_embeds_for_ticket(bot, ticket_channel_id: int):
    """Met à jour les embeds dispos liés à un ticket (ex. après fermeture → rouge)."""
    dispos_list = await db.list_disponibilites_by_ticket_channel(ticket_channel_id)
    for dispos in dispos_list:
        ch_id = dispos.get("channel_id")
        msg_id = dispos.get("message_id")
        if not ch_id or not msg_id:
            continue
        channel = bot.get_channel(ch_id)
        if not channel:
            continue
        try:
            msg = await channel.fetch_message(msg_id)
            embed = await _build_dispos_embed(dispos, ticket_status="closed")
            view = DisponibilitesStaffView(dispos["id"])
            bot.add_view(view)
            await msg.edit(embed=embed, view=view)
        except (discord.NotFound, discord.HTTPException):
            pass


class CloseTicketModal(discord.ui.Modal, title="Motif de fermeture"):
    reason = discord.ui.TextInput(
        label="Motif de fermeture",
        style=discord.TextStyle.paragraph,
        placeholder="Ex : Entretien terminé, accès accordé, demande résolue…",
        max_length=500,
        required=True,
    )

    def __init__(self, ticket_id: int):
        super().__init__()
        self.ticket_id = ticket_id

    async def on_submit(self, interaction: discord.Interaction):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message("Ticket déjà fermé.", ephemeral=True)
            return
        reason = (self.reason.value or "").strip()
        await db.close_ticket(ticket["id"], close_reason=reason)
        ticket["close_reason"] = reason
        await interaction.response.send_message(
            f"🔒 Ticket fermé par {interaction.user.mention}.\n"
            f"**Motif :** {reason}\n"
            f"Suppression dans 5 secondes…"
        )
        await _send_ticket_log(
            interaction.guild,
            action="close",
            ticket=ticket,
            actor=interaction.user,
        )
        await _refresh_dispos_embeds_for_ticket(interaction.client, interaction.channel_id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(
                reason=f"Ticket fermé par {interaction.user} — {reason}"
            )
        except discord.HTTPException:
            pass


async def _close_ticket_interaction(interaction: discord.Interaction):
    """Ouvre le modal de motif de fermeture (bouton ou préparation commande)."""
    if not await _is_staff(interaction):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket or ticket["user_id"] != interaction.user.id:
            await interaction.response.send_message(
                "🚫 Seul le staff ou le créateur peut fermer.", ephemeral=True
            )
            return
    ticket = await db.get_ticket_by_channel(interaction.channel_id)
    if not ticket or ticket["status"] != "open":
        await interaction.response.send_message("Ticket déjà fermé.", ephemeral=True)
        return
    await interaction.response.send_modal(CloseTicketModal(ticket["id"]))


async def _ask_disponibilites(interaction: discord.Interaction):
    """Demande les disponibilités au membre du ticket (bouton ou slash)."""
    # defer si possible (slash) — les boutons n'ont pas encore répondu
    if interaction.response.is_done():
        send = interaction.followup.send
    else:
        # bouton : on répond via followup après defer
        await interaction.response.defer(ephemeral=False)
        send = interaction.followup.send

    if not await _is_staff(interaction):
        await send("🚫 Staff uniquement.", ephemeral=True)
        return

    ticket = await db.get_ticket_by_channel(interaction.channel_id)
    if not ticket:
        await send(
            "Cette action s'utilise **dans un salon ticket**.", ephemeral=True
        )
        return

    member = interaction.guild.get_member(ticket["user_id"])
    if not member:
        await send("Membre introuvable sur le serveur.", ephemeral=True)
        return

    view = AskDisposView(member.id, interaction.user.id)
    await send(
        content=(
            f"{member.mention}, le staff souhaite connaître tes **disponibilités** "
            f"pour un entretien.\nClique sur le bouton ci-dessous pour les indiquer."
        ),
        view=view,
    )


class TicketCloseView(discord.ui.View):
    """Vue tickets Support : Fermer + Prendre en charge."""

    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.children[0].custom_id = f"ticket_close_{ticket_id}"
        self.children[1].custom_id = f"ticket_claim_{ticket_id}"

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, emoji="🔒")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _close_ticket_interaction(interaction)

    @discord.ui.button(label="Prendre en charge", style=discord.ButtonStyle.success, emoji="✋")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _is_staff(interaction):
            await interaction.response.send_message("🚫 Staff uniquement.", ephemeral=True)
            return
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message("Ticket introuvable ou fermé.", ephemeral=True)
            return
        await db.claim_ticket(ticket["id"], interaction.user.id)

        # Renommer le salon : 🟢 + nom du staff
        creator = interaction.guild.get_member(ticket["user_id"])
        creator_name = creator.name if creator else str(ticket["user_id"])
        new_name = _ticket_channel_name(
            ticket["ticket_type"], creator_name, interaction.user.name
        )
        try:
            await interaction.channel.edit(
                name=new_name,
                reason=f"Pris en charge par {interaction.user}",
            )
        except discord.HTTPException:
            pass

        ticket = await db.get_ticket_by_channel(interaction.channel_id) or ticket
        await _send_ticket_log(
            interaction.guild,
            action="claim",
            ticket=ticket,
            actor=interaction.user,
        )

        await interaction.response.send_message(
            f"✋ {interaction.user.mention} a pris en charge ce ticket."
        )


class TicketAccessCloseView(discord.ui.View):
    """Vue tickets Accès : Fermer + Donner mes disponibilités (membre)."""

    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.children[0].custom_id = f"ticket_close_access_{ticket_id}"
        self.children[1].custom_id = f"ticket_dispos_{ticket_id}"

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, emoji="🔒")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _close_ticket_interaction(interaction)

    @discord.ui.button(
        label="Donner mes disponibilités",
        style=discord.ButtonStyle.primary,
        emoji="📅",
    )
    async def dispos_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Le membre du ticket indique ses dispos directement (pas le staff)."""
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message(
                "Ticket introuvable ou fermé.", ephemeral=True
            )
            return
        # Membre du ticket OU staff (au cas où)
        if interaction.user.id != ticket["user_id"] and not await _is_staff(interaction):
            await interaction.response.send_message(
                "Ce bouton est réservé au membre du ticket.", ephemeral=True
            )
            return
        member = interaction.guild.get_member(ticket["user_id"]) or interaction.user
        # requested_by = le membre lui-même s'il clique, sinon le staff
        staff_or_self = interaction.user
        await interaction.response.send_modal(
            DisponibilitesModal(member, staff_or_self)
        )


class TicketPanelView(discord.ui.View):
    """Panel permanent Support uniquement (l'accès a son propre panneau)."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SupportMotifSelect())

    async def _open_ticket(
        self,
        interaction: discord.Interaction,
        ticket_type: str,
        motif: str | None = None,
    ):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        send = interaction.followup.send

        existing = await db.get_open_ticket_for_user(
            interaction.guild_id, interaction.user.id, ticket_type
        )
        if existing:
            await send(
                f"Tu as déjà un ticket ouvert : <#{existing['channel_id']}>",
                ephemeral=True,
            )
            return

        conf = await db.get_guild_config(interaction.guild_id) or {}
        meta = TICKET_TYPES[ticket_type]
        # Accès → catégorie accès ; le reste (support + compagnie) → catégorie support
        cat_key = (
            "ticket_access_category_id"
            if ticket_type == "access"
            else "ticket_support_category_id"
        )
        category = None
        if conf.get(cat_key):
            category = interaction.guild.get_channel(conf[cat_key])

        staff_role = None
        if conf.get("staff_role_id"):
            staff_role = interaction.guild.get_role(conf["staff_role_id"])

        # Plus de ping du rôle Staff à l'ouverture : uniquement le créateur
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True, read_message_history=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        name = _ticket_channel_name(ticket_type, interaction.user.name)
        try:
            channel = await interaction.guild.create_text_channel(
                name=name,
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason=f"Ticket {ticket_type} — {interaction.user}",
            )
        except discord.HTTPException as e:
            await send(f"❌ Impossible de créer le salon : {e}", ephemeral=True)
            return

        ticket_id = await db.create_ticket(
            interaction.guild_id,
            channel.id,
            interaction.user.id,
            ticket_type,
            motif=motif,
        )
        if ticket_type == "access":
            view = TicketAccessCloseView(ticket_id)
            embed_description = (
                f"Bonjour et bienvenue sur votre ticket d'accès {interaction.user.mention} !\n\n"
                "⚠️ Pour accéder à SkyCommunity, un court **entretien** permettra de voir "
                "quel parcours vous correspond le mieux :\n\n"
                "✈️ **Formation Avion** : apprendre à voler\n"
                "🎙️ **Formation Pilote** : apprendre à communiquer avec l'ATC\n"
                "📡 **Formation ATC** : apprendre à devenir contrôleur\n"
                "✅ Ou un **accès direct** si votre niveau le permet.\n\n"
                "📅 Clique sur **Donner mes disponibilités** ci-dessous pour indiquer "
                "quand tu es libre pour l'entretien.\n"
                "Tes dispos apparaîtront **directement dans ce ticket**.\n\n"
                "**Staff**\n"
                "• `/disponibilites` pour relancer le membre s'il n'a pas répondu.\n"
                "• **Prendre l'entretien** sur l'embed de dispos une fois reçues.\n"
                "• **Fermer le ticket** une fois l'accueil terminé."
            )
        elif ticket_type == "candidature":
            view = TicketCloseView(ticket_id)
            embed_description = (
                f"Bienvenue {interaction.user.mention} !\n\n"
                "Tu as ouvert un ticket **Candidature** pour rejoindre la compagnie.\n\n"
                "Merci de préciser :\n"
                "• Ton expérience (heures de vol, appareils maîtrisés…)\n"
                "• Pourquoi tu souhaites rejoindre la compagnie\n"
                "• Tes disponibilités pour un éventuel entretien\n\n"
                "Un membre du staff te répondra bientôt.\n\n"
                "**Staff**\n"
                "• Prendre en charge si besoin.\n"
                "• **Fermer le ticket** une fois la candidature traitée."
            )
        elif ticket_type == "formation":
            view = TicketCloseView(ticket_id)
            embed_description = (
                f"Bienvenue {interaction.user.mention} !\n\n"
                "Tu as ouvert un ticket **Formation**.\n\n"
                "Indique :\n"
                "• L'avion / type de formation souhaité\n"
                "• Ton niveau actuel\n"
                "• Tes disponibilités\n\n"
                "Un formateur ou membre du staff te répondra bientôt.\n\n"
                "**Staff**\n"
                "• Prendre en charge si besoin.\n"
                "• **Fermer le ticket** une fois la demande traitée."
            )
        else:
            view = TicketCloseView(ticket_id)
            motif_label = SUPPORT_MOTIF_LABELS.get(motif, motif) if motif else None
            motif_line = f"**Motif :** {motif_label}\n\n" if motif_label else ""
            embed_description = (
                f"Bienvenue {interaction.user.mention} !\n\n"
                f"{motif_line}"
                "Explique ta demande ci-dessous. Un membre du staff te répondra bientôt.\n\n"
                "**Staff**\n"
                "• **Prendre en charge** si besoin.\n"
                "• `/disponibilites` pour les dispos d'entretien.\n"
                "• **Fermer le ticket** une fois terminé."
            )
        interaction.client.add_view(view)

        embed = discord.Embed(
            title=f"{meta['emoji']} {meta['label']} #{ticket_id}",
            description=embed_description,
            color=meta["color"],
        )
        # Mentions : créateur uniquement pour les tickets Accès ;
        # créateur + rôle Support dédié pour les tickets Support.
        mentions = [interaction.user.mention]
        ping_role = None
        if ticket_type == "support" and conf.get("ticket_support_ping_role_id"):
            ping_role = interaction.guild.get_role(conf["ticket_support_ping_role_id"])
        if ping_role:
            mentions.append(ping_role.mention)
        await channel.send(
            content=" ".join(mentions),
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
        )

        ticket_row = {
            "id": ticket_id,
            "ticket_type": ticket_type,
            "user_id": interaction.user.id,
            "channel_id": channel.id,
            "claimed_by": None,
            "motif": motif,
        }
        await _send_ticket_log(
            interaction.guild,
            action="open",
            ticket=ticket_row,
            actor=interaction.user,
        )

        await send(f"✅ Ton ticket a été créé : {channel.mention}", ephemeral=True)


class SupportMotifSelect(discord.ui.Select):
    """Menu déroulant des motifs pour ouvrir un ticket Support."""

    def __init__(self):
        options = [
            discord.SelectOption(
                label=m["label"],
                value=m["value"],
                description=m["description"][:100],
                emoji=m.get("emoji"),
            )
            for m in SUPPORT_MOTIFS
        ]
        super().__init__(
            placeholder="Choisir le motif du ticket Support…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_panel_support_motif",
        )

    async def callback(self, interaction: discord.Interaction):
        motif = self.values[0]
        panel = TicketPanelView()
        await panel._open_ticket(interaction, "support", motif=motif)


class TicketAccessPanelView(discord.ui.View):
    """Panel dédié Accès uniquement (texte d'accueil long)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ouvrir mon ticket d'accès",
        style=discord.ButtonStyle.secondary,
        emoji="🎫",
        custom_id="ticket_panel_access_only",
    )
    async def access_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TicketPanelView()
        await view._open_ticket(interaction, "access")


class TicketCompanyPanelView(discord.ui.View):
    """Panneau tickets pour les serveurs de compagnies (Candidature / Formation / Support)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Candidature",
        style=discord.ButtonStyle.success,
        emoji="📩",
        custom_id="ticket_panel_company_candidature",
    )
    async def candidature_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        view = TicketPanelView()
        await view._open_ticket(interaction, "candidature")

    @discord.ui.button(
        label="Formation",
        style=discord.ButtonStyle.primary,
        emoji="🎓",
        custom_id="ticket_panel_company_formation",
    )
    async def formation_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        view = TicketPanelView()
        await view._open_ticket(interaction, "formation")

    @discord.ui.button(
        label="Support",
        style=discord.ButtonStyle.secondary,
        emoji="🛠️",
        custom_id="ticket_panel_company_support",
    )
    async def support_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        view = TicketPanelView()
        await view._open_ticket(interaction, "support")


# ---------------------------------------------------------------------------
# Disponibilités — vues & modals
# ---------------------------------------------------------------------------

class DisponibilitesModal(discord.ui.Modal, title="Tes disponibilités"):
    dispos = discord.ui.TextInput(
        label="Disponibilités",
        style=discord.TextStyle.paragraph,
        placeholder="Ex : Lundi 18h-20h, Mercredi après 14h, Weekend…",
        max_length=1000,
        required=True,
    )
    commentaire = discord.ui.TextInput(
        label="Commentaire (optionnel)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, target_user: discord.Member, staff_user: discord.Member):
        super().__init__()
        self.target_user = target_user
        self.staff_user = staff_user

    async def on_submit(self, interaction: discord.Interaction):
        conf = await db.get_guild_config(interaction.guild_id) or {}
        # Toujours dans le ticket concerné (plus de salon dispos dédié)
        ticket_channel = interaction.channel
        ticket_channel_id = ticket_channel.id if ticket_channel else None

        dispos_id = await db.create_disponibilite(
            guild_id=interaction.guild_id,
            target_user_id=self.target_user.id,
            requested_by=self.staff_user.id,
            dispos_text=self.dispos.value,
            commentaire=self.commentaire.value or None,
            ticket_channel_id=ticket_channel_id,
        )

        dispos = await db.get_disponibilite(dispos_id)
        embed = await _build_dispos_embed(dispos)
        view = DisponibilitesStaffView(dispos_id)
        interaction.client.add_view(view)

        # Ping le rôle Staff à chaque nouvelle disponibilité
        staff_role = None
        if conf.get("staff_role_id"):
            staff_role = interaction.guild.get_role(conf["staff_role_id"])
        content = staff_role.mention if staff_role else None

        sent = False
        msg = None
        if ticket_channel:
            try:
                msg = await ticket_channel.send(
                    content=content,
                    embed=embed,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
                sent = True
            except discord.HTTPException:
                pass

        if msg:
            await db.update_disponibilite(
                dispos_id, channel_id=msg.channel.id, message_id=msg.id
            )

        # Renommer le ticket en 🟠 (dispos données, pas encore pris en charge)
        if ticket_channel and interaction.guild:
            ticket = await db.get_ticket_by_channel(ticket_channel.id)
            if ticket and ticket.get("status") == "open" and not ticket.get("claimed_by"):
                creator = interaction.guild.get_member(ticket["user_id"])
                creator_name = creator.name if creator else str(ticket["user_id"])
                new_name = _ticket_channel_name(
                    ticket.get("ticket_type") or "access",
                    creator_name,
                    has_dispos=True,
                )
                try:
                    await ticket_channel.edit(
                        name=new_name,
                        reason="Disponibilités reçues — en attente de prise en charge",
                    )
                except discord.HTTPException:
                    pass

        await interaction.response.send_message(
            "✅ Merci ! Tes disponibilités ont été postées dans le ticket."
            + ("" if sent else "\n⚠️ Impossible d'envoyer l'embed dans le ticket."),
            ephemeral=True,
        )


class NewScheduleModal(discord.ui.Modal, title="Nouvel horaire"):
    dispos = discord.ui.TextInput(
        label="Nouvelles disponibilités",
        style=discord.TextStyle.paragraph,
        placeholder="Ex : Mardi 19h-21h, Samedi matin…",
        max_length=1000,
        required=True,
    )
    commentaire = discord.ui.TextInput(
        label="Commentaire (optionnel)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, dispos_id: int, staff_id: int):
        super().__init__()
        self.dispos_id = dispos_id
        self.staff_id = staff_id

    async def on_submit(self, interaction: discord.Interaction):
        dispos = await db.get_disponibilite(self.dispos_id)
        if not dispos:
            await interaction.response.send_message(
                "Disponibilités introuvables.", ephemeral=True
            )
            return

        await db.update_disponibilite(
            self.dispos_id,
            dispos_text=self.dispos.value,
            commentaire=self.commentaire.value or None,
        )
        dispos = await db.get_disponibilite(self.dispos_id)

        # Met à jour l'embed dans le salon (remplace les dispos)
        channel = interaction.client.get_channel(dispos.get("channel_id"))
        if channel and dispos.get("message_id"):
            try:
                msg = await channel.fetch_message(dispos["message_id"])
                embed = await _build_dispos_embed(dispos)
                view = DisponibilitesStaffView(self.dispos_id)
                interaction.client.add_view(view)
                await msg.edit(embed=embed, view=view)
            except (discord.NotFound, discord.HTTPException):
                pass

        # MP de confirmation au staff qui a demandé le nouvel horaire
        staff = interaction.client.get_user(self.staff_id)
        if staff:
            try:
                confirm_embed = discord.Embed(
                    title="📅 Nouvel horaire reçu",
                    description=(
                        f"**Membre :** <@{dispos['target_user_id']}>\n\n"
                        f"**Nouvelles disponibilités :**\n{self.dispos.value}"
                    ),
                    color=discord.Color.green(),
                )
                if self.commentaire.value:
                    confirm_embed.add_field(
                        name="Commentaire", value=self.commentaire.value, inline=False
                    )
                await staff.send(embed=confirm_embed)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            "✅ Tes nouvelles disponibilités ont été transmises et l'annonce a été mise à jour.",
            ephemeral=True,
        )


class AskNewScheduleView(discord.ui.View):
    """Vue envoyée en MP au membre pour proposer un nouvel horaire."""

    def __init__(self, dispos_id: int, staff_id: int):
        super().__init__(timeout=86400 * 3)  # 3 jours
        self.dispos_id = dispos_id
        self.staff_id = staff_id
        if self.children:
            self.children[0].custom_id = f"dispos_new_schedule_{dispos_id}_{staff_id}"

    @discord.ui.button(
        label="Proposer un nouvel horaire",
        style=discord.ButtonStyle.primary,
        emoji="📅",
    )
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        dispos = await db.get_disponibilite(self.dispos_id)
        if not dispos:
            await interaction.response.send_message(
                "Disponibilités introuvables.", ephemeral=True
            )
            return
        if interaction.user.id != dispos["target_user_id"]:
            await interaction.response.send_message(
                "Ce bouton est réservé au membre concerné.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            NewScheduleModal(self.dispos_id, self.staff_id)
        )


class ReleaseChargeView(discord.ui.View):
    """Bouton « Ne plus prendre en charge » (MP staff ou salon)."""

    def __init__(self, dispos_id: int):
        super().__init__(timeout=None)
        self.dispos_id = dispos_id
        if self.children:
            self.children[0].custom_id = f"dispos_release_{dispos_id}"

    @discord.ui.button(
        label="Ne plus prendre en charge",
        style=discord.ButtonStyle.danger,
        emoji="↩️",
    )
    async def release_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Id depuis custom_id (robuste après restart bot)
        dispos_id = self.dispos_id
        try:
            cid = (interaction.data or {}).get("custom_id") or ""
            if "dispos_release" in cid:
                dispos_id = int(cid.rsplit("_", 1)[-1])
                self.dispos_id = dispos_id
        except Exception:
            pass

        dispos = await db.get_disponibilite(dispos_id)
        if not dispos:
            await interaction.response.send_message(
                "Disponibilités introuvables.", ephemeral=True
            )
            return

        is_admin = False
        if interaction.guild and isinstance(interaction.user, discord.Member):
            is_admin = bool(interaction.user.guild_permissions.administrator)

        # SQLite peut renvoyer taken_by en str
        try:
            taken_by = int(dispos["taken_by"]) if dispos.get("taken_by") is not None else None
        except (TypeError, ValueError):
            taken_by = dispos.get("taken_by")

        if taken_by != interaction.user.id and not is_admin:
            if interaction.guild:
                if not await _is_staff(interaction):
                    await interaction.response.send_message(
                        "🚫 Seul le staff qui a pris en charge (ou un admin) peut relâcher.",
                        ephemeral=True,
                    )
                    return
            else:
                await interaction.response.send_message(
                    "🚫 Seul le staff qui a pris en charge peut relâcher.",
                    ephemeral=True,
                )
                return

        if dispos.get("status") != "taken":
            await interaction.response.send_message(
                "Ces disponibilités ne sont plus prises en charge.", ephemeral=True
            )
            return

        staff_name = interaction.user.display_name
        await db.update_disponibilite(
            self.dispos_id, status="pending", taken_by=None
        )
        dispos = await db.get_disponibilite(self.dispos_id)

        guild = interaction.guild
        if not guild and dispos.get("guild_id"):
            guild = interaction.client.get_guild(dispos["guild_id"])

        updated = False
        if dispos.get("channel_id") and dispos.get("message_id"):
            ch = interaction.client.get_channel(dispos["channel_id"])
            if ch:
                try:
                    msg = await ch.fetch_message(dispos["message_id"])
                    embed = await _build_dispos_embed(dispos)
                    view = DisponibilitesStaffView(self.dispos_id)
                    interaction.client.add_view(view)
                    await msg.edit(embed=embed, view=view)
                    updated = True
                except (discord.NotFound, discord.HTTPException):
                    pass

        # Remettre le ticket en 🟠 (dispos toujours présentes, plus de staff assigné)
        if guild and dispos.get("ticket_channel_id"):
            ticket = await db.get_ticket_by_channel(dispos["ticket_channel_id"])
            if ticket and ticket.get("status") == "open":
                await db.claim_ticket(ticket["id"], None)
                creator = guild.get_member(ticket["user_id"])
                creator_name = creator.name if creator else str(ticket["user_id"])
                new_name = _ticket_channel_name(
                    ticket.get("ticket_type") or "access",
                    creator_name,
                    has_dispos=True,
                )
                ticket_ch = guild.get_channel(dispos["ticket_channel_id"])
                if ticket_ch:
                    try:
                        await ticket_ch.edit(
                            name=new_name,
                            reason=f"Prise en charge annulée par {interaction.user}",
                        )
                    except discord.HTTPException:
                        pass

        # MP au membre qui a donné ses disponibilités
        member = None
        if guild:
            member = guild.get_member(dispos["target_user_id"])
        if not member:
            try:
                member = await interaction.client.fetch_user(dispos["target_user_id"])
            except discord.HTTPException:
                member = None
        if member:
            try:
                dm_embed = discord.Embed(
                    title="↩️ Prise en charge annulée",
                    description=(
                        f"Bonjour,\n\n"
                        f"**{staff_name}** a annulé la prise en charge de ton entretien.\n\n"
                        f"Tes disponibilités sont de nouveau en attente. "
                        f"Un autre membre du staff pourra les reprendre."
                    ),
                    color=discord.Color.orange(),
                )
                await member.send(embed=dm_embed)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            "✅ Prise en charge annulée. Les disponibilités sont de nouveau en attente dans le ticket."
            + ("" if updated else "\n⚠️ Impossible de mettre à jour l'embed automatiquement."),
            ephemeral=True,
        )


class DisponibilitesStaffView(discord.ui.View):
    """Vue sur l'embed du salon dispos."""

    def __init__(self, dispos_id: int):
        super().__init__(timeout=None)
        self.dispos_id = dispos_id
        # Forcer des custom_id stables
        for i, child in enumerate(self.children):
            if i == 0:
                child.custom_id = f"dispos_take_{dispos_id}"
            elif i == 1:
                child.custom_id = f"dispos_ask_reschedule_{dispos_id}"
            elif i == 2:
                child.custom_id = f"dispos_release_salon_{dispos_id}"

    @discord.ui.button(
        label="Prendre l'entretien",
        style=discord.ButtonStyle.success,
        emoji="✋",
    )
    async def take_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _is_staff(interaction):
            await interaction.response.send_message("🚫 Staff uniquement.", ephemeral=True)
            return

        dispos = await db.get_disponibilite(self.dispos_id)
        if not dispos:
            await interaction.response.send_message(
                "Disponibilités introuvables.", ephemeral=True
            )
            return
        if dispos.get("status") == "taken":
            await interaction.response.send_message(
                f"Déjà pris en charge par <@{dispos['taken_by']}>.", ephemeral=True
            )
            return

        await db.update_disponibilite(
            self.dispos_id, status="taken", taken_by=interaction.user.id
        )
        dispos = await db.get_disponibilite(self.dispos_id)

        # Prendre en charge le ticket lié : claim + salon en 🟢-type-nomstaff
        ticket_renamed = False
        if dispos.get("ticket_channel_id") and interaction.guild:
            ticket = await db.get_ticket_by_channel(dispos["ticket_channel_id"])
            if ticket and ticket.get("status") == "open":
                await db.claim_ticket(ticket["id"], interaction.user.id)
                creator = interaction.guild.get_member(ticket["user_id"])
                creator_name = creator.name if creator else str(ticket["user_id"])
                new_name = _ticket_channel_name(
                    ticket.get("ticket_type") or "access",
                    creator_name,
                    interaction.user.name,
                )
                ticket_ch = interaction.guild.get_channel(dispos["ticket_channel_id"])
                if ticket_ch:
                    try:
                        await ticket_ch.edit(
                            name=new_name,
                            reason=f"Entretien pris en charge par {interaction.user}",
                        )
                        ticket_renamed = True
                    except discord.HTTPException:
                        pass
                ticket = await db.get_ticket_by_channel(dispos["ticket_channel_id"]) or ticket
                await _send_ticket_log(
                    interaction.guild,
                    action="claim",
                    ticket=ticket,
                    actor=interaction.user,
                    extra="Via prise en charge de l'entretien (dispos).",
                )

        embed = await _build_dispos_embed(dispos)
        view = DisponibilitesStaffView(self.dispos_id)
        interaction.client.add_view(view)
        try:
            await interaction.message.edit(embed=embed, view=view)
        except discord.HTTPException:
            pass

        # DM au membre
        member = interaction.guild.get_member(dispos["target_user_id"]) if interaction.guild else None
        if member:
            try:
                dm_embed = discord.Embed(
                    title="✅ Entretien confirmé",
                    description=(
                        f"Bonjour {member.display_name},\n\n"
                        f"**{interaction.user.display_name}** a pris en charge ton entretien.\n\n"
                        f"Tes disponibilités :\n{dispos['dispos_text']}\n\n"
                        "Tu seras contacté(e) pour convenir de l'horaire précis."
                    ),
                    color=discord.Color.green(),
                )
                await member.send(embed=dm_embed)
            except discord.HTTPException:
                pass

        # DM au staff + bouton relâcher
        release_view = ReleaseChargeView(self.dispos_id)
        interaction.client.add_view(release_view)
        try:
            staff_embed = discord.Embed(
                title="✅ Tu as pris en charge un entretien",
                description=(
                    f"**Membre :** <@{dispos['target_user_id']}>\n"
                    f"**Disponibilités :**\n{dispos['dispos_text']}\n\n"
                    "Tu peux relâcher la prise en charge à tout moment avec le bouton ci-dessous."
                ),
                color=discord.Color.orange(),
            )
            if dispos.get("ticket_channel_id"):
                staff_embed.add_field(
                    name="Ticket",
                    value=f"<#{dispos['ticket_channel_id']}>",
                    inline=False,
                )
            await interaction.user.send(embed=staff_embed, view=release_view)
        except discord.HTTPException:
            pass

        extra = ""
        if ticket_renamed:
            extra = " Le ticket a été passé en 🟢 avec ton nom."
        await interaction.response.send_message(
            f"✅ Tu as pris en charge l'entretien de <@{dispos['target_user_id']}>."
            f"{extra} Un message privé de confirmation t'a été envoyé.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Demander un autre horaire",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
    )
    async def reschedule_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _is_staff(interaction):
            await interaction.response.send_message("🚫 Staff uniquement.", ephemeral=True)
            return

        dispos = await db.get_disponibilite(self.dispos_id)
        if not dispos:
            await interaction.response.send_message(
                "Disponibilités introuvables.", ephemeral=True
            )
            return

        if dispos.get("status") != "taken" or int(dispos.get("taken_by") or 0) != interaction.user.id:
            await interaction.response.send_message(
                "🚫 Seul le staff qui a **pris en charge** cet entretien peut demander un autre horaire.",
                ephemeral=True,
            )
            return

        member = interaction.guild.get_member(dispos["target_user_id"]) if interaction.guild else None
        if not member:
            await interaction.response.send_message(
                "Membre introuvable sur le serveur.", ephemeral=True
            )
            return

        # Vue temporaire (timeout) → ne PAS appeler add_view (sinon ValueError)
        ask_view = AskNewScheduleView(self.dispos_id, interaction.user.id)
        try:
            await member.send(
                content=(
                    f"📅 **Demande d'un autre horaire**\n\n"
                    f"{interaction.user.display_name} (staff) te demande de proposer "
                    f"**un nouvel horaire** pour ton entretien.\n"
                    f"Clique sur le bouton ci-dessous pour indiquer tes nouvelles disponibilités."
                ),
                view=ask_view,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Impossible d'envoyer un message privé au membre "
                "(MP fermés ou membre parti).",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Demande envoyée en message privé à {member.mention}.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Ne plus prendre en charge",
        style=discord.ButtonStyle.danger,
        emoji="↩️",
    )
    async def release_salon_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Parse l'id depuis custom_id (robuste) puis même logique que MP
        dispos_id = self.dispos_id
        try:
            cid = (interaction.data or {}).get("custom_id") or ""
            if cid.startswith("dispos_release_salon_"):
                dispos_id = int(cid.rsplit("_", 1)[-1])
        except Exception:
            pass
        release = ReleaseChargeView(dispos_id)
        await release.release_btn.callback(interaction, button)


class AskDisposView(discord.ui.View):
    def __init__(self, target_id: int, staff_id: int):
        super().__init__(timeout=86400)  # 24h
        self.target_id = target_id
        self.staff_id = staff_id

    @discord.ui.button(
        label="Indiquer mes disponibilités",
        style=discord.ButtonStyle.primary,
        emoji="📅",
    )
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id:
            await interaction.response.send_message(
                "Ce bouton est réservé au membre concerné.", ephemeral=True
            )
            return
        staff = interaction.guild.get_member(self.staff_id) or interaction.user
        await interaction.response.send_modal(
            DisponibilitesModal(interaction.user, staff)
        )


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketAccessPanelView())
        self.bot.add_view(TicketCompanyPanelView())

        import aiosqlite
        from config import DB_PATH

        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT id, ticket_type FROM tickets WHERE status = 'open'"
            )
            rows = await cur.fetchall()
            for row in rows:
                if row["ticket_type"] == "access":
                    self.bot.add_view(TicketAccessCloseView(row["id"]))
                else:
                    self.bot.add_view(TicketCloseView(row["id"]))

        open_dispos = await db.list_open_disponibilites()
        for d in open_dispos:
            self.bot.add_view(DisponibilitesStaffView(d["id"]))
            self.bot.add_view(ReleaseChargeView(d["id"]))

    # ---------- Config ----------

    @app_commands.command(
        name="ticket-panel",
        description="Publier le panneau de tickets Support",
    )
    @_require_admin_or_staff()
    async def ticket_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="🎫 Centre de tickets — Support",
            description=(
                "Besoin d'aide ? Choisis un **motif** dans le menu ci-dessous pour ouvrir un ticket Support.\n\n"
                "• 🚨 Signalement\n"
                "• 🎓 Formation\n"
                "• 📝 Candidature\n"
                "• 🤝 Partenariat\n"
                "• 💬 Autre demande\n\n"
                "Pour les demandes d'accès au serveur, utilise le panneau "
                "**ACCÈS À SKYCOMMUNITY**."
            ),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Un seul ticket Support ouvert à la fois")
        # Photo SkyCommunity en grand en bas de l'embed
        if SKYCOMMUNITY_LOGO_URL:
            embed.set_image(url=SKYCOMMUNITY_LOGO_URL)
        await interaction.channel.send(embed=embed, view=TicketPanelView())
        await interaction.followup.send(
            "✅ Panneau Support publié."
            + (
                ""
                if SKYCOMMUNITY_LOGO_URL
                else "\n⚠️ Logo non défini : ajoute `SKYCOMMUNITY_LOGO_URL` dans le `.env` "
                "pour afficher le logo en bas de l'embed."
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="ticket-panel-acces",
        description="Publier le panneau d'accès SkyCommunity (texte d'accueil complet)",
    )
    @_require_admin_or_staff()
    async def ticket_panel_acces(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title=ACCESS_PANEL_TITLE,
            description=ACCESS_PANEL_DESCRIPTION,
            color=discord.Color.blurple(),
        )
        # Image en grand en bas de l'embed (set_image), pas en vignette
        if SKYCOMMUNITY_LOGO_URL:
            embed.set_image(url=SKYCOMMUNITY_LOGO_URL)
        await interaction.channel.send(embed=embed, view=TicketAccessPanelView())
        await interaction.followup.send(
            "✅ Panneau d'accès publié."
            + (
                ""
                if SKYCOMMUNITY_LOGO_URL
                else "\n⚠️ Logo non défini : ajoute `SKYCOMMUNITY_LOGO_URL` dans le `.env` "
                "pour afficher le logo en bas de l'embed."
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="ticket-panel-compagnie",
        description="Publier le panneau de tickets pour un serveur de compagnie",
    )
    @_require_admin_or_staff()
    async def ticket_panel_compagnie(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="🎫 Centre de tickets — Compagnie",
            description=(
                "Besoin d'aide ou envie de rejoindre la compagnie ?\n"
                "Choisis le type de ticket ci-dessous :\n\n"
                "📩 **Candidature** — pour postuler et rejoindre la compagnie\n"
                "🎓 **Formation** — pour demander une formation avion\n"
                "🛠️ **Support** — pour toute autre question ou problème\n\n"
                "Un seul ticket du même type ouvert à la fois."
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="SkyAirlines • Serveur compagnie")
        await interaction.channel.send(embed=embed, view=TicketCompanyPanelView())
        await interaction.followup.send(
            "✅ Panneau tickets compagnie publié.", ephemeral=True
        )

    @app_commands.command(name="config-role-staff", description="Définir le rôle staff (tickets)")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_role_staff(self, interaction: discord.Interaction, role: discord.Role):
        await db.set_staff_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle staff : {role.mention}", ephemeral=True
        )

    @app_commands.command(
        name="config-role-mention-tickets",
        description="Rôle mentionné à l'ouverture des tickets (plus utilisé pour Accès)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_role_mention_tickets(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await db.set_ticket_ping_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle mentionné à l'ouverture des tickets (Accès + Support) : {role.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="config-categorie-acces",
        description="Catégorie des tickets Accès",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_cat_acces(
        self, interaction: discord.Interaction, categorie: discord.CategoryChannel
    ):
        await db.set_ticket_access_category(interaction.guild_id, categorie.id)
        await interaction.response.send_message(
            f"✅ Catégorie Accès : **{categorie.name}**", ephemeral=True
        )

    @app_commands.command(
        name="config-categorie-support",
        description="Catégorie des tickets Support",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_cat_support(
        self, interaction: discord.Interaction, categorie: discord.CategoryChannel
    ):
        await db.set_ticket_support_category(interaction.guild_id, categorie.id)
        await interaction.response.send_message(
            f"✅ Catégorie Support : **{categorie.name}**", ephemeral=True
        )

    @app_commands.command(
        name="config-canal-logs-tickets",
        description="Salon de logs tickets (repli global si logs Accès/Support non définis)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_logs(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        await db.set_ticket_log_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(
            f"✅ Logs tickets (global / repli) : {canal.mention}", ephemeral=True
        )

    @app_commands.command(
        name="config-canal-logs-acces",
        description="Salon de logs dédié aux tickets Accès",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_logs_acces(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        await db.set_ticket_access_log_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(
            f"✅ Logs tickets Accès : {canal.mention}", ephemeral=True
        )

    @app_commands.command(
        name="config-canal-logs-support",
        description="Salon de logs dédié aux tickets Support",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_logs_support(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        await db.set_ticket_support_log_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(
            f"✅ Logs tickets Support : {canal.mention}", ephemeral=True
        )

    @app_commands.command(
        name="config-canal-disponibilites",
        description="Salon où envoyer les disponibilités d'entretien",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_dispos(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        await db.set_disponibilites_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(
            f"✅ Salon disponibilités : {canal.mention}", ephemeral=True
        )

    # ---------- Actions ticket ----------

    @app_commands.command(
        name="ticket-fermer",
        description="Fermer le ticket du salon actuel (demande un motif)",
    )
    async def ticket_fermer(self, interaction: discord.Interaction):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(
                "Ce salon n'est pas un ticket.", ephemeral=True
            )
            return
        is_staff = await _is_staff(interaction)
        if not is_staff and ticket["user_id"] != interaction.user.id:
            await interaction.response.send_message("🚫 Permission refusée.", ephemeral=True)
            return
        if ticket["status"] != "open":
            await interaction.response.send_message("Ticket déjà fermé.", ephemeral=True)
            return
        await interaction.response.send_modal(CloseTicketModal(ticket["id"]))

    @app_commands.command(
        name="disponibilites",
        description="Demander les disponibilités d'entretien au membre du ticket",
    )
    async def disponibilites(self, interaction: discord.Interaction):
        # Répondre immédiatement pour éviter l'erreur 10062 (Unknown interaction)
        # si la DB ou le réseau prend un peu trop de temps.
        await interaction.response.defer(ephemeral=False)
        await _ask_disponibilites(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))