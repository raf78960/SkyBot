"""
Planning ATC hebdomadaire — fréquences ouvertes de la semaine.
- Les ATC proposent leurs créneaux (semaine en cours + semaine suivante)
- Les admins et Gérants ATC peuvent modifier / supprimer n'importe quel créneau
- Embed permanent mis à jour automatiquement
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import TIMEZONE

try:
    from config import ATC_ROLE_ID
except ImportError:
    ATC_ROLE_ID = 0

try:
    from config import GERANT_ATC_ROLE_ID
except ImportError:
    GERANT_ATC_ROLE_ID = 0

log = logging.getLogger(__name__)

DAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MONTHS_FR = [
    "",
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def _tz() -> ZoneInfo:
    return ZoneInfo(TIMEZONE)


def _now_local() -> datetime:
    return datetime.now(_tz())


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_start_for_offset(offset: int = 0) -> date:
    """offset 0 = semaine en cours, 1 = semaine suivante."""
    today = _now_local().date()
    monday = _monday_of(today)
    return monday + timedelta(weeks=offset)


def _fmt_date_short(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _fmt_date_long(d: date) -> str:
    return f"{d.day:02d} {MONTHS_FR[d.month].upper()} {d.year}"


def _fmt_week_range(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    return f"DU {_fmt_date_short(monday)} AU {_fmt_date_short(sunday)}"


def _is_atc(member: discord.Member) -> bool:
    """Rôle ATC (env ATC_ROLE_ID) ou rôle dont le nom contient « atc » / « contrôleur »."""
    if not member or member.bot:
        return False
    if ATC_ROLE_ID and any(r.id == ATC_ROLE_ID for r in member.roles):
        return True
    for r in member.roles:
        name = r.name.lower()
        if "atc" in name or "controleur" in name or "contrôleur" in name:
            return True
    return False


async def _is_gerant_atc(member: discord.Member) -> bool:
    """Rôle Gérant ATC — peut modifier le planning (ajouter / annuler créneaux).

    Source principale : gerant_atc_role_id en base (config dashboard / commande).
    Fallback : GERANT_ATC_ROLE_ID env, puis nom de rôle contenant « gérant atc ».
    """
    if not member or member.bot:
        return False
    # Config serveur (DB)
    try:
        conf = await db.get_guild_config(member.guild.id) or {}
        allowed = set(db.parse_id_list(conf.get("gerant_atc_role_id")))
        if allowed and any(r.id in allowed for r in member.roles):
            return True
    except Exception:
        pass
    # Env (compat)
    if GERANT_ATC_ROLE_ID and any(r.id == GERANT_ATC_ROLE_ID for r in member.roles):
        return True
    # Fallback nom
    for r in member.roles:
        name = r.name.lower()
        if "gérant atc" in name or "gerant atc" in name:
            return True
    return False


async def _is_admin(interaction: discord.Interaction) -> bool:
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


async def _is_staff(member: discord.Member) -> bool:
    """Rôle staff configuré sur le serveur (guild_config.staff_role_id)."""
    if not member or member.bot:
        return False
    try:
        conf = await db.get_guild_config(member.guild.id) or {}
        staff_id = conf.get("staff_role_id")
        if staff_id and any(r.id == int(staff_id) for r in member.roles):
            return True
    except Exception:
        pass
    return False


async def _can_manage_planning(interaction: discord.Interaction) -> bool:
    """Admin OU Gérant ATC peuvent modifier le planning."""
    if await _is_admin(interaction):
        return True
    member = interaction.user
    if isinstance(member, discord.Member) and await _is_gerant_atc(member):
        return True
    return False


async def _can_propose_slot(interaction: discord.Interaction) -> bool:
    """ATC, staff, Gérant ATC ou admin peuvent proposer un créneau."""
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if _is_atc(member):
        return True
    if await _is_admin(interaction):
        return True
    if await _is_gerant_atc(member):
        return True
    if await _is_staff(member):
        return True
    return False


def _parse_time(text: str) -> tuple[int, int] | None:
    """Parse HH:MM, HHhMM, HHHmm, HHh, HH."""
    t = (text or "").strip().lower().replace(" ", "")
    m = re.match(r"^(\d{1,2})(?:[:hH]?(\d{2}))?$", t)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    if h < 0 or h > 23 or mi < 0 or mi > 59:
        return None
    return h, mi


def _parse_duration(text: str) -> int | None:
    """Parse durée en minutes. Ex: 1h30, 2h, 90, 1.5h."""
    t = (text or "").strip().lower().replace(" ", "")
    if not t:
        return None
    # 1h30 / 2h15
    m = re.match(r"^(\d+)h(\d{1,2})?$", t)
    if m:
        hours = int(m.group(1))
        mins = int(m.group(2) or 0)
        total = hours * 60 + mins
        return total if total > 0 else None
    # 90 (minutes)
    if t.isdigit():
        total = int(t)
        return total if total > 0 else None
    # 1.5h
    m = re.match(r"^(\d+(?:[.,]\d+)?)h$", t)
    if m:
        hours = float(m.group(1).replace(",", "."))
        total = int(hours * 60)
        return total if total > 0 else None
    return None


def _add_minutes(h: int, mi: int, duration: int) -> tuple[int, int]:
    total = h * 60 + mi + duration
    return (total // 60) % 24, total % 60


def _fmt_hm(h: int, mi: int) -> str:
    return f"{h:02d}h{mi:02d}"


def _display_name(guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    if member:
        return member.display_name
    return f"User {user_id}"


def build_planning_embed(
    guild: discord.Guild,
    slots: list[dict],
    week_monday: date,
    week_offset: int = 0,
) -> discord.Embed:
    sunday = week_monday + timedelta(days=6)
    label = "SEMAINE EN COURS" if week_offset == 0 else "SEMAINE SUIVANTE"

    embed = discord.Embed(
        title="📡 PLANNING ATC",
        description=(
            f"**FRÉQUENCES OUVERTES DE LA SEMAINE**\n"
            f"📅 **{_fmt_week_range(week_monday)}** · _{label}_"
        ),
        color=0x1E90FF,
        timestamp=_now_local(),
    )

    # Grouper par jour
    by_day: dict[str, list[dict]] = {str(week_monday + timedelta(days=i)): [] for i in range(7)}
    for s in slots:
        d = s.get("slot_date")
        if d in by_day:
            by_day[d].append(s)

    for i in range(7):
        day = week_monday + timedelta(days=i)
        day_key = str(day)
        day_slots = by_day.get(day_key, [])
        header = f"📅 {DAYS_FR[i]} · {_fmt_date_long(day)}"

        if not day_slots:
            value = "_Aucun créneau_"
        else:
            lines = []
            for s in day_slots:
                name = _display_name(guild, s["atc_user_id"])
                start = s["start_time"]  # HH:MM stored
                end = s["end_time"]
                # Affichage type 18h00-19h00
                try:
                    sh, sm = map(int, start.split(":"))
                    eh, em = map(int, end.split(":"))
                    time_str = f"{_fmt_hm(sh, sm)} – {_fmt_hm(eh, em)}"
                except Exception:
                    time_str = f"{start} – {end}"
                loc = s.get("location") or "—"
                lines.append(f"👤 **{name}**\n🕐 {time_str}\n🗼 {loc}")
            value = "\n\n".join(lines)

        embed.add_field(name=header, value=value[:1024], inline=True)

    # Discord : 3 champs inline par ligne → 7 champs = 3+3+1
    embed.set_footer(
        text="🕐 Heure locale Paris · Liste non exhaustive · Modifiable à tout moment"
    )
    return embed


async def refresh_planning_panels(bot: commands.Bot, guild_id: int):
    """Met à jour tous les panels enregistrés pour ce serveur."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    panels = await db.list_atc_planning_panels(guild_id)
    for panel in panels:
        try:
            channel = guild.get_channel(panel["channel_id"])
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                msg = await channel.fetch_message(panel["message_id"])
            except (discord.NotFound, discord.HTTPException):
                continue
            offset = int(panel.get("week_offset") or 0)
            monday = _week_start_for_offset(offset)
            slots = await db.list_atc_planning_slots(guild_id, str(monday))
            embed = build_planning_embed(guild, slots, monday, offset)
            await msg.edit(embed=embed, view=PlanningPanelView(week_offset=offset))
        except Exception as e:
            log.warning("Refresh panel planning ATC échoué: %s", e)


