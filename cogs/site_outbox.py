"""
Poll l'outbox du site SkyCommunity Radar et publie les messages sur Discord.

Le site dépose des messages prêts à publier (pré-ouvertures, absences, alertes…).
Ce cog les récupère toutes les 30 s, les poste, puis confirme l'envoi.

Variables d'environnement :
  SITE_API_URL          http://127.0.0.1:8001/api
  BOT_API_SECRET        (ou SITE_API_SECRET en repli) — Bearer vers /api/bot/*
  CHANNEL_ANNONCES      (optionnel) override du salon annonces
  CHANNEL_RESP_PILOTES  ID salon staff pilotes (optionnel)
  CHANNEL_RESP_ATC      ID salon staff ATC (optionnel)

Pour « annonces », on réutilise automatiquement le salon déjà configuré
via /freq-config-annonces (freq_announce_channel_id en base).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp
import discord
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

SITE_API_URL = os.getenv("SITE_API_URL", "").rstrip("/")
SITE_API_SECRET = (
    os.getenv("BOT_API_SECRET", "").strip()
    or os.getenv("SITE_API_SECRET", "").strip()
)

CHANNEL_ANNONCES = int(os.getenv("CHANNEL_ANNONCES", "0") or 0)
CHANNEL_RESP_PILOTES = int(os.getenv("CHANNEL_RESP_PILOTES", "0") or 0)
CHANNEL_RESP_ATC = int(os.getenv("CHANNEL_RESP_ATC", "0") or 0)

# Mémoire locale id site → message Discord (pour type "traitee")
_sent: dict[str, tuple[int, int]] = {}  # site_msg_id → (channel_id, message_id)



class PreopenCancelView(discord.ui.View):
    """Boutons staff : accepter / refuser une demande d'annulation de pré-ouverture (site)."""

    def __init__(self, pre_id: str):
        super().__init__(timeout=None)
        self.pre_id = pre_id
        accept = discord.ui.Button(
            label="Accepter l'annulation",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"site_preopen_cancel:accept:{pre_id}",
        )
        refuse = discord.ui.Button(
            label="Refuser",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id=f"site_preopen_cancel:refuse:{pre_id}",
        )
        accept.callback = self._accept
        refuse.callback = self._refuse
        self.add_item(accept)
        self.add_item(refuse)

    async def _staff_ok(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        import database as db
        conf = await db.get_guild_config(interaction.guild.id) or {}
        allowed = set(db.parse_id_list(conf.get("gerant_atc_role_id")))
        if allowed and any(r.id in allowed for r in interaction.user.roles):
            return True
        # fallback noms
        for r in interaction.user.roles:
            n = r.name.lower()
            if "gérant atc" in n or "gerant atc" in n or "responsable atc" in n:
                return True
        return False

    async def _decide(self, interaction: discord.Interaction, decision: str):
        if not await self._staff_ok(interaction):
            await interaction.response.send_message(
                "❌ Réservé aux administrateurs et Responsable / Gérant ATC.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        if not SITE_API_URL or not SITE_API_SECRET:
            await interaction.followup.send("❌ SITE_API_URL / secret manquants.", ephemeral=True)
            return
        url = f"{SITE_API_URL}/bot/preopenings/{self.pre_id}/cancel-decision"
        headers = {
            "Authorization": f"Bearer {SITE_API_SECRET}",
            "Content-Type": "application/json",
            "User-Agent": "SkyCommunityBot/1.0",
        }
        payload = {
            "decision": decision,
            "staff_name": interaction.user.display_name,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    body = await resp.text()
                    if resp.status not in (200, 201):
                        await interaction.followup.send(
                            f"❌ Site HTTP {resp.status}: {body[:300]}", ephemeral=True
                        )
                        return
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur appel site : {e}", ephemeral=True)
            return

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        if decision == "accept":
            embed.color = discord.Color.green()
            embed.title = "✅ ANNULATION DE PRÉ-OUVERTURE ACCEPTÉE"
        else:
            embed.color = discord.Color.red()
            embed.title = "⛔ ANNULATION DE PRÉ-OUVERTURE REFUSÉE"
        embed.set_footer(text=f"Traitée par {interaction.user.display_name}")
        try:
            await interaction.message.edit(embed=embed, view=None)
        except Exception:
            pass
        await interaction.followup.send(
            f"{'✅ Annulation acceptée.' if decision == 'accept' else '⛔ Demande refusée.'}",
            ephemeral=True,
        )

    async def _accept(self, interaction: discord.Interaction):
        await self._decide(interaction, "accept")

    async def _refuse(self, interaction: discord.Interaction):
        await self._decide(interaction, "refuse")


class SiteOutbox(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if SITE_API_URL and SITE_API_SECRET:
            self.poll_outbox.start()
            log.info("SiteOutbox: polling %s/bot/outbox toutes les 30 s", SITE_API_URL)
        else:
            log.warning("SiteOutbox désactivé (SITE_API_URL / SITE_API_SECRET manquants)")

    def cog_unload(self):
        self.poll_outbox.cancel()

    @tasks.loop(seconds=30)
    async def poll_outbox(self):
        if not SITE_API_URL or not SITE_API_SECRET:
            return
        try:
            messages = await self._fetch_outbox()
            for msg in messages:
                await self._handle(msg)
        except aiohttp.ClientConnectorError:
            # Site non démarré (port 8001 fermé) — silencieux, on retentera
            log.debug("Site injoignable (%s) — outbox ignorée", SITE_API_URL)
        except Exception as e:
            log.warning("poll_outbox: %s", e)

    @poll_outbox.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Boutons persistants demande d'annulation pré-ouverture (site)."""
        if interaction.data is None:
            return
        if interaction.type is not discord.InteractionType.component:
            return
        cid = str(interaction.data.get("custom_id") or "")
        if not cid.startswith("site_preopen_cancel:"):
            return
        parts = cid.split(":")
        if len(parts) != 3:
            return
        _, decision, pre_id = parts
        if decision not in ("accept", "refuse"):
            return
        view = PreopenCancelView(pre_id)
        if decision == "accept":
            await view._accept(interaction)
        else:
            await view._refuse(interaction)


    async def _fetch_outbox(self) -> list[dict]:
        url = f"{SITE_API_URL}/bot/outbox?limit=50"
        headers = {
            "Authorization": f"Bearer {SITE_API_SECRET}",
            "User-Agent": "SkyCommunityBot/1.0",
            "ngrok-skip-browser-warning": "true",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    log.warning("outbox HTTP %s: %s", resp.status, text[:200])
                    return []
                return await resp.json()

    async def _confirm(self, msg_id: str) -> None:
        url = f"{SITE_API_URL}/bot/outbox/{msg_id}/done"
        headers = {
            "Authorization": f"Bearer {SITE_API_SECRET}",
            "User-Agent": "SkyCommunityBot/1.0",
            "ngrok-skip-browser-warning": "true",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status not in (200, 201):
                        log.warning("confirm %s → HTTP %s", msg_id, resp.status)
        except Exception as e:
            log.warning("confirm %s failed: %s", msg_id, e)

    async def _resolve_annonces_channel(self):
        """Réutilise le salon d'annonces déjà configuré via /freq-config-annonces."""
        if CHANNEL_ANNONCES:
            ch = self.bot.get_channel(CHANNEL_ANNONCES)
            if ch:
                return ch
        # Même salon que les embeds ouverture/fermeture de fréquences
        import database as db
        from config import GUILD_ID
        guild = self.bot.get_guild(GUILD_ID) if GUILD_ID else (self.bot.guilds[0] if self.bot.guilds else None)
        if not guild:
            return None
        conf = await db.get_guild_config(guild.id) or {}
        ch_id = conf.get("freq_announce_channel_id")
        if ch_id:
            return guild.get_channel(ch_id)
        return None

    async def _resolve_validation_atc_channel(self):
        """Même salon que les demandes de modification de planning ATC."""
        import database as db
        from config import GUILD_ID
        guild = self.bot.get_guild(GUILD_ID) if GUILD_ID else (self.bot.guilds[0] if self.bot.guilds else None)
        if not guild:
            return None
        conf = await db.get_guild_config(guild.id) or {}
        ch_id = conf.get("atc_planning_mod_channel_id")
        if ch_id:
            return guild.get_channel(int(ch_id))
        # fallback: CHANNEL_RESP_ATC
        if CHANNEL_RESP_ATC:
            return self.bot.get_channel(CHANNEL_RESP_ATC)
        return None


    def _controller_proxy(self, payload: dict):
        """Objet minimal avec .mention pour les embeds de frequencies.py."""
        did = payload.get("discord_id") or payload.get("atc_discord_id")
        name = (payload.get("controller") or "").strip() or "—"
        mention = name
        if did:
            try:
                mention = f"<@{int(did)}>"
            except (TypeError, ValueError):
                pass

        class _C:
            pass

        c = _C()
        c.mention = mention
        c.display_name = name
        return c

    def _freq_embed_from_payload(self, mtype: str, payload: dict):
        """Réutilise strictement les embeds de cogs.frequencies."""
        from cogs.frequencies import (
            _embed_open,
            _embed_close,
            _embed_preopen,
            _embed_preclose,
            _service_label,
        )

        icao = (payload.get("icao") or (payload.get("callsign") or "?").split("_")[0] or "?").upper()
        position = (payload.get("position") or payload.get("type") or (payload.get("callsign") or "?").split("_")[-1] or "?").upper()
        frequency = payload.get("frequency") or payload.get("frequency_mhz") or "—"
        languages = payload.get("languages") or "—"
        hour = payload.get("hour") or payload.get("start_at") or "—"
        if isinstance(hour, str) and "T" in hour:
            try:
                hour = hour.replace("Z", "").split("T")[1][:5]
            except Exception:
                pass
        controller = self._controller_proxy(payload)

        if mtype == "preouverture":
            return _embed_preopen(icao, frequency, position, str(hour), languages, controller)
        if mtype in ("ouverture", "frequency_open", "freq_open"):
            return _embed_open(icao, frequency, position, languages, controller)
        if mtype in ("fermeture", "frequency_close", "freq_close"):
            return _embed_close(icao, position, controller)
        if mtype in ("prefermeture", "preclose"):
            return _embed_preclose(icao, position, str(hour), controller)
        if mtype == "preouverture_annulee":
            # Pas d'équivalent exact dans frequencies.py : même grille visuelle que preopen, titre annulé
            embed = _embed_preopen(icao, frequency, position, str(hour), languages, controller)
            embed.title = "❌ PRÉ-OUVERTURE ANNULÉE"
            embed.color = discord.Color.red()
            if payload.get("cancelled_by"):
                embed.add_field(name="Annulée par", value=str(payload["cancelled_by"]), inline=True)
            if payload.get("cancel_reason"):
                embed.add_field(name="Motif", value=str(payload["cancel_reason"])[:500], inline=False)
            return embed
        if mtype == "preouverture_demande_annulation":
            embed = discord.Embed(
                title="🔔 DEMANDE D'ANNULATION DE PRÉ-OUVERTURE",
                color=discord.Color.blurple(),
            )
            embed.add_field(name="🛫 Aéroport", value=icao, inline=True)
            freq_txt = f"{frequency} MHz" if frequency != "—" and "MHz" not in str(frequency) else str(frequency)
            embed.add_field(name="📻 Fréquence", value=freq_txt, inline=True)
            embed.add_field(name="📡 Service", value=_service_label(position), inline=False)
            embed.add_field(name="🕑 Heure", value=str(hour), inline=True)
            embed.add_field(name="👤 Contrôleur", value=controller.mention, inline=False)
            if payload.get("reason"):
                embed.add_field(name="Motif", value=str(payload["reason"])[:500], inline=False)
            return embed
        return None

    async def _freq_ping_mentions(self, guild: discord.Guild | None) -> str:
        """Ping fréquences déjà configuré via /freq-config-role (freq_ping_role_id)."""
        if not guild:
            return ""
        import database as db
        conf = await db.get_guild_config(guild.id) or {}
        rid = conf.get("freq_ping_role_id")
        if not rid:
            return ""
        role = guild.get_role(int(rid))
        return role.mention if role else ""

    async def _absence_ping_mentions(self, guild: discord.Guild | None) -> str:
        """Pings absences déjà configurés (absence_ping_role_ids via /config-panel)."""
        if not guild:
            return ""
        import database as db
        conf = await db.get_guild_config(guild.id) or {}
        mentions: list[str] = []
        try:
            for rid in db.parse_id_list(conf.get("absence_ping_role_ids")):
                role = guild.get_role(int(rid))
                if role and role.mention not in mentions:
                    mentions.append(role.mention)
        except Exception:
            pass
        return " ".join(mentions)

    def _absence_embed_from_site(self, mtype: str, text: str, payload: dict) -> discord.Embed:
        """Embed absence site — même esprit que cogs/absences._absence_embed."""
        if mtype == "absence_demande":
            title, color = "📝 Demande d'absence", discord.Color.gold()
        elif mtype == "absence_frequente":
            title, color = "⚠️ Absences fréquentes", discord.Color.red()
        elif mtype.startswith("absence_") and mtype.endswith(("acceptee", "accept")):
            title, color = "✅ Absence acceptée", discord.Color.green()
        elif mtype.startswith("absence_") and mtype.endswith(("refusee", "refuse")):
            title, color = "❌ Absence refusée", discord.Color.dark_grey()
        else:
            title, color = "🏖️ Absence déclarée", discord.Color.orange()
        embed = discord.Embed(title=title, description=text[:4000], color=color)
        if payload.get("absence_id"):
            embed.set_footer(text=f"absence_id={payload['absence_id']} · site SkyCommunity")
        else:
            embed.set_footer(text="site SkyCommunity Radar")
        return embed

    async def _handle(self, msg: dict[str, Any]) -> None:
        mid = msg.get("id")
        if not mid:
            return
        mtype = msg.get("type") or ""
        target = msg.get("target") or ""
        text = (msg.get("text") or "").strip()
        payload = msg.get("payload") or {}

        # Message de type "traitee" → édite le message d'origine
        if mtype == "traitee":
            replaces = payload.get("replaces")
            if replaces and replaces in _sent:
                ch_id, msg_id = _sent[replaces]
                try:
                    channel = self.bot.get_channel(ch_id) or await self.bot.fetch_channel(ch_id)
                    if isinstance(channel, (discord.TextChannel, discord.Thread)):
                        old = await channel.fetch_message(msg_id)
                        new_content = (old.content or "") + f"\n\n✅ **Traitée** — {text}"
                        if len(new_content) > 1900:
                            new_content = new_content[:1900] + "…"
                        await old.edit(content=new_content)
                except Exception as e:
                    log.warning("traitee edit %s: %s", replaces, e)
            await self._confirm(mid)
            return

        if not text:
            await self._confirm(mid)
            return

        channel = None
        member = None

        if target == "membre":
            did = msg.get("discord_id")
            if did:
                try:
                    user = await self.bot.fetch_user(int(did))
                    member = user
                except Exception:
                    log.warning("membre introuvable %s", did)
        elif target == "annonces":
            channel = await self._resolve_annonces_channel()
        elif target == "validation_atc":
            channel = await self._resolve_validation_atc_channel()
        elif target == "responsables_pilotes" and CHANNEL_RESP_PILOTES:
            channel = self.bot.get_channel(CHANNEL_RESP_PILOTES)
        elif target == "responsables_atc" and CHANNEL_RESP_ATC:
            channel = self.bot.get_channel(CHANNEL_RESP_ATC)

        sent_msg = None
        try:
            if member:
                sent_msg = await member.send(text[:2000])
            elif channel and isinstance(channel, (discord.TextChannel, discord.Thread)):
                embed = None
                content = text[:2000]
                allowed = discord.AllowedMentions.none()
                from config import GUILD_ID
                guild = channel.guild or (self.bot.get_guild(GUILD_ID) if GUILD_ID else None)

                # Ouverture / pré-ouverture / fermeture / annulation → embeds de frequencies.py
                if mtype in (
                    "preouverture",
                    "preouverture_annulee",
                    "ouverture",
                    "frequency_open",
                    "freq_open",
                    "fermeture",
                    "frequency_close",
                    "freq_close",
                    "prefermeture",
                    "preclose",
                ) and (
                    payload.get("embed")
                    or payload.get("icao")
                    or payload.get("callsign")
                    or payload.get("frequency")
                ):
                    embed = self._freq_embed_from_payload(mtype, payload)
                    pings = await self._freq_ping_mentions(guild)
                    content = pings if pings else None
                    allowed = discord.AllowedMentions(roles=True, users=True)

                # Absences → embed + ping absence_ping_role_ids (/config-panel)
                if mtype.startswith("absence"):
                    embed = self._absence_embed_from_site(mtype, text, payload)
                    pings = await self._absence_ping_mentions(guild)
                    content = pings if pings else None
                    if pings:
                        allowed = discord.AllowedMentions(roles=True, users=True)

                # Demande d'annulation pré-ouverture → embed (contrôleur) + ping freq
                if mtype == "preouverture_demande_annulation":
                    embed = self._freq_embed_from_payload(mtype, payload)
                    pings = await self._freq_ping_mentions(guild)
                    content = pings if pings else None
                    allowed = discord.AllowedMentions(roles=True, users=True)
                    pre_id = str(payload.get("id") or "")
                    view = PreopenCancelView(pre_id) if pre_id else None
                    if embed is not None:
                        sent_msg = await channel.send(
                            content=content, embed=embed, view=view, allowed_mentions=allowed
                        )
                        if sent_msg:
                            _sent[mid] = (sent_msg.channel.id, sent_msg.id)
                        await self._confirm(mid)
                        log.info("Outbox publié: %s → %s (boutons validation)", mtype, target)
                        return

                if mtype == "planning_demande_modification":
                    embed = discord.Embed(
                        title="🔔 Demande de modification planning",
                        description=text[:4000],
                        color=discord.Color.blurple(),
                    )
                    if payload.get("requested_by") or payload.get("controller"):
                        embed.add_field(
                            name="🎧 Contrôleur",
                            value=str(payload.get("requested_by") or payload.get("controller")),
                            inline=True,
                        )
                    embed.set_footer(text="site SkyCommunity Radar")
                    pings = await self._freq_ping_mentions(guild)
                    content = pings if pings else None
                    if pings:
                        allowed = discord.AllowedMentions(roles=True, users=True)

                if embed is not None:
                    sent_msg = await channel.send(
                        content=content, embed=embed, allowed_mentions=allowed
                    )
                else:
                    sent_msg = await channel.send(content, allowed_mentions=allowed)
            else:
                log.warning("Pas de destination pour target=%s type=%s", target, mtype)
                await self._confirm(mid)
                return
        except discord.Forbidden:
            log.warning("Impossible d'envoyer (Forbidden) target=%s", target)
            await self._confirm(mid)
            return
        except Exception as e:
            log.exception("envoi outbox %s: %s", mid, e)
            return

        if sent_msg:
            _sent[mid] = (sent_msg.channel.id, sent_msg.id)
            if len(_sent) > 500:
                for k in list(_sent.keys())[:100]:
                    _sent.pop(k, None)

        await self._confirm(mid)
        log.info("Outbox publié: %s → %s", mtype, target)


async def setup(bot: commands.Bot):
    await bot.add_cog(SiteOutbox(bot))