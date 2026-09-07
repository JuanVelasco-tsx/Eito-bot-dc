"""EITO SERVER SETUP BOT - crea categorias, canales, roles y da funciones al server."""

import json
import os
import re
import time
from datetime import timedelta

import discord
from discord.ext import commands

# Cargar variables desde un archivo .env local (si existe).
# En produccion (hosting) las variables se ponen en el panel, no hace falta .env.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- TOKEN ---
TOKEN = os.getenv("DISCORD_TOKEN", "PON_TU_TOKEN_AQUI")

# --- NOMBRES DE CANALES CLAVE (deben coincidir con los creados en el setup) ---
CANAL_BIENVENIDA = "👋・bienvenida"
CANAL_REGLAS = "📜・reglas"
CANAL_ROLES = "🎭・roles"
CANAL_ANUNCIOS = "📣・anuncios"
CANAL_PRESENTACIONES = "🙋・presentaciones"
CANAL_NIVELES = "📈・niveles"
CANAL_SUGERENCIAS = "💡・sugerencias"
CANAL_LOGS = "🛡️・registros"
CANAL_STEAM = "🎮・perfiles-steam"

# --- ROL QUE SE DA AUTOMATICAMENTE AL ENTRAR ---
ROL_AUTOMATICO = "COMUNIDAD"

# --- ROLES QUE SE PUEDEN AUTOASIGNAR CON BOTONES ---
# (etiqueta del boton, nombre exacto del rol, emoji)
ROLES_PLATAFORMA = [
    ("PC", "PC", "🖥️"),
    ("XBOX", "XBOX", "🟢"),
    ("PlayStation", "PlayStation", "🔵"),
    ("Switch", "Switch", "🔴"),
    ("Mobile", "Mobile", "📱"),
]
ROLES_REGION = [
    ("Europe", "Europe", "🇪🇺"),
    ("North America", "North America", "🌎"),
    ("South America", "South America", "🌎"),
    ("Asia", "Asia", "🌏"),
    ("Oceania", "Oceania", "🌏"),
    ("Africa", "Africa", "🌍"),
]

# --- ESTRUCTURA DE CANALES ---
ESTRUCTURA = [
    {"categoria": "📢 INFORMACIÓN", "canales": [
        (CANAL_BIENVENIDA, "text"), (CANAL_REGLAS, "text"),
        ("📣・anuncios", "text"), (CANAL_ROLES, "text"),
        ("📅・eventos", "text"), ("🙋・presentaciones", "text")]},
    {"categoria": "💬 COMUNIDAD", "canales": [
        ("💬・general", "text"), ("📸・clips-y-capturas", "text"),
        ("🤖・comandos", "text"), (CANAL_NIVELES, "text"),
        (CANAL_SUGERENCIAS, "text")]},
    {"categoria": "🧟 LEFT 4 DEAD", "canales": [
        ("📦・packs", "text"), ("⚙️・autoexec", "text"),
        ("📜・scripts", "text"), ("🗂️・colecciones", "text"),
        (CANAL_STEAM, "text")]},
    {"categoria": "🔊 PA JUGARR", "canales": [
        ("🎧 Sala de espera", "voice"), ("🎮 Juegos", "voice")]},
    {"categoria": "🛡️ STAFF", "canales": [
        (CANAL_LOGS, "text")]},
]

# --- ROLES (nombre, color, hoist, mentionable) ---
ROLES = [
    ("♡ Admins", 0x5865F2, True, True),
    ("・∴Moderador∴・", 0x9B59B6, True, True),
    ("🤖 carl-bot", 0x95A5A6, False, False),
    ("COMUNIDAD", 0x2ECC71, True, True),
    ("━━ Plataforma ━━", 0x2F3136, True, False),
    ("PC", 0xE67E22, False, True),
    ("XBOX", 0x2ECC71, False, True),
    ("PlayStation", 0x3498DB, False, True),
    ("Switch", 0xE74C3C, False, True),
    ("Mobile", 0xF1C40F, False, True),
    ("━━ Región ━━", 0x2F3136, True, False),
    ("Europe", 0x3498DB, False, True),
    ("North America", 0x3498DB, False, True),
    ("South America", 0x3498DB, False, True),
    ("Asia", 0x3498DB, False, True),
    ("Oceania", 0x3498DB, False, True),
    ("Africa", 0x3498DB, False, True),
]

# --- TEXTO DE LAS REGLAS ---
TEXTO_REGLAS = (
    "📜 **REGLAS DE EITO** 📜\n\n"
    "1️⃣ Respeta a todos los miembros. Nada de insultos, racismo ni acoso.\n"
    "2️⃣ Prohibido el spam, la publicidad sin permiso y los enlaces sospechosos.\n"
    "3️⃣ Usa cada canal para su tema. Lee los nombres antes de escribir.\n"
    "4️⃣ Nada de contenido NSFW ni ilegal.\n"
    "5️⃣ Respeta las decisiones del staff.\n\n"
    "Al estar aquí aceptas estas normas. ¡Disfruta y a jugar! 🎮"
)

