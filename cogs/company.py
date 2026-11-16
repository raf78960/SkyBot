"""
Fonctionnalités compagnies (multi-compagnies) :
- Registre de compagnies (serveur principal)
- Statut opérationnel + recrutement (boutons par compagnie)
- Plusieurs cartes publiées sur le serveur principal
- Liste des pilotes (par serveur compagnie, basée sur un rôle)
"""

import discord
from discord import app_commands
from discord.ext import commands

import database as db


STATUS_OPERATIONNELLE = "operationnelle"
STATUS_NON_OPERATIONNELLE = "non_operationnelle"

RECRUIT_OUVERT = "ouvert"
RECRUIT_FERME = "ferme"


def _status_label(status: str | None) -> str:
    if status == STATUS_OPERATIONNELLE:
        return "🟢 Opérationnelle"
    if status == STATUS_NON_OPERATIONNELLE:
        return "🔴 Non opérationnelle"
    return "⚪ Non défini"


def _recruit_label(status: str | None) -> str:
    if status == RECRUIT_OUVERT:
        return "🟢 Ouvert"
    if status == RECRUIT_FERME:
        return "🔴 Fermé"
    return "⚪ Non défini"


def _build_status_embed(company: dict) -> discord.Embed:
    status = company.get("status")
    name = company.get("name") or "Compagnie"
    if status == STATUS_OPERATIONNELLE:
        color = discord.Color.green()
        status_line = "🟢 **Opérationnelle** — la compagnie est active et organise des vols."
    elif status == STATUS_NON_OPERATIONNELLE:
        color = discord.Color.red()
        status_line = "🔴 **Non opérationnelle** — la compagnie est temporairement inactive."
    else:
        color = discord.Color.greyple()
        status_line = "⚪ **Non défini** — le staff n'a pas encore défini le statut."

    embed = discord.Embed(
        title=f"🏷️ Statut — {name}",
        description=(
            f"{status_line}\n\n"
            "• **Opérationnelle** : active, organise des vols.\n"
            "• **Non opérationnelle** : temporairement inactive.\n\n"
            "Le recrutement se gère avec `/recrutement-panel`."
        ),
        color=color,
    )
    embed.set_footer(text=f"SkyCommunity • Compagnie #{company['id']}")
    return embed


def _build_recruit_embed(company: dict) -> discord.Embed:
    status = company.get("recruit_status")
    name = company.get("name") or "Compagnie"
    if status == RECRUIT_OUVERT:
        color = discord.Color.green()
        line = "🟢 **Ouvert** — la compagnie accepte de nouveaux pilotes."
    elif status == RECRUIT_FERME:
        color = discord.Color.red()
        line = "🔴 **Fermé** — le recrutement est temporairement suspendu."
    else:
        color = discord.Color.greyple()
        line = "⚪ **Non défini** — le staff n'a pas encore défini le recrutement."

    embed = discord.Embed(
        title=f"✈️ Recrutement — {name}",
        description=(
            f"{line}\n\n"
            "• **Ouvert** : candidatures acceptées.\n"
            "• **Fermé** : pas de nouvelles candidatures.\n\n"
            "Indépendant du statut opérationnel."
        ),
        color=color,
    )
    embed.set_footer(text=f"SkyCommunity • Compagnie #{company['id']}")
    return embed


def _build_company_card(company: dict) -> tuple[str, discord.Embed]:
    ceo_id = company.get("ceo_id")
    ceo_text = f"<@{ceo_id}>" if ceo_id else "*Non configuré*"

    status = company.get("status")
    recruit = company.get("recruit_status")
    invite = (company.get("invite_url") or "").strip()
    logo = (company.get("logo_url") or "").strip()
    name = company.get("name") or "Compagnie"

    status_txt = {
        STATUS_OPERATIONNELLE: "Opérationnelle",
        STATUS_NON_OPERATIONNELLE: "Non opérationnelle",
    }.get(status, "Non défini")

    recruit_txt = {
        RECRUIT_OUVERT: "Ouvert",
        RECRUIT_FERME: "Fermé",
    }.get(recruit, "Non défini")

    lines = [
        f"**Ceo :** {ceo_text}",
        f"**Statut :** {status_txt}",
        f"**Recrutement pilotes :** {recruit_txt}",
    ]
    if invite:
        lines.append("")
        lines.append(f"**Invitation au serveur :** {invite}")

    content = "\n".join(lines)

    if status == STATUS_OPERATIONNELLE:
        color = discord.Color.green()
    elif status == STATUS_NON_OPERATIONNELLE:
        color = discord.Color.red()
    else:
        color = discord.Color.blurple()

    embed = discord.Embed(
        title=name,
        description=f"{_status_label(status)}  ·  {_recruit_label(recruit)}",
        color=color,
    )
    if logo:
        embed.set_image(url=logo)
    embed.set_footer(text=f"SkyCommunity • Compagnie #{company['id']}")
    return content, embed


