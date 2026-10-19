"""PERFIL TEMPORAL "Phantom Shadows Studios" (PSS) - extension del bot Eito.

Se carga desde setup_hook de eito_setup_bot.py solo si PSS_PROFILE_ENABLED=1:
    await bot.load_extension("profiles.pss")

IMPORTANTE: este modulo NO importa eito_setup_bot. Con `python eito_setup_bot.py` ese
archivo corre como __main__ y un `import eito_setup_bot` lo cargaria otra vez (otro bot,
otros loops). El bot principal habla con el cog solo a traves de `bot.get_cog("PerfilPSS")`:
    maneja(guild)            ¿este servidor es el del perfil?
    permite(guild, evento)   ¿se permite "xp" / "voz" / "anti_multicuentas" aqui?
    canal_logs(guild)        canal de logs de moderacion del perfil (o None)
    al_entrar(member)        sustituye al on_member_join de EITO en este servidor

Todo lo demas (el check que bloquea comandos de EITO y los comandos !pss) solo actua cuando
guild.id coincide con `guild_id` del TOML.
"""

import os
import traceback
import uuid
from pathlib import Path

import discord
from discord.ext import commands

from profiles import pss_db
from profiles.pss_config import ConfigInvalida, PERMISOS_ELEVADOS, cargar
from profiles.pss_exec import (
    construir_snapshot, ejecutar, reunir_estado_mensajes,
)
from profiles.pss_plan import MENSAJE_COINCIDE, ORDEN_DESPLIEGUE, calcular_plan, lineas_plan

RUTA_POR_DEFECTO = Path(__file__).with_name("pss.toml")
TIMEOUT_CONFIRMACION = 60
COOLDOWN_SEGUNDOS = 30
LIMITE_EMBED = 3900
MSG_YA_EN_CURSO = "⚠️ Ya hay una aplicación en curso en este servidor."


class PssNoAplica(commands.CheckFailure):
    """El comando se uso fuera del servidor del perfil: se ignora sin responder."""


class PssSinPermiso(commands.CheckFailure):
    """Quien lo usa no es el dueño ni un gestor."""


def trocear(lineas, limite=LIMITE_EMBED):
    """Junta lineas en bloques de como mucho `limite` caracteres (para los embeds)."""
    bloques, actual = [], ""
    for linea in lineas:
        linea = linea if len(linea) <= limite else linea[: limite - 1] + "…"
        if actual and len(actual) + 1 + len(linea) > limite:
            bloques.append(actual)
            actual = linea
        else:
            actual = f"{actual}\n{linea}" if actual else linea
    if actual:
        bloques.append(actual)
    return bloques


# --- Vistas -------------------------------------------------------------------------------
class BotonEspecialidad(discord.ui.Button):
    """Boton persistente que da o quita un rol de especialidad (custom_id pss::rol::<key>)."""

    def __init__(self, cog, key, etiqueta):
        super().__init__(label=etiqueta, style=discord.ButtonStyle.secondary, custom_id=f"pss::rol::{key}")
        self.cog, self.key = cog, key

    async def callback(self, interaction: discord.Interaction):
        await self.cog.alternar_especialidad(interaction, self.key)


class PanelEspecialidades(discord.ui.View):
    def __init__(self, cog, keys):
        super().__init__(timeout=None)
        for key in keys:
            rol = cog.config.rol(key)
            if rol is not None:
                self.add_item(BotonEspecialidad(cog, key, rol.nombre))