# --- TEXTO DE LA PLANTILLA DE PRESENTACIONES ---
TEXTO_PRESENTACIONES = (
    "🙋 **¡Preséntate a la comunidad!** 🙋\n\n"
    "Copia esta plantilla, rellénala y mándala en este canal:\n\n"
    "```\n"
    "👤 Nombre / apodo:\n"
    "🎮 Juegos favoritos:\n"
    "🕹️ Plataforma:\n"
    "🌍 Región:\n"
    "💬 Algo sobre ti:\n"
    "```\n"
    "¡Así te conocemos mejor! 🎉"
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Necesario para la bienvenida automatica (on_member_join)

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# =====================================================================
#  PERSISTENCIA DE DATOS (XP y avisos en archivos JSON)
# =====================================================================
ARCHIVO_XP = "niveles.json"
ARCHIVO_WARNS = "avisos.json"

# Configuracion de XP
XP_POR_MENSAJE = 15        # XP que se gana por mensaje
COOLDOWN_XP = 60           # segundos entre ganancias de XP (anti-spam)

# Cache en memoria: {"guild_id": {"user_id": xp}}
xp_data = {}
warns_data = {}
# Control de cooldown de XP en memoria: {(guild_id, user_id): timestamp}
ultimo_xp = {}


def _cargar_json(ruta):
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _guardar_json(ruta, data):
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"⚠️ No se pudo guardar {ruta}: {e}")


def xp_necesaria(nivel):
    """XP total necesaria para alcanzar un nivel dado."""
    return 5 * (nivel ** 2) + 50 * nivel + 100


def nivel_desde_xp(xp):
    """Calcula el nivel a partir de la XP acumulada."""
    nivel = 0
    while xp >= xp_necesaria(nivel):
        xp -= xp_necesaria(nivel)
        nivel += 1
    return nivel


def buscar_canal(guild, nombre):
    """Devuelve el canal de texto por nombre, o None si no existe."""
    return discord.utils.get(guild.text_channels, name=nombre)


async def registrar_log(guild, texto):
    """Escribe una linea en el canal de registros de moderacion si existe."""
    canal = buscar_canal(guild, CANAL_LOGS)
    if canal is not None:
        try:
            await canal.send(texto)
        except discord.Forbidden:
            pass


# =====================================================================
#  PANEL DE ROLES CON BOTONES
# =====================================================================
class BotonRol(discord.ui.Button):
    """Boton que da o quita un rol al pulsarlo."""

    def __init__(self, etiqueta, nombre_rol, emoji):
        # custom_id fijo para que la vista sea persistente tras reiniciar el bot
        super().__init__(
            label=etiqueta,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            custom_id=f"rol::{nombre_rol}",
        )
        self.nombre_rol = nombre_rol

    async def callback(self, interaction: discord.Interaction):
        rol = discord.utils.get(interaction.guild.roles, name=self.nombre_rol)
        if rol is None:
            await interaction.response.send_message(
                f"⚠️ El rol '{self.nombre_rol}' no existe. Avisa a un admin.",
                ephemeral=True,
            )
            return

        miembro = interaction.user
        try:
            if rol in miembro.roles:
                await miembro.remove_roles(rol)
                await interaction.response.send_message(
                    f"➖ Te quité el rol **{self.nombre_rol}**.", ephemeral=True
                )
            else:
                await miembro.add_roles(rol)
                await interaction.response.send_message(
                    f"➕ Te di el rol **{self.nombre_rol}**.", ephemeral=True
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ No tengo permisos para darte ese rol. "
                "Mi rol debe estar por encima del rol a asignar.",
                ephemeral=True,
            )


class PanelRoles(discord.ui.View):
    """Vista persistente con todos los botones de roles."""

    def __init__(self):
        super().__init__(timeout=None)  # persistente
        for etiqueta, nombre_rol, emoji in ROLES_PLATAFORMA + ROLES_REGION:
            self.add_item(BotonRol(etiqueta, nombre_rol, emoji))


# =====================================================================
#  EVENTOS
# =====================================================================
@bot.event
async def on_ready():
    global xp_data, warns_data
    # Cargar datos persistentes
    xp_data = _cargar_json(ARCHIVO_XP)
    warns_data = _cargar_json(ARCHIVO_WARNS)
    # Registrar la vista persistente para que los botones funcionen tras reiniciar
    bot.add_view(PanelRoles())
    print(f"✅ Conectado como {bot.user}")
    print("Admin: !setup !setupsteam !reglas !panelroles !presentaciones !anuncio")
    print("Moderación: !borrar !kick !ban !mute !unmute !warn !warns")
    print("Comunidad: !ping !miembros !avatar !serverinfo !ayuda !nivel !top")
    print("Utilidad: !encuesta !sugerencia")


