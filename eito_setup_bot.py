"""EITO SERVER SETUP BOT - crea categorias, canales, roles y da funciones al server."""

import io
import json
import os
import re
import time
import traceback
from datetime import datetime, timedelta, timezone

import discord
from aiohttp import web
from discord.ext import commands, tasks

from database import (
    add_user_xp,
    add_warn,
    add_xp_mensual,
    crear_tablas,
    get_all_xp,
    get_mensaje_cochipuerco,
    get_mensaje_fijo,
    get_user_xp,
    get_warns,
    guardar_ganadores,
    importar_xp_mensual,
    mes_ya_premiado,
    set_mensaje_cochipuerco,
    set_mensaje_fijo,
    top_xp_mensual,
)

# Cargar variables desde un archivo .env local (si existe).
# En produccion (hosting) las variables se ponen en el panel, no hace falta .env.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- TOKEN ---
TOKEN = os.getenv("DISCORD_TOKEN", "PON_TU_TOKEN_AQUI")

# --- WEBHOOK HTTP (para notificaciones de nuevas versiones via GitHub Actions) ---
RELEASE_CHANNEL_ID = os.getenv("RELEASE_CHANNEL_ID")
RELEASE_WEBHOOK_SECRET = os.getenv("RELEASE_WEBHOOK_SECRET")
WEBHOOK_PORT = int(os.getenv("PORT") or 8080)

# --- SERVIDOR PRINCIPAL (si esta definido, !darnivel se bloquea en este server) ---
EITO_GUILD_ID = (os.getenv("EITO_GUILD_ID") or "").strip()

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
CANAL_BUSCAR_PARTIDA = "🎮・buscar-partida"

# --- ROL DE AVISOS DE PARTIDA (opt-in) ---
ROL_LEFTSITO = "Leftsito"

CANAL_MODLOADER = "🔧・l4d2-mod-loader"
ROL_MODLOADER = "🔔 Mod Loader"

# --- ROL QUE SE DA AUTOMATICAMENTE AL ENTRAR ---
ROL_AUTOMATICO = "1544900113716084736"

# --- ROL +18 Y ACCESO A LA CATEGORIA NSFW ---
ROL_COCHIPUERCO = "Cochipuercoso"
# ID de la categoria NSFW (buscar por nombre fallaba por el encoding del emoji).
ID_CATEGORIA_NSFW = 1550995935071436800
# Canales que viven dentro de la categoria NSFW (solo para el mensaje de error).
CANALES_NSFW = ["los-nudes-de-eito-💪", "6-7", "juegos-h"]
# ID del rol 🔧 DEVELOPER (tiene acceso a NSFW y queda excluido del Activo del mes).
ROL_DEVELOPER_ID = 1546590434451787776
# Roles de staff que ya existen en el server y tienen acceso automatico a NSFW
# (no se crean con !setup, se buscan por ID con guild.get_role()).
ROLES_STAFF_NSFW = [
    1544889052011040828,  # 👑 EITO LA GOAT
    ROL_DEVELOPER_ID,     # 🔧 DEVELOPER
    1545581826654076979,  # 🛡 Admins
    1546381843132317736,  # ⁘Moderador⁘
]

# --- RECOMPENSAS POR NIVEL (canal privado que se desbloquea) ---
# (nivel requerido, nombre exacto del rol, color, nombre exacto del canal)
CANAL_NIVEL_10 = "🔓・nivel-10"
NIVEL_RECOMPENSAS = [
    (10, "🔓 Nivel 10", 0x1ABC9C, CANAL_NIVEL_10),
]

# --- ACTIVO DEL MES (top de XP mensual; se premia el mes anterior) ---
# El nombre solo lo usa !setup para crear el rol en servers nuevos; el bot lo
# busca por ID.
ROL_ACTIVO_MES = "🔥 Activo del mes"
ROL_ACTIVO_MES_ID = 1555315477893619763
# Excluidos de ser premiados: el dueño (owner_id), los bots y el rol ROL_DEVELOPER_ID.
PUESTOS_ACTIVO_MES = 3
# Cuantos candidatos del top se revisan por si varios estan excluidos o ya salieron.
CANDIDATOS_ACTIVO_MES = 50

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
        (CANAL_STEAM, "text"), (CANAL_MODLOADER, "text")]},
    {"categoria": "🛡️ STAFF", "canales": [
        (CANAL_LOGS, "text")]},
    {"categoria": "🔒 EXCLUSIVO", "canales": [
        (nombre_canal, "text") for _n, _r, _c, nombre_canal in NIVEL_RECOMPENSAS]},
]

# --- ROLES (nombre, color, hoist, mentionable) ---
ROLES = [
    ("Leftsito", 0xE74C3C, False, True),
    ("🔔 Mod Loader", 0x9184D9, False, True),
    (ROL_ACTIVO_MES, 0xFF5722, True, False),
    ("PC", 0xE67E22, False, True),
    ("XBOX", 0x2ECC71, False, True),
    ("PlayStation", 0x3498DB, False, True),
    ("Switch", 0xE74C3C, False, True),
    ("Mobile", 0xF1C40F, False, True),
    ("Europe", 0x3498DB, False, True),
    ("North America", 0x3498DB, False, True),
    ("South America", 0x3498DB, False, True),
    ("Asia", 0x3498DB, False, True),
    ("Oceania", 0x3498DB, False, True),
    ("Africa", 0x3498DB, False, True),
    *[(nombre_rol, color, False, False) for _n, nombre_rol, color, _c in NIVEL_RECOMPENSAS],
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

# --- GUIA DE INICIO (respuestas a las dudas mas comunes) ---
# Se rellena en tiempo real con las menciones a los canales reales.
def construir_guia(guild):
    """Devuelve el texto de la guia con los canales del server mencionados."""
    def canal_txt(nombre):
        c = discord.utils.get(guild.text_channels, name=nombre)
        return c.mention if c else f"#{nombre}"

    def canal_voz(nombre):
        c = discord.utils.get(guild.voice_channels, name=nombre)
        return c.mention if c else nombre

    return (
        "👋 **¡Bienvenido/a a EITO! Empieza por aquí** 👇\n\n"

        "**🕹️ ¿Quieres jugar Left 4 Dead con alguien?**\n"
        f"No preguntes en {canal_txt('💬・general')} 😅. Escribe `!jugar` en "
        f"{canal_txt('🤖・comandos')} y avisará a todos los que quieren jugar.\n"
        f"Activa el rol **🔔 Avisos de partida** en {canal_txt('🎭・roles')} "
        "para enterarte cuando alguien busque gente.\n\n"

        "**📦 ¿Buscas packs, scripts o addons?**\n"
        f"Están en la sección **🧟 LEFT 4 DEAD**: {canal_txt('📦・packs')}, "
        f"{canal_txt('⚙️・autoexec')}, {canal_txt('📜・scripts')} y "
        f"{canal_txt('🗂️・colecciones')}.\n\n"

        "**🎭 ¿Cómo consigo mis roles?**\n"
        f"Ve a {canal_txt('🎭・roles')} y pulsa los botones de tu plataforma "
        "(PC, XBOX...) y región.\n\n"

        "**🎮 ¿Cómo comparto mi Steam?**\n"
        f"Escribe `!steam <tu enlace>` en {canal_txt('🤖・comandos')} y tu perfil "
        f"aparecerá en {canal_txt('🎮・perfiles-steam')}.\n\n"

        "**❓ ¿Qué comandos hay?**\n"
        f"Escribe `!ayuda` en {canal_txt('🤖・comandos')} para ver todo lo que puedes hacer.\n\n"

        "**📜 Y lo más importante:** lee las reglas y respeta a la comunidad. 🎉"
    )

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Necesario para la bienvenida automatica (on_member_join)
# intents.reactions ya viene activado por defecto en Intents.default() (no es
# privilegiado) y alcanza para on_raw_reaction_add/remove del rol +18.

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)



