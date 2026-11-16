"""
Commandes Discord pour lier le site Radar :
- /site-compte-atc  : génère un compte site (email + mdp temporaire) pour un ATC et l'envoie en MP.
"""

from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from config import ATC_ROLE_ID
from cogs.site_api import provision_site_atc_account

log = logging.getLogger(__name__)


def _is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    if ATC_ROLE_ID and any(r.id == ATC_ROLE_ID for r in member.roles):
        return True
    names = " ".join(r.name.lower() for r in member.roles)
    return "admin" in names or "gérant" in names or "gerant" in names or "staff" in names


class SiteAccounts(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="site-compte-atc",
        description="Créer un compte site Radar pour un ATC (email + mdp temporaire en MP)",
    )
    @app_commands.describe(
        membre="Membre ATC qui recevra les identifiants",
        email="Email du compte site (optionnel — sinon atc.<id>@skycommunity.fr)",
    )
    async def site_compte_atc(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        email: str | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not _is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Réservé aux administrateurs / staff / rôle ATC (gérant).",
                ephemeral=True,
            )
            return

        if email:
            email = email.strip().lower()
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                await interaction.response.send_message("❌ Email invalide.", ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True)

        result = await provision_site_atc_account(
            discord_user_id=membre.id,
            display_name=membre.display_name or membre.name,
            email=email,
        )
        if result.get("error"):
            await interaction.followup.send(
                f"❌ Impossible de créer le compte site : `{result['error']}`\n"
                f"Vérifie `SITE_API_URL` et `SITE_API_SECRET` côté bot, et l'endpoint site.",
                ephemeral=True,
            )
            return

        mail = result["email"]
        password = result["password"]
        created = result.get("created", True)
        reset = result.get("reset", False)

        embed = discord.Embed(
            title="✈️ Compte SkyCommunity Radar (ATC)",
            description=(
                "Voici tes identifiants pour te connecter au **site Radar**.\n"
                "Change ton mot de passe dès la première connexion (Profil)."
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(name="Email", value=f"`{mail}`", inline=False)
        embed.add_field(name="Mot de passe temporaire", value=f"`{password}`", inline=False)
        if reset:
            embed.set_footer(text="Compte existant : mot de passe réinitialisé + ATC autorisé.")
        elif not created:
            embed.set_footer(text="Compte déjà existant (ATC autorisé).")
        else:
            embed.set_footer(text="Nouveau compte créé avec droits ATC.")

        dm_ok = False
        try:
            await membre.send(embed=embed)
            dm_ok = True
        except discord.HTTPException:
            pass

        # Confirmation staff
        msg = (
            f"✅ Compte site pour {membre.mention}\n"
            f"**Email :** `{mail}`\n"
            f"**MDP temporaire :** `{password}`\n"
        )
        if dm_ok:
            msg += "📬 Identifiants envoyés en MP."
        else:
            msg += "⚠️ MP fermés — transmets les identifiants manuellement (affichés ci-dessus)."

        await interaction.followup.send(msg, ephemeral=True)
        log.info(
            "site-compte-atc: staff=%s target=%s email=%s created=%s",
            interaction.user.id,
            membre.id,
            mail,
            created,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SiteAccounts(bot))

   