@bot.event
async def on_message(message: discord.Message):
    # Ignorar bots y mensajes fuera de un servidor
    if message.author.bot or message.guild is None:
        # Aun asi procesar comandos (por si acaso)
        await bot.process_commands(message)
        return

    gid = str(message.guild.id)
    uid = str(message.author.id)
    clave = (gid, uid)
    ahora = time.time()

    # Ganar XP con cooldown
    if ahora - ultimo_xp.get(clave, 0) >= COOLDOWN_XP:
        ultimo_xp[clave] = ahora
        xp_data.setdefault(gid, {})
        nivel_previo = nivel_desde_xp(xp_data[gid].get(uid, 0))
        xp_data[gid][uid] = xp_data[gid].get(uid, 0) + XP_POR_MENSAJE
        nivel_nuevo = nivel_desde_xp(xp_data[gid][uid])
        _guardar_json(ARCHIVO_XP, xp_data)

        # Aviso de subida de nivel (en el canal de niveles si existe)
        if nivel_nuevo > nivel_previo:
            canal_nivel = buscar_canal(message.guild, CANAL_NIVELES) or message.channel
            try:
                await canal_nivel.send(
                    f"🎉 ¡{message.author.mention} subió al **nivel {nivel_nuevo}**!"
                )
            except discord.Forbidden:
                pass

    # IMPORTANTE: dejar que los comandos sigan funcionando
    await bot.process_commands(message)