# =====================================================================
#  SERVIDOR WEB INTERNO (webhook HTTP para notificaciones de releases)
# =====================================================================
async def handle_release_webhook(request):
    """POST /release-webhook - recibe notificaciones de nuevas versiones."""
    if not RELEASE_WEBHOOK_SECRET:
        return web.json_response(
            {"error": "RELEASE_WEBHOOK_SECRET no configurado"}, status=503)
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {RELEASE_WEBHOOK_SECRET}":
        return web.json_response({"error": "No autorizado"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "JSON invalido"}, status=400)
    version = data.get("version")
    if not version:
        return web.json_response({"error": "Falta el campo version"}, status=400)
    changelog = data.get("changelog", "Sin changelog.")

    canal = None
    if RELEASE_CHANNEL_ID:
        try:
            canal = bot.get_channel(int(RELEASE_CHANNEL_ID))
            if canal is None:
                canal = await bot.fetch_channel(int(RELEASE_CHANNEL_ID))
        except Exception as e:
            return web.json_response(
                {"error": f"No se pudo encontrar el canal: {e}"}, status=500)
    else:
        for guild in bot.guilds:
            canal = discord.utils.get(guild.text_channels, name=CANAL_MODLOADER)
            if canal is not None:
                break
        if canal is None:
            return web.json_response(
                {"error": f"No se encontro el canal {CANAL_MODLOADER}. Corre !setup primero."},
                status=500)

    rol = discord.utils.get(canal.guild.roles, name=ROL_MODLOADER) if canal.guild else None

    embed = discord.Embed(
        title=f"\U0001f680 Nueva version: {version}",
        description=changelog,
        colour=discord.Colour(0x9184D9),
    )
    try:
        if rol is not None:
            await canal.send(
                content=rol.mention,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=[rol]),
            )
        else:
            await canal.send(embed=embed)
    except Exception as e:
        return web.json_response(
            {"error": f"No se pudo enviar el mensaje: {e}"}, status=500)
    return web.json_response({"ok": True, "version": version}, status=200)


async def handle_health(request):
    """GET / - health check basico para Railway."""
    return web.json_response({"status": "ok", "bot": str(bot.user)})


async def start_web_server():
    """Arranca el servidor web aiohttp en el loop actual sin bloquear al bot."""
    app = web.Application()
    app.router.add_post("/release-webhook", handle_release_webhook)
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()
    print(f"\U0001f310 Servidor web escuchando en 0.0.0.0:{WEBHOOK_PORT}")


@bot.event
async def setup_hook():
    """Se ejecuta antes de on_ready, cuando el loop de asyncio ya esta corriendo."""
    if not RELEASE_CHANNEL_ID:
        print("\u26a0\ufe0f  RELEASE_CHANNEL_ID no definido. El endpoint /release-webhook no podra enviar mensajes.")
    if not RELEASE_WEBHOOK_SECRET:
        print("\u26a0\ufe0f  RELEASE_WEBHOOK_SECRET no definido. El endpoint /release-webhook rechazara todas las peticiones.")
    if not EITO_GUILD_ID:
        print("⚠️  EITO_GUILD_ID no definido. !darnivel funciona en cualquier servidor, incluido el de produccion.")
    bot.loop.create_task(start_web_server())
    if not premiar_activo_mes.is_running():
        premiar_activo_mes.start()


# =====================================================================
#  PERSISTENCIA DE DATOS (XP y avisos en PostgreSQL, ver database.py)
# =====================================================================
# Configuracion de XP
XP_POR_MENSAJE = 15        # XP que se gana por mensaje
COOLDOWN_XP = 60           # segundos entre ganancias de XP (anti-spam)

# Cooldown del comando !jugar (segundos) para no abusar de la mencion
COOLDOWN_JUGAR = 600       # 10 minutos por persona
# Control en memoria del ultimo !jugar: {(guild_id, user_id): timestamp}
ultimo_jugar = {}

# Control de cooldown de XP en memoria: {(guild_id, user_id): timestamp}
ultimo_xp = {}


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


def xp_acumulada(nivel):
    """XP total necesaria para alcanzar `nivel` (0 si nivel <= 0).

    Es la inversa de nivel_desde_xp: la misma suma que usa !darnivel."""
    return sum(xp_necesaria(n) for n in range(max(nivel, 0)))


# Texto EXACTO del aviso de subida de nivel (lo envia on_message). Lo usa
# tambien !importarniveles para reconocer esos avisos en el historial.
AVISO_NIVEL = "🎉 ¡{mencion} subió al **nivel {nivel}**!"
# Misma plantilla convertida en regex: acepta <@id> y <@!id>, nivel de 1 a 4 digitos.
REGEX_AVISO_NIVEL = re.compile(
    re.escape(AVISO_NIVEL)
    .replace(re.escape("{mencion}"), r"<@!?(\d+)>")
    .replace(re.escape("{nivel}"), r"(\d{1,4})")
)


def mes_utc(fecha=None):
    """Mes de `fecha` (por defecto ahora) en UTC como 'YYYY-MM'."""
    fecha = fecha or datetime.now(timezone.utc)
    return fecha.strftime("%Y-%m")