class ConfirmarAplicar(discord.ui.View):
    """Confirmacion de `!pss aplicar`: 60 s y solo para quien lo invoco."""

    def __init__(self, cog, autor_id, huella):
        super().__init__(timeout=TIMEOUT_CONFIRMACION)
        self.cog, self.autor_id, self.huella = cog, autor_id, huella
        self.message = None
        token = uuid.uuid4().hex[:8]
        self.confirmar.custom_id = f"pss::confirmar:{token}"
        self.cancelar.custom_id = f"pss::cancelar:{token}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.autor_id:
            return True
        await interaction.response.send_message("❌ Solo quien ejecutó el comando puede confirmar.", ephemeral=True)
        return False

    @discord.ui.button(label="Confirmar y aplicar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, boton: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="⏳ Aplicando…", view=None)
        await self.cog.aplicar_confirmado(interaction.message, interaction.guild, self.huella)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, boton: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❎ Cancelado. No se tocó nada.", embed=None, view=None)

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(content="⌛ Tiempo agotado (60 s). No se tocó nada.", embed=None, view=None)
            except discord.HTTPException:
                pass


# --- Cog --------------------------------------------------------------------------------------
class PerfilPSS(commands.Cog):
    def __init__(self, bot, config, ruta):
        self.bot, self.config, self.ruta = bot, config, ruta
        self.ids = {}            # key -> ID de Discord (cache de perfil_recursos)

    # ---- ciclo de vida ----
    async def cog_load(self):
        # Sin BD el perfil carga igual (bloqueos y eventos funcionan); !pss avisara del fallo.
        try:
            await pss_db.asegurar_tabla()
            await self._cargar_ids()
        except Exception:
            print("⚠️ Perfil PSS: no pude preparar la tabla perfil_recursos (¿BD caída?); "
                  "!pss plan/aplicar lo reintentarán:")
            traceback.print_exc()
        self.bot.add_check(self._bloquear_comando)
        self._registrar_vista()
        print(f"✅ Perfil PSS cargado (servidor {self.config.guild_id}, "
              f"{len(self.config.comandos_bloqueados)} comandos de EITO bloqueados ahí).")

    async def cog_unload(self):
        self.bot.remove_check(self._bloquear_comando)

    def _registrar_vista(self):
        keys = [r.key for r in self.config.roles_autoasignables()]
        if keys:
            self.bot.add_view(self.fabrica_vista(keys))

    def fabrica_vista(self, keys):
        return PanelEspecialidades(self, keys)

    async def _cargar_ids(self):
        mapa = await pss_db.cargar_mapa(self.config.guild_id)
        self.ids = {key: reg.discord_id for key, reg in mapa.items()}

    # ---- API para el bot principal ----
    def maneja(self, guild):
        return guild is not None and guild.id == self.config.guild_id

    def permite(self, guild, evento):
        """False solo si `guild` es el del perfil y el TOML apaga `evento`."""
        if not self.maneja(guild) or evento not in ("xp", "voz", "anti_multicuentas"):
            return True
        return getattr(self.config.eventos, evento)

    def canal_logs(self, guild):
        """Canal de logs de moderacion del perfil, o None (el bot usa entonces el de EITO)."""
        key = self.config.eventos.canal_logs
        if not self.maneja(guild) or not key:
            return None
        canal = guild.get_channel(self.ids.get(key, 0))
        return canal if isinstance(canal, discord.TextChannel) else None

    async def al_entrar(self, member):
        """Sustituye al on_member_join de EITO en el servidor del perfil."""
        if member.bot:
            return
        guild = member.guild
        if self.config.eventos.anti_multicuentas:
            # El filtro de EITO no escucha por su cuenta: lo llama on_member_join, asi que
            # aqui se invoca solo si el TOML lo pide.
            cog = self.bot.get_cog("AntiMulticuentas")
            if cog is not None and not await cog.filtrar_miembro(member):
                return
        key_rol = self.config.eventos.rol_al_entrar
        if key_rol:
            rol = guild.get_role(self.ids.get(key_rol, 0))
            if rol is None:
                print(f"⚠️ Perfil PSS: el rol '{key_rol}' aún no existe; {member} entra sin él.")
            else:
                try:
                    await member.add_roles(rol, reason="Perfil PSS: rol al entrar")
                except discord.HTTPException as e:
                    print(f"⚠️ Perfil PSS: no pude dar {rol.name} a {member}: {e}")
        key_canal = self.config.eventos.bienvenida
        canal = guild.get_channel(self.ids.get(key_canal, 0)) if key_canal else None
        if isinstance(canal, discord.TextChannel):
            lineas = [f"¡Hola {member.mention}! 🎉"]
            for key, texto in (("reglas", "📜 Lee las reglas y la guía en"),):
                destino = guild.get_channel(self.ids.get(key, 0))
                if destino is not None:
                    lineas.append(f"{texto} {destino.mention}")
            lineas.append(f"Eres el miembro **#{guild.member_count}** 🎊")
            embed = discord.Embed(
                title=f"👋 ¡Bienvenido/a a {guild.name}!", description="\n".join(lineas),
                colour=discord.Colour(0x2ECC71),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            try:
                await canal.send(embed=embed)
            except discord.HTTPException as e:
                print(f"⚠️ Perfil PSS: no pude enviar la bienvenida de {member}: {e}")

    # ---- bloqueo de comandos de EITO ----
    def _bloquear_comando(self, ctx):
        """Check global: en el servidor del perfil, los comandos de la lista no se ejecutan."""
        if ctx.guild is None or ctx.guild.id != self.config.guild_id or ctx.command is None:
            return True
        if ctx.command.qualified_name in self.config.comandos_bloqueados:
            raise commands.CheckFailure(
                f"Este comando de EITO no está disponible en {self.config.nombre}."
            )
        return True

    # ---- botones de especialidad ----
    async def alternar_especialidad(self, interaction, key):
        guild = interaction.guild
        rol_cfg = self.config.rol(key)
        if guild is None or guild.id != self.config.guild_id or rol_cfg is None or not rol_cfg.autoasignable:
            await interaction.response.send_message("❌ Este botón no está disponible.", ephemeral=True)
            return
        if key not in self.ids:
            try:
                await self._cargar_ids()
            except Exception:
                traceback.print_exc()
        rol = guild.get_role(self.ids.get(key, 0))
        if rol is None:
            await interaction.response.send_message(
                "⚠️ Ese rol todavía no existe. Avisa a un gestor.", ephemeral=True)
            return
        # Defensa: aunque el TOML lo marque, nunca se auto-asigna un rol con permisos elevados.
        if rol.permissions.value & PERMISOS_ELEVADOS:
            await interaction.response.send_message("❌ Ese rol no se puede autoasignar.", ephemeral=True)
            return
        try:
            if rol in interaction.user.roles:
                await interaction.user.remove_roles(rol, reason="Perfil PSS: especialidad")
                texto = f"➖ Te quité **{rol.name}**."
            else:
                await interaction.user.add_roles(rol, reason="Perfil PSS: especialidad")
                texto = f"➕ Te di **{rol.name}**."
        except discord.Forbidden:
            texto = "❌ No tengo permisos para darte ese rol (mi rol debe estar por encima)."
        await interaction.response.send_message(texto, ephemeral=True)

    # ---- comprobaciones y errores de !pss ----
    def _es_gestor(self, miembro):
        if miembro.id == miembro.guild.owner_id:
            return True
        ids_gestores = {self.ids.get(k) for k in self.config.gestores}
        return any(rol.id in ids_gestores for rol in miembro.roles)

    async def cog_check(self, ctx):
        if ctx.guild is None or ctx.guild.id != self.config.guild_id:
            raise PssNoAplica()
        if not self._es_gestor(ctx.author):
            raise PssSinPermiso("Solo el dueño del servidor o los gestores del perfil pueden usar `!pss`.")
        return True

    async def cog_command_error(self, ctx, error):
        if isinstance(error, (PssNoAplica, commands.NoPrivateMessage)):
            return    # fuera de PSS el comando no existe a efectos practicos
        if isinstance(error, PssSinPermiso):
            await ctx.send(f"❌ {error}")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Espera {error.retry_after:.0f} s antes de repetirlo.")
        elif isinstance(error, commands.CommandInvokeError):
            print(f"⚠️ Perfil PSS: error en !{ctx.command.qualified_name}: {error.original!r}")
            traceback.print_exception(error.original)
            await ctx.send("❌ Error interno en el perfil (detalle en los logs del bot). No se aplicó nada más.")
        else:
            await ctx.send(f"❌ {error}")

    # ---- calculo ----
    async def _calcular(self, guild):
        """(plan, estado): lee Discord y la BD, no escribe nada."""
        await pss_db.asegurar_tabla()
        estado = await pss_db.cargar_mapa(guild.id)
        if not guild.chunked:
            await guild.chunk()
        snap = construir_snapshot(guild)
        mensajes = await reunir_estado_mensajes(guild, self.config, estado)
        return calcular_plan(self.config, snap, estado, mensajes), estado

    async def _enviar_plan(self, destino, plan, titulo):
        bloques = trocear(lineas_plan(plan))
        for i, texto in enumerate(bloques):
            embed = discord.Embed(title=titulo if i == 0 else None, description=texto,
                                  colour=discord.Colour(0xF1C40F))
            if i == len(bloques) - 1:
                embed.add_field(name="​", value=MENSAJE_COINCIDE if plan.coincide() else ORDEN_DESPLIEGUE,
                                inline=False)
            await destino.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    # ---- comandos ----
    @commands.group(name="pss", invoke_without_command=True)
    async def pss(self, ctx):
        await ctx.send(
            "**Perfil PSS** — `!pss plan` (ver qué haría, sin tocar nada) · `!pss aplicar` · "
            "`!pss recargar` · `!pss estado` · `!pss olvidar <key>`"
        )

    @pss.command(name="plan")
    @commands.cooldown(1, COOLDOWN_SEGUNDOS, commands.BucketType.guild)
    async def plan(self, ctx):
        async with ctx.typing():
            plan, _estado = await self._calcular(ctx.guild)
        await self._enviar_plan(ctx, plan, "🔍 Plan PSS — no se tocó nada")

    @pss.command(name="aplicar")
    @commands.cooldown(1, COOLDOWN_SEGUNDOS, commands.BucketType.guild)
    async def aplicar(self, ctx):
        async with ctx.typing():
            plan, _estado = await self._calcular(ctx.guild)
        if not plan.pendientes():
            await self._enviar_plan(ctx, plan, "✅ Nada que aplicar")
            return
        resumen = plan.resumen()
        lineas = [
            f"🆕 crear **{resumen['crear']}** · ✏️ actualizar **{resumen['actualizar']}** · "
            f"🔗 vincular **{resumen['vincular']}** · ⛔ bloqueado **{resumen['bloqueado']}**",
        ]
        explicitos = [
            f"• `{a.key}`: {a.detalle}" + (f" — {a.razon}" if a.razon else "")
            for a in plan.con_op("actualizar")
            if {"mover", "sincronizar", "nombre", "tipo", "borrar_antiguo"} & set(a.cambios)
        ]
        if explicitos:
            lineas += ["", "**Se moverán, renombrarán, convertirán o sincronizarán recursos existentes (y se borrarán mensajes antiguos del bot al republicarlos):**", *explicitos]
        if plan.bloqueadas():
            lineas += ["", "**Bloqueado (no se hará):**",
                       *[f"• `{a.key}`: {a.razon}" for a in plan.bloqueadas()]]
        if plan.manuales:
            lineas += ["", "**🧹 A mano después (el bot nunca borra canales ni categorías):**",
                       *[f"• {m}" for m in plan.manuales]]
        if plan.advertencias:
            lineas += ["", "**⚠️ Advertencias**", *[f"• {a}" for a in plan.advertencias]]
        lineas += ["", "Usa `!pss plan` para ver el detalle completo. No se borran canales, categorías ni roles."]
        embed = discord.Embed(
            title="⚠️ ¿Aplicar el perfil PSS?",
            description=trocear(lineas)[0],
            colour=discord.Colour(0xE67E22),
        )
        vista = ConfirmarAplicar(self, ctx.author.id, plan.huella())
        vista.message = await ctx.send(embed=embed, view=vista, allowed_mentions=discord.AllowedMentions.none())

    async def aplicar_confirmado(self, mensaje, guild, huella):
        """Se llama al pulsar «Confirmar»: toma el lock por servidor, revalida y ejecuta."""
        async def avisar(texto):
            try:
                await mensaje.edit(content=texto)
            except discord.HTTPException:
                pass

        try:
            async with pss_db.lock_aplicar(guild.id) as obtenido:
                if not obtenido:
                    await mensaje.edit(content=MSG_YA_EN_CURSO, embed=None, view=None)
                    return
                plan, estado = await self._calcular(guild)
                if plan.huella() != huella:
                    await mensaje.edit(
                        content="⚠️ El plan cambió desde que lo viste. No se tocó nada: ejecuta `!pss aplicar` otra vez.",
                        embed=None, view=None)
                    return
                resultado = await ejecutar(guild, plan, self.config, estado, self.fabrica_vista, avisar)
                await self._cargar_ids()
        except Exception:
            print("⚠️ Perfil PSS: fallo aplicando:")
            traceback.print_exc()
            await avisar("❌ La aplicación falló a medias (detalle en los logs). Revisa con `!pss plan`: es seguro repetirla.")
            return
        await avisar(f"✅ Terminado: {len(resultado.hechos)} operaciones, {len(resultado.fallos)} fallos.")
        lineas = [f"**Hecho ({len(resultado.hechos)})**", *[f"• {h}" for h in resultado.hechos]]
        if resultado.fallos:
            lineas += ["", f"**❌ Fallos ({len(resultado.fallos)})**", *[f"• {f}" for f in resultado.fallos]]
        if resultado.bloqueadas:
            lineas += ["", f"**⛔ Bloqueado ({len(resultado.bloqueadas)})**",
                       *[f"• bloqueado: {b}" for b in resultado.bloqueadas]]
        if plan.manuales:
            lineas += ["", "**🧹 A mano (el bot nunca borra canales ni categorías)**",
                       *[f"• {m}" for m in plan.manuales]]
        if plan.advertencias:
            lineas += ["", "**⚠️ Advertencias**", *[f"• {a}" for a in plan.advertencias]]
        bloques = trocear(lineas)
        for i, texto in enumerate(bloques):
            embed = discord.Embed(title="📋 Resultado de !pss aplicar" if i == 0 else None,
                                  description=texto, colour=discord.Colour(0x2ECC71 if not resultado.fallos else 0xE74C3C))
            if i == len(bloques) - 1:
                embed.add_field(name="​", value=ORDEN_DESPLIEGUE, inline=False)
            await mensaje.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @pss.command(name="recargar")
    async def recargar(self, ctx):
        try:
            nueva = cargar(self.ruta)
        except ConfigInvalida as e:
            await ctx.send("❌ El TOML no es válido; sigo con la versión anterior:\n```\n"
                           + "\n".join(f"- {x}" for x in e.errores)[:1800] + "\n```")
            return
        if nueva.guild_id != self.config.guild_id:
            await ctx.send("❌ No se puede cambiar `guild_id` con `recargar`: reinicia el bot.")
            return
        self.config = nueva
        self._registrar_vista()
        await ctx.send(f"✅ TOML recargado: {len(nueva.roles)} roles, {len(nueva.categorias)} categorías, "
                       f"{len(nueva.canales)} canales, {len(nueva.mensajes)} mensajes. Usa `!pss plan`.")

    @pss.command(name="estado")
    async def estado(self, ctx):
        await pss_db.asegurar_tabla()
        mapa = await pss_db.cargar_mapa(ctx.guild.id)
        if not mapa:
            await ctx.send("ℹ️ Todavía no hay nada guardado (no se ha aplicado el perfil).")
            return
        lineas = []
        for key, reg in sorted(mapa.items()):
            existe = (ctx.guild.get_role(reg.discord_id) if reg.tipo == "rol" else ctx.guild.get_channel(reg.discord_id)) \
                if reg.tipo != "mensaje" else True
            lineas.append(f"{'✅' if existe else '❓'} `{key}` ({reg.tipo}) → `{reg.discord_id}`"
                          + (" · creado por el perfil" if reg.creado else ""))
        for i, texto in enumerate(trocear(lineas)):
            await ctx.send(embed=discord.Embed(title="🗂️ Estado guardado" if i == 0 else None, description=texto))

    @pss.command(name="olvidar")
    async def olvidar(self, ctx, key: str):
        borrado = await pss_db.borrar(ctx.guild.id, key)
        if borrado:
            await self._cargar_ids()
            await ctx.send(f"🧹 Olvidé el mapeo de `{key}`. No toqué nada en Discord; el próximo `!pss plan` lo resolverá de nuevo.")
        else:
            await ctx.send(f"ℹ️ No había nada guardado para `{key}`.")


async def setup(bot):
    ruta = Path(os.getenv("PSS_PROFILE_CONFIG") or RUTA_POR_DEFECTO)
    config = cargar(ruta)   # ConfigInvalida -> la extension no carga y el bot lo registra
    await bot.add_cog(PerfilPSS(bot, config, ruta))