async def _build_pilot_list_embed(
    guild: discord.Guild, role: discord.Role | None
) -> discord.Embed:
    if role is None:
        return discord.Embed(
            title="📋 Liste des pilotes",
            description=(
                "Aucun rôle pilote configuré.\n"
                "Un administrateur doit utiliser `/config-role-pilotes`."
            ),
            color=discord.Color.orange(),
        )

    members = sorted(
        [m for m in role.members if not m.bot],
        key=lambda m: (m.display_name or m.name).lower(),
    )

    callsigns = await db.get_all_pilot_callsigns(guild.id)

    if not members:
        body = f"Aucun membre avec le rôle {role.mention} pour le moment."
    else:
        lines = []
        for m in members:
            cs = callsigns.get(m.id)
            if cs:
                lines.append(f"• {m.mention} — `{m.display_name}` → **`{cs}`**")
            else:
                lines.append(f"• {m.mention} — `{m.display_name}`")
        body = "\n".join(lines)
        if len(body) > 3900:
            body = "\n".join(lines[:80]) + f"\n… et {len(lines) - 80} autres."

    embed = discord.Embed(
        title="📋 Liste officielle des pilotes",
        description=(
            f"Rôle suivi : {role.mention}\n"
            f"**{len(members)}** pilote(s)\n\n"
            f"{body}"
        ),
        color=discord.Color.blue(),
    )
    embed.set_footer(
        text="Actualise avec le bouton • Callsigns : /callsign-set • Basé sur le rôle configuré"
    )
    return embed


async def _is_staff_or_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    conf = await db.get_guild_config(interaction.guild_id) or {}
    staff_id = conf.get("staff_role_id")
    if not staff_id:
        return False
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    return any(r.id == staff_id for r in member.roles)


async def _can_manage_company(
    interaction: discord.Interaction, company_id: int
) -> bool:
    """Admin, rôle staff, ou CEO de cette compagnie."""
    if await _is_staff_or_admin(interaction):
        return True
    company = await db.get_company(company_id)
    if not company:
        return False
    ceo_id = company.get("ceo_id")
    return bool(ceo_id and int(ceo_id) == interaction.user.id)


def staff_or_admin():
    """Check : Administrateur Discord OU rôle staff configuré sur le serveur."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if await _is_staff_or_admin(interaction):
            return True
        raise app_commands.CheckFailure(
            "🚫 Réservé aux **admins** ou au **rôle staff** configuré."
        )

    return app_commands.check(predicate)


async def _can_manage_callsigns(interaction: discord.Interaction) -> bool:
    """Rôle callsign manager de CE serveur (compagnie), ou administrateur."""
    if not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    conf = await db.get_guild_config(interaction.guild_id) or {}
    rid = conf.get("callsign_manager_role_id")
    if not rid:
        return False
    role = interaction.guild.get_role(int(rid))
    return bool(role and role in interaction.user.roles)


def callsign_manager():
    """Check : rôle callsign manager du serveur compagnie, ou admin."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if await _can_manage_callsigns(interaction):
            return True
        raise app_commands.CheckFailure(
            "🚫 Réservé au **rôle gestion callsigns** de ce serveur "
            "(ou aux administrateurs). Configure-le avec `/config-role-callsign`."
        )

    return app_commands.check(predicate)


async def _resolve_forum_channel(
    bot: commands.Bot, guild: discord.Guild, preferred: discord.abc.GuildChannel | None
) -> discord.ForumChannel | None:
    """Forum cible : salon actuel s'il est un forum, sinon forum configuré sur le serveur."""
    if isinstance(preferred, discord.ForumChannel):
        return preferred
    conf = await db.get_guild_config(guild.id) or {}
    fid = conf.get("companies_forum_channel_id")
    if not fid:
        return None
    ch = guild.get_channel(fid) or bot.get_channel(fid)
    if ch is None:
        try:
            ch = await bot.fetch_channel(fid)
        except Exception:
            return None
    return ch if isinstance(ch, discord.ForumChannel) else None


async def _create_company_forum_post(
    forum: discord.ForumChannel,
    company: dict,
    view: discord.ui.View | None = None,
) -> tuple[discord.Thread, discord.Message]:
    """
    Crée un post forum AU NOM DE LA COMPAGNIE.
    La carte est UNIQUEMENT dans le premier message, publié par le bot.
    """
    post_name = (company.get("name") or "Compagnie")[:100]
    content, embed = _build_company_card(company)

    kwargs: dict = {
        "name": post_name,
        "content": content,
        "embed": embed,
    }
    if view is not None:
        kwargs["view"] = view
    available = list(getattr(forum, "available_tags", None) or [])
    if getattr(forum, "requires_tags", False) and available:
        kwargs["applied_tags"] = [available[0]]

    created = await forum.create_thread(**kwargs)
    thread = getattr(created, "thread", created)
    msg = getattr(created, "message", None)

    if msg is None:
        try:
            msg = await thread.fetch_message(thread.id)
        except Exception:
            async for m in thread.history(limit=1, oldest_first=True):
                msg = m
                break

    if msg is None:
        raise RuntimeError("Post créé mais premier message introuvable")

    return thread, msg