@bot.event
async def on_member_join(member: discord.Member):
    """Da la bienvenida y asigna el rol automatico cuando entra alguien."""
    guild = member.guild

    # Rol automatico
    rol = discord.utils.get(guild.roles, name=ROL_AUTOMATICO)
    if rol is not None:
        try:
            await member.add_roles(rol)
        except discord.Forbidden:
            print(f"⚠️ Sin permisos para dar el rol {ROL_AUTOMATICO}")

    # Mensaje de bienvenida (embed con foto y contador de miembros)
    canal = discord.utils.get(guild.text_channels, name=CANAL_BIENVENIDA)
    if canal is not None:
        embed = discord.Embed(
            title=f"👋 ¡Bienvenido/a a {guild.name}!",
            description=(
                f"¡Hola {member.mention}! 🎉\n\n"
                f"Pásate por {CANAL_REGLAS} y date tus roles en {CANAL_ROLES}.\n\n"
                f"Eres el miembro **#{guild.member_count}** 🎊"
            ),
            colour=discord.Colour(0x2ECC71),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await canal.send(embed=embed)


# =====================================================================
#  COMANDO: SETUP (crea roles y canales)
# =====================================================================
@bot.command(name="setup")
@commands.has_permissions(administrator=True)
async def setup(ctx):
    guild = ctx.guild
    await ctx.send("🔧 Montando la estructura...")

    n_roles = 0
    for nombre, color, hoist, ment in ROLES:
        if discord.utils.get(guild.roles, name=nombre):
            continue
        try:
            await guild.create_role(name=nombre, colour=discord.Colour(color),
                                    hoist=hoist, mentionable=ment)
            n_roles += 1
        except discord.Forbidden:
            await ctx.send(f"⚠️ Sin permisos para el rol: {nombre}")
    await ctx.send(f"👥 Roles creados: {n_roles}")

    n_can = 0
    for bloque in ESTRUCTURA:
        cat = discord.utils.get(guild.categories, name=bloque["categoria"])
        if not cat:
            cat = await guild.create_category(bloque["categoria"])
        for nombre_canal, tipo in bloque["canales"]:
            if discord.utils.get(cat.channels, name=nombre_canal):
                continue
            if tipo == "voice":
                await guild.create_voice_channel(nombre_canal, category=cat)
            else:
                await guild.create_text_channel(nombre_canal, category=cat)
            n_can += 1
    await ctx.send(f"✅ ¡Listo! Canales creados: {n_can} 🎉")

    # Configurar el canal de perfiles de Steam como "solo-bot"
    await configurar_canal_steam(ctx)


async def configurar_canal_steam(ctx):
    """Deja el canal de Steam solo-lectura para @everyone (solo el bot escribe)
    y publica un mensaje fijo de instrucciones si aun no existe."""
    guild = ctx.guild
    canal = buscar_canal(guild, CANAL_STEAM)
    if canal is None:
        return

    # Permisos: todos ven pero no escriben; el bot si puede escribir
    try:
        await canal.set_permissions(
            guild.default_role, send_messages=False, add_reactions=False
        )
        if guild.me.top_role:
            await canal.set_permissions(guild.me, send_messages=True)
    except discord.Forbidden:
        await ctx.send(
            f"⚠️ No pude ajustar permisos de {canal.mention}. "
            "Revisa que mi rol esté arriba y tenga Gestionar canales."
        )

    # Mensaje fijo de instrucciones (solo si el canal esta vacio)
    historial = [m async for m in canal.history(limit=1)]
    if not historial:
        embed = discord.Embed(
            title="🎮 Comparte tu perfil de Steam",
            description=(
                "Este canal es un **escaparate de perfiles** para buscar con quién jugar.\n\n"
                "Para aparecer aquí, escribe en 🤖・comandos:\n"
                "```\n!steam <tu enlace de Steam>\n```\n"
                "Ejemplo:\n"
                "`!steam https://steamcommunity.com/id/tunombre`\n\n"
                "El bot publicará tu tarjeta aquí automáticamente. "
                "Este canal se mantiene limpio: solo el bot escribe. 🤖"
            ),
            colour=discord.Colour(0x1B2838),
        )
        try:
            await canal.send(embed=embed)
        except discord.Forbidden:
            pass


@setup.error
async def setup_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: SETUPSTEAM (reconfigura solo el canal de Steam)
# =====================================================================
@bot.command(name="setupsteam")
@commands.has_permissions(administrator=True)
async def setupsteam(ctx):
    canal = buscar_canal(ctx.guild, CANAL_STEAM)
    if canal is None:
        await ctx.send(f"⚠️ No encuentro {CANAL_STEAM}. Corre !setup primero.")
        return
    await configurar_canal_steam(ctx)
    await ctx.send(f"✅ Canal {canal.mention} configurado como solo-bot.")


@setupsteam.error
async def setupsteam_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: REGLAS (publica las reglas en el canal de reglas)
# =====================================================================
@bot.command(name="reglas")
@commands.has_permissions(administrator=True)
async def reglas(ctx):
    guild = ctx.guild
    canal = discord.utils.get(guild.text_channels, name=CANAL_REGLAS)
    if canal is None:
        await ctx.send(f"⚠️ No encuentro el canal {CANAL_REGLAS}. Corre !setup primero.")
        return
    embed = discord.Embed(
        description=TEXTO_REGLAS,
        colour=discord.Colour(0x5865F2),
    )
    await canal.send(embed=embed)
    await ctx.send(f"✅ Reglas publicadas en {canal.mention}")


@reglas.error
async def reglas_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: PANELROLES (publica el panel de botones en el canal de roles)
# =====================================================================
@bot.command(name="panelroles")
@commands.has_permissions(administrator=True)
async def panelroles(ctx):
    guild = ctx.guild
    canal = discord.utils.get(guild.text_channels, name=CANAL_ROLES)
    if canal is None:
        await ctx.send(f"⚠️ No encuentro el canal {CANAL_ROLES}. Corre !setup primero.")
        return
    embed = discord.Embed(
        title="🎭 Elige tus roles",
        description=(
            "Pulsa un botón para darte o quitarte un rol.\n\n"
            "**🎮 Plataforma:** en qué juegas.\n"
            "**🌍 Región:** desde dónde te conectas."
        ),
        colour=discord.Colour(0x2ECC71),
    )
    await canal.send(embed=embed, view=PanelRoles())
    await ctx.send(f"✅ Panel de roles publicado en {canal.mention}")


@panelroles.error
async def panelroles_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: PRESENTACIONES (publica la plantilla en el canal)
# =====================================================================
@bot.command(name="presentaciones")
@commands.has_permissions(administrator=True)
async def presentaciones(ctx):
    guild = ctx.guild
    canal = discord.utils.get(guild.text_channels, name=CANAL_PRESENTACIONES)
    if canal is None:
        await ctx.send(
            f"⚠️ No encuentro el canal {CANAL_PRESENTACIONES}. Corre !setup primero."
        )
        return
    embed = discord.Embed(
        description=TEXTO_PRESENTACIONES,
        colour=discord.Colour(0xF1C40F),
    )
    await canal.send(embed=embed)
    await ctx.send(f"✅ Plantilla publicada en {canal.mention}")


@presentaciones.error
async def presentaciones_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: ANUNCIO (publica un anuncio con formato en el canal de anuncios)
# =====================================================================
@bot.command(name="anuncio")
@commands.has_permissions(administrator=True)
async def anuncio(ctx, *, texto: str):
    guild = ctx.guild
    canal = discord.utils.get(guild.text_channels, name=CANAL_ANUNCIOS)
    if canal is None:
        await ctx.send(f"⚠️ No encuentro el canal {CANAL_ANUNCIOS}. Corre !setup primero.")
        return
    embed = discord.Embed(
        title="📣 ANUNCIO",
        description=texto,
        colour=discord.Colour(0xE67E22),
    )
    embed.set_footer(text=f"Publicado por {ctx.author.display_name}")
    await canal.send(embed=embed)
    await ctx.send(f"✅ Anuncio publicado en {canal.mention}")


@anuncio.error
async def anuncio_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!anuncio <texto del anuncio>`")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  MODERACIÓN: BORRAR MENSAJES
# =====================================================================
@bot.command(name="borrar")
@commands.has_permissions(manage_messages=True)
async def borrar(ctx, cantidad: int):
    if cantidad < 1 or cantidad > 100:
        await ctx.send("❌ Elige un número entre 1 y 100.")
        return
    # +1 para borrar tambien el mensaje del propio comando
    borrados = await ctx.channel.purge(limit=cantidad + 1)
    aviso = await ctx.send(f"🧹 Borré {len(borrados) - 1} mensajes.")
    await aviso.delete(delay=3)


@borrar.error
async def borrar_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas el permiso de Gestionar mensajes.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!borrar <cantidad>` (ej. `!borrar 10`)")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ La cantidad debe ser un número.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  MODERACIÓN: KICK
# =====================================================================
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, miembro: discord.Member, *, razon: str = "Sin razón indicada"):
    if miembro == ctx.author:
        await ctx.send("❌ No puedes expulsarte a ti mismo.")
        return
    if miembro.top_role >= ctx.author.top_role:
        await ctx.send("❌ No puedes expulsar a alguien con un rol igual o superior al tuyo.")
        return
    try:
        await miembro.kick(reason=razon)
        await ctx.send(f"👢 **{miembro.display_name}** fue expulsado. Razón: {razon}")
        await registrar_log(
            ctx.guild,
            f"👢 **{miembro}** expulsado por **{ctx.author.display_name}**. Razón: {razon}",
        )
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para expulsar a ese miembro (revisa mi rol).")


