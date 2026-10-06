"""ANTI-MULTICUENTAS - expulsa al entrar las cuentas de Discord demasiado nuevas.

Integracion en eito_setup_bot.py:
    from anti_multicuentas import AntiMulticuentas

    # dentro de setup_hook:
    await bot.add_cog(AntiMulticuentas(bot, registrar_log))

    # PRIMERAS lineas de on_member_join (antes del rol COMUNIDAD y la bienvenida):
    cog = bot.get_cog("AntiMulticuentas")
    if cog is not None and not await cog.filtrar_miembro(member):
        return
"""

import os
import traceback

import discord
from discord.ext import commands

from database import (
    es_usuario_permitido,
    permitir_usuario,
    quitar_usuario_permitido,
)

EDAD_MINIMA_POR_DEFECTO = 7


def _leer_edad_minima() -> int:
    """Lee EDAD_MINIMA_DIAS del entorno sin que un valor raro impida arrancar.

    Sin variable o vacia -> 7; entero >= 0 -> ese valor (0 desactiva el filtro);
    no numerica o negativa -> 7, con aviso en consola."""
    crudo = os.getenv("EDAD_MINIMA_DIAS")
    valor = (crudo or "").strip()
    if not valor:
        return EDAD_MINIMA_POR_DEFECTO
    try:
        dias = int(valor)
    except ValueError:
        dias = None
    if dias is None or dias < 0:
        print(f"⚠️ EDAD_MINIMA_DIAS={crudo!r} no es válido (debe ser un entero >= 0); "
              f"se usa {EDAD_MINIMA_POR_DEFECTO}.")
        return EDAD_MINIMA_POR_DEFECTO
    return dias


# Dias minimos de antiguedad de la cuenta de Discord para poder entrar.
# Se cambia con la variable EDAD_MINIMA_DIAS en Railway, sin tocar codigo.
EDAD_MINIMA_DIAS = _leer_edad_minima()


