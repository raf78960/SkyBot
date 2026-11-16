"""
Dépôt de plans de vol (IFR / VFR) lié aux fréquences ATC actives.
Équivalent du système BotGhost .panelplan.
"""

import re

import discord
from discord import app_commands
from discord.ext import commands

import database as db


def _normalize_icao(value: str) -> str:
    return (value or "").strip().upper()


def _is_valid_icao(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{4}", _normalize_icao(value)))


# Statuts strips (alignés sur le tableau opérationnel)
STRIP_STATUSES = [
    ("STAND", "🔵 STAND", discord.ButtonStyle.primary),
    ("PUSHBACK", "🩵 PUSHBACK", discord.ButtonStyle.primary),
    ("TAXI", "🟡 TAXI", discord.ButtonStyle.secondary),
    ("TAKE-OFF", "🟢 TAKE-OFF", discord.ButtonStyle.success),
    ("CRUIZE", "🟣 CRUIZE", discord.ButtonStyle.primary),
    ("APPROACH", "🟠 APPROACH", discord.ButtonStyle.secondary),
    ("LANDING", "🔴 LANDING", discord.ButtonStyle.danger),
    ("LAST TAXI", "🩷 LAST TAXI", discord.ButtonStyle.secondary),
]

STRIP_STATUS_EMOJI = {
    "STAND": "🔵",
    "PUSHBACK": "🩵",
    "TAXI": "🟡",
    "TAKE-OFF": "🟢",
    "CRUIZE": "🟣",
    "APPROACH": "🟠",
    "LANDING": "🔴",
    "LAST TAXI": "🩷",
}

STRIP_STATUS_COLOR = {
    "STAND": discord.Color.from_str("#2F6FED"),
    "PUSHBACK": discord.Color.from_str("#22D3EE"),
    "TAXI": discord.Color.from_str("#EAB308"),
    "TAKE-OFF": discord.Color.from_str("#22C55E"),
    "CRUIZE": discord.Color.from_str("#A855F7"),
    "APPROACH": discord.Color.from_str("#F97316"),
    "LANDING": discord.Color.from_str("#EF4444"),
    "LAST TAXI": discord.Color.from_str("#EC4899"),
}


def _cell(value, width: int) -> str:
    s = (str(value) if value not in (None, "") else "—")[:width]
    return s.ljust(width)


def _format_board_header() -> str:
    return (
        f"{_cell('CS', 8)} {_cell('DEP', 4)} {_cell('ARR', 4)} "
        f"{_cell('STD', 5)} {_cell('XPDR', 5)} {_cell('SID/RWY', 12)} "
        f"{_cell('STAR/RWY', 10)} {_cell('CLB', 6)} {_cell('STATUT', 9)} "
        f"{_cell('ATC', 10)} REMARK"
    )


def _format_board_row(plan: dict) -> str:
    return (
        f"{_cell(plan.get('callsign'), 8)} "
        f"{_cell(plan.get('departure'), 4)} "
        f"{_cell(plan.get('arrival'), 4)} "
        f"{_cell(plan.get('gate'), 5)} "
        f"{_cell(plan.get('squawk'), 5)} "
        f"{_cell(plan.get('sid_rwy'), 12)} "
        f"{_cell(plan.get('star_rwy'), 10)} "
        f"{_cell(plan.get('initial_climb'), 6)} "
        f"{_cell(plan.get('strip_status') or 'STAND', 9)} "
        f"{_cell(plan.get('strip_atc'), 10)} "
        f"{(plan.get('remark') or '—')[:20]}"
    )


def _build_strip_embed(plan: dict) -> discord.Embed:
    status = (plan.get("strip_status") or "STAND").upper()
    color = STRIP_STATUS_COLOR.get(status, discord.Color.dark_grey())
    emoji = STRIP_STATUS_EMOJI.get(status, "⚪")
    cs = (plan.get("callsign") or "?").upper()
    embed = discord.Embed(
        title=f"🧾 Strip {cs} · {emoji} {status}",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Callsign", value=f"`{cs}`", inline=True)
    embed.add_field(name="Departure", value=f"`{plan.get('departure') or '—'}`", inline=True)
    embed.add_field(name="Arrival", value=f"`{plan.get('arrival') or '—'}`", inline=True)
    embed.add_field(name="Stand", value=f"`{plan.get('gate') or '—'}`", inline=True)
    embed.add_field(name="Transpondeur", value=f"`{plan.get('squawk') or '—'}`", inline=True)
    embed.add_field(name="SID/RWY", value=f"`{plan.get('sid_rwy') or '—'}`", inline=True)
    embed.add_field(name="STAR/RWY", value=f"`{plan.get('star_rwy') or '—'}`", inline=True)
    embed.add_field(name="Initial Climb", value=f"`{plan.get('initial_climb') or '—'}`", inline=True)
    embed.add_field(name="Statut", value=f"{emoji} **{status}**", inline=True)
    embed.add_field(name="ATC", value=f"`{plan.get('strip_atc') or '—'}`", inline=True)
    embed.add_field(
        name="Remark",
        value=plan.get("remark") or "—",
        inline=False,
    )
    embed.add_field(
        name="Pilote",
        value=f"<@{plan['user_id']}>" if plan.get("user_id") else "—",
        inline=True,
    )
    if plan.get("simbrief_url"):
        embed.add_field(
            name="SimBrief",
            value=f"[Ouvrir]({plan['simbrief_url']})",
            inline=True,
        )
    embed.set_footer(text=f"Strip #{plan.get('id', '?')} · {plan.get('flight_type', '')}")
    return embed


def _build_board_embed(plans: list[dict], scope: str, hours: int) -> discord.Embed:
    header = _format_board_header()
    rows = [_format_board_row(p) for p in plans[:20]]
    body = header + "\n" + ("─" * min(len(header), 90)) + "\n" + "\n".join(rows)
    if len(body) > 3800:
        body = body[:3800] + "\n…"

    legend = (
        "🔵 STAND · 🩵 PUSHBACK · 🟡 TAXI · 🟢 TAKE-OFF · "
        "🟣 CRUIZE · 🟠 APPROACH · 🔴 LANDING · 🩷 LAST TAXI"
    )
    embed = discord.Embed(
        title="🧾 Tableau des strips ATC",
        description=f"**Fenêtre :** {hours} h · {scope}\n```\n{body}\n```\n{legend}",
        color=discord.Color.dark_gold(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=f"{len(plans)} strip(s) · /strip-edit pour compléter SID/STAR/statut")
    return embed


async def _user_is_atc_or_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    # Rôle ATC via config Frequencies (nom contenant atc) ou ATC_ROLE_ID
    try:
        from config import ATC_ROLE_ID
    except Exception:
        ATC_ROLE_ID = 0
    if ATC_ROLE_ID:
        role = interaction.guild.get_role(ATC_ROLE_ID)
        if role and role in interaction.user.roles:
            return True
    return any("atc" in r.name.lower() for r in interaction.user.roles)


class FlightPlanModal(discord.ui.Modal):
    callsign = discord.ui.TextInput(
        label="Callsign",
        placeholder="Ex : AFR123 / N123AB",
        max_length=20,
    )
    departure = discord.ui.TextInput(
        label="Aéroport de départ (ICAO)",
        placeholder="Ex : LFPG",
        max_length=4,
        min_length=4,
    )
    arrival = discord.ui.TextInput(
        label="Aéroport d'arrivée (ICAO)",
        placeholder="Ex : LFPO",
        max_length=4,
        min_length=4,
    )
    gate = discord.ui.TextInput(
        label="Porte / parking",
        placeholder="Ex : A12 ou Stand 45",
        max_length=30,
        required=False,
    )

    def __init__(self, flight_type: str):
        title = f"Plan de vol {flight_type}"
        super().__init__(title=title)
        self.flight_type = flight_type  # IFR ou VFR
        if flight_type == "IFR":
            self.simbrief = discord.ui.TextInput(
                label="Lien SimBrief",
                placeholder="https://www.simbrief.com/...",
                max_length=200,
                required=True,
            )
            self.add_item(self.simbrief)
        else:
            self.simbrief = None

    async def on_submit(self, interaction: discord.Interaction):
        dep = _normalize_icao(self.departure.value)
        arr = _normalize_icao(self.arrival.value)
        callsign = self.callsign.value.strip().upper()
        gate = (self.gate.value or "").strip() or "—"
        simbrief_url = None
        if self.simbrief is not None:
            simbrief_url = self.simbrief.value.strip()
            if not simbrief_url.startswith("http"):
                await interaction.response.send_message(
                    "❌ Le lien SimBrief doit commencer par http(s)://",
                    ephemeral=True,
                )
                return

        if not _is_valid_icao(dep) or not _is_valid_icao(arr):
            await interaction.response.send_message(
                "❌ ICAO invalide (4 lettres, ex: LFPG).", ephemeral=True
            )
            return

        freq_dep = await db.get_active_atc_for_icao(interaction.guild_id, dep)
        freq_arr = await db.get_active_atc_for_icao(interaction.guild_id, arr)

        if not freq_dep and not freq_arr:
            active = await db.list_active_icaos(interaction.guild_id)
            liste = (
                ", ".join(f"`{a['icao']}`" for a in active)
                if active
                else "aucune fréquence ouverte"
            )
            await interaction.response.send_message(
                "❌ Tu dois sélectionner **au minimum un aéroport** avec une fréquence "
                f"ATC ouverte sur le serveur.\nAéroports disponibles : {liste}",
                ephemeral=True,
            )
            return

        conf = await db.get_guild_config(interaction.guild_id) or {}
        plan_ch_id = conf.get("flightplan_channel_id")
        log_ch_id = conf.get("flightplan_log_channel_id")
        plan_ch = interaction.guild.get_channel(plan_ch_id) if plan_ch_id else None
        log_ch = interaction.guild.get_channel(log_ch_id) if log_ch_id else None

        if not plan_ch:
            await interaction.response.send_message(
                "❌ Salon des plans de vol non configuré. "
                "Un admin doit utiliser `/config-canal-plandenvol`.",
                ephemeral=True,
            )
            return

        # Mentions ATC concernés
        atc_mentions = []
        seen = set()
        for freq in (freq_dep, freq_arr):
            if freq and freq.get("atc_user_id") and freq["atc_user_id"] not in seen:
                atc_mentions.append(f"<@{freq['atc_user_id']}>")
                seen.add(freq["atc_user_id"])
        ping = " ".join(atc_mentions) if atc_mentions else ""

        # Assigner la strip à l'ATC du départ (sinon arrivée)
        owner_freq = freq_dep or freq_arr
        strip_atc = None
        strip_atc_user_id = None
        if owner_freq:
            strip_atc_user_id = owner_freq.get("atc_user_id")
            if owner_freq.get("name"):
                strip_atc = owner_freq["name"]
            elif owner_freq.get("icao"):
                pos = (owner_freq.get("position") or "TWR").upper()
                strip_atc = f"{owner_freq['icao']} {pos}"

        plan_id = await db.create_flight_plan(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            flight_type=self.flight_type,
            callsign=callsign,
            departure=dep,
            arrival=arr,
            gate=gate,
            simbrief_url=simbrief_url,
            message_id=None,
            strip_status="STAND",
            strip_atc=strip_atc,
            strip_atc_user_id=strip_atc_user_id,
        )

        plan = await db.get_flight_plan(plan_id) or {
            "id": plan_id,
            "callsign": callsign,
            "flight_type": self.flight_type,
            "departure": dep,
            "arrival": arr,
            "gate": gate,
            "user_id": interaction.user.id,
            "simbrief_url": simbrief_url,
            "strip_status": "STAND",
            "strip_atc": strip_atc,
        }
        embed = _build_strip_embed(plan)
        view = _make_strip_control_view(plan_id)

        try:
            msg = await plan_ch.send(content=ping or None, embed=embed, view=view)
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Impossible d'envoyer le plan : {e}", ephemeral=True
            )
            return

        await db.set_flight_plan_message(plan_id, msg.id)
        interaction.client.add_view(view)

        if log_ch:
            log_embed = discord.Embed(
                title="🗂️ Logs — Plan de vol",
                color=discord.Color.dark_grey(),
                description=(
                    f"Déposé par {interaction.user.mention}\n"
                    f"**Callsign :** {callsign}\n"
                    f"**Type :** {self.flight_type}\n"
                    f"**Départ :** {dep} → **Arrivée :** {arr}\n"
                    f"**Porte :** {gate}"
                    + (f"\n**SimBrief :** {simbrief_url}" if simbrief_url else "")
                ),
                timestamp=discord.utils.utcnow(),
            )
            try:
                await log_ch.send(embed=log_embed)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            f"✅ Plan de vol **{self.flight_type}** envoyé avec succès !",
            ephemeral=True,
        )


class TypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="IFR", value="IFR", description="Vol IFR (lien SimBrief requis)", emoji="🧭"
            ),
            discord.SelectOption(
                label="VFR", value="VFR", description="Vol VFR", emoji="☀️"
            ),
        ]
        super().__init__(
            placeholder="Sélectionnez un type de vol",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="flightplan_type_select",
        )

    async def callback(self, interaction: discord.Interaction):
        flight_type = self.values[0]
        await interaction.response.send_modal(FlightPlanModal(flight_type))


class TypeSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(TypeSelect())


class FlightPlanPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Déposer",
        style=discord.ButtonStyle.secondary,
        emoji="🗺️",
        custom_id="flightplan_deposit",
    )
    async def deposit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Sélectionnez le type de vol :",
            view=TypeSelectView(),
            ephemeral=True,
        )


class StripStatusSelect(discord.ui.Select):
    def __init__(self, plan_id: int):
        self.plan_id = plan_id
        options = [
            discord.SelectOption(label=code, value=code, emoji=STRIP_STATUS_EMOJI.get(code, "⚪"))
            for code, _label, _style in STRIP_STATUSES
        ]
        super().__init__(
            placeholder="Changer le statut…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"strip_status_{plan_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        if not await _user_is_atc_or_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux ATC.", ephemeral=True
            )
            return
        status = self.values[0]
        await db.update_flight_plan(self.plan_id, strip_status=status)
        plan = await db.get_flight_plan(self.plan_id)
        if not plan:
            await interaction.response.send_message("Strip introuvable.", ephemeral=True)
            return
        embed = _build_strip_embed(plan)
        await interaction.response.edit_message(
            embed=embed, view=_make_strip_control_view(self.plan_id)
        )


class StripControlView(discord.ui.View):
    """Contrôle strip : statut + édition (SID/STAR/climb/XPDR) + remark."""

    def __init__(self, plan_id: int):
        super().__init__(timeout=None)
        self.plan_id = plan_id
        self.add_item(StripStatusSelect(plan_id))
        edit_btn = discord.ui.Button(
            label="Éditer strip",
            style=discord.ButtonStyle.secondary,
            emoji="✏️",
            custom_id=f"strip_edit_{plan_id}",
        )
        edit_btn.callback = self._edit_callback
        self.add_item(edit_btn)
        remark_btn = discord.ui.Button(
            label="Remark",
            style=discord.ButtonStyle.secondary,
            emoji="📝",
            custom_id=f"strip_remark_{plan_id}",
        )
        remark_btn.callback = self._remark_callback
        self.add_item(remark_btn)

    async def _edit_callback(self, interaction: discord.Interaction):
        if not await _user_is_atc_or_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux ATC.", ephemeral=True
            )
            return
        plan = await db.get_flight_plan(self.plan_id)
        if not plan:
            await interaction.response.send_message("Strip introuvable.", ephemeral=True)
            return
        await interaction.response.send_modal(StripEditModal(self.plan_id, plan))

    async def _remark_callback(self, interaction: discord.Interaction):
        if not await _user_is_atc_or_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux ATC.", ephemeral=True
            )
            return
        plan = await db.get_flight_plan(self.plan_id)
        if not plan:
            await interaction.response.send_message("Strip introuvable.", ephemeral=True)
            return
        await interaction.response.send_modal(StripRemarkModal(self.plan_id, plan))