@kick.error
async def kick_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas el permiso de Expulsar miembros.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!kick @usuario [razón]`")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  MODERACIÓN: BAN
# =====================================================================
@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, miembro: discord.Member, *, razon: str = "Sin razón indicada"):
    if miembro == ctx.author:
        await ctx.send("❌ No puedes banearte a ti mismo.")
        return
    if miembro.top_role >= ctx.author.top_role:
        await ctx.send("❌ No puedes banear a alguien con un rol igual o superior al tuyo.")
        return
    try:
        await miembro.ban(reason=razon)
        await ctx.send(f"🔨 **{miembro.display_name}** fue baneado. Razón: {razon}")
        await registrar_log(
            ctx.guild,
            f"🔨 **{miembro}** baneado por **{ctx.author.display_name}**. Razón: {razon}",
        )
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para banear a ese miembro (revisa mi rol).")


@ban.error
async def ban_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas el permiso de Banear miembros.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!ban @usuario [razón]`")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  MODERACIÓN: MUTE (timeout de Discord)
# =====================================================================
def _parsear_duracion(texto):
    """Convierte '10m', '2h', '30s', '1d' en segundos. None si es invalido."""
    if not texto:
        return None
    unidades = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unidad = texto[-1].lower()
    if unidad not in unidades:
        return None
    try:
        cantidad = int(texto[:-1])
    except ValueError:
        return None
    if cantidad <= 0:
        return None
    return cantidad * unidades[unidad]


@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, miembro: discord.Member, duracion: str,
               *, razon: str = "Sin razón indicada"):
    if miembro.top_role >= ctx.author.top_role:
        await ctx.send("❌ No puedes silenciar a alguien con un rol igual o superior al tuyo.")
        return
    segundos = _parsear_duracion(duracion)
    if segundos is None:
        await ctx.send("❌ Duración inválida. Usa s/m/h/d. Ej: `10m`, `2h`, `1d`.")
        return
    if segundos > 28 * 86400:
        await ctx.send("❌ El máximo permitido por Discord es 28 días.")
        return
    try:
        await miembro.timeout(timedelta(seconds=segundos), reason=razon)
        await ctx.send(
            f"🔇 **{miembro.display_name}** silenciado por {duracion}. Razón: {razon}"
        )
        await registrar_log(
            ctx.guild,
            f"🔇 **{miembro}** silenciado {duracion} por "
            f"**{ctx.author.display_name}**. Razón: {razon}",
        )
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para silenciar a ese miembro (revisa mi rol).")


@mute.error
async def mute_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas el permiso de Moderar miembros (timeout).")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!mute @usuario <duración> [razón]` (ej. `!mute @user 10m spam`)")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  MODERACIÓN: UNMUTE
# =====================================================================
@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, miembro: discord.Member):
    try:
        await miembro.timeout(None)
        await ctx.send(f"🔊 **{miembro.display_name}** ya no está silenciado.")
    except discord.Forbidden:
        await ctx.send("❌ No tengo permisos para hacer eso (revisa mi rol).")