class AntiMulticuentas(commands.Cog):
    """Filtro de edad de cuenta + lista de excepciones aprobadas por el staff."""

    def __init__(self, bot, registrar_log):
        self.bot = bot
        # Se recibe la funcion de logs del bot principal para no duplicarla
        self.registrar_log = registrar_log

    # -----------------------------------------------------------------
    #  FILTRO (se llama desde on_member_join)
    # -----------------------------------------------------------------
    async def filtrar_miembro(self, member: discord.Member) -> bool:
        """Devuelve True si el miembro puede quedarse, False si no."""
        if member.bot:
            return True

        # 0 = filtro desactivado (explicito: con el reloj un poco desfasado una
        # cuenta recien creada daria edad negativa y no pasaria el >=)
        if EDAD_MINIMA_DIAS == 0:
            return True

        edad = discord.utils.utcnow() - member.created_at
        if edad.days >= EDAD_MINIMA_DIAS:
            return True

        guild = member.guild
        creada = discord.utils.format_dt(member.created_at, "R")

        # Excepciones aprobadas con !permitir
        try:
            if await es_usuario_permitido(str(guild.id), str(member.id)):
                await self.registrar_log(
                    guild,
                    f"✅ **{member}** (`{member.id}`) entró con cuenta nueva "
                    f"(creada {creada}) porque está en la lista de permitidos.",
                )
                return True
        except Exception as e:
            # Si la BD falla se aplica el filtro igual (es lo mas seguro)
            print(f"⚠️ Error consultando usuarios permitidos: {e}")

        dias_faltantes = max(EDAD_MINIMA_DIAS - edad.days, 1)

        # 1) DM ANTES del kick: despues ya no comparte servidor con el bot
        aviso = discord.Embed(
            title=f"⛔ No pudiste entrar a {guild.name}",
            description=(
                f"Tu cuenta de Discord es muy nueva (**{edad.days} días**). "
                f"Por seguridad pedimos al menos **{EDAD_MINIMA_DIAS} días** "
                "de antigüedad.\n\n"
                f"Podrás entrar en **{dias_faltantes} día(s)**. Si conoces a "
                "alguien del staff, pídele que te autorice para entrar antes."
            ),
            colour=discord.Colour(0xE74C3C),
        )
        try:
            await member.send(embed=aviso)
        except (discord.Forbidden, discord.HTTPException):
            pass  # DMs cerrados: se expulsa igual

        # 2) Expulsar
        try:
            await member.kick(
                reason=(
                    f"Anti-multicuentas: cuenta de {edad.days} días "
                    f"(mínimo {EDAD_MINIMA_DIAS})"
                )
            )
        except discord.Forbidden:
            # No se pudo expulsar: se queda sin rol COMUNIDAD ni bienvenida
            await self.registrar_log(
                guild,
                f"⚠️ No pude expulsar a **{member}** (`{member.id}`), cuenta "
                f"creada {creada}. Revisa que mi rol esté arriba y tenga "
                "el permiso Expulsar miembros.",
            )
            return False

        # 3) Registro para el staff
        await self.registrar_log(
            guild,
            f"🚫 **{member}** (`{member.id}`) expulsado por cuenta nueva "
            f"(creada {creada}, mínimo {EDAD_MINIMA_DIAS} días). "
            f"Si es legítimo: `!permitir {member.id}`",
        )
        return False

    # -----------------------------------------------------------------
    #  UTILIDAD
    # -----------------------------------------------------------------
    async def _buscar_usuario(self, user_id: int):
        """Devuelve el usuario de Discord o None si el ID no existe."""
        try:
            return await self.bot.fetch_user(user_id)
        except (discord.NotFound, discord.HTTPException):
            return None

    # -----------------------------------------------------------------
    #  COMANDO: PERMITIR (excepcion para una cuenta nueva legitima)
    # -----------------------------------------------------------------
    @commands.command(name="permitir")
    @commands.has_permissions(moderate_members=True)
    async def permitir(self, ctx, user_id: int):
        usuario = await self._buscar_usuario(user_id)
        if usuario is None:
            await ctx.send("❌ Ese ID no corresponde a ninguna cuenta de Discord.")
            return

        nuevo = await permitir_usuario(
            str(ctx.guild.id), str(user_id), ctx.author.display_name
        )
        if not nuevo:
            await ctx.send(f"ℹ️ **{usuario}** ya estaba en la lista de permitidos.")
            return

        await ctx.send(
            f"✅ **{usuario}** puede entrar aunque su cuenta sea nueva. "
            "Pásale la invitación."
        )
        await self.registrar_log(
            ctx.guild,
            f"✅ **{usuario}** (`{user_id}`) añadido a permitidos por "
            f"**{ctx.author.display_name}**.",
        )

    # -----------------------------------------------------------------
    #  COMANDO: DESPERMITIR (quitar la excepcion)
    # -----------------------------------------------------------------
    @commands.command(name="despermitir")
    @commands.has_permissions(moderate_members=True)
    async def despermitir(self, ctx, user_id: int):
        quitado = await quitar_usuario_permitido(str(ctx.guild.id), str(user_id))
        if not quitado:
            await ctx.send("ℹ️ Ese ID no estaba en la lista de permitidos.")
            return

        await ctx.send(f"➖ `{user_id}` quitado de la lista de permitidos.")
        await self.registrar_log(
            ctx.guild,
            f"➖ `{user_id}` quitado de permitidos por "
            f"**{ctx.author.display_name}**.",
        )

    # -----------------------------------------------------------------
    #  ERRORES DE LOS COMANDOS DE ESTE MODULO
    # -----------------------------------------------------------------
    async def cog_command_error(self, ctx, error):
        uso = f"`!{ctx.command.name} <ID de usuario>`"
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Necesitas el permiso de Moderar miembros.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Uso: {uso}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(
                f"❌ El ID debe ser un número. Uso: {uso}\n"
                "Lo encuentras en el registro de expulsión o con el modo "
                "desarrollador (clic derecho → Copiar ID)."
            )
        elif isinstance(error, commands.CheckFailure):
            # Va despues de MissingPermissions (que es subclase de CheckFailure):
            # aqui llega el check global solo_en_servidor cuando se usa por DM
            await ctx.send("❌ Este comando solo funciona en el servidor.")
        elif isinstance(error, commands.CommandInvokeError):
            # Fallo interno (p. ej. la BD caida): al usuario un mensaje generico,
            # el detalle a consola (logs de Railway)
            print(f"⚠️ Error en !{ctx.command.name}: {error.original!r}")
            traceback.print_exception(error.original)
            await ctx.send("❌ No pude completar la acción. Inténtalo de nuevo en un rato.")
        else:
            await ctx.send(f"❌ Error: {error}")