# ---------- Views / Modals ----------

class ProposeSlotModal(discord.ui.Modal, title="Proposer un créneau ATC"):
    def __init__(self, bot: commands.Bot, week_offset: int = 0):
        super().__init__()
        self.bot = bot
        self.week_offset = week_offset

        monday = _week_start_for_offset(week_offset)
        sunday = monday + timedelta(days=6)
        # Labels Discord max 45 caractères
        self.date_input = discord.ui.TextInput(
            label=f"Date JJ/MM/AAAA ({_fmt_date_short(monday)}→{_fmt_date_short(sunday)})",
            placeholder="Ex : 30/10/2026",
            max_length=10,
            required=True,
        )
        self.start_input = discord.ui.TextInput(
            label="Heure de début (Paris)",
            placeholder="Ex : 18h00 ou 18:00",
            max_length=8,
            required=True,
        )
        self.duration_input = discord.ui.TextInput(
            label="Durée",
            placeholder="Ex : 1h30 · 2h · 90",
            max_length=10,
            required=True,
        )
        self.location_input = discord.ui.TextInput(
            label="Aéroport / position",
            placeholder="Ex : LFML APP · ESSA · LFPG",
            max_length=50,
            required=True,
        )
        self.add_item(self.date_input)
        self.add_item(self.start_input)
        self.add_item(self.duration_input)
        self.add_item(self.location_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not await _can_propose_slot(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux ATC, au staff, aux Gérants ATC et aux admins.",
                ephemeral=True,
            )
            return

        monday = _week_start_for_offset(self.week_offset)
        sunday = monday + timedelta(days=6)

        # Date
        try:
            parts = self.date_input.value.strip().replace("-", "/").split("/")
            if len(parts) != 3:
                raise ValueError
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if year < 100:
                year += 2000
            slot_d = date(year, month, day)
        except Exception:
            await interaction.response.send_message(
                "❌ Date invalide. Format attendu : JJ/MM/AAAA", ephemeral=True
            )
            return

        if slot_d < monday or slot_d > sunday:
            await interaction.response.send_message(
                f"❌ La date doit être dans la semaine "
                f"**{_fmt_date_short(monday)} → {_fmt_date_short(sunday)}**.",
                ephemeral=True,
            )
            return

        # Heure début
        parsed = _parse_time(self.start_input.value)
        if not parsed:
            await interaction.response.send_message(
                "❌ Heure de début invalide. Ex : `18h00` ou `18:00`", ephemeral=True
            )
            return
        sh, sm = parsed

        # Durée
        duration = _parse_duration(self.duration_input.value)
        if not duration or duration > 12 * 60:
            await interaction.response.send_message(
                "❌ Durée invalide (ex. `1h30`, `2h`, `90`). Max 12h.",
                ephemeral=True,
            )
            return

        eh, em = _add_minutes(sh, sm, duration)
        location = self.location_input.value.strip()
        if not location:
            await interaction.response.send_message(
                "❌ Indique un aéroport / position.", ephemeral=True
            )
            return

        start_str = f"{sh:02d}:{sm:02d}"
        end_str = f"{eh:02d}:{em:02d}"

        await db.create_atc_planning_slot(
            guild_id=interaction.guild_id,
            atc_user_id=interaction.user.id,
            week_start=str(monday),
            slot_date=str(slot_d),
            start_time=start_str,
            end_time=end_str,
            duration_minutes=duration,
            location=location,
            created_by=interaction.user.id,
        )

        await interaction.response.send_message(
            f"✅ Créneau ajouté : **{_fmt_date_short(slot_d)}** "
            f"`{_fmt_hm(sh, sm)} – {_fmt_hm(eh, em)}` · **{location}**",
            ephemeral=True,
        )
        await refresh_planning_panels(self.bot, interaction.guild_id)


class AdminAddSlotModal(discord.ui.Modal, title="Admin — Ajouter un créneau"):
    def __init__(self, bot: commands.Bot, atc_user: discord.Member, week_offset: int = 0):
        super().__init__()
        self.bot = bot
        self.atc_user = atc_user
        self.week_offset = week_offset

        monday = _week_start_for_offset(week_offset)
        sunday = monday + timedelta(days=6)
        self.date_input = discord.ui.TextInput(
            label=f"Date JJ/MM/AAAA ({_fmt_date_short(monday)}→{_fmt_date_short(sunday)})",
            placeholder="Ex : 30/10/2026",
            max_length=10,
            required=True,
        )
        self.start_input = discord.ui.TextInput(
            label="Heure de début (Paris)",
            placeholder="Ex : 18h00",
            max_length=8,
            required=True,
        )
        self.duration_input = discord.ui.TextInput(
            label="Durée",
            placeholder="Ex : 1h30",
            max_length=10,
            required=True,
        )
        self.location_input = discord.ui.TextInput(
            label="Aéroport / position",
            placeholder="Ex : LFML APP",
            max_length=50,
            required=True,
        )
        self.add_item(self.date_input)
        self.add_item(self.start_input)
        self.add_item(self.duration_input)
        self.add_item(self.location_input)

    async def on_submit(self, interaction: discord.Interaction):
        monday = _week_start_for_offset(self.week_offset)
        sunday = monday + timedelta(days=6)

        try:
            parts = self.date_input.value.strip().replace("-", "/").split("/")
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if year < 100:
                year += 2000
            slot_d = date(year, month, day)
        except Exception:
            await interaction.response.send_message("❌ Date invalide.", ephemeral=True)
            return

        if slot_d < monday or slot_d > sunday:
            await interaction.response.send_message(
                f"❌ Date hors semaine {_fmt_date_short(monday)} → {_fmt_date_short(sunday)}.",
                ephemeral=True,
            )
            return

        parsed = _parse_time(self.start_input.value)
        if not parsed:
            await interaction.response.send_message("❌ Heure invalide.", ephemeral=True)
            return
        sh, sm = parsed
        duration = _parse_duration(self.duration_input.value)
        if not duration:
            await interaction.response.send_message("❌ Durée invalide.", ephemeral=True)
            return
        eh, em = _add_minutes(sh, sm, duration)
        location = self.location_input.value.strip()

        await db.create_atc_planning_slot(
            guild_id=interaction.guild_id,
            atc_user_id=self.atc_user.id,
            week_start=str(monday),
            slot_date=str(slot_d),
            start_time=f"{sh:02d}:{sm:02d}",
            end_time=f"{eh:02d}:{em:02d}",
            duration_minutes=duration,
            location=location,
            created_by=interaction.user.id,
        )

        await interaction.response.send_message(
            f"✅ Créneau ajouté pour **{self.atc_user.display_name}** : "
            f"**{_fmt_date_short(slot_d)}** `{_fmt_hm(sh, sm)} – {_fmt_hm(eh, em)}` · {location}",
            ephemeral=True,
        )
        await refresh_planning_panels(self.bot, interaction.guild_id)


class CancelSlotSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, slots: list[dict], guild: discord.Guild):
        self.bot = bot
        options = []
        for s in slots[:25]:
            try:
                d = date.fromisoformat(s["slot_date"])
                date_label = _fmt_date_short(d)
            except Exception:
                date_label = s["slot_date"]
            sh, sm = s["start_time"].split(":")
            eh, em = s["end_time"].split(":")
            label = f"{date_label} {_fmt_hm(int(sh), int(sm))}-{_fmt_hm(int(eh), int(em))} · {s['location']}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(s["id"]),
                    description=f"ID {s['id']}",
                )
            )
        super().__init__(
            placeholder="Choisis le créneau à annuler…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not await _can_manage_planning(interaction):
            await interaction.response.send_message(
                "❌ Seuls les administrateurs et les Gérants ATC peuvent annuler un créneau.",
                ephemeral=True,
            )
            return

        slot_id = int(self.values[0])
        slot = await db.get_atc_planning_slot(slot_id)
        if not slot or slot["status"] != "active":
            await interaction.response.send_message(
                "❌ Créneau introuvable ou déjà annulé.", ephemeral=True
            )
            return

        await db.cancel_atc_planning_slot(slot_id)
        await interaction.response.send_message(
            f"✅ Créneau **#{slot_id}** annulé.", ephemeral=True
        )
        await refresh_planning_panels(self.bot, interaction.guild_id)


class CancelSlotView(discord.ui.View):
    def __init__(self, bot: commands.Bot, slots: list[dict], guild: discord.Guild):
        super().__init__(timeout=120)
        self.add_item(CancelSlotSelect(bot, slots, guild))


class ModifySlotSelectView(discord.ui.View):
    """Sélection d'un créneau personnel à modifier."""

    def __init__(self, bot: commands.Bot, slots: list[dict], week_offset: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.week_offset = week_offset
        options = []
        for s in slots[:25]:
            label = f"{s.get('slot_date')} {s.get('start_time')}-{s.get('end_time')} · {s.get('location')}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(s["id"]),
                    description=f"#{s['id']}",
                )
            )
        select = discord.ui.Select(
            placeholder="Créneau à modifier…",
            options=options,
            min_values=1,
            max_values=1,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        slot_id = int(interaction.data["values"][0])
        slot = await db.get_atc_planning_slot(slot_id)
        if not slot or slot.get("status") != "active":
            await interaction.response.send_message("❌ Créneau introuvable.", ephemeral=True)
            return
        # Seul le propriétaire (ou admin/gérant) peut modifier
        is_owner = slot["atc_user_id"] == interaction.user.id
        if not is_owner and not await _can_manage_planning(interaction):
            await interaction.response.send_message(
                "❌ Tu ne peux modifier que **tes** créneaux.", ephemeral=True
            )
            return
        pending = await db.get_pending_modification_for_slot(slot_id)
        if pending:
            await interaction.response.send_message(
                "⏳ Une modification est déjà **en attente de validation** pour ce créneau.\n"
                "Attends la décision Admin / Gérant ATC avant d'en proposer une autre.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            ModifySlotModal(self.bot, slot, self.week_offset)
        )


class ModifySlotModal(discord.ui.Modal, title="Modifier un créneau ATC"):
    def __init__(self, bot: commands.Bot, slot: dict, week_offset: int = 0):
        super().__init__()
        self.bot = bot
        self.slot = slot
        self.week_offset = week_offset
        monday = _week_start_for_offset(week_offset)
        sunday = monday + timedelta(days=6)

        # Pré-remplir avec les valeurs actuelles
        try:
            d = date.fromisoformat(slot["slot_date"])
            date_default = d.strftime("%d/%m/%Y")
        except Exception:
            date_default = slot.get("slot_date") or ""

        self.date_input = discord.ui.TextInput(
            label=f"Date JJ/MM/AAAA ({_fmt_date_short(monday)}→{_fmt_date_short(sunday)})",
            default=date_default,
            max_length=10,
            required=True,
        )
        self.start_input = discord.ui.TextInput(
            label="Heure de début (Paris)",
            default=str(slot.get("start_time") or ""),
            max_length=8,
            required=True,
        )
        self.duration_input = discord.ui.TextInput(
            label="Durée",
            default=str(slot.get("duration_minutes") or 90),
            max_length=10,
            required=True,
        )
        self.location_input = discord.ui.TextInput(
            label="Aéroport / position",
            default=str(slot.get("location") or ""),
            max_length=50,
            required=True,
        )
        self.add_item(self.date_input)
        self.add_item(self.start_input)
        self.add_item(self.duration_input)
        self.add_item(self.location_input)

    async def on_submit(self, interaction: discord.Interaction):
        monday = _week_start_for_offset(self.week_offset)
        sunday = monday + timedelta(days=6)

        try:
            parts = self.date_input.value.strip().replace("-", "/").split("/")
            if len(parts) != 3:
                raise ValueError
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if year < 100:
                year += 2000
            slot_d = date(year, month, day)
        except Exception:
            await interaction.response.send_message(
                "❌ Date invalide. Format attendu : JJ/MM/AAAA", ephemeral=True
            )
            return

        if slot_d < monday or slot_d > sunday:
            await interaction.response.send_message(
                f"❌ La date doit être dans la semaine "
                f"**{_fmt_date_short(monday)} → {_fmt_date_short(sunday)}**.",
                ephemeral=True,
            )
            return

        parsed = _parse_time(self.start_input.value)
        if not parsed:
            await interaction.response.send_message(
                "❌ Heure de début invalide.", ephemeral=True
            )
            return
        sh, sm = parsed
        duration = _parse_duration(self.duration_input.value)
        if not duration or duration > 12 * 60:
            await interaction.response.send_message(
                "❌ Durée invalide (max 12h).", ephemeral=True
            )
            return
        eh, em = _add_minutes(sh, sm, duration)
        location = self.location_input.value.strip()
        if not location:
            await interaction.response.send_message("❌ Lieu obligatoire.", ephemeral=True)
            return

        new_data = {
            "slot_date": str(slot_d),
            "start_time": f"{sh:02d}:{sm:02d}",
            "end_time": f"{eh:02d}:{em:02d}",
            "duration_minutes": duration,
            "location": location,
        }
        old_data = {
            "slot_date": self.slot.get("slot_date"),
            "start_time": self.slot.get("start_time"),
            "end_time": self.slot.get("end_time"),
            "duration_minutes": self.slot.get("duration_minutes"),
            "location": self.slot.get("location"),
        }

        # Si rien n'a changé
        if all(str(old_data.get(k)) == str(new_data.get(k)) for k in new_data):
            await interaction.response.send_message(
                "ℹ️ Aucune modification détectée.", ephemeral=True
            )
            return

        conf = await db.get_guild_config(interaction.guild_id) or {}
        mod_ch_id = conf.get("atc_planning_mod_channel_id")
        if not mod_ch_id:
            await interaction.response.send_message(
                "❌ Salon de validation des modifications non configuré "
                "(panel config → Fréquences → Salon validation modifs planning).",
                ephemeral=True,
            )
            return
        mod_ch = interaction.guild.get_channel(int(mod_ch_id))
        if not mod_ch:
            await interaction.response.send_message(
                "❌ Salon de validation introuvable.", ephemeral=True
            )
            return

        mod_id = await db.create_atc_planning_modification(
            slot_id=self.slot["id"],
            guild_id=interaction.guild_id,
            requested_by=interaction.user.id,
            old=old_data,
            new=new_data,
        )

        embed = discord.Embed(
            title="✏️ Demande de modification — Planning ATC",
            description=(
                f"**Demandeur :** {interaction.user.mention}\n"
                f"**Créneau #{self.slot['id']}**"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.now(_tz()),
        )
        embed.add_field(
            name="Avant",
            value=(
                f"`{old_data['slot_date']}` {old_data['start_time']}–{old_data['end_time']}\n"
                f"**{old_data['location']}** ({old_data['duration_minutes']} min)"
            ),
            inline=True,
        )
        embed.add_field(
            name="Après",
            value=(
                f"`{new_data['slot_date']}` {new_data['start_time']}–{new_data['end_time']}\n"
                f"**{new_data['location']}** ({new_data['duration_minutes']} min)"
            ),
            inline=True,
        )
        embed.set_footer(text=f"mod_id={mod_id} · En attente Admin / Gérant ATC")

        view = PlanningModerationView(mod_id)
        self.bot.add_view(view)
        try:
            msg = await mod_ch.send(embed=embed, view=view)
            await db.set_atc_planning_modification_message(mod_id, mod_ch.id, msg.id)
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Impossible d'envoyer la notif staff : {e}", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "✅ Demande de modification envoyée. Le créneau affiché reste **inchangé** "
            "jusqu'à validation par un Admin ou Gérant ATC.",
            ephemeral=True,
        )


class PlanningModerationView(discord.ui.View):
    """Valider / Refuser une modification de créneau (Admin + Gérant ATC)."""

    def __init__(self, mod_id: int):
        super().__init__(timeout=None)
        self.mod_id = mod_id
        approve = discord.ui.Button(
            label="Valider",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"atc_planning_mod:approve:{mod_id}",
        )
        refuse = discord.ui.Button(
            label="Refuser",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id=f"atc_planning_mod:refuse:{mod_id}",
        )
        approve.callback = self._approve
        refuse.callback = self._refuse
        self.add_item(approve)
        self.add_item(refuse)

    async def _approve(self, interaction: discord.Interaction):
        if not await _can_manage_planning(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux administrateurs et Gérants ATC.", ephemeral=True
            )
            return
        mod = await db.get_atc_planning_modification(self.mod_id)
        if not mod or mod.get("status") != "pending":
            await interaction.response.send_message(
                "❌ Demande déjà traitée ou introuvable.", ephemeral=True
            )
            return
        await db.update_atc_planning_slot(
            mod["slot_id"],
            slot_date=mod["new_slot_date"],
            start_time=mod["new_start_time"],
            end_time=mod["new_end_time"],
            duration_minutes=mod["new_duration_minutes"],
            location=mod["new_location"],
        )
        await db.resolve_atc_planning_modification(
            self.mod_id, "approved", interaction.user.id
        )
        await refresh_planning_panels(interaction.client, interaction.guild_id)

        # MP au demandeur
        try:
            user = interaction.client.get_user(mod["requested_by"]) or await interaction.client.fetch_user(
                mod["requested_by"]
            )
            if user:
                await user.send(
                    f"✅ Ta modification de créneau planning ATC a été **validée** "
                    f"par {interaction.user.display_name}.\n"
                    f"**Nouveau :** `{mod['new_slot_date']}` "
                    f"{mod['new_start_time']}–{mod['new_end_time']} · **{mod['new_location']}**"
                )
        except Exception:
            pass

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.green()
        embed.set_footer(text=f"Validée par {interaction.user} · mod_id={self.mod_id}")
        await interaction.response.edit_message(embed=embed, view=None)
        await interaction.followup.send("✅ Modification validée et planning mis à jour.", ephemeral=True)

    async def _refuse(self, interaction: discord.Interaction):
        if not await _can_manage_planning(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux administrateurs et Gérants ATC.", ephemeral=True
            )
            return
        mod = await db.get_atc_planning_modification(self.mod_id)
        if not mod or mod.get("status") != "pending":
            await interaction.response.send_message(
                "❌ Demande déjà traitée ou introuvable.", ephemeral=True
            )
            return
        await db.resolve_atc_planning_modification(
            self.mod_id, "refused", interaction.user.id
        )
        try:
            user = interaction.client.get_user(mod["requested_by"]) or await interaction.client.fetch_user(
                mod["requested_by"]
            )
            if user:
                await user.send(
                    f"❌ Ta modification de créneau planning ATC a été **refusée** "
                    f"par {interaction.user.display_name}.\n"
                    f"Le créneau initial reste inchangé "
                    f"(`{mod.get('old_slot_date')}` {mod.get('old_start_time')}–{mod.get('old_end_time')} "
                    f"· **{mod.get('old_location')}**)."
                )
        except Exception:
            pass

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.red()
        embed.set_footer(text=f"Refusée par {interaction.user} · mod_id={self.mod_id}")
        await interaction.response.edit_message(embed=embed, view=None)
        await interaction.followup.send("Modification refusée. Demandeur notifié en MP.", ephemeral=True)


class PlanningPanelView(discord.ui.View):
    """Boutons sous le panel permanent (custom_id unique par week_offset)."""

    def __init__(self, week_offset: int = 0):
        super().__init__(timeout=None)
        self.week_offset = week_offset
        # Suffixe pour distinguer les deux panels dans le même salon
        week_tag = "" if week_offset == 0 else " (S+1)"
        # Boutons dynamiques avec custom_id distincts pour la persistance
        propose = discord.ui.Button(
            label=f"Proposer un créneau{week_tag}",
            style=discord.ButtonStyle.success,
            emoji="➕",
            custom_id=f"atc_planning:propose:{week_offset}",
        )
        modify = discord.ui.Button(
            label=f"Modifier mon créneau{week_tag}",
            style=discord.ButtonStyle.primary,
            emoji="✏️",
            custom_id=f"atc_planning:modify:{week_offset}",
        )
        cancel = discord.ui.Button(
            label=f"Annuler un créneau{week_tag}",
            style=discord.ButtonStyle.danger,
            emoji="🗑️",
            custom_id=f"atc_planning:cancel:{week_offset}",
        )
        refresh = discord.ui.Button(
            label=f"Rafraîchir{week_tag}",
            style=discord.ButtonStyle.secondary,
            emoji="🔄",
            custom_id=f"atc_planning:refresh:{week_offset}",
        )
        propose.callback = self._propose
        modify.callback = self._modify
        cancel.callback = self._cancel
        refresh.callback = self._refresh
        self.add_item(propose)
        self.add_item(modify)
        self.add_item(cancel)
        self.add_item(refresh)

    async def _propose(self, interaction: discord.Interaction):
        if not await _can_propose_slot(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux ATC, au staff, aux Gérants ATC et aux admins.",
                ephemeral=True,
            )
            return
        modal = ProposeSlotModal(interaction.client, week_offset=self.week_offset)
        await interaction.response.send_modal(modal)

    async def _modify(self, interaction: discord.Interaction):
        if not await _can_propose_slot(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux ATC, au staff, aux Gérants ATC et aux admins.",
                ephemeral=True,
            )
            return
        monday = _week_start_for_offset(self.week_offset)
        slots = await db.list_atc_planning_slots_for_user(
            interaction.guild_id, interaction.user.id, str(monday)
        )
        # Admin / Gérant peuvent aussi modifier n'importe quel créneau de la semaine
        if not slots and await _can_manage_planning(interaction):
            slots = await db.list_atc_planning_slots(interaction.guild_id, str(monday))
        if not slots:
            await interaction.response.send_message(
                "❌ Aucun créneau à modifier pour cette semaine (ou ce n'est pas le tien).",
                ephemeral=True,
            )
            return
        view = ModifySlotSelectView(interaction.client, slots, self.week_offset)
        await interaction.response.send_message(
            "Sélectionne le créneau à modifier :", view=view, ephemeral=True
        )

    async def _cancel(self, interaction: discord.Interaction):
        if not await _can_manage_planning(interaction):
            await interaction.response.send_message(
                "❌ Seuls les administrateurs et les Gérants ATC peuvent annuler un créneau.",
                ephemeral=True,
            )
            return
        monday = _week_start_for_offset(self.week_offset)
        slots = await db.list_atc_planning_slots(interaction.guild_id, str(monday))
        if not slots:
            await interaction.response.send_message(
                "Aucun créneau à annuler pour cette semaine.", ephemeral=True
            )
            return
        view = CancelSlotView(interaction.client, slots, interaction.guild)
        await interaction.response.send_message(
            "Sélectionne le créneau à annuler :", view=view, ephemeral=True
        )

    async def _refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await refresh_planning_panels(interaction.client, interaction.guild_id)
        await interaction.followup.send("✅ Planning rafraîchi.", ephemeral=True)


# ---------- Cog ----------

class AtcPlanning(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Vues persistantes (boutons après redémarrage) — un offset par semaine
        self.bot.add_view(PlanningPanelView(week_offset=0))
        self.bot.add_view(PlanningPanelView(week_offset=1))
        # Ré-enregistrer les validations de modifs en attente
        try:
            pending = await db.list_pending_atc_planning_modifications()
            for mod in pending:
                self.bot.add_view(PlanningModerationView(mod["id"]))
        except Exception as e:
            log.warning("Impossible de recharger les modifs planning en attente: %s", e)

    planning = app_commands.Group(
        name="atc-planning",
        description="Planning ATC hebdomadaire (fréquences de la semaine)",
    )

    async def _publish_one_panel(
        self,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        offset: int,
    ) -> discord.Message:
        """Publie (ou remplace) un panel pour une semaine donnée. Lève en cas d'échec d'envoi."""
        monday = _week_start_for_offset(offset)
        slots = await db.list_atc_planning_slots(guild.id, str(monday))
        embed = build_planning_embed(guild, slots, monday, offset)
        view = PlanningPanelView(week_offset=offset)

        existing = await db.get_atc_planning_panel(guild.id, offset)
        if existing:
            try:
                old_ch = guild.get_channel(existing["channel_id"])
                if old_ch is not None:
                    old_msg = await old_ch.fetch_message(existing["message_id"])
                    await old_msg.delete()
            except Exception:
                pass

        msg = await channel.send(embed=embed, view=view)
        await db.set_atc_planning_panel(guild.id, offset, channel.id, msg.id)
        return msg

    @planning.command(
        name="panel",
        description="Publier / mettre à jour le(s) panel(s) planning ATC",
    )
    @app_commands.describe(
        salon="Salon où publier le panel (par défaut : salon actuel)",
        semaine="Semaine à publier (vide = les deux : en cours + suivante)",
    )
    @app_commands.choices(
        semaine=[
            app_commands.Choice(name="Semaine en cours", value=0),
            app_commands.Choice(name="Semaine suivante", value=1),
            app_commands.Choice(name="Les deux semaines", value=2),
        ]
    )
    async def panel(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel | None = None,
        semaine: app_commands.Choice[int] | None = None,
    ):
        if not await _can_manage_planning(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux administrateurs et Gérants ATC.\n"
                "Configure le rôle avec `/config-role-gerant-atc` si besoin.",
                ephemeral=True,
            )
            return

        channel = salon or interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "❌ Choisis un salon texte.", ephemeral=True
            )
            return

        # Par défaut (ou choix « Les deux ») : semaine en cours + semaine suivante
        if semaine is None or int(semaine.value) == 2:
            offsets = [0, 1]
        else:
            offsets = [int(semaine.value)]

        await interaction.response.defer(ephemeral=True)

        published = []
        try:
            for offset in offsets:
                await self._publish_one_panel(interaction.guild, channel, offset)
                published.append(
                    "semaine en cours" if offset == 0 else "semaine suivante"
                )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Impossible d'envoyer le panel ici "
                "(permissions manquantes : Envoyer des messages / Embeds).",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(
                f"❌ Erreur lors de la publication du panel : `{e}`",
                ephemeral=True,
            )
            return

        await db.set_atc_planning_channel(interaction.guild_id, channel.id)

        labels = " + ".join(published)
        await interaction.followup.send(
            f"✅ Panel planning ATC publié dans {channel.mention} (**{labels}**).\n"
            f"Chaque panel a les boutons Proposer / Annuler / Rafraîchir pour sa semaine.",
            ephemeral=True,
        )

    @planning.command(name="proposer", description="Proposer un créneau de contrôle ATC")
    @app_commands.describe(semaine="Semaine ciblée")
    @app_commands.choices(
        semaine=[
            app_commands.Choice(name="Semaine en cours", value=0),
            app_commands.Choice(name="Semaine suivante", value=1),
        ]
    )
    async def proposer(
        self,
        interaction: discord.Interaction,
        semaine: app_commands.Choice[int] | None = None,
    ):
        if not await _can_propose_slot(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux ATC, au staff, aux Gérants ATC et aux admins.",
                ephemeral=True,
            )
            return
        offset = int(semaine.value) if semaine else 0
        await interaction.response.send_modal(
            ProposeSlotModal(self.bot, week_offset=offset)
        )

    @planning.command(name="annuler", description="[Admin / Gérant ATC] Annuler un créneau ATC")
    @app_commands.describe(semaine="Semaine ciblée")
    @app_commands.choices(
        semaine=[
            app_commands.Choice(name="Semaine en cours", value=0),
            app_commands.Choice(name="Semaine suivante", value=1),
        ]
    )
    async def annuler(
        self,
        interaction: discord.Interaction,
        semaine: app_commands.Choice[int] | None = None,
    ):
        if not await _can_manage_planning(interaction):
            await interaction.response.send_message(
                "❌ Seuls les administrateurs et les Gérants ATC peuvent annuler un créneau.",
                ephemeral=True,
            )
            return
        offset = int(semaine.value) if semaine else 0
        monday = _week_start_for_offset(offset)
        slots = await db.list_atc_planning_slots(interaction.guild_id, str(monday))

        if not slots:
            await interaction.response.send_message(
                "Aucun créneau à annuler pour cette semaine.", ephemeral=True
            )
            return

        view = CancelSlotView(self.bot, slots, interaction.guild)
        await interaction.response.send_message(
            "Sélectionne le créneau à annuler :", view=view, ephemeral=True
        )

    @planning.command(
        name="ajouter",
        description="[Admin / Gérant ATC] Ajouter un créneau pour un ATC",
    )
    @app_commands.describe(
        atc="ATC pour qui ajouter le créneau",
        semaine="Semaine ciblée",
    )
    @app_commands.choices(
        semaine=[
            app_commands.Choice(name="Semaine en cours", value=0),
            app_commands.Choice(name="Semaine suivante", value=1),
        ]
    )
    async def ajouter(
        self,
        interaction: discord.Interaction,
        atc: discord.Member,
        semaine: app_commands.Choice[int] | None = None,
    ):
        if not await _can_manage_planning(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux administrateurs et Gérants ATC.", ephemeral=True
            )
            return
        offset = int(semaine.value) if semaine else 0
        await interaction.response.send_modal(
            AdminAddSlotModal(self.bot, atc, week_offset=offset)
        )

    @planning.command(name="voir", description="Afficher le planning ATC (éphémère)")
    @app_commands.describe(semaine="Semaine à afficher")
    @app_commands.choices(
        semaine=[
            app_commands.Choice(name="Semaine en cours", value=0),
            app_commands.Choice(name="Semaine suivante", value=1),
        ]
    )
    async def voir(
        self,
        interaction: discord.Interaction,
        semaine: app_commands.Choice[int] | None = None,
    ):
        offset = int(semaine.value) if semaine else 0
        monday = _week_start_for_offset(offset)
        slots = await db.list_atc_planning_slots(interaction.guild_id, str(monday))
        embed = build_planning_embed(interaction.guild, slots, monday, offset)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @planning.command(name="rafraichir", description="[Admin / Gérant ATC] Rafraîchir les panels planning")
    async def rafraichir(self, interaction: discord.Interaction):
        if not await _can_manage_planning(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux administrateurs et Gérants ATC.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await refresh_planning_panels(self.bot, interaction.guild_id)
        await interaction.followup.send("✅ Panels rafraîchis.", ephemeral=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        log.exception("Erreur commande planning: %s", error)
        msg = f"❌ Erreur : `{error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AtcPlanning(bot))