@unmute.error
async def unmute_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas el permiso de Moderar miembros.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!unmute @usuario`")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  MODERACIÓN: WARN (avisos guardados)
# =====================================================================
@bot.command(name="warn")
@commands.has_permissions(kick_members=True)
async def warn(ctx, miembro: discord.Member, *, razon: str = "Sin razón indicada"):
    if miembro.bot:
        await ctx.send("❌ No puedes avisar a un bot.")
        return
    gid = str(ctx.guild.id)
    uid = str(miembro.id)
    warns_data.setdefault(gid, {})
    warns_data[gid].setdefault(uid, [])
    warns_data[gid][uid].append({
        "razon": razon,
        "mod": ctx.author.display_name,
    })
    _guardar_json(ARCHIVO_WARNS, warns_data)
    total = len(warns_data[gid][uid])
    await ctx.send(
        f"⚠️ **{miembro.display_name}** avisado. Razón: {razon}\n"
        f"Total de avisos: **{total}**"
    )
    await registrar_log(
        ctx.guild,
        f"⚠️ **{miembro}** avisado por **{ctx.author.display_name}** "
        f"(total {total}). Razón: {razon}",
    )


@warn.error
async def warn_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas el permiso de Expulsar miembros.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!warn @usuario [razón]`")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  MODERACIÓN: WARNS (ver avisos de un miembro)
# =====================================================================
@bot.command(name="warns")
async def warns(ctx, miembro: discord.Member = None):
    miembro = miembro or ctx.author
    gid = str(ctx.guild.id)
    uid = str(miembro.id)
    lista = warns_data.get(gid, {}).get(uid, [])
    if not lista:
        await ctx.send(f"✅ **{miembro.display_name}** no tiene avisos.")
        return
    embed = discord.Embed(
        title=f"⚠️ Avisos de {miembro.display_name}",
        description=f"Total: **{len(lista)}**",
        colour=discord.Colour(0xE67E22),
    )
    for i, w in enumerate(lista, 1):
        embed.add_field(
            name=f"Aviso #{i}",
            value=f"Razón: {w['razon']}\nPor: {w['mod']}",
            inline=False,
        )
    await ctx.send(embed=embed)


@warns.error
async def warns_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  UTILIDAD: ENCUESTA (👍👎)
# =====================================================================
@bot.command(name="encuesta")
async def encuesta(ctx, *, pregunta: str):
    embed = discord.Embed(
        title="📊 Encuesta",
        description=pregunta,
        colour=discord.Colour(0x3498DB),
    )
    embed.set_footer(text=f"Encuesta de {ctx.author.display_name}")
    mensaje = await ctx.send(embed=embed)
    await mensaje.add_reaction("👍")
    await mensaje.add_reaction("👎")


@encuesta.error
async def encuesta_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!encuesta <pregunta>`")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  UTILIDAD: SUGERENCIA
# =====================================================================
@bot.command(name="sugerencia")
async def sugerencia(ctx, *, texto: str):
    embed = discord.Embed(
        title="💡 Nueva sugerencia",
        description=texto,
        colour=discord.Colour(0xF1C40F),
    )
    embed.set_author(
        name=ctx.author.display_name,
        icon_url=ctx.author.display_avatar.url,
    )
    # Publicar en el canal de sugerencias si existe; si no, en el canal actual
    canal = buscar_canal(ctx.guild, CANAL_SUGERENCIAS) or ctx.channel
    mensaje = await canal.send(embed=embed)
    await mensaje.add_reaction("👍")
    await mensaje.add_reaction("👎")
    if canal != ctx.channel:
        await ctx.send(f"✅ ¡Sugerencia enviada a {canal.mention}!")


@sugerencia.error
async def sugerencia_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!sugerencia <texto>`")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  GAMING: STEAM (publica una tarjeta con el perfil de Steam)
# =====================================================================
# Base para convertir un accountID (32 bits) en un SteamID64 (formula oficial)
STEAM_ID64_BASE = 76561197960265728