def _make_strip_control_view(plan_id: int) -> StripControlView:
    return StripControlView(plan_id)


class StripEditModal(discord.ui.Modal, title="Éditer la strip"):
    stand = discord.ui.TextInput(label="Stand", required=False, max_length=20)
    squawk = discord.ui.TextInput(
        label="Transpondeur (squawk)",
        placeholder="Ex : 2000 / 7000",
        required=False,
        max_length=8,
    )
    sid_rwy = discord.ui.TextInput(
        label="SID/RWY", placeholder="Ex : LATRA6A/27L", required=False, max_length=30
    )
    star_rwy = discord.ui.TextInput(
        label="STAR/RWY", placeholder="Ex : LATRA", required=False, max_length=30
    )
    initial_climb = discord.ui.TextInput(
        label="Initial Climb", placeholder="Ex : FL070", required=False, max_length=15
    )

    def __init__(self, plan_id: int, plan: dict):
        super().__init__()
        self.plan_id = plan_id
        self.stand.default = plan.get("gate") or ""
        self.squawk.default = plan.get("squawk") or ""
        self.sid_rwy.default = plan.get("sid_rwy") or ""
        self.star_rwy.default = plan.get("star_rwy") or ""
        self.initial_climb.default = plan.get("initial_climb") or ""

    async def on_submit(self, interaction: discord.Interaction):
        await db.update_flight_plan(
            self.plan_id,
            gate=(self.stand.value or "").strip() or None,
            squawk=(self.squawk.value or "").strip() or None,
            sid_rwy=(self.sid_rwy.value or "").strip() or None,
            star_rwy=(self.star_rwy.value or "").strip() or None,
            initial_climb=(self.initial_climb.value or "").strip() or None,
        )
        plan = await db.get_flight_plan(self.plan_id)
        embed = _build_strip_embed(plan)
        view = _make_strip_control_view(self.plan_id)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.HTTPException:
            await interaction.response.send_message(
                "✅ Strip mise à jour.", ephemeral=True
            )