def mes_anterior_utc(fecha=None):
    """Mes anterior al de `fecha` (por defecto ahora) en UTC como 'YYYY-MM'."""
    fecha = fecha or datetime.now(timezone.utc)
    return (fecha.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def limites_mes_utc(mes):
    """Devuelve (inicio, fin) UTC del mes 'YYYY-MM'; fin es exclusivo."""
    anio, num = int(mes[:4]), int(mes[5:7])
    inicio = datetime(anio, num, 1, tzinfo=timezone.utc)
    fin = datetime(anio + (num == 12), num % 12 + 1, 1, tzinfo=timezone.utc)
    return inicio, fin


def es_excluido_activo(guild, miembro):
    """True si el miembro no puede ganar el Activo del mes (bot, dueño o DEVELOPER).

    Se evalua al premiar, no al ganar XP. Admins y moderadores SI participan."""
    return (
        miembro.bot
        or miembro.id == guild.owner_id
        or any(rol.id == ROL_DEVELOPER_ID for rol in miembro.roles)
    )


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


async def otorgar_recompensas(guild, member, nivel_previo, nivel_nuevo, canal_aviso=None):
    """Da los roles y avisa por cada nivel de NIVEL_RECOMPENSAS cruzado
    entre nivel_previo (exclusivo) y nivel_nuevo (inclusive)."""
    for nivel_req, nombre_rol, _color, nombre_canal in NIVEL_RECOMPENSAS:
        if not (nivel_previo < nivel_req <= nivel_nuevo):
            continue

        rol = discord.utils.get(guild.roles, name=nombre_rol)
        if rol is not None and rol not in member.roles:
            try:
                await member.add_roles(rol)
            except discord.Forbidden:
                pass

        canal_recompensa = buscar_canal(guild, nombre_canal)
        canal_destino = canal_aviso or canal_recompensa
        if canal_destino is not None:
            mencion_canal = canal_recompensa.mention if canal_recompensa else nombre_canal
            try:
                await canal_destino.send(
                    f"🔓 ¡{member.mention} desbloqueó {mencion_canal} "
                    f"al llegar al nivel {nivel_req}!"
                )
            except discord.Forbidden:
                pass


# =====================================================================
#  ACTIVO DEL MES (premio mensual al top de XP del mes anterior)
# =====================================================================
async def obtener_miembro(guild, user_id):
    """Miembro por ID (cache o API). None si ya no esta en el server."""
    miembro = guild.get_member(user_id)
    if miembro is not None:
        return miembro
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


# (guild_id, mes) cuyo problema de jerarquia ya se aviso en el canal de logs.
avisos_jerarquia_activo_mes = set()


async def premiar_activo_mes_guild(guild, mes):
    """Premia el top del mes `mes` en un servidor si todavia no se premio."""
    if await mes_ya_premiado(guild.id, mes):
        return

    rol = guild.get_role(ROL_ACTIVO_MES_ID)
    if rol is None:
        # Sin rol no se guarda nada: el mes sigue pendiente hasta que exista.
        print(f"⚠️ [{guild.name}] No existe el rol {ROL_ACTIVO_MES} con ID "
              f"{ROL_ACTIVO_MES_ID}; revisa ROL_ACTIVO_MES_ID. "
              f"Activo del mes {mes} pendiente.")
        return

    # El bot solo puede dar/quitar roles que esten por debajo de su rol mas alto.
    # Si no, no se guarda nada y se reintenta en el siguiente tick.
    if guild.me.top_role <= rol:
        print(f"⚠️ [{guild.name}] Mi rol más alto no está por encima de {ROL_ACTIVO_MES}. "
              f"Activo del mes {mes} pendiente.")
        if (guild.id, mes) not in avisos_jerarquia_activo_mes:
            # Una sola vez por servidor y mes, para no llenar el canal de logs cada hora.
            avisos_jerarquia_activo_mes.add((guild.id, mes))
            await registrar_log(
                guild,
                f"⚠️ No puedo premiar el Activo del mes {mes}: mi rol más alto debe estar "
                f"por encima de **{ROL_ACTIVO_MES}**. Reintento cada hora.",
            )
        return

    # Candidatos del top, saltando excluidos y quienes ya no estan en el server
    ganadores = []  # (miembro, puesto, xp)
    for uid, xp in await top_xp_mensual(guild.id, mes, CANDIDATOS_ACTIVO_MES):
        miembro = await obtener_miembro(guild, int(uid))
        if miembro is None or es_excluido_activo(guild, miembro):
            continue
        ganadores.append((miembro, len(ganadores) + 1, xp))
        if len(ganadores) == PUESTOS_ACTIVO_MES:
            break
    if not ganadores:
        return

    # Quitar el rol a los ganadores anteriores y darlo a los nuevos
    nuevos_ids = {miembro.id for miembro, _p, _x in ganadores}
    for anterior in list(rol.members):
        if anterior.id in nuevos_ids:
            continue
        try:
            await anterior.remove_roles(rol, reason=f"Activo del mes {mes}")
        except discord.HTTPException as e:
            print(f"⚠️ [{guild.name}] No pude quitar {ROL_ACTIVO_MES} a {anterior}: {e}")
    for miembro, _puesto, _xp in ganadores:
        if rol in miembro.roles:
            continue
        try:
            await miembro.add_roles(rol, reason=f"Activo del mes {mes}")
        except discord.HTTPException as e:
            print(f"⚠️ [{guild.name}] No pude dar {ROL_ACTIVO_MES} a {miembro}: {e}")

    await guardar_ganadores(
        guild.id, mes, [(miembro.id, puesto, xp) for miembro, puesto, xp in ganadores]
    )

    canal = buscar_canal(guild, CANAL_NIVELES)
    if canal is None:
        print(f"⚠️ [{guild.name}] No encuentro {CANAL_NIVELES} para anunciar el Activo del mes.")
        return
    medallas = ["🥇", "🥈", "🥉"]
    lineas = [
        f"{medallas[puesto - 1]} {miembro.mention} — {xp} XP"
        for miembro, puesto, xp in ganadores
    ]
    try:
        await canal.send(
            f"🏆 **Activo del mes — {mes}**\n" + "\n".join(lineas)
            + f"\n\nGanan el rol **{ROL_ACTIVO_MES}** hasta el próximo mes. ¡Gracias por estar activos! 🎉",
            allowed_mentions=discord.AllowedMentions(
                users=[miembro for miembro, _p, _x in ganadores],
                roles=False,
                everyone=False,
            ),
        )
    except discord.HTTPException as e:
        print(f"⚠️ [{guild.name}] No pude anunciar el Activo del mes: {e}")


@tasks.loop(hours=1)
async def premiar_activo_mes():
    """Cada hora revisa si el mes anterior (UTC) ya fue premiado en cada server."""
    mes = mes_anterior_utc()
    for guild in bot.guilds:
        try:
            await premiar_activo_mes_guild(guild, mes)
        except Exception:
            print(f"⚠️ Error premiando Activo del mes {mes} en {guild.name}:")
            traceback.print_exc()


@premiar_activo_mes.before_loop
async def antes_de_premiar_activo_mes():
    await bot.wait_until_ready()
    # on_ready tambien las crea, pero no hay garantia de orden con la 1a vuelta.
    try:
        await crear_tablas()
    except Exception:
        print("⚠️ crear_tablas() fallo antes de Activo del mes:")
        traceback.print_exc()


# =====================================================================
#  PANEL DE ROLES CON BOTONES
# =====================================================================
class BotonRol(discord.ui.Button):
    """Boton que da o quita un rol al pulsarlo."""

    def __init__(self, etiqueta, nombre_rol, emoji,
                 estilo=discord.ButtonStyle.secondary,
                 mensaje_al_activar=None):
        # custom_id fijo para que la vista sea persistente tras reiniciar el bot
        super().__init__(
            label=etiqueta,
            emoji=emoji,
            style=estilo,
            custom_id=f"rol::{nombre_rol}",
        )
        self.nombre_rol = nombre_rol
        self.mensaje_al_activar = mensaje_al_activar

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
                # Mensaje personalizado al activar (ej. explicacion del rol Leftsito)
                texto = self.mensaje_al_activar or f"➕ Te di el rol **{self.nombre_rol}**."
                await interaction.response.send_message(texto, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ No tengo permisos para darte ese rol. "
                "Mi rol debe estar por encima del rol a asignar.",
                ephemeral=True,
            )


# Mensaje que ve el usuario al activarse el rol Leftsito
MENSAJE_LEFTSITO = (
    "🔔 **¡Ahora eres Leftsito!**\n\n"
    "Recibirás una notificación cuando alguien use `!jugar` para buscar gente "
    f"con quién jugar (en {CANAL_BUSCAR_PARTIDA}).\n\n"
    "Vuelve a pulsar el botón cuando quieras dejar de recibir avisos. 🎮"
)

# Mensaje que ve el usuario al activarse el rol Mod Loader
MENSAJE_MODLOADER = (
    "🛠️ **¡Ahora recibirás avisos de nuevas versiones del L4D2 Mod Loader!**\n\n"
    f"Te voy a mencionar en {CANAL_MODLOADER} cada vez que salga una actualización.\n\n"
    "Vuelve a pulsar el botón cuando quieras dejar de recibirlos. 🎮"
)


class PanelRoles(discord.ui.View):
    """Vista persistente con todos los botones de roles."""

    def __init__(self):
        super().__init__(timeout=None)  # persistente
        for etiqueta, nombre_rol, emoji in ROLES_PLATAFORMA + ROLES_REGION:
            self.add_item(BotonRol(etiqueta, nombre_rol, emoji))
        # Boton especial para el rol de avisos de partida
        self.add_item(BotonRol(
            "Avisos de partida", ROL_LEFTSITO, "🔔",
            estilo=discord.ButtonStyle.success,
            mensaje_al_activar=MENSAJE_LEFTSITO,
        ))
        self.add_item(BotonRol(
            "Avisos Mod Loader", ROL_MODLOADER, "🛠️",
            estilo=discord.ButtonStyle.success,
            mensaje_al_activar=MENSAJE_MODLOADER,
        ))


# =====================================================================
#  EVENTOS
# =====================================================================
@bot.event
async def on_ready():
    # Crear las tablas de la base de datos si todavia no existen
    await crear_tablas()
    # Registrar la vista persistente para que los botones funcionen tras reiniciar
    bot.add_view(PanelRoles())
    print(f"✅ Conectado como {bot.user}")
    print("Admin: !setup !setupsteam !reglas !info !panelroles !presentaciones !anuncio")
    print("Moderación: !borrar !kick !ban !mute !unmute !warn !warns")
    print("Comunidad: !ping !miembros !avatar !serverinfo !ayuda !nivel !top")
    print("Utilidad: !encuesta !sugerencia !steam !jugar")


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

    # Ganar XP con cooldown. Los mensajes que empiezan con el prefijo (comandos)
    # no dan XP, para que no se gane spameando comandos.
    es_comando = message.content.startswith(bot.command_prefix)
    if not es_comando and ahora - ultimo_xp.get(clave, 0) >= COOLDOWN_XP:
        # Si algo falla (BD caida, etc.) se registra en consola, pero los
        # comandos de abajo deben seguir funcionando SIEMPRE.
        try:
            ultimo_xp[clave] = ahora
            nivel_previo = nivel_desde_xp(await get_user_xp(gid, uid))
            xp_total = await add_user_xp(gid, uid, XP_POR_MENSAJE)
            nivel_nuevo = nivel_desde_xp(xp_total)

            # Misma XP al acumulado del mes actual (UTC) para el Activo del mes.
            # Aislado para que un fallo aqui no impida el aviso de nivel.
            try:
                await add_xp_mensual(gid, uid, mes_utc(), XP_POR_MENSAJE)
            except Exception:
                print("⚠️ Error sumando XP mensual:")
                traceback.print_exc()

            # Aviso de subida de nivel (en el canal de niveles si existe)
            if nivel_nuevo > nivel_previo:
                canal_nivel = buscar_canal(message.guild, CANAL_NIVELES) or message.channel
                try:
                    await canal_nivel.send(
                        AVISO_NIVEL.format(
                            mencion=message.author.mention, nivel=nivel_nuevo
                        )
                    )
                except discord.Forbidden:
                    pass
                await otorgar_recompensas(
                    message.guild, message.author, nivel_previo, nivel_nuevo, canal_nivel
                )
        except Exception:
            print(f"⚠️ Error procesando XP de {message.author} en {message.guild}:")
            traceback.print_exc()

    # IMPORTANTE: dejar que los comandos sigan funcionando
    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Da el rol Cochipuercoso al reaccionar con 🔞 en el panel +18."""
    if payload.guild_id is None or str(payload.emoji) != "🔞":
        return
    if payload.member is None or payload.member.bot:
        return

    mensaje_id = await get_mensaje_cochipuerco(str(payload.guild_id))
    if mensaje_id is None or str(payload.message_id) != mensaje_id:
        return

    guild = payload.member.guild
    rol = discord.utils.get(guild.roles, name=ROL_COCHIPUERCO)
    if rol is None:
        await registrar_log(guild, f"⚠️ No encuentro el rol **{ROL_COCHIPUERCO}** para asignarlo.")
        return

    try:
        await payload.member.add_roles(rol)
    except discord.Forbidden:
        await registrar_log(
            guild,
            f"⚠️ Sin permisos para dar el rol **{ROL_COCHIPUERCO}** a {payload.member}.",
        )


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """Quita el rol Cochipuercoso al retirar la reacción 🔞 del panel +18."""
    if payload.guild_id is None or str(payload.emoji) != "🔞":
        return

    mensaje_id = await get_mensaje_cochipuerco(str(payload.guild_id))
    if mensaje_id is None or str(payload.message_id) != mensaje_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    miembro = guild.get_member(payload.user_id)
    if miembro is None or miembro.bot:
        return

    rol = discord.utils.get(guild.roles, name=ROL_COCHIPUERCO)
    if rol is None:
        await registrar_log(guild, f"⚠️ No encuentro el rol **{ROL_COCHIPUERCO}** para quitarlo.")
        return

    try:
        await miembro.remove_roles(rol)
    except discord.Forbidden:
        await registrar_log(
            guild,
            f"⚠️ Sin permisos para quitar el rol **{ROL_COCHIPUERCO}** a {miembro}.",
        )


@bot.event
async def on_member_join(member: discord.Member):
    """Da la bienvenida y asigna el rol automatico cuando entra alguien."""
    guild = member.guild

    # Rol automatico
    rol = guild.get_role(int(ROL_AUTOMATICO))
    if rol is None:
        print(f"⚠️ No existe el rol automático con ID {ROL_AUTOMATICO} en {guild.name}")
    else:
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
    await configurar_canal_modloader(ctx)
    await configurar_canales_recompensa(ctx)


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


async def configurar_canal_modloader(ctx):
    """Publica un mensaje fijo de presentacion en el canal del Mod Loader
    si el canal esta vacio."""
    guild = ctx.guild
    canal = buscar_canal(guild, CANAL_MODLOADER)
    if canal is None:
        return
    historial = [m async for m in canal.history(limit=1)]
    if not historial:
        embed = discord.Embed(
            title="🔧 L4D2 Versus Addon Manager",
            description=(
                "Gestiona tus addons de la Workshop para jugar Versus con "
                "varios combinados a la vez, sin reempaquetar VPKs a mano.\n\n"
                "📥 **Descarga:** https://www.mediafire.com/file/d512mqnuww1co2v/L4D2+Versus+Addon+Manager_v1.0.0-beta.exe/file\n\n"
                f"Activá el rol **Avisos Mod Loader** en {CANAL_ROLES} para "
                "que te avise apenas salga una actualización nueva."
            ),
            colour=discord.Colour(0x9184D9),
        )
        try:
            await canal.send(embed=embed)
        except discord.Forbidden:
            pass


async def configurar_canales_recompensa(ctx):
    """Oculta los canales de NIVEL_RECOMPENSAS para @everyone y los deja
    visibles solo para quien tenga el rol de recompensa correspondiente."""
    guild = ctx.guild
    for _nivel, nombre_rol, _color, nombre_canal in NIVEL_RECOMPENSAS:
        canal = buscar_canal(guild, nombre_canal)
        if canal is None:
            continue
        rol = discord.utils.get(guild.roles, name=nombre_rol)
        try:
            await canal.set_permissions(guild.default_role, view_channel=False)
            if rol is not None:
                await canal.set_permissions(rol, view_channel=True)
            await canal.set_permissions(guild.me, view_channel=True)
        except discord.Forbidden:
            await ctx.send(
                f"⚠️ No pude ajustar permisos de {canal.mention}. "
                "Revisa que mi rol esté arriba y tenga Gestionar canales."
            )


async def configurar_nsfw(ctx) -> bool:
    """Oculta la categoría NSFW para @everyone y la deja visible solo para
    quien tenga el rol Cochipuercoso o sea staff. Los permisos se aplican
    a nivel de categoría para que los hereden todos sus canales.

    Devuelve True si se pudo configurar todo, False si falló algo."""
    guild = ctx.guild

    # Ubicar la categoría directamente por ID (buscar por nombre de canal
    # fallaba por el encoding del emoji 💪).
    categoria = ctx.guild.get_channel(ID_CATEGORIA_NSFW)
    if categoria is None or not isinstance(categoria, discord.CategoryChannel):
        await ctx.send(
            "⚠️ No encuentro la categoría NSFW (busco los canales "
            f"{', '.join(CANALES_NSFW)})."
        )
        return False

    rol_cochipuerco = discord.utils.get(guild.roles, name=ROL_COCHIPUERCO)
    if rol_cochipuerco is None:
        await ctx.send(f"⚠️ No encuentro el rol **{ROL_COCHIPUERCO}** en el servidor.")
        return False

    try:
        await categoria.set_permissions(guild.default_role, view_channel=False)
        await categoria.set_permissions(rol_cochipuerco, view_channel=True)
        for id_rol in ROLES_STAFF_NSFW:
            rol = guild.get_role(id_rol)
            if rol is not None:
                await categoria.set_permissions(rol, view_channel=True)
        await categoria.set_permissions(guild.me, view_channel=True)
    except discord.Forbidden:
        await ctx.send(
            f"⚠️ No pude ajustar permisos de la categoría **{categoria.name}**. "
            "Revisa que mi rol esté arriba y tenga Gestionar canales."
        )
        return False

    return True


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
#  COMANDO: SETUPRECOMPENSAS (reconfigura los canales de nivel)
# =====================================================================
@bot.command(name="setuprecompensas")
@commands.has_permissions(administrator=True)
async def setuprecompensas(ctx):
    await configurar_canales_recompensa(ctx)
    await ctx.send("✅ Canales de recompensa por nivel configurados.")


@setuprecompensas.error
async def setuprecompensas_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: PANELCOCHIPUERCO (rol +18 con acceso a la categoría NSFW)
# =====================================================================
@bot.command(name="panelcochipuerco")
@commands.has_permissions(administrator=True)
async def panelcochipuerco(ctx):
    if not await configurar_nsfw(ctx):
        return
    embed = discord.Embed(
        title="🔞 Contenido +18",
        description=(
            "Reacciona con 🔞 para obtener el rol **Cochipuercoso** "
            "y acceder a los canales de contenido para mayores de edad.\n\n"
            "Discord verificará tu edad al entrar a esos canales."
        ),
        colour=discord.Colour(0xE74C3C),
    )
    mensaje = await ctx.send(embed=embed)
    await mensaje.add_reaction("🔞")
    await set_mensaje_cochipuerco(str(ctx.guild.id), str(mensaje.id))
    await ctx.send(f"✅ Panel publicado y permisos NSFW configurados. Mensaje ID: `{mensaje.id}`")


@panelcochipuerco.error
async def panelcochipuerco_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  MENSAJES FIJOS (reglas, guia, panel de roles, presentaciones)
# =====================================================================
async def publicar_o_editar_fijo(guild, canal, clave, embed, view=None):
    """Edita el mensaje fijo guardado para `clave`; si no hay o fue borrado,
    publica uno nuevo en `canal` y guarda su ID. Devuelve (mensaje, editado).

    Si ya hay un mensaje guardado se edita ese, aunque este en otro canal
    distinto de `canal`. `view` (opcional) se aplica en ambos casos."""
    extra = {"view": view} if view is not None else {}
    guardado = await get_mensaje_fijo(guild.id, clave)
    if guardado is not None:
        canal_guardado = guild.get_channel(int(guardado[0]))
        if canal_guardado is not None:
            try:
                mensaje = await canal_guardado.fetch_message(int(guardado[1]))
                await mensaje.edit(embed=embed, **extra)
                return mensaje, True
            except discord.NotFound:
                pass  # el mensaje fue borrado: se publica uno nuevo
    mensaje = await canal.send(embed=embed, **extra)
    await set_mensaje_fijo(guild.id, clave, canal.id, mensaje.id)
    return mensaje, False


# =====================================================================
#  COMANDO: REGLAS (publica o edita las reglas en el canal de reglas)
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
    mensaje, editado = await publicar_o_editar_fijo(guild, canal, "reglas", embed)
    accion = "editadas" if editado else "publicadas"
    await ctx.send(f"✅ Reglas {accion} en {mensaje.channel.mention}")


@reglas.error
async def reglas_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: INFO / GUIA (publica o edita la guia de inicio para los que llegan)
# =====================================================================
@bot.command(name="info", aliases=["guia"])
@commands.has_permissions(administrator=True)
async def info(ctx):
    guild = ctx.guild
    # Por defecto se publica junto a las reglas; si no existe, en el canal actual
    canal = discord.utils.get(guild.text_channels, name=CANAL_REGLAS) or ctx.channel
    embed = discord.Embed(
        title="📌 Guía rápida de EITO",
        description=construir_guia(guild),
        colour=discord.Colour(0x2ECC71),
    )
    mensaje, editado = await publicar_o_editar_fijo(guild, canal, "guia", embed)
    accion = "editada" if editado else "publicada"
    await ctx.send(f"✅ Guía {accion} en {mensaje.channel.mention}")


@info.error
async def info_error(ctx, error):
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
    # Al editar se vuelve a pasar PanelRoles(): los custom_id no cambian.
    mensaje, editado = await publicar_o_editar_fijo(
        guild, canal, "panel_roles", embed, view=PanelRoles()
    )
    accion = "editado" if editado else "publicado"
    await ctx.send(f"✅ Panel de roles {accion} en {mensaje.channel.mention}")


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
    mensaje, editado = await publicar_o_editar_fijo(guild, canal, "presentaciones", embed)
    accion = "editada" if editado else "publicada"
    await ctx.send(f"✅ Plantilla {accion} en {mensaje.channel.mention}")


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
@commands.has_permissions(manage_guild=True)
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
        await ctx.send("❌ Necesitas el permiso de Gestionar servidor.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!anuncio <texto del anuncio>`")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: DARNIVEL (asigna un nivel exacto a un miembro, solo testing)
# =====================================================================
@bot.command(name="darnivel")
@commands.has_permissions(administrator=True)
async def darnivel(ctx, nivel: int, miembro: discord.Member = None):
    # Solo toca la XP total (user_xp). NO debe tocar xp_mensual (Activo del mes).
    if EITO_GUILD_ID and str(ctx.guild.id) == EITO_GUILD_ID:
        await ctx.send("🔒 `!darnivel` está deshabilitado en este servidor (solo para pruebas).")
        return
    miembro = miembro or ctx.author
    if nivel < 0:
        await ctx.send("❌ El nivel debe ser 0 o mayor.")
        return

    gid = str(ctx.guild.id)
    uid = str(miembro.id)
    xp_actual = await get_user_xp(gid, uid)
    nivel_previo = nivel_desde_xp(xp_actual)

    xp_total = sum(xp_necesaria(n) for n in range(nivel))
    await add_user_xp(gid, uid, xp_total - xp_actual)

    nivel_nuevo = nivel_desde_xp(xp_total)
    await otorgar_recompensas(ctx.guild, miembro, nivel_previo, nivel_nuevo, ctx.channel)
    await ctx.send(
        f"✅ {miembro.mention} pasó del nivel **{nivel_previo}** al nivel "
        f"**{nivel_nuevo}** ({xp_total} XP total)."
    )


@darnivel.error
async def darnivel_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!darnivel <nivel> [@usuario]`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ El nivel debe ser un número entero.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: IMPORTARNIVELES (reconstruye la XP de un mes desde los avisos)
# =====================================================================
@bot.command(name="importarniveles")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def importarniveles(ctx, mes: str, confirmar: str = None):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        await ctx.send("❌ El mes debe tener formato `YYYY-MM` (ej. `2026-09`).")
        return
    if mes > mes_utc():
        await ctx.send("❌ Ese mes todavía no ha ocurrido.")
        return
    if confirmar is not None and confirmar.lower() != "confirmar":
        await ctx.send("❌ Uso: `!importarniveles <YYYY-MM> [confirmar]`")
        return

    canal = buscar_canal(ctx.guild, CANAL_NIVELES)
    if canal is None:
        await ctx.send(f"⚠️ No encuentro el canal {CANAL_NIVELES}.")
        return

    await ctx.send(f"📥 Leyendo el historial de {canal.mention} de {mes} (puede tardar)...")
    inicio, fin = limites_mes_utc(mes)
    rangos = {}  # user_id -> [nivel_min, nivel_max]
    leidos = avisos = 0
    async for msg in canal.history(limit=None, after=inicio, before=fin, oldest_first=True):
        leidos += 1
        if msg.author.id != bot.user.id:
            continue
        encontrado = REGEX_AVISO_NIVEL.fullmatch(msg.content)
        if encontrado is None:
            continue
        uid, nivel_aviso = encontrado.group(1), int(encontrado.group(2))
        if nivel_aviso < 1:
            continue
        avisos += 1
        rango = rangos.setdefault(uid, [nivel_aviso, nivel_aviso])
        rango[0] = min(rango[0], nivel_aviso)
        rango[1] = max(rango[1], nivel_aviso)

    if not rangos:
        await ctx.send(
            f"ℹ️ No encontré avisos de subida de nivel de {mes} "
            f"({leidos} mensajes leídos)."
        )
        return

    # XP ganada ~ xp_acumulada(max) - xp_acumulada(min - 1)
    xp_por_usuario = {
        uid: xp_acumulada(mx) - xp_acumulada(mn - 1) for uid, (mn, mx) in rangos.items()
    }

    if confirmar is None:
        ranking = sorted(xp_por_usuario.items(), key=lambda x: x[1], reverse=True)[:10]
        lineas = []
        for i, (uid, xp) in enumerate(ranking, 1):
            mn, mx = rangos[uid]
            miembro = ctx.guild.get_member(int(uid))
            marcas = ""
            if miembro is None:
                marcas += " (salió)"
            elif es_excluido_activo(ctx.guild, miembro):
                marcas += " — excluido"
            lineas.append(f"**{i}.** <@{uid}> — nivel {mn}→{mx} · ~{xp} XP{marcas}")
        embed = discord.Embed(
            title=f"📥 Vista previa de importación — {mes}",
            description="\n".join(lineas),
            colour=discord.Colour(0x3498DB),
        )
        embed.set_footer(
            text=f"{len(rangos)} usuarios · {avisos} avisos · {leidos} mensajes leídos"
        )
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await ctx.send(
            f"Si se ve bien, guarda con `!importarniveles {mes} confirmar`.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    guardados = await importar_xp_mensual(ctx.guild.id, mes, xp_por_usuario)
    await ctx.send(
        f"✅ Importados **{guardados}** usuarios en la XP mensual de {mes} "
        "(se conserva el mayor entre lo existente y lo importado)."
    )


@importarniveles.error
async def importarniveles_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso: `!importarniveles <YYYY-MM> [confirmar]`")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ Este comando solo funciona en un servidor.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMANDO: EXPORTARSERVER (auditoria: vuelca roles y canales a JSON por DM)
# =====================================================================
def es_dueno_o_developer(ctx):
    """Check de !exportarserver (ademas de administrator): solo el dueño del
    servidor o un miembro con el rol DEVELOPER (ROL_DEVELOPER_ID)."""
    if ctx.guild is None:
        return False
    return (
        ctx.author.id == ctx.guild.owner_id
        or any(rol.id == ROL_DEVELOPER_ID for rol in ctx.author.roles)
    )


def _permisos_activos(permisos):
    """Nombres de los permisos en True de un objeto discord.Permissions."""
    return [nombre for nombre, valor in permisos if valor]


def _overrides_canal(canal):
    """Overrides de permisos de un canal: por rol (nombre) o 'usuario:<id>'."""
    resultado = []
    for objetivo, ow in canal.overwrites.items():
        permite, niega = ow.pair()
        es_rol = isinstance(objetivo, discord.Role)
        resultado.append({
            "objetivo": objetivo.name if es_rol else f"usuario:{objetivo.id}",
            "tipo": "rol" if es_rol else "usuario",
            "id": objetivo.id,
            "permite": _permisos_activos(permite),
            "niega": _permisos_activos(niega),
        })
    return resultado


def _datos_canal(canal):
    """Datos exportables de un canal (sin mensajes)."""
    datos = {
        "nombre": canal.name,
        "id": canal.id,
        "tipo": canal.type.name,
        "posicion": canal.position,
        "overrides": _overrides_canal(canal),
    }
    if isinstance(canal, (discord.TextChannel, discord.ForumChannel)):
        datos["tema"] = canal.topic
        datos["nsfw"] = canal.nsfw
        datos["slowmode"] = canal.slowmode_delay
    elif isinstance(canal, (discord.VoiceChannel, discord.StageChannel)):
        datos["limite_usuarios"] = canal.user_limit
    return datos


@bot.command(name="exportarserver")
@commands.guild_only()
@commands.has_permissions(administrator=True)
@commands.check(es_dueno_o_developer)
async def exportarserver(ctx):
    guild = ctx.guild
    rol_bot = guild.me.top_role
    datos = {
        "servidor": {
            "nombre": guild.name,
            "id": guild.id,
            "owner_id": guild.owner_id,
            "miembros": guild.member_count,
        },
        "rol_mas_alto_del_bot": {
            "nombre": rol_bot.name, "id": rol_bot.id, "posicion": rol_bot.position,
        },
        "roles": [
            {
                "nombre": r.name,
                "id": r.id,
                "posicion": r.position,
                "color": str(r.colour),
                "hoist": r.hoist,
                "mencionable": r.mentionable,
                "managed": r.managed,
                "miembros": len(r.members),
                "administrador": r.permissions.administrator,
                "permisos": _permisos_activos(r.permissions),
            }
            for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
        ],
        "categorias": [
            {
                "nombre": cat.name,
                "id": cat.id,
                "tipo": cat.type.name,
                "posicion": cat.position,
                "overrides": _overrides_canal(cat),
                "canales": [_datos_canal(c) for c in cat.channels],
            }
            for cat in guild.categories
        ],
        "canales_sin_categoria": [
            _datos_canal(c) for c in guild.channels
            if c.category is None and not isinstance(c, discord.CategoryChannel)
        ],
    }

    contenido = json.dumps(datos, ensure_ascii=False, indent=2).encode("utf-8")
    archivo = discord.File(io.BytesIO(contenido), filename=f"eito_export_{guild.id}.json")
    try:
        await ctx.author.send("📦 Exportación del servidor:", file=archivo)
    except discord.Forbidden:
        await ctx.send("❌ No pude enviarte el archivo por DM. Abre tus mensajes directos y repite el comando.")
        return
    await ctx.send("📬 Te mandé la exportación por mensaje directo.")


@exportarserver.error
async def exportarserver_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas ser Administrador.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ Este comando solo funciona en un servidor.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("❌ Solo el dueño del servidor o un DEVELOPER pueden usar este comando.")
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
    total = await add_warn(gid, uid, razon, ctx.author.display_name)
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
MAX_AVISOS_EMBED = 20  # un embed admite 25 fields como maximo


def puede_ver_avisos_ajenos(perms):
    """True si `perms` (guild_permissions) permite ver los avisos de otros."""
    return perms is not None and (perms.kick_members or perms.moderate_members)
@bot.command(name="warns")
async def warns(ctx, miembro: discord.Member = None):
    miembro = miembro or ctx.author
    # Cualquiera ve sus propios avisos; los de otros solo moderadores.
    if miembro != ctx.author and not puede_ver_avisos_ajenos(ctx.author.guild_permissions):
        await ctx.send("❌ Solo los moderadores pueden ver los avisos de otros.")
        return
    gid = str(ctx.guild.id)
    uid = str(miembro.id)
    lista = await get_warns(gid, uid)
    if not lista:
        await ctx.send(f"✅ **{miembro.display_name}** no tiene avisos.")
        return

    # Un embed admite 25 fields: se muestran los MAX_AVISOS_EMBED mas recientes
    # (get_warns devuelve de mas antiguo a mas nuevo).
    total = len(lista)
    if total > MAX_AVISOS_EMBED:
        descripcion = f"Total: **{total}** (mostrando los {MAX_AVISOS_EMBED} más recientes)"
    else:
        descripcion = f"Total: **{total}**"
    embed = discord.Embed(
        title=f"⚠️ Avisos de {miembro.display_name}",
        description=descripcion,
        colour=discord.Colour(0xE67E22),
    )
    primero = total - min(total, MAX_AVISOS_EMBED) + 1
    for i, w in enumerate(lista[-MAX_AVISOS_EMBED:], primero):
        razon = w["reason"]
        if len(razon) > 200:  # evita pasar el limite de tamaño del embed
            razon = razon[:199] + "…"
        fecha = w["timestamp"].strftime("%d/%m/%Y") if w.get("timestamp") else "?"
        embed.add_field(
            name=f"Aviso #{i} · {fecha}",
            value=f"Razón: {razon}\nPor: {w['moderator']}",
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
#  GAMING: JUGAR (convoca a los Leftsito para buscar partida)
# =====================================================================
@bot.command(name="jugar")
async def jugar(ctx, *, mensaje: str = ""):
    guild = ctx.guild
    clave = (str(guild.id), str(ctx.author.id))
    ahora = time.time()

    # Anti-spam: cooldown por persona
    restante = COOLDOWN_JUGAR - (ahora - ultimo_jugar.get(clave, 0))
    if restante > 0:
        minutos = int(restante // 60)
        segundos = int(restante % 60)
        aviso = await ctx.send(
            f"⏳ Espera un poco antes de volver a convocar "
            f"({minutos}m {segundos}s)."
        )
        await aviso.delete(delay=8)
        return

    rol = discord.utils.get(guild.roles, name=ROL_LEFTSITO)
    if rol is None:
        await ctx.send(
            f"⚠️ No existe el rol {ROL_LEFTSITO}. Un admin debe correr !setup."
        )
        return

    canal = buscar_canal(guild, CANAL_BUSCAR_PARTIDA)
    if canal is None:
        await ctx.send(
            f"⚠️ No encuentro el canal {CANAL_BUSCAR_PARTIDA}. Avisa a un admin."
        )
        return

    # Registrar el uso para el cooldown
    ultimo_jugar[clave] = ahora

    texto_extra = mensaje.strip() if mensaje.strip() else "¡Se busca gente para jugar!"
    embed = discord.Embed(
        title="🎮 ¡Alguien quiere jugar!",
        description=(
            f"**{ctx.author.display_name}** está buscando compañía.\n\n"
            f"💬 {texto_extra}\n\n"
            "Reacciona con ✅ si te apuntas."
        ),
        colour=discord.Colour(0xE74C3C),
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    # Mencionar al rol Leftsito (permitido explicitamente)
    mensaje_enviado = await canal.send(
        content=f"{rol.mention}",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(roles=[rol]),
    )
    await mensaje_enviado.add_reaction("✅")

    # Confirmar al que convoco y limpiar su comando si es en otro canal
    if canal != ctx.channel:
        aviso = await ctx.send(f"✅ ¡Convocatoria enviada a {canal.mention}!")
        await aviso.delete(delay=6)
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass


@jugar.error
async def jugar_error(ctx, error):
    await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMUNIDAD: NIVEL (ver tu nivel y XP)
# =====================================================================
@bot.command(name="nivel")
async def nivel(ctx, miembro: discord.Member = None):
    miembro = miembro or ctx.author
    gid = str(ctx.guild.id)
    uid = str(miembro.id)
    xp_total = await get_user_xp(gid, uid)
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
    datos = await get_all_xp(gid)
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


# Secciones de !ayuda: (titulo del field, [(comando, texto, condicion_extra)]).
# Cada linea solo se muestra si quien pide la ayuda puede usar el comando
# (await comando.can_run(ctx)); un field sin lineas visibles no se muestra.
# condicion_extra(ctx) cubre lo que el propio comando no restringe con un check.
AYUDA_SECCIONES = [
    ("🎮 Comunidad", [
        ("ping", "`!ping` — comprueba que el bot responde", None),
        ("miembros", "`!miembros` — cuántos miembros hay", None),
        ("avatar", "`!avatar [@usuario]` — muestra un avatar en grande", None),
        ("serverinfo", "`!serverinfo` — info del servidor", None),
        ("nivel", "`!nivel [@usuario]` — muestra tu nivel y XP", None),
        ("top", "`!top` — ranking de niveles del servidor", None),
        ("warns", "`!warns` — muestra tus avisos", None),
        ("ayuda", "`!ayuda` — muestra esta lista", None),
    ]),
    ("📊 Utilidad", [
        ("encuesta", "`!encuesta <pregunta>` — crea una encuesta 👍👎", None),
        ("sugerencia", "`!sugerencia <texto>` — envía una sugerencia con votación", None),
        ("steam", "`!steam <enlace o SteamID>` — publica tu perfil de Steam", None),
        ("jugar", "`!jugar [mensaje]` — avisa a los Leftsito para buscar partida", None),
    ]),
    ("🛡️ Moderación", [
        ("borrar", "`!borrar <n>` — borra los últimos N mensajes (1–100)", None),
        ("kick", "`!kick @usuario [razón]` — expulsa a un miembro", None),
        ("ban", "`!ban @usuario [razón]` — banea a un miembro", None),
        ("mute", "`!mute @usuario <duración> [razón]` — silencia (ej. 10m, 2h)", None),
        ("unmute", "`!unmute @usuario` — quita el silencio", None),
        ("warn", "`!warn @usuario [razón]` — avisa a un miembro", None),
        # !warns no tiene check propio (cualquiera ve los suyos): esta linea es
        # solo para quien puede ver los avisos de otros.
        ("warns", "`!warns [@usuario]` — muestra los avisos",
         lambda ctx: puede_ver_avisos_ajenos(getattr(ctx.author, "guild_permissions", None))),
    ]),
    ("📝 Publicar", [
        ("reglas", "`!reglas` — publica o actualiza las reglas", None),
        ("info", "`!info` — publica o actualiza la guía de inicio", None),
        ("panelroles", "`!panelroles` — publica o actualiza el panel de roles con botones", None),
        ("presentaciones", "`!presentaciones` — publica o actualiza la plantilla de presentación", None),
        ("anuncio", "`!anuncio <texto>` — publica un anuncio", None),
        ("panelcochipuerco", "`!panelcochipuerco` — publica el panel del rol +18 y configura NSFW", None),
    ]),
    ("⚙️ Configurar y datos", [
        ("setup", "`!setup` — crea canales, categorías y roles", None),
        ("setupsteam", "`!setupsteam` — reconfigura el canal de perfiles", None),
        ("setuprecompensas", "`!setuprecompensas` — reconfigura los canales de nivel", None),
        ("importarniveles", "`!importarniveles <YYYY-MM> [confirmar]` — importa la XP de un mes desde los avisos de nivel", None),
        ("exportarserver", "`!exportarserver` — exporta roles y canales a JSON por DM (dueño o DEVELOPER)", None),
        ("darnivel", "`!darnivel <nivel> [@usuario]` — asigna un nivel exacto (solo en server de pruebas)", None),
    ]),
]


async def comando_visible(ctx, nombre, condicion=None):
    """True si quien pide la ayuda puede usar el comando `nombre`.

    Usa can_run (checks del propio comando) en vez de duplicar los permisos."""
    comando = bot.get_command(nombre)
    if comando is None:
        return False
    try:
        if condicion is not None and not condicion(ctx):
            return False
        return await comando.can_run(ctx)
    except commands.CommandError:
        return False


# =====================================================================
#  COMANDO: AYUDA (muestra solo los comandos que puedes usar)
# =====================================================================
@bot.command(name="ayuda")
async def ayuda(ctx):
    embed = discord.Embed(
        title="📖 Comandos de EITO",
        description="Todos los comandos usan el prefijo `!`",
        colour=discord.Colour(0x5865F2),
    )
    for titulo, entradas in AYUDA_SECCIONES:
        lineas = [
            texto for nombre, texto, condicion in entradas
            if await comando_visible(ctx, nombre, condicion)
        ]
        if lineas:
            embed.add_field(name=titulo, value="\n".join(lineas), inline=False)

    embed.set_footer(
        text="Ganas XP al escribir (los comandos no cuentan) · "
             "El top 3 del mes gana 🔥 Activo del mes"
    )
    await ctx.send(embed=embed)


if __name__ == "__main__":
    if TOKEN == "PON_TU_TOKEN_AQUI":
        print("⚠️  Falta el TOKEN. Ponlo en la variable DISCORD_TOKEN.")
    else:
        bot.run(TOKEN)