def normalizar_steam(entrada):
    """Convierte lo que ponga el usuario en una URL valida de perfil de Steam.

    Acepta:
      - URL completa: https://steamcommunity.com/id/nombre
      - URL completa: https://steamcommunity.com/profiles/7656...
      - SteamID64 a secas: 7656... -> /profiles/7656...
      - AccountID / friend code numerico: 1214417234 -> se convierte a SteamID64
      - Vanity a secas (con letras): nombre -> /id/nombre
    Devuelve la URL o None si no es valido.
    """
    entrada = entrada.strip()

    # URL ya completa de steamcommunity
    match = re.match(
        r"^(https?://)?steamcommunity\.com/(id|profiles)/[\w-]+/?$",
        entrada,
        re.IGNORECASE,
    )
    if match:
        url = entrada if entrada.lower().startswith("http") else "https://" + entrada
        return url.rstrip("/")

    # SteamID64 suelto (17 digitos que empiezan por 7656)
    if re.fullmatch(r"7656\d{13}", entrada):
        return f"https://steamcommunity.com/profiles/{entrada}"

    # Numero puro que NO es SteamID64 -> tratarlo como accountID / friend code
    if entrada.isdigit():
        account_id = int(entrada)
        # Rango razonable de un accountID de 32 bits (evita numeros absurdos)
        if 0 < account_id < 2**32:
            steam_id64 = STEAM_ID64_BASE + account_id
            return f"https://steamcommunity.com/profiles/{steam_id64}"
        return None

    # Vanity name suelto (debe contener letras, no ser solo numeros)
    if re.fullmatch(r"[\w-]{2,32}", entrada):
        return f"https://steamcommunity.com/id/{entrada}"

    return None


@bot.command(name="steam")
async def steam(ctx, *, entrada: str):
    url = normalizar_steam(entrada)
    if url is None:
        await ctx.send(
            "❌ No reconozco ese perfil. Manda tu enlace de Steam completo "
            "(ej. `https://steamcommunity.com/id/tunombre`) o tu SteamID64."
        )
        return

    embed = discord.Embed(
        title=f"🎮 Perfil de Steam de {ctx.author.display_name}",
        description=f"🔗 **[Ver perfil / Añadir amigo]({url})**\n\n`{url}`",
        colour=discord.Colour(0x1B2838),  # azul oscuro estilo Steam
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    # Añadir plataforma y region si el usuario tiene esos roles
    roles_juego = [
        r.name for r in ctx.author.roles
        if r.name in [p[1] for p in ROLES_PLATAFORMA + ROLES_REGION]
    ]
    if roles_juego:
        embed.add_field(name="🕹️ Perfil de jugador", value=", ".join(roles_juego))

    embed.set_footer(text="¡Añádelo y a matar zombies juntos! 🧟")

    # Publicar SIEMPRE en el canal de perfiles (Opcion A: escaparate solo-bot)
    canal = buscar_canal(ctx.guild, CANAL_STEAM)
    if canal is None:
        await ctx.send(
            f"⚠️ No encuentro el canal {CANAL_STEAM}. Un admin debe correr !setup."
        )
        return

    await canal.send(embed=embed)

    # Borrar el mensaje del comando para mantener limpio el chat
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass

    # Confirmacion breve que se auto-borra a los 5s (no ensucia)
    aviso = await ctx.send(f"✅ {ctx.author.mention}, tu perfil se publicó en {canal.mention}")
    await aviso.delete(delay=5)


@steam.error
async def steam_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Uso: `!steam <tu enlace de Steam o SteamID64>`\n"
            "Ej: `!steam https://steamcommunity.com/id/tunombre`"
        )
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMUNIDAD: NIVEL (ver tu nivel y XP)
# =====================================================================
@bot.command(name="nivel")
async def nivel(ctx, miembro: discord.Member = None):
    miembro = miembro or ctx.author
    gid = str(ctx.guild.id)
    uid = str(miembro.id)
    xp_total = xp_data.get(gid, {}).get(uid, 0)
    nivel_actual = nivel_desde_xp(xp_total)

    # XP dentro del nivel actual
    xp_restante = xp_total
    for n in range(nivel_actual):
        xp_restante -= xp_necesaria(n)
    xp_para_subir = xp_necesaria(nivel_actual)

    embed = discord.Embed(
        title=f"📈 Nivel de {miembro.display_name}",
        colour=discord.Colour(0x9B59B6),
    )
    embed.set_thumbnail(url=miembro.display_avatar.url)
    embed.add_field(name="Nivel", value=str(nivel_actual))
    embed.add_field(name="XP total", value=str(xp_total))
    embed.add_field(
        name="Progreso",
        value=f"{xp_restante} / {xp_para_subir} XP para el siguiente nivel",
        inline=False,
    )
    await ctx.send(embed=embed)