class StripRemarkModal(discord.ui.Modal, title="Remark strip"):
    remark = discord.ui.TextInput(
        label="Remark",
        style=discord.TextStyle.paragraph,
        placeholder="Remarque libre…",
        required=False,
        max_length=200,
    )

    def __init__(self, plan_id: int, plan: dict):
        super().__init__()
        self.plan_id = plan_id
        self.remark.default = plan.get("remark") or ""

    async def on_submit(self, interaction: discord.Interaction):
        await db.update_flight_plan(
            self.plan_id,
            remark=(self.remark.value or "").strip() or None,
        )
        plan = await db.get_flight_plan(self.plan_id)
        embed = _build_strip_embed(plan)
        view = _make_strip_control_view(self.plan_id)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.HTTPException:
            await interaction.response.send_message(
                "✅ Remark mise à jour.", ephemeral=True
            )


class FlightPlans(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(FlightPlanPanelView())
        try:
            for pid in await db.list_recent_flight_plan_ids(hours=48, limit=80):
                self.bot.add_view(_make_strip_control_view(pid))
        except Exception:
            pass

    @app_commands.command(
        name="panel-plan",
        description="Publier le panneau de dépôt de plan de vol",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def panel_plan(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🗺️ Déposer un plan de vol",
            color=discord.Color.from_str("#3498db"),
            description=(
                "Ce salon est dédié uniquement au dépôt de plan de vol dans le cadre "
                "d’un vol sous contrôle ATC avec une fréquence ouverte.\n\n"
                "Pour envoyer votre plan de vol :\n\n"
                "1️⃣ Cliquez sur le bouton **Déposer**\n"
                "2️⃣ Sélectionnez votre type de vol : **IFR** ou **VFR**\n"
                "3️⃣ Remplissez le formulaire :\n"
                "🔹 Callsign\n"
                "🔹 Aéroport de départ\n"
                "🔹 Aéroport d’arrivée\n"
                "🔹 Porte / parking\n"
                "🔹 Lien du plan de vol SimBrief *(IFR uniquement)*\n\n"
                "**Plan de vol SimBrief :**\n"
                "🔹 Cliquez sur “View PDF”\n"
                "🔹 Téléchargez votre plan de vol\n"
                "🔹 Copiez le lien SimBrief depuis la barre de recherche\n"
                "🔹 Collez ce lien dans le formulaire\n\n"
                "⚠️ Merci d’envoyer votre plan de vol **une seule fois**.\n"
                "Ne le renvoyez que si un ATC vous le demande en cas d’erreur.\n\n"
                "❌ Tout abus du système pourra entraîner des sanctions."
            ),
        )
        await interaction.channel.send(embed=embed, view=FlightPlanPanelView())
        await interaction.response.send_message("✅ Panneau publié.", ephemeral=True)

    @app_commands.command(
        name="config-canal-plandenvol",
        description="Salon où publier les plans de vol",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_plan_channel(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        await db.set_flightplan_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(
            f"✅ Plans de vol → {canal.mention}", ephemeral=True
        )

    @app_commands.command(
        name="config-canal-logs-plandenvol",
        description="Salon de logs des plans de vol",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_plan_logs(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ):
        await db.set_flightplan_log_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(
            f"✅ Logs plans de vol → {canal.mention}", ephemeral=True
        )

    @app_commands.command(
        name="aeroports-ouverts",
        description="Lister les aéroports avec une fréquence ATC active",
    )
    async def aeroports_ouverts(self, interaction: discord.Interaction):
        active = await db.list_active_icaos(interaction.guild_id)
        if not active:
            await interaction.response.send_message(
                "Aucun aéroport avec fréquence ouverte pour le moment.",
                ephemeral=True,
            )
            return
        lines = [
            f"`{a['icao']}` — **{a['name']}** · ATC <@{a['atc_user_id']}>"
            for a in active
        ]
        embed = discord.Embed(
            title="✈️ Aéroports contrôlés",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="strips",
        description="Tableau des strips — un board par ATC (le tien par défaut)",
    )
    @app_commands.describe(
        atc="ATC dont afficher le tableau (défaut : toi). Admins : voir un autre ATC",
        icao="Filtrer sur un aéroport (départ ou arrivée)",
        heures="Fenêtre en heures (défaut 6, max 24)",
        tous="Oui = tous les ATC / toutes les strips (admin)",
    )
    async def strips(
        self,
        interaction: discord.Interaction,
        atc: discord.Member | None = None,
        icao: str | None = None,
        heures: app_commands.Range[int, 1, 24] = 6,
        tous: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        filter_icao = _normalize_icao(icao) if icao else None
        if filter_icao and not _is_valid_icao(filter_icao):
            await interaction.followup.send(
                "❌ ICAO invalide (4 lettres, ex: LFML).", ephemeral=True
            )
            return

        is_admin = interaction.user.guild_permissions.administrator

        # Mode global : un message par ATC en ligne
        if tous:
            if not is_admin and not await _user_is_atc_or_admin(interaction):
                await interaction.followup.send("🚫 Permission refusée.", ephemeral=True)
                return
            active = await db.list_active_frequencies(interaction.guild_id)
            if not active:
                plans = await db.list_flight_plans(
                    interaction.guild_id, icao=filter_icao, hours=heures, limit=25
                )
                if not plans:
                    await interaction.followup.send(
                        "📭 Aucune strip récente.", ephemeral=True
                    )
                    return
                embed = _build_board_embed(plans, "global", heures)
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Grouper par ATC
            sent = 0
            for freq in active:
                uid = freq.get("atc_user_id")
                if not uid:
                    continue
                plans = await db.list_flight_plans(
                    interaction.guild_id,
                    icao=filter_icao or (freq.get("icao") or None),
                    hours=heures,
                    limit=20,
                    atc_user_id=uid,
                )
                # Si pas encore d'assignation atc_user_id, fallback ICAO
                if not plans and freq.get("icao"):
                    plans = await db.list_flight_plans(
                        interaction.guild_id,
                        icao=freq["icao"],
                        hours=heures,
                        limit=20,
                    )
                label = freq.get("name") or f"{freq.get('icao', '?')} {freq.get('position', '')}"
                scope = f"<@{uid}> · **{label}**"
                if not plans:
                    continue
                embed = _build_board_embed(plans, scope, heures)
                embed.title = f"🧾 Strips — {label}"
                await interaction.followup.send(embed=embed, ephemeral=True)
                sent += 1
            if sent == 0:
                await interaction.followup.send(
                    "📭 Aucune strip pour les ATC en ligne.", ephemeral=True
                )
            return

        # Board d'un ATC précis (défaut = auteur de la commande)
        target = atc or interaction.user
        if (
            target.id != interaction.user.id
            and not is_admin
            and not await _user_is_atc_or_admin(interaction)
        ):
            await interaction.followup.send(
                "🚫 Tu ne peux voir que **ton** tableau de strips.", ephemeral=True
            )
            return

        my_freq = await db.get_active_frequency_for_atc(
            interaction.guild_id, target.id
        )
        plans = await db.list_flight_plans(
            interaction.guild_id,
            icao=filter_icao,
            hours=heures,
            limit=25,
            atc_user_id=target.id,
        )
        # Fallback : strips sur l'ICAO de sa fréquence ouverte
        if not plans and my_freq and my_freq.get("icao") and not filter_icao:
            plans = await db.list_flight_plans(
                interaction.guild_id,
                icao=my_freq["icao"],
                hours=heures,
                limit=25,
            )

        if my_freq:
            label = my_freq.get("name") or (
                f"{my_freq.get('icao', '?')} {(my_freq.get('position') or '').upper()}"
            )
            scope = f"<@{target.id}> · **{label}**"
            title = f"🧾 Strips — {label}"
        else:
            scope = f"<@{target.id}> (pas de fréquence ouverte)"
            title = f"🧾 Strips — {target.display_name}"

        if not plans:
            await interaction.followup.send(
                f"📭 Aucune strip pour {scope} sur **{heures} h**.",
                ephemeral=True,
            )
            return

        embed = _build_board_embed(plans, scope, heures)
        embed.title = title
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="strip-edit",
        description="Compléter une strip (SID/RWY, STAR, climb, stand, remark, ATC)",
    )
    @app_commands.describe(
        plan_id="ID de la strip (voir footer du message ou /strips)",
        stand="Stand / porte",
        sid_rwy="SID / piste (ex: LATRA6A/27L)",
        star_rwy="STAR / piste",
        initial_climb="Initial climb (ex: FL070)",
        atc="Position ATC affichée (ex: LFPG TWR)",
        remark="Remarque",
        statut="Statut de la strip",
    )
    @app_commands.choices(
        statut=[
            app_commands.Choice(name=code, value=code)
            for code, _l, _s in STRIP_STATUSES
        ]
    )
    async def strip_edit(
        self,
        interaction: discord.Interaction,
        plan_id: int,
        stand: str | None = None,
        sid_rwy: str | None = None,
        star_rwy: str | None = None,
        initial_climb: str | None = None,
        atc: str | None = None,
        remark: str | None = None,
        statut: app_commands.Choice[str] | None = None,
    ):
        if not await _user_is_atc_or_admin(interaction):
            await interaction.response.send_message(
                "🚫 Réservé aux ATC.", ephemeral=True
            )
            return

        plan = await db.get_flight_plan(plan_id)
        if not plan or plan["guild_id"] != interaction.guild_id:
            await interaction.response.send_message(
                "Strip introuvable.", ephemeral=True
            )
            return

        fields = {}
        if stand is not None:
            fields["gate"] = stand.strip() or None
        if sid_rwy is not None:
            fields["sid_rwy"] = sid_rwy.strip() or None
        if star_rwy is not None:
            fields["star_rwy"] = star_rwy.strip() or None
        if initial_climb is not None:
            fields["initial_climb"] = initial_climb.strip() or None
        if atc is not None:
            fields["strip_atc"] = atc.strip() or None
        if remark is not None:
            fields["remark"] = remark.strip() or None
        if statut is not None:
            fields["strip_status"] = statut.value

        if not fields:
            await interaction.response.send_message(
                "Rien à modifier — renseigne au moins un champ.", ephemeral=True
            )
            return

        await db.update_flight_plan(plan_id, **fields)
        plan = await db.get_flight_plan(plan_id)
        embed = _build_strip_embed(plan)
        await interaction.response.send_message(
            content=f"✅ Strip **#{plan_id}** mise à jour.",
            embed=embed,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(FlightPlans(bot))