async def _refresh_company_card(bot: commands.Bot, company: dict) -> bool:
    """
    Met à jour le premier message du post + boutons + titre.
    Recharge toujours la compagnie depuis la DB pour avoir le bon statut.
    """
    company_id = company.get("id")
    if company_id:
        fresh = await db.get_company(int(company_id))
        if fresh:
            company = fresh

    ch_id = company.get("card_channel_id")
    msg_id = company.get("card_message_id")
    if not ch_id or not msg_id:
        return False

    channel = bot.get_channel(ch_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(ch_id)
        except Exception:
            return False

    # Désarchiver le post forum si besoin (sinon edit impossible)
    if isinstance(channel, discord.Thread):
        try:
            if channel.archived:
                await channel.edit(archived=False, locked=False)
        except Exception:
            pass

    try:
        msg = await channel.fetch_message(msg_id)
    except Exception:
        # Fallback forum : message de démarrage = id du thread
        try:
            msg = await channel.fetch_message(ch_id)
        except Exception:
            return False

    content, embed = _build_company_card(company)
    view = CompanyCardView(bot, int(company["id"]))
    try:
        await msg.edit(content=content, embed=embed, view=view)
    except Exception:
        try:
            await msg.edit(content=content, embed=embed)
        except Exception:
            return False

    if isinstance(channel, discord.Thread):
        name = (company.get("name") or "Compagnie")[:100]
        if channel.name != name:
            try:
                await channel.edit(name=name)
            except Exception:
                pass
    return True


async def _company_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    rows = await db.search_companies(current, limit=25)
    return [
        app_commands.Choice(name=f"{r['name']} (#{r['id']})", value=r["id"])
        for r in rows
    ]


# ---------- Views (custom_id unique par compagnie) ----------


async def _apply_status(
    bot: commands.Bot,
    interaction: discord.Interaction,
    company_id: int,
    status: str,
    *,
    edit_panel: bool = False,
    panel_view: discord.ui.View | None = None,
):
    if not await _can_manage_company(interaction, company_id):
        await interaction.response.send_message(
            "🚫 Réservé au **CEO** de la compagnie, au staff ou aux admins.",
            ephemeral=True,
        )
        return
    await db.set_company_status_by_id(company_id, status)
    company = await db.get_company(company_id)
    if not company:
        await interaction.response.send_message(
            "❌ Compagnie introuvable.", ephemeral=True
        )
        return

    label = (
        "Opérationnelle"
        if status == STATUS_OPERATIONNELLE
        else "Non opérationnelle"
    )
    # Si on clique depuis la carte → on édite la carte directement
    if not edit_panel:
        content, embed = _build_company_card(company)
        view = CompanyCardView(bot, company_id)
        await interaction.response.edit_message(
            content=content, embed=embed, view=view
        )
        await interaction.followup.send(
            f"✅ **{company['name']}** → **{label}**", ephemeral=True
        )
        return

    await interaction.response.edit_message(
        embed=_build_status_embed(company), view=panel_view
    )
    await interaction.followup.send(
        f"✅ **{company['name']}** → **{label}**", ephemeral=True
    )
    ok = await _refresh_company_card(bot, company)
    if not ok:
        await interaction.followup.send(
            "⚠️ Statut enregistré, mais la **carte** n'a pas pu être mise à jour "
            "(republie avec `/carte-compagnie`).",
            ephemeral=True,
        )


async def _apply_recruit(
    bot: commands.Bot,
    interaction: discord.Interaction,
    company_id: int,
    recruit: str,
    *,
    edit_panel: bool = False,
    panel_view: discord.ui.View | None = None,
):
    if not await _can_manage_company(interaction, company_id):
        await interaction.response.send_message(
            "🚫 Réservé au **CEO** de la compagnie, au staff ou aux admins.",
            ephemeral=True,
        )
        return
    await db.set_company_recruit_by_id(company_id, recruit)
    company = await db.get_company(company_id)
    if not company:
        await interaction.response.send_message(
            "❌ Compagnie introuvable.", ephemeral=True
        )
        return

    label = "Ouvert" if recruit == RECRUIT_OUVERT else "Fermé"
    if not edit_panel:
        content, embed = _build_company_card(company)
        view = CompanyCardView(bot, company_id)
        await interaction.response.edit_message(
            content=content, embed=embed, view=view
        )
        await interaction.followup.send(
            f"✅ **{company['name']}** recrutement → **{label}**", ephemeral=True
        )
        return

    await interaction.response.edit_message(
        embed=_build_recruit_embed(company), view=panel_view
    )
    await interaction.followup.send(
        f"✅ **{company['name']}** recrutement → **{label}**", ephemeral=True
    )
    ok = await _refresh_company_card(bot, company)
    if not ok:
        await interaction.followup.send(
            "⚠️ Recrutement enregistré, mais la **carte** n'a pas pu être mise à jour "
            "(republie avec `/carte-compagnie`).",
            ephemeral=True,
        )


class CompanyCardView(discord.ui.View):
    """Boutons sur la carte elle-même (statut + recrutement)."""

    def __init__(self, bot: commands.Bot, company_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.company_id = company_id

        buttons = [
            ("🟢 Opérationnelle", discord.ButtonStyle.success, f"cc_st_op:{company_id}", self._op),
            ("🔴 Non opérationnelle", discord.ButtonStyle.danger, f"cc_st_non:{company_id}", self._non),
            ("🟢 Recrut. ouvert", discord.ButtonStyle.success, f"cc_rc_op:{company_id}", self._rop),
            ("🔴 Recrut. fermé", discord.ButtonStyle.danger, f"cc_rc_cl:{company_id}", self._rcl),
        ]
        for label, style, cid, cb in buttons:
            btn = discord.ui.Button(label=label, style=style, custom_id=cid)
            btn.callback = cb
            self.add_item(btn)

    async def _op(self, interaction: discord.Interaction):
        await _apply_status(
            self.bot, interaction, self.company_id, STATUS_OPERATIONNELLE
        )

    async def _non(self, interaction: discord.Interaction):
        await _apply_status(
            self.bot, interaction, self.company_id, STATUS_NON_OPERATIONNELLE
        )

    async def _rop(self, interaction: discord.Interaction):
        await _apply_recruit(
            self.bot, interaction, self.company_id, RECRUIT_OUVERT
        )

    async def _rcl(self, interaction: discord.Interaction):
        await _apply_recruit(
            self.bot, interaction, self.company_id, RECRUIT_FERME
        )


class CompanyStatusView(discord.ui.View):
    def __init__(self, bot: commands.Bot, company_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.company_id = company_id

        op_btn = discord.ui.Button(
            label="Opérationnelle",
            style=discord.ButtonStyle.success,
            emoji="🟢",
            custom_id=f"company_status_op:{company_id}",
        )
        non_btn = discord.ui.Button(
            label="Non opérationnelle",
            style=discord.ButtonStyle.danger,
            emoji="🔴",
            custom_id=f"company_status_non:{company_id}",
        )
        op_btn.callback = self._set_op
        non_btn.callback = self._set_non
        self.add_item(op_btn)
        self.add_item(non_btn)

    async def _set_op(self, interaction: discord.Interaction):
        await _apply_status(
            self.bot,
            interaction,
            self.company_id,
            STATUS_OPERATIONNELLE,
            edit_panel=True,
            panel_view=self,
        )

    async def _set_non(self, interaction: discord.Interaction):
        await _apply_status(
            self.bot,
            interaction,
            self.company_id,
            STATUS_NON_OPERATIONNELLE,
            edit_panel=True,
            panel_view=self,
        )


class CompanyRecruitView(discord.ui.View):
    def __init__(self, bot: commands.Bot, company_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.company_id = company_id

        open_btn = discord.ui.Button(
            label="Ouvert",
            style=discord.ButtonStyle.success,
            emoji="🟢",
            custom_id=f"company_recruit_open:{company_id}",
        )
        close_btn = discord.ui.Button(
            label="Fermé",
            style=discord.ButtonStyle.danger,
            emoji="🔴",
            custom_id=f"company_recruit_close:{company_id}",
        )
        open_btn.callback = self._set_open
        close_btn.callback = self._set_close
        self.add_item(open_btn)
        self.add_item(close_btn)

    async def _set_open(self, interaction: discord.Interaction):
        await _apply_recruit(
            self.bot,
            interaction,
            self.company_id,
            RECRUIT_OUVERT,
            edit_panel=True,
            panel_view=self,
        )

    async def _set_close(self, interaction: discord.Interaction):
        await _apply_recruit(
            self.bot,
            interaction,
            self.company_id,
            RECRUIT_FERME,
            edit_panel=True,
            panel_view=self,
        )


class PilotListView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Actualiser",
        style=discord.ButtonStyle.primary,
        emoji="🔄",
        custom_id="company_pilot_list_refresh",
    )
    async def refresh(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        conf = await db.get_guild_config(interaction.guild_id) or {}
        role = None
        if conf.get("pilot_role_id"):
            role = interaction.guild.get_role(conf["pilot_role_id"])
        embed = await _build_pilot_list_embed(interaction.guild, role)
        await interaction.response.edit_message(embed=embed, view=self)


class Company(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PilotListView())
        try:
            companies = await db.list_companies()
        except Exception:
            companies = []
        for c in companies:
            self._register_views(c["id"])

    def _register_views(self, company_id: int):
        self.bot.add_view(CompanyStatusView(self.bot, company_id))
        self.bot.add_view(CompanyRecruitView(self.bot, company_id))
        self.bot.add_view(CompanyCardView(self.bot, company_id))

    # ---------- Registre compagnies ----------

    @app_commands.command(
        name="compagnie-ajouter",
        description="Ajouter une compagnie au registre (pour carte sur le serveur principal)",
    )
    @app_commands.describe(
        nom="Nom affiché de la compagnie",
        ceo="CEO / dirigeant",
        invitation="Lien d'invitation Discord",
        logo_url="URL du logo",
        serveur_id="ID Discord du serveur de la compagnie (optionnel)",
    )
    @staff_or_admin()
    async def compagnie_ajouter(
        self,
        interaction: discord.Interaction,
        nom: str,
        ceo: discord.Member | None = None,
        invitation: str | None = None,
        logo_url: str | None = None,
        serveur_id: str | None = None,
    ):
        invite = (invitation or "").strip() or None
        logo = (logo_url or "").strip() or None
        guild_id = None
        if serveur_id:
            try:
                guild_id = int(serveur_id.strip())
            except ValueError:
                await interaction.response.send_message(
                    "⚠️ `serveur_id` doit être un nombre (ID Discord).",
                    ephemeral=True,
                )
                return
        if invite and not (
            invite.startswith("https://discord.gg/")
            or invite.startswith("https://discord.com/invite/")
        ):
            await interaction.response.send_message(
                "⚠️ Invitation : `https://discord.gg/...` ou `https://discord.com/invite/...`",
                ephemeral=True,
            )
            return
        if logo and not (logo.startswith("http://") or logo.startswith("https://")):
            await interaction.response.send_message(
                "⚠️ Logo : URL `http://` ou `https://`.",
                ephemeral=True,
            )
            return

        cid = await db.create_company(
            nom,
            company_guild_id=guild_id,
            ceo_id=ceo.id if ceo else None,
            invite_url=invite,
            logo_url=logo,
        )
        self._register_views(cid)
        await interaction.response.send_message(
            f"✅ Compagnie **{nom}** créée (`#{cid}`).\n"
            f"• `/carte-compagnie compagnie:{nom}` → publier la carte (salon principal)\n"
            f"• `/statut-panel` / `/recrutement-panel` → panneaux boutons\n"
            f"• `/compagnie-modifier` pour ajuster CEO / invite / logo",
            ephemeral=True,
        )

    @app_commands.command(
        name="compagnie-modifier",
        description="Modifier une compagnie du registre",
    )
    @app_commands.describe(
        compagnie="Compagnie à modifier",
        nom="Nouveau nom",
        ceo="CEO / dirigeant",
        invitation="Lien d'invitation (vide = garder)",
        logo_url="URL logo (vide = garder)",
        serveur_id="ID serveur compagnie (0 = retirer le lien)",
    )
    @app_commands.autocomplete(compagnie=_company_autocomplete)
    @staff_or_admin()
    async def compagnie_modifier(
        self,
        interaction: discord.Interaction,
        compagnie: int,
        nom: str | None = None,
        ceo: discord.Member | None = None,
        invitation: str | None = None,
        logo_url: str | None = None,
        serveur_id: str | None = None,
    ):
        company = await db.get_company(compagnie)
        if not company:
            await interaction.response.send_message(
                "❌ Compagnie introuvable.", ephemeral=True
            )
            return

        fields: dict = {}
        parts = []
        if nom is not None and nom.strip():
            fields["name"] = nom.strip()
            parts.append(f"Nom → **{nom.strip()}**")
        if ceo is not None:
            fields["ceo_id"] = ceo.id
            parts.append(f"CEO → {ceo.mention}")
        if invitation is not None:
            inv = invitation.strip()
            if inv and not (
                inv.startswith("https://discord.gg/")
                or inv.startswith("https://discord.com/invite/")
            ):
                await interaction.response.send_message(
                    "⚠️ Invitation invalide.", ephemeral=True
                )
                return
            fields["invite_url"] = inv or None
            parts.append(f"Invitation → `{inv or 'supprimée'}`")
        if logo_url is not None:
            logo = logo_url.strip()
            if logo and not (
                logo.startswith("http://") or logo.startswith("https://")
            ):
                await interaction.response.send_message(
                    "⚠️ Logo : URL http(s).", ephemeral=True
                )
                return
            fields["logo_url"] = logo or None
            parts.append(f"Logo → `{logo or 'supprimé'}`")
        if serveur_id is not None:
            s = serveur_id.strip()
            if s in ("0", ""):
                fields["company_guild_id"] = None
                parts.append("Serveur lié → aucun")
            else:
                try:
                    fields["company_guild_id"] = int(s)
                    parts.append(f"Serveur lié → `{s}`")
                except ValueError:
                    await interaction.response.send_message(
                        "⚠️ serveur_id invalide.", ephemeral=True
                    )
                    return

        if not fields:
            await interaction.response.send_message(
                "Rien à modifier — passe au moins une option.", ephemeral=True
            )
            return

        await db.update_company(compagnie, **fields)
        company = await db.get_company(compagnie)
        await interaction.response.send_message(
            "✅ Mis à jour :\n• " + "\n• ".join(parts),
            ephemeral=True,
        )
        if company:
            await _refresh_company_card(self.bot, company)

    @app_commands.command(
        name="compagnie-supprimer",
        description="Supprimer une compagnie du registre (ne supprime pas le message carte)",
    )
    @app_commands.describe(compagnie="Compagnie à supprimer")
    @app_commands.autocomplete(compagnie=_company_autocomplete)
    @staff_or_admin()
    async def compagnie_supprimer(
        self, interaction: discord.Interaction, compagnie: int
    ):
        company = await db.get_company(compagnie)
        if not company:
            await interaction.response.send_message(
                "❌ Compagnie introuvable.", ephemeral=True
            )
            return
        await db.delete_company(compagnie)
        await interaction.response.send_message(
            f"🗑️ **{company['name']}** (`#{compagnie}`) supprimée du registre.\n"
            f"(Le message carte éventuel reste dans le salon — supprime-le à la main.)",
            ephemeral=True,
        )

    @app_commands.command(
        name="compagnie-liste",
        description="Lister les compagnies du registre",
    )
    @staff_or_admin()
    async def compagnie_liste(self, interaction: discord.Interaction):
        rows = await db.list_companies()
        if not rows:
            await interaction.response.send_message(
                "Aucune compagnie. Utilise `/compagnie-ajouter`.",
                ephemeral=True,
            )
            return
        lines = []
        for c in rows:
            card = (
                "✅ carte"
                if c.get("card_channel_id") and c.get("card_message_id")
                else "— pas de carte"
            )
            lines.append(
                f"• **{c['name']}** `#{c['id']}` — {_status_label(c.get('status'))} · "
                f"{_recruit_label(c.get('recruit_status'))} · {card}"
            )
        await interaction.response.send_message(
            "**Compagnies enregistrées :**\n" + "\n".join(lines),
            ephemeral=True,
        )

    # ---------- Panneaux & carte ----------

    async def _resolve_company(
        self, interaction: discord.Interaction, compagnie: int | None
    ) -> dict | None:
        if compagnie is not None:
            return await db.get_company(compagnie)
        # Auto : serveur compagnie lié
        found = await db.get_company_by_guild(interaction.guild_id)
        return found

    @app_commands.command(
        name="statut-panel",
        description="Publier le panneau de statut opérationnel d'une compagnie",
    )
    @app_commands.describe(
        compagnie="Compagnie (autocomplete). Optionnel si ce serveur est lié."
    )
    @app_commands.autocomplete(compagnie=_company_autocomplete)
    @staff_or_admin()
    async def statut_panel(
        self,
        interaction: discord.Interaction,
        compagnie: int | None = None,
    ):
        company = await self._resolve_company(interaction, compagnie)
        if not company:
            await interaction.response.send_message(
                "❌ Compagnie introuvable.\n"
                "Utilise `/compagnie-ajouter` puis `/statut-panel compagnie:…`",
                ephemeral=True,
            )
            return
        self._register_views(company["id"])
        view = CompanyStatusView(self.bot, company["id"])
        msg = await interaction.channel.send(
            embed=_build_status_embed(company), view=view
        )
        await db.set_company_status_message_by_id(
            company["id"], interaction.channel.id, msg.id
        )
        await interaction.response.send_message(
            f"✅ Panneau **statut** pour **{company['name']}** publié.",
            ephemeral=True,
        )

    @app_commands.command(
        name="recrutement-panel",
        description="Publier le panneau de recrutement d'une compagnie (Ouvert / Fermé)",
    )
    @app_commands.describe(
        compagnie="Compagnie (autocomplete). Optionnel si ce serveur est lié."
    )
    @app_commands.autocomplete(compagnie=_company_autocomplete)
    @staff_or_admin()
    async def recrutement_panel(
        self,
        interaction: discord.Interaction,
        compagnie: int | None = None,
    ):
        company = await self._resolve_company(interaction, compagnie)
        if not company:
            await interaction.response.send_message(
                "❌ Compagnie introuvable.\n"
                "Utilise `/compagnie-ajouter` puis `/recrutement-panel compagnie:…`",
                ephemeral=True,
            )
            return
        self._register_views(company["id"])
        view = CompanyRecruitView(self.bot, company["id"])
        msg = await interaction.channel.send(
            embed=_build_recruit_embed(company), view=view
        )
        await db.set_company_recruit_message_by_id(
            company["id"], interaction.channel.id, msg.id
        )
        await interaction.response.send_message(
            f"✅ Panneau **recrutement** pour **{company['name']}** publié.\n"
            f"La carte sur le serveur principal se met à jour auto.",
            ephemeral=True,
        )

    @app_commands.command(
        name="config-forum-compagnies",
        description="Définir le salon FORUM où le bot crée les posts compagnies",
    )
    @app_commands.describe(forum="Salon forum (obligatoire)")
    @staff_or_admin()
    async def config_forum_compagnies(
        self, interaction: discord.Interaction, forum: discord.ForumChannel
    ):
        await db.set_companies_forum_channel(interaction.guild_id, forum.id)
        await interaction.response.send_message(
            f"✅ Forum compagnies : {forum.mention}\n"
            f"Ensuite : `/carte-compagnie compagnie:…`\n"
            f"→ le **bot** crée un **post** au nom de la compagnie, "
            f"avec la carte dans le **premier message**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="carte-compagnie",
        description="Le bot crée un post forum (titre = nom compagnie, carte = 1er message)",
    )
    @app_commands.describe(compagnie="Compagnie à publier")
    @app_commands.autocomplete(compagnie=_company_autocomplete)
    @staff_or_admin()
    async def carte_compagnie(
        self, interaction: discord.Interaction, compagnie: int
    ):
        company = await db.get_company(compagnie)
        if not company:
            await interaction.response.send_message(
                "❌ Compagnie introuvable. `/compagnie-ajouter` d'abord.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        forum = await _resolve_forum_channel(
            self.bot, interaction.guild, interaction.channel
        )
        if forum is None:
            await interaction.followup.send(
                "❌ Aucun **salon forum** cible.\n"
                "1. Crée un salon de type **Forum**\n"
                "2. `/config-forum-compagnies forum:#ton-forum`\n"
                "   *ou* lance `/carte-compagnie` **directement dans le forum**",
                ephemeral=True,
            )
            return

        self._register_views(company["id"])
        card_view = CompanyCardView(self.bot, company["id"])
        try:
            thread, msg = await _create_company_forum_post(
                forum, company, view=card_view
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ Permission refusée sur {forum.mention}.\n"
                f"Le bot doit pouvoir **voir le salon**, **envoyer des messages** "
                f"et **créer des posts publics**.",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(
                f"❌ Impossible de créer le post : `{e}`",
                ephemeral=True,
            )
            return

        await db.set_company_card_message_by_id(company["id"], thread.id, msg.id)
        # S'assurer que les boutons sont bien sur le 1er message
        try:
            content, embed = _build_company_card(company)
            await msg.edit(content=content, embed=embed, view=card_view)
        except Exception:
            pass
        await interaction.followup.send(
            f"✅ Post créé **par le bot**\n"
            f"• Titre : **{thread.name}**\n"
            f"• Carte = **premier message** + boutons statut/recrutement\n"
            f"• Lien : {thread.mention}\n"
            f"Clique les boutons sous la carte pour changer les statuts "
            f"(la carte se met à jour tout de suite).",
            ephemeral=True,
        )

    # ---------- Liste pilotes (par serveur) ----------

    @app_commands.command(
        name="config-role-pilotes",
        description="Définir le rôle utilisé pour la liste officielle des pilotes (ce serveur)",
    )
    @app_commands.describe(role="Rôle attribué aux pilotes de la compagnie")
    @staff_or_admin()
    async def config_role_pilotes(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await db.set_pilot_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle pilotes : {role.mention}\n"
            f"Utilise `/liste-pilotes-panel` pour publier / mettre à jour la liste.",
            ephemeral=True,
        )

    @app_commands.command(
        name="config-role-callsign",
        description="Rôle autorisé à gérer les callsigns sur CE serveur compagnie",
    )
    @app_commands.describe(role="Rôle qui pourra utiliser /callsign-set et /callsign-supprimer")
    @staff_or_admin()
    async def config_role_callsign(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await db.set_callsign_manager_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Rôle gestion callsigns : {role.mention}\n"
            f"Seuls ce rôle (et les admins) peuvent utiliser `/callsign-set` "
            f"et `/callsign-supprimer` sur **ce serveur**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="liste-pilotes-panel",
        description="Publier la liste officielle des pilotes (basée sur un rôle)",
    )
    @staff_or_admin()
    async def liste_pilotes_panel(self, interaction: discord.Interaction):
        conf = await db.get_guild_config(interaction.guild_id) or {}
        role = None
        if conf.get("pilot_role_id"):
            role = interaction.guild.get_role(conf["pilot_role_id"])
        if role is None:
            await interaction.response.send_message(
                "⚠️ Configure d'abord le rôle avec `/config-role-pilotes`.",
                ephemeral=True,
            )
            return
        embed = await _build_pilot_list_embed(interaction.guild, role)
        view = PilotListView()
        msg = await interaction.channel.send(embed=embed, view=view)
        await db.set_pilot_list_message(
            interaction.guild_id, interaction.channel.id, msg.id
        )
        await interaction.response.send_message(
            "✅ Liste des pilotes publiée. Bouton **Actualiser** pour rafraîchir.",
            ephemeral=True,
        )

    async def _refresh_pilot_list_panel(self, guild: discord.Guild) -> bool:
        """Met à jour le message de liste pilotes s'il existe. Retourne True si OK."""
        conf = await db.get_guild_config(guild.id) or {}
        channel_id = conf.get("pilot_list_channel_id")
        message_id = conf.get("pilot_list_message_id")
        if not channel_id or not message_id:
            return False
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                return False
        role = None
        if conf.get("pilot_role_id"):
            role = guild.get_role(conf["pilot_role_id"])
        try:
            msg = await channel.fetch_message(message_id)
            embed = await _build_pilot_list_embed(guild, role)
            await msg.edit(embed=embed, view=PilotListView())
            return True
        except Exception:
            return False

    @app_commands.command(
        name="callsign-set",
        description="Attribuer un callsign à un employé (affiché dans la liste des pilotes)",
    )
    @app_commands.describe(
        membre="Employé / pilote concerné",
        callsign="Callsign à attribuer (ex: EZY5283D)",
    )
    @callsign_manager()
    async def callsign_set(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        callsign: str,
    ):
        cs = (callsign or "").strip().upper()
        if not cs or len(cs) > 16:
            await interaction.response.send_message(
                "⚠️ Callsign invalide (1–16 caractères).",
                ephemeral=True,
            )
            return
        await db.set_pilot_callsign(interaction.guild_id, membre.id, cs)
        refreshed = await self._refresh_pilot_list_panel(interaction.guild)
        extra = " Liste des pilotes mise à jour." if refreshed else (
            " Utilise le bouton **Actualiser** sur la liste (ou `/liste-pilotes-panel`)."
        )
        await interaction.response.send_message(
            f"✅ Callsign de {membre.mention} : **`{cs}`**.{extra}",
            ephemeral=True,
        )

    @app_commands.command(
        name="callsign-supprimer",
        description="Retirer le callsign d'un employé",
    )
    @app_commands.describe(membre="Employé / pilote concerné")
    @callsign_manager()
    async def callsign_supprimer(
        self, interaction: discord.Interaction, membre: discord.Member
    ):
        removed = await db.remove_pilot_callsign(interaction.guild_id, membre.id)
        if not removed:
            await interaction.response.send_message(
                f"ℹ️ {membre.mention} n'avait pas de callsign enregistré.",
                ephemeral=True,
            )
            return
        refreshed = await self._refresh_pilot_list_panel(interaction.guild)
        extra = " Liste des pilotes mise à jour." if refreshed else (
            " Utilise le bouton **Actualiser** sur la liste."
        )
        await interaction.response.send_message(
            f"✅ Callsign de {membre.mention} retiré.{extra}",
            ephemeral=True,
        )

    @app_commands.command(
        name="sync-commandes",
        description="Forcer la synchronisation des commandes slash sur CE serveur",
    )
    @staff_or_admin()
    async def sync_commandes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            self.bot.tree.copy_global_to(guild=interaction.guild)
            synced = await self.bot.tree.sync(guild=interaction.guild)
            names = ", ".join(f"/{c.name}" for c in synced[:15])
            more = f" (+{len(synced) - 15})" if len(synced) > 15 else ""
            await interaction.followup.send(
                f"✅ **{len(synced)}** commandes synchronisées sur **{interaction.guild.name}**.\n"
                f"{names}{more}\n\n"
                f"Tape `/` pour les voir (parfois 10–30 s).",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Erreur de synchronisation : `{e}`", ephemeral=True
            )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            msg = str(error) or "🚫 Permission insuffisante."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        if isinstance(error, app_commands.MissingPermissions):
            msg = "🚫 Il te faut la permission **Administrateur** ou le **rôle staff**."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Company(bot))