@nivel.error
async def nivel_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMUNIDAD: TOP (ranking de niveles)
# =====================================================================
@bot.command(name="top")
async def top(ctx):
    gid = str(ctx.guild.id)
    datos = xp_data.get(gid, {})
    if not datos:
        await ctx.send("Aún no hay XP registrada. ¡Escribe para ganar! 💬")
        return
    ranking = sorted(datos.items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(
        title="🏆 Ranking de niveles",
        colour=discord.Colour(0xF1C40F),
    )
    medallas = ["🥇", "🥈", "🥉"]
    lineas = []
    for i, (uid, xp) in enumerate(ranking):
        miembro = ctx.guild.get_member(int(uid))
        nombre = miembro.display_name if miembro else f"Usuario {uid}"
        prefijo = medallas[i] if i < 3 else f"**{i + 1}.**"
        lineas.append(f"{prefijo} {nombre} — Nivel {nivel_desde_xp(xp)} ({xp} XP)")
    embed.description = "\n".join(lineas)
    await ctx.send(embed=embed)


# =====================================================================
#  COMUNIDAD: PING
# =====================================================================
@bot.command(name="ping")
async def ping(ctx):
    latencia = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latencia: {latencia} ms")


# =====================================================================
#  COMUNIDAD: MIEMBROS
# =====================================================================
@bot.command(name="miembros")
async def miembros(ctx):
    total = ctx.guild.member_count
    await ctx.send(f"👥 Somos **{total}** miembros en {ctx.guild.name}.")


# =====================================================================
#  COMUNIDAD: AVATAR
# =====================================================================
@bot.command(name="avatar")
async def avatar(ctx, miembro: discord.Member = None):
    miembro = miembro or ctx.author
    embed = discord.Embed(
        title=f"Avatar de {miembro.display_name}",
        colour=discord.Colour(0x5865F2),
    )
    embed.set_image(url=miembro.display_avatar.url)
    await ctx.send(embed=embed)


@avatar.error
async def avatar_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMUNIDAD: SERVERINFO
# =====================================================================
@bot.command(name="serverinfo")
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(
        title=f"ℹ️ Información de {guild.name}",
        colour=discord.Colour(0x2ECC71),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="👥 Miembros", value=str(guild.member_count))
    embed.add_field(name="💬 Canales", value=str(len(guild.channels)))
    embed.add_field(name="🎭 Roles", value=str(len(guild.roles)))
    if guild.owner:
        embed.add_field(name="👑 Dueño", value=guild.owner.display_name)
    embed.add_field(
        name="📅 Creado el",
        value=guild.created_at.strftime("%d/%m/%Y"),
    )
    await ctx.send(embed=embed)


# =====================================================================
#  COMANDO: AYUDA (muestra la lista de comandos)
# =====================================================================
@bot.command(name="ayuda")
async def ayuda(ctx):
    perms = ctx.author.guild_permissions
    es_admin = perms.administrator
    es_mod = perms.kick_members or perms.ban_members or perms.moderate_members

    embed = discord.Embed(
        title="📖 Comandos de EITO",
        description="Todos los comandos usan el prefijo `!`",
        colour=discord.Colour(0x5865F2),
    )

    # Seccion visible para TODOS
    embed.add_field(
        name="🎮 Comunidad",
        value=(
            "`!ping` — comprueba que el bot responde\n"
            "`!miembros` — cuántos miembros hay\n"
            "`!avatar [@usuario]` — muestra un avatar en grande\n"
            "`!serverinfo` — info del servidor\n"
            "`!nivel [@usuario]` — muestra tu nivel y XP\n"
            "`!top` — ranking de niveles del servidor\n"
            "`!ayuda` — muestra esta lista"
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Utilidad",
        value=(
            "`!encuesta <pregunta>` — crea una encuesta 👍👎\n"
            "`!sugerencia <texto>` — envía una sugerencia con votación\n"
            "`!steam <enlace o SteamID>` — publica tu perfil de Steam"
        ),
        inline=False,
    )

    # Solo para moderadores
    if es_mod or es_admin:
        embed.add_field(
            name="🛡️ Moderación",
            value=(
                "`!borrar <n>` — borra los últimos N mensajes (1–100)\n"
                "`!kick @usuario [razón]` — expulsa a un miembro\n"
                "`!ban @usuario [razón]` — banea a un miembro\n"
                "`!mute @usuario <duración> [razón]` — silencia (ej. 10m, 2h)\n"
                "`!unmute @usuario` — quita el silencio\n"
                "`!warn @usuario [razón]` — avisa a un miembro\n"
                "`!warns [@usuario]` — muestra los avisos"
            ),
            inline=False,
        )

    # Solo para admins
    if es_admin:
        embed.add_field(
            name="🔧 Administración",
            value=(
                "`!setup` — crea canales, categorías y roles\n"
                "`!setupsteam` — reconfigura el canal de perfiles\n"
                "`!reglas` — publica las reglas\n"
                "`!panelroles` — publica el panel de roles con botones\n"
                "`!presentaciones` — publica la plantilla de presentación\n"
                "`!anuncio <texto>` — publica un anuncio"
            ),
            inline=False,
        )

    embed.set_footer(text="Ganas XP al escribir. Además: bienvenida y rol automático al entrar 🎉")
    await ctx.send(embed=embed)


if __name__ == "__main__":
    if TOKEN == "PON_TU_TOKEN_AQUI":
        print("⚠️  Falta el TOKEN. Ponlo en la variable DISCORD_TOKEN.")
    else:
        bot.run(TOKEN)
