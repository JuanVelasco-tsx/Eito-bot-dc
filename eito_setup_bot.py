"""EITO SERVER SETUP BOT - crea categorias, canales, roles y da funciones al server."""

import asyncio
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
    alternar_participante,
    cerrar_lfg_post,
    contar_activo_del_mes,
    crear_lfg_post,
    crear_tablas,
    get_all_xp,
    get_fundador,
    get_lfg_post_por_mensaje,
    get_mensaje_cochipuerco,
    get_mensaje_fijo,
    get_user_xp,
    get_warns,
    guardar_fundadores,
    guardar_ganadores,
    hay_fundadores,
    importar_xp_mensual,
    incrementar_contador,
    incrementar_contador_con_tope,
    lfg_posts_vencidos,
    listar_participantes,
    mes_ya_premiado,
    obtener_contadores,
    purgar_contadores_diarios,
    set_mensaje_cochipuerco,
    set_mensaje_fijo,
    set_user_xp,
    top_xp_mensual,
    usuarios_con_contador,
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
# Canal de logros: lo crea el admin a mano (no esta en ESTRUCTURA). Si no
# existe, los logros se anuncian en el canal de niveles.
CANAL_LOGROS = "🏅・logros"

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

# --- TICKETS DE SOPORTE ---
CANAL_SOPORTE = "🎫・soporte"
CATEGORIA_TICKETS = "🎫 TICKETS"
# Canal privado del staff donde se guardan las transcripciones (no es el de registros).
CANAL_TRANSCRIPCIONES = "📁・tickets-log"
# Roles de staff de los tickets: se buscan por ID (como ROLES_STAFF_NSFW), no por
# nombre, porque los nombres reales del server llevan simbolos distintos.
# Ven cada ticket y el canal de transcripciones, y pueden cerrar tickets.
ROLES_STAFF_TICKETS = [
    1544889052011040828,  # 👑 EITO LA GOAT
    ROL_DEVELOPER_ID,     # 🔧 DEVELOPER
    1545581826654076979,  # 🛡 Admins
    1546381843132317736,  # ⁘Moderador⁘
]
# Los unicos que se mencionan en el embed de bienvenida de cada ticket.
ROLES_PING_TICKETS = [
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

# --- FUNDADORES (los primeros miembros por fecha de entrada) ---
# El nombre solo lo usa !setup para crear el rol en servers nuevos; el bot lo
# busca por ID.
ROL_FUNDADOR = "🌱 Fundador"
ROL_FUNDADOR_ID = 1555338989043454132
MAX_FUNDADORES = 100

# --- RANGOS POR ANTIGUEDAD (solo tiempo en el server, sin nivel) ---
# Los nombres solo los usa !setup; el bot busca los roles por ID.
ROL_VETERANO = "🥉 Veterano"
ROL_VETERANO_ID = 1555339142362304642
ROL_LEYENDA = "🥈 Leyenda"
ROL_LEYENDA_ID = 1555339179406262332
# OG es manual: el bot nunca lo da ni lo quita, solo lo muestra en !antiguedad.
ROL_OG = "🥇 OG"
ROL_OG_ID = 1555339224637775954
# Roles de honor que da el staff a mano: al AGREGARSE a un miembro se anuncia
# un logro ("Reconocido por el staff"). Quitarlos o cualquier otro rol no anuncia.
ROLES_HONOR_IDS = [ROL_OG_ID]
DIAS_VETERANO = 90
DIAS_LEYENDA = 180

# --- RANGOS POR CONTADOR (permanentes: el bot nunca los quita) ---
# Los nombres solo los usa !setup; el bot busca los roles por ID.
# Si un ID es 0 o no existe en el server, el bot no asigna ese rol (los
# contadores se registran igual y el rol se da cuando haya un ID valido).
ROL_SUPERVIVIENTE = "🧟 Superviviente"
ROL_SUPERVIVIENTE_ID = 1555354849162563676
ROL_CONVOCADOR = "🎯 Convocador"
ROL_CONVOCADOR_ID = 1555354957253841008
ROL_VOZ_ACTIVA = "🎧 Voz activa"
ROL_VOZ_ACTIVA_ID = 1555372947324280852
# (tipo de contador, umbral, ID del rol)
RANGOS_POR_CONTADOR = [
    ("partidas", 10, ROL_SUPERVIVIENTE_ID),             # 🧟 Superviviente
    ("convocatorias_exitosas", 10, ROL_CONVOCADOR_ID),  # 🎯 Convocador
    ("voz_minutos", 3000, ROL_VOZ_ACTIVA_ID),           # 🎧 Voz activa (3000 min = 50 h)
]
# Texto del motivo del logro: "<umbral> <nombre>" (p. ej. "10 partidas jugadas")
NOMBRES_CONTADOR = {
    "partidas": "partidas jugadas",
    "convocatorias_exitosas": "convocatorias exitosas",
    "voz_minutos": "minutos en voz",
}


def motivo_umbral(tipo, umbral):
    """Texto del motivo de un rango por contador ("10 partidas jugadas"; la voz se
    expresa en horas: "50 horas en voz")."""
    if tipo == "voz_minutos":
        return f"{umbral // 60} horas en voz"
    return f"{umbral} {NOMBRES_CONTADOR[tipo]}"

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
# "categoria_id" (opcional): las categorias se renombran por temporadas, asi que
# !setup las busca primero por ID, luego por nombre y solo si no existen las crea
# con "categoria". Los bloques sin ID se buscan solo por nombre.
ESTRUCTURA = [
    {"categoria": "📢 INFORMACIÓN", "categoria_id": 1546637166434582691, "canales": [
        (CANAL_BIENVENIDA, "text"), (CANAL_REGLAS, "text"),
        ("📣・anuncios", "text"), (CANAL_ROLES, "text"),
        ("📅・eventos", "text"), ("🙋・presentaciones", "text")]},
    {"categoria": "💬 COMUNIDAD", "categoria_id": 1544888934293708840, "canales": [
        ("💬・general", "text"), ("📸・clips-y-capturas", "text"),
        ("🤖・comandos", "text"), (CANAL_NIVELES, "text"),
        (CANAL_SUGERENCIAS, "text"), (CANAL_SOPORTE, "text")]},
    {"categoria": "🧟 LEFT 4 DEAD", "categoria_id": 1546637174097580043, "canales": [
        ("📦・packs", "text"), ("⚙️・autoexec", "text"),
        ("📜・scripts", "text"), ("🗂️・colecciones", "text"),
        (CANAL_STEAM, "text"), (CANAL_MODLOADER, "text")]},
    {"categoria": "🛡️ STAFF", "categoria_id": 1546647219162189895, "canales": [
        (CANAL_LOGS, "text"), (CANAL_TRANSCRIPCIONES, "text")]},
    {"categoria": "🔒 EXCLUSIVO", "categoria_id": 1549612006523404318, "canales": [
        (nombre_canal, "text") for _n, _r, _c, nombre_canal in NIVEL_RECOMPENSAS]},
]

# --- ROLES (nombre, color, hoist, mentionable) ---
ROLES = [
    ("Leftsito", 0xE74C3C, False, True),
    ("🔔 Mod Loader", 0x9184D9, False, True),
    (ROL_ACTIVO_MES, 0xFF5722, True, False),
    (ROL_FUNDADOR, 0x57F287, False, False),
    (ROL_VETERANO, 0xCD7F32, False, False),
    (ROL_LEYENDA, 0xC0C0C0, False, False),
    (ROL_OG, 0xFFD700, True, False),
    (ROL_SUPERVIVIENTE, 0x1ABC9C, False, False),
    (ROL_CONVOCADOR, 0xE74C3C, False, False),
    (ROL_VOZ_ACTIVA, 0x3498DB, False, False),
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

# --- CANALES SOLO MENCIONADOS EN LOS TEXTOS (no los crea !setup) ---
CANAL_PREGUNTAS = "❔・preguntas"
CANAL_MEMES = "🥵・memes"
CANAL_SPRAYS = "🗞️・como-poner-sprays"


def _sin_selector_emoji(nombre):
    """Quita el selector de variacion de emoji (U+FE0F), que Discord a veces
    añade o quita al guardar un nombre de canal."""
    return nombre.replace("\ufe0f", "")


def buscar_canal_tolerante(guild, nombre):
    """Canal de texto `nombre` o None; tolera el selector de variacion de emoji."""
    objetivo = _sin_selector_emoji(nombre)
    return next(
        (c for c in guild.text_channels if _sin_selector_emoji(c.name) == objetivo),
        None,
    )


def mencion_canal(guild, nombre):
    """Mencion clicable del canal de texto `nombre`, o '#nombre' si no existe.

    Se resuelve en tiempo real y tolera el selector de variacion de emoji."""
    canal = buscar_canal_tolerante(guild, nombre)
    return canal.mention if canal else f"#{nombre}"


# --- TEXTO DE LAS REGLAS (con menciones a canales en tiempo real) ---
def construir_reglas(guild):
    """Devuelve el texto de las reglas con los canales del server mencionados."""
    preguntas = mencion_canal(guild, CANAL_PREGUNTAS)
    memes = mencion_canal(guild, CANAL_MEMES)
    return (
        "📜 **REGLAS DE EITO** 📜\n\n"
        "1️⃣ **Respeto ante todo.** Nada de insultos, racismo, acoso ni discriminación.\n"
        "2️⃣ **Sin spam ni publicidad.** Nada de enlaces sospechosos ni invitaciones "
        "a otros servers sin permiso.\n"
        f"3️⃣ **Cada cosa en su canal.** Dudas en {preguntas}, memes en {memes}, "
        "partidas con `!jugar`.\n"
        "4️⃣ **No farmees XP.** Mandar mensajes solo para subir de nivel está "
        "prohibido y descalifica de 🔥 Activo del mes.\n"
        "5️⃣ **Nada de pings masivos** ni abuso de `!jugar`.\n"
        "6️⃣ **Contenido +18 solo en 🔞 NSFW** y solo para mayores de edad. "
        "Fuera de ahí está prohibido.\n"
        "7️⃣ **Nada de cheats** en partidas de la comunidad ni contenido ilegal.\n"
        "8️⃣ **Respeta al staff.** Si no estás de acuerdo con una sanción, habla "
        "con un admin por privado.\n\n"
        "⚖️ **Sanciones:** aviso → silencio → expulsión → baneo, según la gravedad. "
        "Las faltas graves pueden ir directo al baneo.\n\n"
        "Al estar aquí aceptas estas normas. ¡A matar zombies! 🧟"
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
    "🎮 Steam (opcional):\n"
    "💬 Algo sobre ti:\n"
    "```\n"
    "¡Así te conocemos mejor! 🎉"
)

# --- TEXTO DEL PANEL DE ROLES (los nombres coinciden con los botones de PanelRoles) ---
TEXTO_PANEL_ROLES = (
    "Pulsa un botón para darte o quitarte un rol.\n\n"
    "**🎮 Plataforma:** en qué juegas.\n"
    "**🌍 Región:** desde dónde te conectas.\n"
    "**🔔 Avisos de partida:** te mencionan cuando alguien busca gente con `!jugar`.\n"
    "**🛠️ Avisos Mod Loader:** te avisamos cuando sale una versión nueva."
)

# --- GUIA DE INICIO (respuestas a las dudas mas comunes) ---
# Se rellena en tiempo real con las menciones a los canales reales.
def construir_guia(guild):
    """Devuelve el texto de la guia con los canales del server mencionados."""
    def canal_txt(nombre):
        return mencion_canal(guild, nombre)

    return (
        "👋 **¡Bienvenido/a a EITO! Empieza por aquí** 👇\n\n"

        "**🕹️ ¿Buscas partida?**\n"
        f"Escribe `!jugar` en {canal_txt('🤖・comandos')} y avisará a todos los que "
        f"tienen 🔔 Avisos de partida (actívalo en {canal_txt(CANAL_ROLES)}). "
        "Las salas de voz para Versus y Campaña están en la categoría 🔊 GAMING.\n\n"

        "**🎭 Tus roles**\n"
        f"En {canal_txt(CANAL_ROLES)} eliges plataforma, región, avisos de partida "
        "y avisos del Mod Loader.\n\n"

        "**📦 Contenido de L4D2**\n"
        f"{canal_txt('📦・packs')}, {canal_txt('⚙️・autoexec')}, "
        f"{canal_txt('📜・scripts')}, {canal_txt('🗂️・colecciones')} y "
        f"{canal_txt(CANAL_SPRAYS)}.\n\n"

        "**🔧 Mod Loader**\n"
        f"Descargas y novedades en {canal_txt(CANAL_MODLOADER)}. Pulsa 🛠️ Avisos Mod Loader "
        f"en {canal_txt(CANAL_ROLES)} para enterarte de cada versión nueva.\n\n"

        "**📈 Niveles**\n"
        "Ganas XP al escribir (los comandos no cuentan). Mira tu progreso con "
        "`!nivel` y el ranking con `!top`. "
        f"Al nivel 10 desbloqueas {canal_txt(CANAL_NIVEL_10)}, y cada mes el top 3 "
        "gana 🔥 **Activo del mes**.\n\n"

        "**🎮 Tu Steam**\n"
        f"Escribe `!steam <tu enlace>` en {canal_txt('🤖・comandos')} y tu perfil "
        f"aparecerá en {canal_txt(CANAL_STEAM)}.\n\n"

        "**❔ ¿Dudas o ideas?**\n"
        f"Pregunta en {canal_txt(CANAL_PREGUNTAS)} y manda ideas con "
        "`!sugerencia <texto>`. Todos los comandos: `!ayuda`.\n\n"

        f"📜 Y lo más importante: lee {canal_txt(CANAL_REGLAS)} y respeta a la "
        "comunidad. 🎉"
    )


intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Necesario para la bienvenida automatica (on_member_join)
# intents.reactions ya viene activado por defecto en Intents.default() (no es
# privilegiado) y alcanza para on_raw_reaction_add/remove del rol +18.

# Proteccion global: ningun mensaje del bot pinguea a @everyone/@here ni a roles
# (p. ej. texto de un usuario copiado en una razon); los envios que SI deben
# mencionar un rol o @everyone lo piden con su propio allowed_mentions.
bot = commands.Bot(
    command_prefix="!", intents=intents, help_command=None,
    allowed_mentions=discord.AllowedMentions(
        everyone=False, roles=False, users=True, replied_user=True
    ),
)



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
    # Las tablas se crean ANTES de arrancar cualquier loop o registrar vistas: los
    # loops consultan la BD apenas arrancan y, en el primer deploy con tablas
    # nuevas, fallarian con "relation ... does not exist". Si falla, se avisa y el
    # bot arranca igual (on_ready y los before_loop lo reintentan; crear_tablas
    # solo hace el trabajo una vez por proceso).
    try:
        await crear_tablas()
    except Exception:
        print("⚠️ crear_tablas() falló en setup_hook; el bot arranca igual:")
        traceback.print_exc()
    bot.loop.create_task(start_web_server())
    # Vista persistente de las convocatorias de !jugar (botones con custom_id fijo)
    bot.add_view(LfgView())
    # Loops: SIEMPRE despues de crear_tablas() y add_view (cualquier loop nuevo va aqui)
    if not premiar_activo_mes.is_running():
        premiar_activo_mes.start()
    if not actualizar_rangos.is_running():
        actualizar_rangos.start()
    if not cerrar_convocatorias_vencidas.is_running():
        cerrar_convocatorias_vencidas.start()
    if not contar_voz.is_running():
        contar_voz.start()


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


async def sumar_xp(miembro, cantidad, canal_fallback=None):
    """Suma `cantidad` de XP a `miembro`: total y del mes actual (UTC, para el
    Activo del mes); si sube de nivel lo avisa en el canal de niveles (o en
    `canal_fallback` si ese canal no existe) y da las recompensas del nivel.

    Es la logica comun de la XP por mensajes y por voz. Devuelve la XP total
    resultante; los errores de la BD se propagan (cada llamador decide)."""
    guild = miembro.guild
    gid, uid = str(guild.id), str(miembro.id)
    nivel_previo = nivel_desde_xp(await get_user_xp(gid, uid))
    xp_total = await add_user_xp(gid, uid, cantidad)
    nivel_nuevo = nivel_desde_xp(xp_total)

    # Misma XP al acumulado del mes actual (UTC) para el Activo del mes.
    # Aislado para que un fallo aqui no impida el aviso de nivel.
    try:
        await add_xp_mensual(gid, uid, mes_utc(), cantidad)
    except Exception:
        print("⚠️ Error sumando XP mensual:")
        traceback.print_exc()

    # Aviso de subida de nivel (en el canal de niveles si existe)
    if nivel_nuevo > nivel_previo:
        canal_nivel = buscar_canal(guild, CANAL_NIVELES) or canal_fallback
        if canal_nivel is not None:
            try:
                await canal_nivel.send(
                    AVISO_NIVEL.format(mencion=miembro.mention, nivel=nivel_nuevo)
                )
            except discord.Forbidden:
                pass
        await otorgar_recompensas(guild, miembro, nivel_previo, nivel_nuevo, canal_nivel)
    return xp_total


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
#  LOGROS (anuncios en el canal de logros)
# =====================================================================
def canal_logros(guild):
    """Canal de logros (tolera U+FE0F); si no existe, el canal de niveles; si
    tampoco, None."""
    return buscar_canal_tolerante(guild, CANAL_LOGROS) or buscar_canal(guild, CANAL_NIVELES)


# Textos del anuncio por rol (clave: ID del rol): (emoji, titulo, frase).
# Un rol que no este aqui usa ("🏅", "Nuevo logro") y el motivo como frase.
LOGROS_INFO = {
    ROL_OG_ID: (
        "🥇", "Nuevo OG de EITO",
        "Parte de la historia de la comunidad, reconocido por el staff.",
    ),
    ROL_SUPERVIVIENTE_ID: (
        "🧟", "Nuevo Superviviente",
        "Se unió a 10 partidas. Los zombies le tienen miedo.",
    ),
    ROL_CONVOCADOR_ID: (
        "🎯", "Nuevo Convocador",
        "Armó 10 partidas con gente. Sin él no se juega.",
    ),
    ROL_VOZ_ACTIVA_ID: (
        "🎧", "Nueva Voz activa",
        "Pasó 50 horas en voz con la comunidad. Siempre en la sala.",
    ),
}


def nombre_sin_emoji(nombre):
    """Nombre del rol sin el emoji (o simbolos) del principio: '🥇 OG' -> 'OG'."""
    limpio = re.sub(r"^[\W_]+", "", nombre)
    return limpio or nombre


async def anunciar_logro(miembro, rol, motivo=""):
    """Anuncia que `miembro` consiguio `rol` en el canal de logros.

    Mensaje "🎉 ¡Felicidades @usuario!" (solo se menciona/pingea al propio
    miembro) y un embed con el color del rol, el avatar, el nombre del rango en
    negrita (sin emoji repetido ni mencion del rol) y su posicion entre quienes lo
    tienen. Los textos salen de LOGROS_INFO; un rol sin entrada usa "Nuevo logro" y
    `motivo` como frase (`motivo` se conserva por compatibilidad).
    Devuelve True si se pudo publicar."""
    canal = canal_logros(miembro.guild)
    if canal is None:
        print(f"⚠️ [{miembro.guild.name}] No hay canal de logros ({CANAL_LOGROS}) ni de "
              f"niveles para anunciar {rol.name} de {miembro}.")
        return False
    emoji, titulo, frase = LOGROS_INFO.get(rol.id, ("🏅", "Nuevo logro", motivo))
    nombre = nombre_sin_emoji(rol.name)
    color = rol.colour if rol.colour.value else discord.Colour(0xF1C40F)
    descripcion = f"{miembro.mention} recibió el rango **{nombre}**."
    if frase:
        descripcion += f"\n*{frase}*"
    embed = discord.Embed(title=f"{emoji} {titulo}", description=descripcion, colour=color)
    embed.set_thumbnail(url=miembro.display_avatar.url)
    # Posicion = cuantos miembros tienen el rol. Si la cache aun no refleja al
    # nuevo (add_roles no la actualiza al instante), se cuenta igual.
    posicion = len({m.id for m in rol.members} | {miembro.id})
    embed.set_footer(text=f"Eres el {nombre} #{posicion} · Mira tus logros con !perfil")
    try:
        # El ping real va en el contenido: las menciones dentro de un embed no notifican.
        await canal.send(
            content=f"🎉 ¡Felicidades {miembro.mention}!",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                users=[miembro], roles=False, everyone=False
            ),
        )
    except discord.HTTPException as e:
        print(f"⚠️ [{miembro.guild.name}] No pude anunciar el logro de {miembro}: {e}")
        return False
    return True


MAX_NOMBRES_RESUMEN = 20


def lista_nombres(miembros):
    """Nombres (sin menciones) de hasta MAX_NOMBRES_RESUMEN miembros y '+X más'."""
    nombres = ", ".join(
        discord.utils.escape_markdown(m.display_name)
        for m in miembros[:MAX_NOMBRES_RESUMEN]
    )
    resto = len(miembros) - MAX_NOMBRES_RESUMEN
    return f"{nombres} +{resto} más" if resto > 0 else nombres


def texto_resumen_rangos(veteranos, leyendas):
    """Resumen de ascensos por antiguedad, con los nombres de cada rango."""
    lineas = [
        f"🎖️ Hoy {len(veteranos)} nuevos Veteranos y {len(leyendas)} nuevas Leyendas. "
        "¡Gracias por seguir en EITO!"
    ]
    if veteranos:
        lineas.append(f"🥉 **Veteranos:** {lista_nombres(veteranos)}")
    if leyendas:
        lineas.append(f"🥈 **Leyendas:** {lista_nombres(leyendas)}")
    return "\n".join(lineas)


# =====================================================================
#  RANGOS POR ANTIGUEDAD (Veterano / Leyenda, solo por tiempo en el server)
# =====================================================================
# Problemas ya avisados por consola: {(guild_id, "roles" | "jerarquia")}.
avisos_rangos = set()


async def actualizar_rangos_guild(guild):
    """Da Veterano (>= DIAS_VETERANO) o Leyenda (>= DIAS_LEYENDA) segun la fecha
    de entrada. Leyenda quita Veterano. Nunca quita Leyenda/Veterano por otra
    razon y nunca toca OG ni Fundador.

    Devuelve (nuevos_veteranos, nuevas_leyendas) como listas de miembros."""
    veterano = guild.get_role(ROL_VETERANO_ID)
    leyenda = guild.get_role(ROL_LEYENDA_ID)
    if veterano is None or leyenda is None:
        if (guild.id, "roles") not in avisos_rangos:
            avisos_rangos.add((guild.id, "roles"))
            print(f"⚠️ [{guild.name}] No existen los roles de rangos (revisa "
                  f"ROL_VETERANO_ID y ROL_LEYENDA_ID); salto este servidor.")
        return [], []
    if guild.me.top_role <= veterano or guild.me.top_role <= leyenda:
        if (guild.id, "jerarquia") not in avisos_rangos:
            avisos_rangos.add((guild.id, "jerarquia"))
            print(f"⚠️ [{guild.name}] Mi rol más alto debe estar por encima de "
                  f"{veterano.name} y {leyenda.name}; salto este servidor.")
        return [], []

    ahora = datetime.now(timezone.utc)
    nuevos_veteranos, nuevas_leyendas = [], []
    for miembro in list(guild.members):
        try:
            if miembro.bot or miembro.joined_at is None:
                continue
            dias = (ahora - miembro.joined_at).days
            if dias >= DIAS_LEYENDA:
                if leyenda not in miembro.roles:
                    await miembro.add_roles(leyenda, reason="Rango por antigüedad")
                    nuevas_leyendas.append(miembro)
                if veterano in miembro.roles:
                    await miembro.remove_roles(veterano, reason="Ahora es Leyenda")
            elif dias >= DIAS_VETERANO:
                if veterano not in miembro.roles and leyenda not in miembro.roles:
                    await miembro.add_roles(veterano, reason="Rango por antigüedad")
                    nuevos_veteranos.append(miembro)
        except Exception as e:
            print(f"⚠️ [{guild.name}] Error con los rangos de {miembro}: {e}")
    return nuevos_veteranos, nuevas_leyendas


@tasks.loop(hours=6)
async def actualizar_rangos():
    """Cada 6 horas actualiza Veterano/Leyenda; publica un resumen si hubo ascensos."""
    for guild in bot.guilds:
        try:
            nuevos_veteranos, nuevas_leyendas = await actualizar_rangos_guild(guild)
            if nuevos_veteranos or nuevas_leyendas:
                canal = canal_logros(guild)
                if canal is not None:
                    await canal.send(
                        texto_resumen_rangos(nuevos_veteranos, nuevas_leyendas),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
        except Exception:
            print(f"⚠️ Error actualizando rangos en {guild.name}:")
            traceback.print_exc()
        # Respaldo de los rangos por contador (sin anunciar), aparte para que un
        # fallo en uno de los dos bloques no impida el otro.
        try:
            await revisar_umbrales_guild(guild)
        except Exception:
            print(f"⚠️ Error revisando los rangos por contador en {guild.name}:")
            traceback.print_exc()
    # Limpieza (una vez por pasada): los contadores diarios de hace mas de
    # DIAS_CONTADORES_DIARIOS dias ya no sirven para el tope.
    try:
        limite = dia_contable(datetime.now(timezone.utc) - timedelta(days=DIAS_CONTADORES_DIARIOS))
        for prefijo in ("partidas_dia:", "convocatorias_dia:", "voz_dia:"):
            await purgar_contadores_diarios(prefijo, limite)
    except Exception:
        print("⚠️ Error limpiando los contadores diarios:")
        traceback.print_exc()


@actualizar_rangos.before_loop
async def antes_de_actualizar_rangos():
    await bot.wait_until_ready()


# =====================================================================
#  RANGOS POR CONTADOR (Superviviente, Convocador: permanentes)
# =====================================================================
# Problemas ya avisados por consola: {(guild_id, tipo, motivo)}.
avisos_contadores = set()


def rol_de_contador(guild, tipo, rol_id):
    """Rol del rango por contador, o None si no se puede dar (ID en 0, rol
    inexistente o jerarquia insuficiente). Avisa por consola una sola vez."""
    def avisar(motivo, texto):
        if (guild.id, tipo, motivo) not in avisos_contadores:
            avisos_contadores.add((guild.id, tipo, motivo))
            print(f"⚠️ [{guild.name}] Rango de «{tipo}»: {texto}; no se asigna.")

    if not rol_id:
        avisar("sin_id", "el ID del rol está en 0 (ROL_*_ID sin configurar)")
        return None
    rol = guild.get_role(rol_id)
    if rol is None:
        avisar("inexistente", f"no existe el rol con ID {rol_id}")
        return None
    if guild.me.top_role <= rol:
        avisar("jerarquia", f"mi rol más alto debe estar por encima de {rol.name}")
        return None
    return rol


async def revisar_rango_contador(guild, miembro, tipo, valor, anunciar=True):
    """Da los roles por umbral de `tipo` a `miembro` si `valor` ya los alcanza y
    todavia no los tiene. Anuncia el logro cuando `anunciar`. Los roles son
    permanentes: nunca se quitan. Devuelve cuantos roles dio."""
    dados = 0
    for tipo_rango, umbral, rol_id in RANGOS_POR_CONTADOR:
        if tipo_rango != tipo or valor < umbral:
            continue
        rol = rol_de_contador(guild, tipo_rango, rol_id)
        if rol is None or rol in miembro.roles:
            continue
        try:
            await miembro.add_roles(rol, reason=motivo_umbral(tipo_rango, umbral))
        except discord.HTTPException as e:
            print(f"⚠️ [{guild.name}] No pude dar {rol.name} a {miembro}: {e}")
            continue
        dados += 1
        if anunciar:
            await anunciar_logro(miembro, rol, motivo_umbral(tipo_rango, umbral))
    return dados


async def contar(guild, user_id, tipo, n=1):
    """Suma `n` al contador `tipo` del usuario y, si ya esta en el server y
    alcanza un umbral, le da el rol y anuncia el logro. Devuelve el valor nuevo."""
    valor = await incrementar_contador(guild.id, user_id, tipo, n)
    miembro = guild.get_member(int(user_id))
    if miembro is not None and not miembro.bot:
        try:
            await revisar_rango_contador(guild, miembro, tipo, valor)
        except Exception as e:
            print(f"⚠️ [{guild.name}] Error revisando el rango de {miembro}: {e}")
    return valor


async def revisar_umbrales_guild(guild):
    """Respaldo (cada 6 h): da los roles por contador a quien ya alcanzo el
    umbral y no los tiene (p. ej. si el ID estaba en 0 o fallo el envio).
    No anuncia."""
    for tipo, umbral, rol_id in RANGOS_POR_CONTADOR:
        rol = rol_de_contador(guild, tipo, rol_id)
        if rol is None:
            continue
        for user_id in await usuarios_con_contador(guild.id, tipo, umbral):
            miembro = guild.get_member(int(user_id))
            if miembro is None or miembro.bot or rol in miembro.roles:
                continue
            try:
                await miembro.add_roles(rol, reason=f"{motivo_umbral(tipo, umbral)} (respaldo)")
            except Exception as e:
                print(f"⚠️ [{guild.name}] No pude dar {rol.name} a {miembro}: {e}")


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
#  TICKETS DE SOPORTE (canal privado con el staff, botones persistentes)
# =====================================================================
# Sin tablas: el dueño del ticket se guarda en el topic del canal ("ticket:<id>").
# En memoria solo se evitan carreras: (guild_id, user_id) creando su ticket y
# canales que ya se estan cerrando.
tickets_en_creacion = set()
tickets_cerrando = set()


def dueno_ticket(canal):
    """ID del usuario dueño del ticket (topic "ticket:<id>") o None si no es un ticket."""
    encontrado = re.fullmatch(r"ticket:(\d+)", getattr(canal, "topic", None) or "")
    return int(encontrado.group(1)) if encontrado else None


def roles_staff_tickets(guild):
    """Roles de ROLES_STAFF_TICKETS que existen en el server."""
    return [rol for rol in (guild.get_role(i) for i in ROLES_STAFF_TICKETS) if rol is not None]


def roles_ping_tickets(guild):
    """Roles de ROLES_PING_TICKETS que existen en el server."""
    return [rol for rol in (guild.get_role(i) for i in ROLES_PING_TICKETS) if rol is not None]


def es_staff_ticket(miembro):
    """True si el miembro tiene algun rol de ROLES_STAFF_TICKETS."""
    return any(rol.id in ROLES_STAFF_TICKETS for rol in miembro.roles)


def nombre_canal_ticket(usuario):
    """"ticket-<nombre>" con el nombre de usuario limpio (solo a-z, 0-9, - y _)."""
    limpio = re.sub(r"[^a-z0-9_-]", "", usuario.name.lower())[:80]
    return f"ticket-{limpio or usuario.id}"


async def generar_transcripcion(canal):
    """Texto de la transcripcion del canal: fecha (UTC), autor, contenido y URLs de adjuntos."""
    lineas = [f"Transcripción de #{canal.name}", ""]
    async for mensaje in canal.history(limit=None, oldest_first=True):
        fecha = mensaje.created_at.strftime("%Y-%m-%d %H:%M:%S")
        contenido = mensaje.clean_content
        if not contenido and mensaje.embeds:
            contenido = "[embed] " + " / ".join(
                filter(None, (mensaje.embeds[0].title, mensaje.embeds[0].description))
            )
        lineas.append(f"[{fecha} UTC] {mensaje.author} ({mensaje.author.id}): {contenido}")
        for adjunto in mensaje.attachments:
            lineas.append(f"    [adjunto] {adjunto.url}")
    return "\n".join(lineas) + "\n"


async def ticket_abrir(interaction):
    """Boton "Abrir ticket": crea el canal privado del usuario (maximo uno abierto)."""
    await interaction.response.defer(ephemeral=True)
    guild, usuario = interaction.guild, interaction.user
    clave = (guild.id, usuario.id)
    if clave in tickets_en_creacion:
        await interaction.followup.send("⏳ Ya estoy creando tu ticket, espera un momento.", ephemeral=True)
        return
    existente = next((c for c in guild.text_channels if dueno_ticket(c) == usuario.id), None)
    if existente is not None:
        await interaction.followup.send(
            f"❌ Ya tienes un ticket abierto: {existente.mention}", ephemeral=True
        )
        return

    tickets_en_creacion.add(clave)
    canal = None
    try:
        categoria = discord.utils.get(guild.categories, name=CATEGORIA_TICKETS)
        if categoria is None:
            categoria = await guild.create_category(
                CATEGORIA_TICKETS,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    guild.me: discord.PermissionOverwrite(view_channel=True),
                },
            )
        staff = roles_staff_tickets(guild)
        permisos = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True
        )
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            usuario: permisos,
            # read_message_history y embed_links: sin ellos el bot no puede generar
            # la transcripcion ni publicar el embed de bienvenida.
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                embed_links=True, manage_channels=True,
            ),
        }
        for rol in staff:
            overwrites[rol] = permisos
        canal = await guild.create_text_channel(
            nombre_canal_ticket(usuario),
            category=categoria,
            topic=f"ticket:{usuario.id}",
            overwrites=overwrites,
            reason=f"Ticket de {usuario}",
        )
        embed = discord.Embed(
            title="🎫 Ticket de soporte",
            description=(
                f"¡Hola {usuario.mention}! El staff te atenderá en cuanto pueda.\n\n"
                "Cuéntanos qué necesitas con el mayor detalle posible. "
                "Cuando termines, pulsa **🔒 Cerrar ticket**."
            ),
            colour=discord.Colour(0x5865F2),
        )
        pings = roles_ping_tickets(guild)
        await canal.send(
            content=" ".join([usuario.mention] + [rol.mention for rol in pings]),
            embed=embed,
            view=CerrarTicket(),
            allowed_mentions=discord.AllowedMentions(users=[usuario], roles=pings, everyone=False),
        )
    except discord.Forbidden:
        await _limpiar_ticket_fallido(canal)
        await interaction.followup.send(
            "❌ No tengo permisos para crear el ticket. Avisa a un admin: mi rol necesita "
            "el permiso **Gestionar canales**.",
            ephemeral=True,
        )
        return
    except discord.HTTPException as e:
        await _limpiar_ticket_fallido(canal)
        print(f"⚠️ [{guild.name}] No pude crear el ticket de {usuario}: {e}")
        await interaction.followup.send(
            "❌ No pude crear el ticket. Inténtalo de nuevo en un momento.", ephemeral=True
        )
        return
    finally:
        tickets_en_creacion.discard(clave)

    await interaction.followup.send(f"✅ Tu ticket está listo: {canal.mention}", ephemeral=True)
    await registrar_log(guild, f"🎫 **{usuario}** abrió el ticket {canal.mention}")


async def _limpiar_ticket_fallido(canal):
    """Borra el canal de un ticket que se creo pero no pudo terminar de montarse."""
    if canal is None:
        return
    try:
        await canal.delete(reason="Ticket que no se pudo terminar de crear")
    except discord.HTTPException:
        pass


async def ticket_cerrar(interaction):
    """Boton "Cerrar ticket": solo el dueño o el staff. Guarda la transcripcion y borra el canal."""
    await interaction.response.defer(ephemeral=True)
    guild, canal = interaction.guild, interaction.channel
    dueno_id = dueno_ticket(canal)
    if dueno_id is None:
        await interaction.followup.send("❌ Este canal no es un ticket.", ephemeral=True)
        return
    if not (interaction.user.id == dueno_id or es_staff_ticket(interaction.user)):
        await interaction.followup.send(
            "❌ Solo quien abrió el ticket o el staff puede cerrarlo.", ephemeral=True
        )
        return
    if canal.id in tickets_cerrando:
        await interaction.followup.send("⏳ Este ticket ya se está cerrando.", ephemeral=True)
        return

    tickets_cerrando.add(canal.id)
    try:
        # Sin transcripcion guardada no se borra nada.
        canal_log = buscar_canal(guild, CANAL_TRANSCRIPCIONES)
        if canal_log is None:
            await interaction.followup.send(
                f"⚠️ No encuentro {CANAL_TRANSCRIPCIONES}, así que no cierro el ticket "
                "(se perdería la transcripción). Avisa a un admin: debe correr `!setup confirmar`.",
                ephemeral=True,
            )
            return
        # La transcripcion es la conversacion privada: si @everyone ve el canal de
        # transcripciones no se envia nada y el ticket no se cierra.
        if canal_log.permissions_for(guild.default_role).view_channel:
            await interaction.followup.send(
                "⚠️ No cerré el ticket: el canal de transcripciones es público.", ephemeral=True
            )
            await canal.send("⚠️ El canal de transcripciones es público; un admin debe corregirlo")
            await registrar_log(
                guild,
                f"⚠️ No se cerró {canal.mention}: {canal_log.mention} es visible para @everyone, "
                "así que no se envió la transcripción. Corrige sus permisos (`!setup confirmar` "
                "o `!paneltickets` los reconfiguran).",
            )
            return
        try:
            texto = await generar_transcripcion(canal)
            archivo = discord.File(io.BytesIO(texto.encode("utf-8")), filename=f"{canal.name}.txt")
            await canal_log.send(
                f"📁 Ticket **{canal.name}** · abierto por <@{dueno_id}> · "
                f"cerrado por {interaction.user.mention}",
                file=archivo,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            print(f"⚠️ [{guild.name}] No pude guardar la transcripción de {canal.name}: {e}")
            await interaction.followup.send(
                "❌ No pude guardar la transcripción, así que el ticket sigue abierto. "
                "Revisa que yo pueda escribir en el canal de transcripciones.",
                ephemeral=True,
            )
            return

        await interaction.followup.send("🔒 Cerrando el ticket…", ephemeral=True)
        await canal.send(
            f"🔒 Ticket cerrado por {interaction.user.mention}. "
            "Este canal se borrará en 5 segundos.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await asyncio.sleep(5)
        try:
            await canal.delete(reason=f"Ticket cerrado por {interaction.user}")
        except discord.HTTPException as e:
            print(f"⚠️ [{guild.name}] No pude borrar el ticket {canal.name}: {e}")
            await canal.send("⚠️ No pude borrar este canal; que un admin lo borre a mano.")
    finally:
        tickets_cerrando.discard(canal.id)


class PanelTickets(discord.ui.View):
    """Vista persistente del panel de soporte (custom_id fijo: sobrevive reinicios)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Abrir ticket", emoji="🎫", style=discord.ButtonStyle.primary,
                       custom_id="ticket::abrir")
    async def abrir(self, interaction: discord.Interaction, boton: discord.ui.Button):
        await ticket_abrir(interaction)


class CerrarTicket(discord.ui.View):
    """Vista persistente dentro de cada ticket (el dueño sale del topic del canal)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Cerrar ticket", emoji="🔒", style=discord.ButtonStyle.danger,
                       custom_id="ticket::cerrar")
    async def cerrar(self, interaction: discord.Interaction, boton: discord.ui.Button):
        await ticket_cerrar(interaction)


# =====================================================================
#  EVENTOS
# =====================================================================
@bot.event
async def on_ready():
    # Crear las tablas de la base de datos si todavia no existen
    await crear_tablas()
    # Registrar la vista persistente para que los botones funcionen tras reiniciar
    bot.add_view(PanelRoles())
    bot.add_view(PanelTickets())
    bot.add_view(CerrarTicket())
    print(f"✅ Conectado como {bot.user}")
    # Lista real de comandos (la misma que usa !ayuda)
    for titulo, entradas in AYUDA_SECCIONES:
        print(f"{titulo}: " + " ".join(f"!{nombre}" for nombre, _texto, _cond in entradas))


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
            await sumar_xp(message.author, XP_POR_MENSAJE, message.channel)
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
async def on_member_update(before: discord.Member, after: discord.Member):
    """Anuncia un logro cuando el staff AGREGA un rol de honor a un miembro."""
    if before.roles == after.roles:
        return
    antes = {rol.id for rol in before.roles}
    try:
        for rol in after.roles:
            if rol.id not in antes and rol.id in ROLES_HONOR_IDS:
                await anunciar_logro(after, rol, "Reconocido por el staff")
    except Exception as e:
        print(f"⚠️ Error anunciando un rol de honor de {after}: {e}")


def embed_bienvenida(member):
    """Embed de bienvenida con las menciones a canales resueltas en tiempo real."""
    guild = member.guild
    embed = discord.Embed(
        title=f"👋 ¡Bienvenido/a a {guild.name}!",
        description=(
            f"¡Hola {member.mention}! 🎉\n\n"
            f"📜 Lee las reglas y la guía de inicio en {mencion_canal(guild, CANAL_REGLAS)}\n"
            f"🎭 Elige tus roles en {mencion_canal(guild, CANAL_ROLES)}\n"
            f"🙋 Preséntate en {mencion_canal(guild, CANAL_PRESENTACIONES)}\n\n"
            f"Eres el miembro **#{guild.member_count}** 🎊"
        ),
        colour=discord.Colour(0x2ECC71),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    return embed


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

    # Fundador: si ya estaba en la lista, recupera su rol. Cualquier fallo
    # (BD, permisos) se registra y no impide la bienvenida.
    try:
        if await get_fundador(guild.id, member.id) is not None:
            rol_fundador = guild.get_role(ROL_FUNDADOR_ID)
            if rol_fundador is not None:
                await member.add_roles(rol_fundador, reason="Fundador que vuelve")
    except Exception as e:
        print(f"⚠️ No pude devolver el rol Fundador a {member} en {guild.name}: {e}")

    # Mensaje de bienvenida (embed con foto y contador de miembros)
    canal = discord.utils.get(guild.text_channels, name=CANAL_BIENVENIDA)
    if canal is not None:
        try:
            await canal.send(embed=embed_bienvenida(member))
        except discord.HTTPException as e:
            print(f"⚠️ No pude enviar la bienvenida de {member} en {guild.name}: {e}")


# =====================================================================
#  COMANDO: SETUP (crea roles y canales)
# =====================================================================
def buscar_categoria_bloque(guild, bloque):
    """Categoria de un bloque de ESTRUCTURA: primero por "categoria_id", luego por
    nombre; None si no existe (el llamador decide si la crea)."""
    cat_id = bloque.get("categoria_id")
    if cat_id:
        cat = guild.get_channel(cat_id)
        if isinstance(cat, discord.CategoryChannel):
            return cat
    return discord.utils.get(guild.categories, name=bloque["categoria"])


def buscar_canal_en_servidor(guild, nombre):
    """Canal (texto o voz) `nombre` en CUALQUIER categoria del servidor, o None.
    Tolera el selector de variacion de emoji."""
    objetivo = _sin_selector_emoji(nombre)
    return next(
        (c for c in guild.channels
         if not isinstance(c, discord.CategoryChannel) and _sin_selector_emoji(c.name) == objetivo),
        None,
    )


def nombre_categoria_de(canal):
    """Nombre de la categoria de un canal, o "sin categoría"."""
    return canal.category.name if canal.category else "sin categoría"


def plan_setup(guild):
    """Lo que !setup haria en este servidor, sin crear nada. Usa los mismos
    criterios que el comando: roles por nombre, categorias por ID y luego por
    nombre, y canales por nombre en todo el servidor (no solo en su categoria).

    Una categoria que no existe solo se crea si algun canal suyo se va a crear.

    Devuelve {"roles": [nombre],
              "categorias": [nombre],           # se crearian
              "categorias_omitidas": [nombre],  # no existen, pero todos sus canales ya existen
              "canales": [(categoria, nombre)],          # se crearian
              "existentes": [(nombre, categoria_actual)]}  # ya existen: no se tocan."""
    roles = [
        nombre for nombre, _color, _hoist, _ment in ROLES
        if discord.utils.get(guild.roles, name=nombre) is None
    ]
    categorias, omitidas, canales, existentes = [], [], [], []
    for bloque in ESTRUCTURA:
        nuevos = 0
        for nombre_canal, _tipo in bloque["canales"]:
            existente = buscar_canal_en_servidor(guild, nombre_canal)
            if existente is None:
                canales.append((bloque["categoria"], nombre_canal))
                nuevos += 1
            else:
                existentes.append((nombre_canal, nombre_categoria_de(existente)))
        if buscar_categoria_bloque(guild, bloque) is None:
            (categorias if nuevos else omitidas).append(bloque["categoria"])
    return {"roles": roles, "categorias": categorias, "categorias_omitidas": omitidas,
            "canales": canales, "existentes": existentes}


def permisos_setup(guild):
    """Lineas de texto con los permisos/mensajes que !setup reconfiguraria."""
    def estado(nombre):
        return "" if buscar_canal(guild, nombre) is not None else " *(se crearía antes)*"
    lineas = [
        f"• {CANAL_STEAM}: solo lectura para @everyone (el bot escribe) y mensaje de "
        f"instrucciones si está vacío{estado(CANAL_STEAM)}",
        f"• {CANAL_MODLOADER}: mensaje de presentación si está vacío{estado(CANAL_MODLOADER)}",
    ]
    for _nivel, nombre_rol, _color, nombre_canal in NIVEL_RECOMPENSAS:
        lineas.append(
            f"• {nombre_canal}: oculto para @everyone y visible solo para {nombre_rol}"
            f"{estado(nombre_canal)}"
        )
    lineas.append(
        f"• {CANAL_TRANSCRIPCIONES}: oculto para @everyone y visible solo para el staff "
        f"de tickets{estado(CANAL_TRANSCRIPCIONES)}"
    )
    lineas.append(
        f"• {CANAL_SOPORTE}: solo lectura para @everyone (el bot escribe){estado(CANAL_SOPORTE)}"
    )
    return lineas


async def vista_previa_setup(ctx):
    """!setup sin argumento: muestra lo que crearia y reconfiguraria, sin tocar nada."""
    guild = ctx.guild
    plan = plan_setup(guild)
    lineas = []
    # Primero la lista completa de lo que se creara (nunca se corta).
    if plan["canales"]:
        lineas.append(f"🆕 **Se creará ({len(plan['canales'])}):**")
        for categoria, nombre in plan["canales"]:
            lineas.append(f"• {nombre} → {categoria}")
    else:
        lineas.append("🆕 **Se creará (0):** ningún canal")
    lineas.append(
        f"👥 **Roles que crearía ({len(plan['roles'])}):** "
        + (", ".join(plan["roles"]) if plan["roles"] else "ninguno")
    )
    lineas.append(
        f"📁 **Categorías que crearía ({len(plan['categorias'])}):** "
        + (", ".join(plan["categorias"]) if plan["categorias"] else "ninguna")
    )
    for categoria in plan["categorias_omitidas"]:
        lineas.append(f"⏭️ {categoria} — categoría omitida: sus canales ya existen")
    if plan["categorias"]:
        lineas.append(
            f"⚠️ **Va a crear {len(plan['categorias'])} categoría(s)** "
            f"({', '.join(plan['categorias'])}): no las encontré ni por ID ni por nombre."
        )
    lineas.append("🔐 **Permisos que reconfiguraría:**")
    lineas.extend(permisos_setup(guild))
    if not (plan["roles"] or plan["categorias"] or plan["canales"]):
        lineas.append("✅ No falta nada: !setup solo reconfiguraría los permisos de arriba.")

    # Resumen de lo que ya existe (conteo por categoria). Es la unica parte que se corta.
    por_categoria = {}
    for _nombre, categoria in plan["existentes"]:
        por_categoria[categoria] = por_categoria.get(categoria, 0) + 1
    resumen = []
    if por_categoria:
        resumen.append(f"✅ **Ya existe, no se toca ({len(plan['existentes'])}):**")
        for categoria, total in por_categoria.items():
            resumen.append(f"• {categoria}: {total} {'canal' if total == 1 else 'canales'}")

    # Si la parte fija supera el limite de un embed, se reparte en varios; el
    # resumen va al final del ultimo y solo el se recorta.
    limite = 4000
    bloques, actual = [], ""
    for linea in lineas:
        if actual and len(actual) + 1 + len(linea) > limite:
            bloques.append(actual)
            actual = linea
        else:
            actual = f"{actual}\n{linea}" if actual else linea
    if resumen:
        texto_resumen = "\n".join(resumen)
        espacio = limite - len(actual) - 1
        if len(texto_resumen) > espacio:
            texto_resumen = texto_resumen[:max(espacio - 2, 0)] + "\n…" if espacio > 2 else ""
        if texto_resumen:
            actual = f"{actual}\n{texto_resumen}"
    bloques.append(actual)

    for i, descripcion in enumerate(bloques):
        embed = discord.Embed(
            title="🔍 Vista previa de !setup — no se creó nada",
            description=descripcion,
            colour=discord.Colour(0xF1C40F),
        )
        if i == len(bloques) - 1:
            embed.set_footer(text="Para ejecutarlo: !setup confirmar")
        await ctx.send(embed=embed)


@bot.command(name="setup")
@commands.has_permissions(administrator=True)
async def setup(ctx, confirmar: str = None):
    # Sin "confirmar" solo se muestra la vista previa: no se crea nada.
    if confirmar is not None and confirmar.lower() != "confirmar":
        await ctx.send("❌ Uso: `!setup` (vista previa) o `!setup confirmar`.")
        return
    if confirmar is None:
        await vista_previa_setup(ctx)
        return

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
        cat = buscar_categoria_bloque(guild, bloque)
        for nombre_canal, tipo in bloque["canales"]:
            # Si existe en cualquier categoria no se crea ni se mueve.
            if buscar_canal_en_servidor(guild, nombre_canal) is not None:
                continue
            # La categoria solo se crea cuando hace falta crear algun canal en ella.
            if cat is None:
                cat = await guild.create_category(bloque["categoria"])
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
    await configurar_canal_transcripciones(ctx)
    await configurar_canal_soporte(ctx)


async def configurar_canal_soporte(ctx):
    """Deja el canal de soporte solo-lectura para @everyone (solo el bot escribe):
    los miembros usan el boton del panel, no escriben ahi."""
    guild = ctx.guild
    canal = buscar_canal(guild, CANAL_SOPORTE)
    if canal is None:
        return
    try:
        await canal.set_permissions(
            guild.default_role, send_messages=False, add_reactions=False
        )
        await canal.set_permissions(guild.me, send_messages=True)
    except discord.Forbidden:
        await ctx.send(
            f"⚠️ No pude ajustar permisos de {canal.mention}. "
            "Revisa que mi rol esté arriba y tenga Gestionar canales."
        )


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


async def configurar_canal_transcripciones(ctx):
    """Oculta el canal de transcripciones de tickets para @everyone y lo deja
    visible solo para ROLES_STAFF_TICKETS (y el bot)."""
    guild = ctx.guild
    canal = buscar_canal(guild, CANAL_TRANSCRIPCIONES)
    if canal is None:
        return
    try:
        await canal.set_permissions(guild.default_role, view_channel=False)
        for rol in roles_staff_tickets(guild):
            await canal.set_permissions(rol, view_channel=True, read_message_history=True)
        await canal.set_permissions(
            guild.me, view_channel=True, send_messages=True, attach_files=True
        )
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
        description=construir_reglas(guild),
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
        description=TEXTO_PANEL_ROLES,
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
#  COMANDO: PANELTICKETS (publica el panel de soporte con el boton "Abrir ticket")
# =====================================================================
@bot.command(name="paneltickets")
@commands.has_permissions(administrator=True)
async def paneltickets(ctx):
    guild = ctx.guild
    canal = buscar_canal(guild, CANAL_SOPORTE) or ctx.channel
    await configurar_canal_soporte(ctx)
    await configurar_canal_transcripciones(ctx)
    embed = discord.Embed(
        title="🎫 Soporte",
        description=(
            "¿Necesitas hablar en privado con el staff? Pulsa **🎫 Abrir ticket** y se "
            "creará un canal solo para ti y el staff.\n\n"
            "Solo puedes tener un ticket abierto a la vez."
        ),
        colour=discord.Colour(0x5865F2),
    )
    # Al editar se vuelve a pasar PanelTickets(): el custom_id no cambia.
    mensaje, editado = await publicar_o_editar_fijo(
        guild, canal, "panel_tickets", embed, view=PanelTickets()
    )
    accion = "editado" if editado else "publicado"
    await ctx.send(f"✅ Panel de tickets {accion} en {mensaje.channel.mention}")


@paneltickets.error
async def paneltickets_error(ctx, error):
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
USO_ANUNCIO = "❌ Uso: `!anuncio [everyone|here] <texto del anuncio>`"


def parsear_anuncio(texto):
    """Separa el ping opcional del texto: ("everyone" | "here" | None, cuerpo).

    "everyone"/"here" solo cuentan si son la PRIMERA palabra (sin importar
    mayusculas); si no hay ping, el cuerpo es el texto tal cual."""
    partes = texto.split(None, 1)
    if partes and partes[0].lower() in ("everyone", "here"):
        return partes[0].lower(), (partes[1].strip() if len(partes) > 1 else "")
    return None, texto


@bot.command(name="anuncio")
@commands.has_permissions(manage_guild=True)
async def anuncio(ctx, *, texto: str):
    guild = ctx.guild
    ping, cuerpo = parsear_anuncio(texto)
    if ping is not None and not cuerpo:
        await ctx.send(USO_ANUNCIO)
        return
    canal = discord.utils.get(guild.text_channels, name=CANAL_ANUNCIOS)
    if canal is None:
        await ctx.send(f"⚠️ No encuentro el canal {CANAL_ANUNCIOS}. Corre !setup primero.")
        return
    if ping is not None and not canal.permissions_for(ctx.author).mention_everyone:
        await ctx.send("❌ Necesitas el permiso Mencionar @everyone para anunciar con ping.")
        return
    embed = discord.Embed(
        title="📣 ANUNCIO",
        description=cuerpo,
        colour=discord.Colour(0xE67E22),
    )
    embed.set_footer(text=f"Publicado por {ctx.author.display_name}")
    if ping is None:
        await canal.send(embed=embed)
        sufijo = ""
    else:
        # El ping va en el content (en el embed no notifica) y solo en este envio
        # se permite mencionar a everyone.
        await canal.send(
            content=f"@{ping}",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=True, roles=False, users=False),
        )
        sufijo = f" (con @{ping})"
    await ctx.send(
        f"✅ Anuncio publicado en {canal.mention}{sufijo}",
        allowed_mentions=discord.AllowedMentions.none(),
    )


@anuncio.error
async def anuncio_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Necesitas el permiso de Gestionar servidor.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(USO_ANUNCIO)
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
#  COMANDOS: SETXP / RESETXP (corrigen la XP TOTAL; solo dueño o DEVELOPER)
# =====================================================================
# Tope razonable: nivel_desde_xp recorre los niveles uno a uno (O(nivel)).
MAX_XP_MANUAL = 10_000_000


async def cambiar_xp_total(ctx, miembro, nueva_xp):
    """Fija la XP total de `miembro` y responde con el antes y el despues.

    Solo toca user_xp: no modifica xp_mensual, no da ni quita roles de
    recompensa y no anuncia subida de nivel (a diferencia de !darnivel).
    Funciona tambien en el servidor principal (no depende de EITO_GUILD_ID)."""
    gid, uid = str(ctx.guild.id), str(miembro.id)
    antes = await get_user_xp(gid, uid)
    await set_user_xp(gid, uid, nueva_xp)
    nivel_antes, nivel_despues = nivel_desde_xp(antes), nivel_desde_xp(nueva_xp)
    await ctx.send(
        f"✅ XP de {miembro.mention}: nivel **{nivel_antes}** ({antes} XP) → "
        f"nivel **{nivel_despues}** ({nueva_xp} XP).",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await registrar_log(
        ctx.guild,
        f"🛠️ **{ctx.author}** cambió la XP total de **{miembro}**: "
        f"{antes} XP → {nueva_xp} XP (nivel {nivel_antes} → {nivel_despues})",
    )


async def responder_error_xp_total(ctx, error, uso):
    """Mensajes de error compartidos por !setxp y !resetxp."""
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ Este comando solo funciona en un servidor.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Uso: {uso}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Argumento inválido. Uso: {uso}")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("❌ Solo el dueño del servidor o un DEVELOPER pueden usar este comando.")
    else:
        await ctx.send(f"❌ Error: {error}")


@bot.command(name="setxp")
@commands.guild_only()
@commands.check(es_dueno_o_developer)
async def setxp(ctx, miembro: discord.Member, xp: int):
    if xp < 0:
        await ctx.send("❌ La XP debe ser 0 o mayor.")
        return
    if xp > MAX_XP_MANUAL:
        await ctx.send(f"❌ La XP máxima permitida es {MAX_XP_MANUAL}.")
        return
    await cambiar_xp_total(ctx, miembro, xp)


@setxp.error
async def setxp_error(ctx, error):
    await responder_error_xp_total(ctx, error, "`!setxp @usuario <xp>`")


@bot.command(name="resetxp")
@commands.guild_only()
@commands.check(es_dueno_o_developer)
async def resetxp(ctx, miembro: discord.Member):
    await cambiar_xp_total(ctx, miembro, 0)


@resetxp.error
async def resetxp_error(ctx, error):
    await responder_error_xp_total(ctx, error, "`!resetxp @usuario`")


# =====================================================================
#  COMANDO: FUNDADORES (rol Fundador para los primeros miembros; dueño o DEVELOPER)
# =====================================================================
def fecha_corta(fecha):
    """dd/mm/aaaa, o '?' si no hay fecha."""
    return fecha.strftime("%d/%m/%Y") if fecha else "?"


@bot.command(name="fundadores")
@commands.guild_only()
@commands.check(es_dueno_o_developer)
async def fundadores(ctx, confirmar: str = None):
    guild = ctx.guild
    if confirmar is not None and confirmar.lower() != "confirmar":
        await ctx.send("❌ Uso: `!fundadores [confirmar]`")
        return
    if await hay_fundadores(guild.id):
        await ctx.send("❌ Los fundadores ya fueron asignados.")
        return
    rol = guild.get_role(ROL_FUNDADOR_ID)
    if rol is None:
        await ctx.send(
            f"⚠️ No existe el rol Fundador con ID {ROL_FUNDADOR_ID}; revisa ROL_FUNDADOR_ID."
        )
        return

    # Los MAX_FUNDADORES miembros no-bot mas antiguos (desempate por ID)
    if not guild.chunked:
        await guild.chunk()
    candidatos = sorted(
        (m for m in guild.members if not m.bot and m.joined_at is not None),
        key=lambda m: (m.joined_at, m.id),
    )
    elegidos = candidatos[:MAX_FUNDADORES]
    if not elegidos:
        await ctx.send("❌ No encuentro miembros para asignar.")
        return

    if confirmar is None:
        # Vista previa: no escribe nada
        def linea(puesto, m):
            return f"**#{puesto}** {m.mention} — {fecha_corta(m.joined_at)}"
        if len(elegidos) <= 15:
            partes = ["\n".join(linea(i, m) for i, m in enumerate(elegidos, 1))]
        else:
            primeros = "\n".join(linea(i, m) for i, m in enumerate(elegidos[:10], 1))
            ultimos = "\n".join(
                linea(i, m) for i, m in enumerate(elegidos[-5:], len(elegidos) - 4)
            )
            partes = [f"**Primeros 10**\n{primeros}", f"**Últimos 5**\n{ultimos}"]
        embed = discord.Embed(
            title="🌱 Vista previa de fundadores",
            description=(
                f"👥 Miembros (sin bots): **{len(candidatos)}**\n"
                f"🌱 Fundadores a asignar: **{len(elegidos)}**\n"
                f"📅 Fecha de corte (#{len(elegidos)}): **{fecha_corta(elegidos[-1].joined_at)}**\n\n"
                + "\n\n".join(partes)
            ),
            colour=discord.Colour(0x57F287),
        )
        embed.set_footer(text="Para asignar: !fundadores confirmar")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        return

    # Antes de guardar nada: el rol debe poder asignarse (si no, quedaria una
    # lista guardada sin roles y el comando ya no se podria repetir).
    if guild.me.top_role <= rol:
        await ctx.send(
            f"❌ Mi rol más alto debe estar por encima de **{rol.name}** para poder asignarlo."
        )
        return

    await guardar_fundadores(
        guild.id, [(m.id, puesto, m.joined_at) for puesto, m in enumerate(elegidos, 1)]
    )
    dados = ya_tenian = fallos = 0
    for m in elegidos:
        if rol in m.roles:
            ya_tenian += 1
            continue
        try:
            await m.add_roles(rol, reason="Fundador")
            dados += 1
        except discord.HTTPException as e:
            fallos += 1
            print(f"⚠️ No pude dar el rol Fundador a {m} en {guild.name}: {e}")
    texto = f"✅ Fundadores guardados: **{len(elegidos)}**. Roles dados: **{dados}**."
    if ya_tenian:
        texto += f" Ya lo tenían: {ya_tenian}."
    if fallos:
        texto += f" ⚠️ Fallaron **{fallos}** asignaciones (revisa la consola)."
    await ctx.send(texto)


@fundadores.error
async def fundadores_error(ctx, error):
    if isinstance(error, commands.NoPrivateMessage):
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
#  VOZ ACTIVA (XP y minutos por estar en canales de voz acompañado)
# =====================================================================
VOZ_MINUTOS_TICK = 5        # el loop corre cada 5 min y cada tick suma 5 min
TOPE_VOZ_DIARIO = 360       # minutos contables por persona y dia (6 h; dia en UTC-5)
XP_POR_MINUTO_VOZ = 1       # 1 XP por minuto contado


def es_elegible_voz(miembro):
    """True si cuenta para la voz: no es un bot y no esta ensordecido (ni por si
    mismo ni por el servidor). Estar muteado SI cuenta."""
    voz = miembro.voice
    return (
        not miembro.bot
        and voz is not None
        and not voz.self_deaf
        and not voz.deaf
    )


async def contar_tick_voz(guild, miembro):
    """Cuenta un tick de voz (VOZ_MINUTOS_TICK minutos) para `miembro`.

    Primero reserva los minutos en el tope diario (atomico: "voz_dia:YYYY-MM-DD"
    nunca pasa de TOPE_VOZ_DIARIO); si ya no caben, el tick no cuenta nada. Si
    cuenta: suma los minutos a "voz_minutos" (con el motor de rangos por umbral) y
    la XP (total y mensual). Devuelve True si el tick conto."""
    reservado = await incrementar_contador_con_tope(
        guild.id, miembro.id, f"voz_dia:{dia_contable()}", TOPE_VOZ_DIARIO, VOZ_MINUTOS_TICK
    )
    if reservado is None:
        return False
    # Cada parte en su try: un fallo en una no impide la otra.
    try:
        await contar(guild, miembro.id, "voz_minutos", VOZ_MINUTOS_TICK)
    except Exception as e:
        print(f"⚠️ [{guild.name}] No pude contar los minutos de voz de {miembro}: {e}")
    try:
        await sumar_xp(miembro, VOZ_MINUTOS_TICK * XP_POR_MINUTO_VOZ)
    except Exception as e:
        print(f"⚠️ [{guild.name}] No pude sumar la XP de voz de {miembro}: {e}")
    return True


async def contar_voz_guild(guild):
    """Un tick de voz en un servidor: recorre los canales de voz (menos el AFK) y
    cuenta a los elegibles de cada canal que tenga al menos 2 elegibles."""
    afk_id = guild.afk_channel.id if guild.afk_channel else None
    for canal in guild.voice_channels:
        if canal.id == afk_id:
            continue
        try:
            elegibles = [m for m in canal.members if es_elegible_voz(m)]
            if len(elegibles) < 2:
                continue  # solo/a, con bots o con ensordecidos: no cuenta
            for miembro in elegibles:
                try:
                    await contar_tick_voz(guild, miembro)
                except Exception as e:
                    print(f"⚠️ [{guild.name}] Error contando la voz de {miembro}: {e}")
        except Exception:
            print(f"⚠️ [{guild.name}] Error en el canal de voz {canal}:")
            traceback.print_exc()


@tasks.loop(minutes=5)
async def contar_voz():
    """Cada 5 minutos suma tiempo y XP de voz a quien este acompañado."""
    for guild in bot.guilds:
        try:
            await contar_voz_guild(guild)
        except Exception:
            print(f"⚠️ Error contando la voz en {guild.name}:")
            traceback.print_exc()


@contar_voz.before_loop
async def antes_de_contar_voz():
    await bot.wait_until_ready()


# =====================================================================
#  CONVOCATORIAS DE !jugar (botones "Me apunto" / "Cerrar", expiracion y conteo)
# =====================================================================
LFG_DURACION = timedelta(hours=2)   # una convocatoria dura 2 horas
# Textos del embed (se reutilizan al cerrar para reescribirlos)
LFG_TEXTO_BUSCA = " está buscando compañía."
LFG_TEXTO_BUSCO = " buscó compañía."
LFG_TEXTO_BOTON = "Pulsa **✋ Me apunto** si te unes."
MAX_APUNTADOS_EMBED = 15            # nombres que se muestran en el embed
# Anti-farmeo: al cerrarse solo cuenta si estuvo abierta al menos LFG_MIN_PARA_CONTAR
# y cada persona suma como maximo TOPE_DIARIO_LFG partidas (y el autor
# convocatorias exitosas) por dia. El dia se mide en UTC-5 fijo.
LFG_MIN_PARA_CONTAR = timedelta(minutes=15)
TOPE_DIARIO_LFG = 3
HORAS_UTC_DIA = -5
DIAS_CONTADORES_DIARIOS = 7         # cuantos dias se conservan los contadores diarios


def dia_contable(ahora=None):
    """Dia (YYYY-MM-DD) en UTC-5 fijo, para los topes diarios."""
    ahora = ahora or datetime.now(timezone.utc)
    return (ahora + timedelta(hours=HORAS_UTC_DIA)).strftime("%Y-%m-%d")


def actualizar_embed_lfg(embed, guild, participantes, cerrada=False, cuenta=True):
    """Actualiza el field "Apuntados" del embed (y, si `cerrada`, el titulo y el
    color). `participantes` son IDs; se muestran hasta MAX_APUNTADOS_EMBED nombres.
    Si se cerro demasiado pronto para contar (`cuenta` False) lo indica en el titulo."""
    nombres = []
    for user_id in participantes[:MAX_APUNTADOS_EMBED]:
        miembro = guild.get_member(int(user_id))
        nombres.append(
            discord.utils.escape_markdown(miembro.display_name) if miembro else f"Usuario {user_id}"
        )
    valor = ", ".join(nombres) if nombres else "Nadie todavía"
    resto = len(participantes) - MAX_APUNTADOS_EMBED
    if resto > 0:
        valor += f" +{resto} más"
    nombre = f"Apuntados finales ({len(participantes)})" if cerrada else f"Apuntados ({len(participantes)})"
    for i, campo in enumerate(embed.fields):
        if campo.name.startswith("Apuntados"):
            embed.set_field_at(i, name=nombre, value=valor, inline=False)
            break
    else:
        embed.add_field(name=nombre, value=valor, inline=False)
    if cerrada:
        # Embed cerrado: "buscó" en pasado y sin la linea que invita a pulsar el boton
        # (se conservan el mensaje opcional del autor y la lista de apuntados).
        descripcion = (embed.description or "").replace(LFG_TEXTO_BUSCA, LFG_TEXTO_BUSCO, 1)
        if descripcion.endswith(LFG_TEXTO_BOTON):
            descripcion = descripcion[: -len(LFG_TEXTO_BOTON)]
        embed.description = descripcion.rstrip()
        embed.title = "🔒 Convocatoria cerrada"
        if not cuenta:
            minutos = int(LFG_MIN_PARA_CONTAR.total_seconds() // 60)
            embed.title += f" (no cuenta: cerrada antes de {minutos} min)"
        embed.colour = discord.Colour(0x95A5A6)
    return embed


def lfg_vencida(post, ahora=None):
    """True si la convocatoria ya paso LFG_DURACION desde que se creo."""
    ahora = ahora or datetime.now(timezone.utc)
    return ahora - post["creado"] >= LFG_DURACION


async def contar_convocatoria(guild, post, participantes):
    """Cuenta una convocatoria cerrada: si hubo al menos un apuntado distinto del
    autor, +1 "convocatorias_exitosas" al autor y +1 "partidas" al autor y a cada
    apuntado. Sin apuntados no cuenta nada.

    Tope diario (anti-farmeo): cada persona suma como maximo TOPE_DIARIO_LFG
    partidas por dia, y el autor TOPE_DIARIO_LFG convocatorias exitosas. Cada
    tope es individual: que uno lo alcance no impide que los demas sumen. Se
    lleva con contadores diarios ("partidas_dia:2026-10-01") cuyo incremento
    comprueba el tope de forma atomica."""
    autor_id = int(post["autor_id"])
    otros = [int(u) for u in participantes if int(u) != autor_id]
    if not otros:
        return
    dia = dia_contable()
    for tipo, tipo_dia, ids in (
        ("convocatorias_exitosas", "convocatorias_dia", [autor_id]),
        ("partidas", "partidas_dia", [autor_id, *otros]),
    ):
        for user_id in ids:
            try:
                bajo_el_tope = await incrementar_contador_con_tope(
                    guild.id, user_id, f"{tipo_dia}:{dia}", TOPE_DIARIO_LFG
                )
                if bajo_el_tope is None:
                    continue  # ya llego al tope de hoy: no suma
                await contar(guild, user_id, tipo)
            except Exception as e:
                print(f"⚠️ [{guild.name}] No pude contar {tipo} de {user_id}: {e}")


async def editar_mensaje_lfg_cerrado(guild, post, participantes, cuenta=True):
    """Edita el mensaje de la convocatoria: "Convocatoria cerrada", lista final y
    botones deshabilitados (con la nota "no cuenta" si `cuenta` es False). Si el
    mensaje ya no existe, no hace nada."""
    canal = guild.get_channel(int(post["canal_id"]))
    if canal is None:
        return
    try:
        mensaje = await canal.fetch_message(int(post["mensaje_id"]))
        if not mensaje.embeds:
            return
        embed = actualizar_embed_lfg(mensaje.embeds[0], guild, participantes, cerrada=True, cuenta=cuenta)
        await mensaje.edit(embed=embed, view=LfgView(cerrada=True))
    except discord.NotFound:
        pass  # el mensaje fue borrado: igual queda cerrada y contada en la BD
    except discord.HTTPException as e:
        print(f"⚠️ [{guild.name}] No pude editar la convocatoria {post['mensaje_id']}: {e}")


async def cerrar_convocatoria(guild, post):
    """Cierra la convocatoria (por expiracion, boton o clic tardio).

    El cierre es atomico: solo la llamada que la pasa de "abierta" a "cerrada"
    edita el mensaje y cuenta las partidas. Solo cuenta si estuvo abierta al
    menos LFG_MIN_PARA_CONTAR (si no, se cierra igual pero no suma nada).

    Devuelve None si ya estaba cerrada, o True/False segun si esta convocatoria
    cuenta o no."""
    duracion = await cerrar_lfg_post(post["id"])
    if duracion is None:
        return None
    participantes = await listar_participantes(post["id"])
    cuenta = duracion >= LFG_MIN_PARA_CONTAR
    if cuenta:
        await contar_convocatoria(guild, post, participantes)
    await editar_mensaje_lfg_cerrado(guild, post, participantes, cuenta)
    return cuenta


async def lfg_apuntar(interaction):
    """Boton "Me apunto": alterna apuntarse y salirse (respuesta ephemeral)."""
    await interaction.response.defer(ephemeral=True)
    post = await get_lfg_post_por_mensaje(interaction.message.id)
    if post is None:
        await interaction.followup.send("❌ Esta convocatoria ya no está registrada.", ephemeral=True)
        return
    if post["estado"] != "abierta":
        await interaction.followup.send("🔒 Esta convocatoria ya cerró.", ephemeral=True)
        return
    if lfg_vencida(post):
        await cerrar_convocatoria(interaction.guild, post)
        await interaction.followup.send("⏰ Esta convocatoria ya cerró (dura 2 horas).", ephemeral=True)
        return
    if str(interaction.user.id) == post["autor_id"]:
        await interaction.followup.send("✅ Ya estás incluido: eres quien convocó.", ephemeral=True)
        return
    se_apunto = await alternar_participante(post["id"], interaction.user.id)
    participantes = await listar_participantes(post["id"])
    try:
        embed = actualizar_embed_lfg(interaction.message.embeds[0], interaction.guild, participantes)
        await interaction.message.edit(embed=embed)
    except discord.HTTPException as e:
        print(f"⚠️ No pude actualizar la convocatoria {post['mensaje_id']}: {e}")
    await interaction.followup.send(
        "✋ ¡Te apuntaste!" if se_apunto else "👋 Saliste de la convocatoria.", ephemeral=True
    )


async def lfg_cerrar_click(interaction):
    """Boton "Cerrar": solo quien convoco o alguien con moderate_members."""
    await interaction.response.defer(ephemeral=True)
    post = await get_lfg_post_por_mensaje(interaction.message.id)
    if post is None:
        await interaction.followup.send("❌ Esta convocatoria ya no está registrada.", ephemeral=True)
        return
    if post["estado"] == "abierta" and lfg_vencida(post):
        await cerrar_convocatoria(interaction.guild, post)
        await interaction.followup.send("⏰ Esta convocatoria ya cerró (dura 2 horas).", ephemeral=True)
        return
    es_autor = str(interaction.user.id) == post["autor_id"]
    es_mod = interaction.user.guild_permissions.moderate_members
    if not (es_autor or es_mod):
        await interaction.followup.send(
            "❌ Solo quien convocó o un moderador puede cerrarla.", ephemeral=True
        )
        return
    if post["estado"] != "abierta":
        await interaction.followup.send("🔒 Esta convocatoria ya estaba cerrada.", ephemeral=True)
        return
    cuenta = await cerrar_convocatoria(interaction.guild, post)
    if cuenta is None:
        texto = "🔒 Esta convocatoria ya estaba cerrada."
    elif cuenta:
        texto = "🔒 Convocatoria cerrada."
    else:
        minutos = int(LFG_MIN_PARA_CONTAR.total_seconds() // 60)
        texto = f"🔒 Convocatoria cerrada (no cuenta: cerrada antes de {minutos} min)."
    await interaction.followup.send(texto, ephemeral=True)


class LfgView(discord.ui.View):
    """Vista persistente de una convocatoria (custom_id fijos: sobrevive reinicios)."""

    def __init__(self, cerrada=False):
        super().__init__(timeout=None)
        if cerrada:
            for boton in self.children:
                boton.disabled = True

    @discord.ui.button(label="Me apunto", emoji="✋", style=discord.ButtonStyle.success,
                       custom_id="lfg:apuntar")
    async def apuntar(self, interaction: discord.Interaction, boton: discord.ui.Button):
        await lfg_apuntar(interaction)

    @discord.ui.button(label="Cerrar", emoji="🔒", style=discord.ButtonStyle.secondary,
                       custom_id="lfg:cerrar")
    async def cerrar(self, interaction: discord.Interaction, boton: discord.ui.Button):
        await lfg_cerrar_click(interaction)


@tasks.loop(minutes=5)
async def cerrar_convocatorias_vencidas():
    """Cada 5 minutos cierra las convocatorias que pasaron LFG_DURACION."""
    try:
        vencidas = await lfg_posts_vencidos(datetime.now(timezone.utc) - LFG_DURACION)
    except Exception:
        print("⚠️ No pude consultar las convocatorias vencidas:")
        traceback.print_exc()
        return
    for post in vencidas:
        try:
            guild = bot.get_guild(int(post["guild_id"]))
            if guild is not None:
                await cerrar_convocatoria(guild, post)
        except Exception:
            print(f"⚠️ Error cerrando la convocatoria {post['mensaje_id']}:")
            traceback.print_exc()


@cerrar_convocatorias_vencidas.before_loop
async def antes_de_cerrar_convocatorias():
    await bot.wait_until_ready()
    try:
        await crear_tablas()
    except Exception:
        print("⚠️ crear_tablas() fallo antes de las convocatorias:")
        traceback.print_exc()


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
            f"**{ctx.author.display_name}**{LFG_TEXTO_BUSCA}\n\n"
            f"💬 {texto_extra}\n\n"
            f"{LFG_TEXTO_BOTON}"
        ),
        colour=discord.Colour(0xE74C3C),
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.add_field(name="Apuntados (0)", value="Nadie todavía", inline=False)

    # Mencionar al rol Leftsito (permitido explicitamente)
    mensaje_enviado = await canal.send(
        content=f"{rol.mention}",
        embed=embed,
        view=LfgView(),
        allowed_mentions=discord.AllowedMentions(roles=[rol]),
    )
    # Registrar la convocatoria para que los botones funcionen. Si falla la BD,
    # se retira el mensaje (sus botones no servirian) y se libera el cooldown.
    try:
        await crear_lfg_post(guild.id, canal.id, mensaje_enviado.id, ctx.author.id)
    except Exception as e:
        print(f"⚠️ No pude registrar la convocatoria de {ctx.author}: {e}")
        ultimo_jugar.pop(clave, None)
        try:
            await mensaje_enviado.delete()
        except discord.HTTPException:
            pass
        await ctx.send("❌ No pude registrar la convocatoria. Inténtalo de nuevo en un momento.")
        return

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
#  COMUNIDAD: ANTIGUEDAD (dias en el server, rango y distinciones)
# =====================================================================
def rango_antiguedad(ids_roles, dias):
    """(rango actual, siguiente rango) segun los dias en el server. El rango
    cuenta por dias o por tener ya el rol (p. ej. puesto a mano). `dias` puede
    ser None si no se sabe cuando entro."""
    es_leyenda = ROL_LEYENDA_ID in ids_roles or (dias is not None and dias >= DIAS_LEYENDA)
    es_veterano = ROL_VETERANO_ID in ids_roles or (dias is not None and dias >= DIAS_VETERANO)
    if es_leyenda:
        return ROL_LEYENDA, "Rango máximo alcanzado 🎉"
    if es_veterano:
        return ROL_VETERANO, (
            f"{ROL_LEYENDA} en **{max(DIAS_LEYENDA - dias, 0)}** días" if dias is not None else "—"
        )
    return "Ninguno todavía", (
        f"{ROL_VETERANO} en **{max(DIAS_VETERANO - dias, 0)}** días" if dias is not None else "—"
    )


@bot.command(name="antiguedad")
@commands.guild_only()
async def antiguedad(ctx, miembro: discord.Member = None):
    miembro = miembro or ctx.author
    ahora = datetime.now(timezone.utc)
    ids_roles = {rol.id for rol in miembro.roles}
    dias = (ahora - miembro.joined_at).days if miembro.joined_at else None

    rango, siguiente = rango_antiguedad(ids_roles, dias)

    embed = discord.Embed(
        title=f"🕰️ Antigüedad de {miembro.display_name}",
        colour=discord.Colour(0x3498DB),
    )
    embed.set_thumbnail(url=miembro.display_avatar.url)
    if dias is not None:
        embed.add_field(
            name="📅 Entró el",
            value=f"{fecha_corta(miembro.joined_at)} · **{dias}** días en el server",
            inline=False,
        )
    else:
        embed.add_field(name="📅 Entró el", value="Fecha desconocida", inline=False)
    embed.add_field(name="🎖️ Rango actual", value=rango, inline=True)
    embed.add_field(name="⏭️ Siguiente rango", value=siguiente, inline=True)

    distinciones = []
    try:
        puesto = await get_fundador(ctx.guild.id, miembro.id)
    except Exception as e:
        puesto = None
        print(f"⚠️ No pude consultar el puesto de fundador de {miembro}: {e}")
    if puesto is not None:
        distinciones.append(f"🌱 Fundador #{puesto}")
    if ROL_OG_ID in ids_roles:
        distinciones.append("🥇 OG")
    if distinciones:
        embed.add_field(name="🏅 Distinciones", value="\n".join(distinciones), inline=False)
    await ctx.send(embed=embed)


@antiguedad.error
async def antiguedad_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ Este comando solo funciona en un servidor.")
    else:
        await ctx.send(f"❌ Error: {error}")


# =====================================================================
#  COMUNIDAD: PERFIL (nivel, antiguedad, distinciones y contadores)
# =====================================================================
async def _seguro(coro, defecto):
    """Espera `coro`; si falla (p. ej. la BD), lo registra y devuelve `defecto`."""
    try:
        return await coro
    except Exception as e:
        print(f"⚠️ !perfil: no pude leer un dato: {e}")
        return defecto


def formato_horas(minutos):
    """'X h Y min' (p. ej. 80 -> '1 h 20 min')."""
    return f"{minutos // 60} h {minutos % 60} min"


def progreso_voz(minutos):
    """'12/50 h' hacia Voz activa, o '✅' si ya llego al umbral."""
    umbral = next((u for t, u, _rol_id in RANGOS_POR_CONTADOR if t == "voz_minutos"), 3000)
    return "✅" if minutos >= umbral else f"{minutos // 60}/{umbral // 60} h"


def progreso_contador(tipo, valor):
    """'7/10' hacia el rango del contador `tipo`, o '✅' si ya llego al umbral."""
    umbral = next((u for t, u, _rol_id in RANGOS_POR_CONTADOR if t == tipo), 10)
    return "✅" if valor >= umbral else f"{valor}/{umbral}"


@bot.command(name="perfil")
@commands.guild_only()
async def perfil(ctx, miembro: discord.Member = None):
    miembro = miembro or ctx.author
    gid = ctx.guild.id
    xp = await _seguro(get_user_xp(gid, miembro.id), 0)
    puesto = await _seguro(get_fundador(gid, miembro.id), None)
    veces_activo = await _seguro(contar_activo_del_mes(gid, miembro.id), 0)
    contadores = await _seguro(obtener_contadores(gid, miembro.id), {})

    ids_roles = {rol.id for rol in miembro.roles}
    dias = (datetime.now(timezone.utc) - miembro.joined_at).days if miembro.joined_at else None
    rango, _siguiente = rango_antiguedad(ids_roles, dias)

    distinciones = []
    if puesto is not None:
        distinciones.append(f"🌱 Fundador #{puesto}")
    if ROL_OG_ID in ids_roles:
        distinciones.append("🥇 OG")
    if veces_activo:
        distinciones.append(f"🔥 Activo del mes ×{veces_activo}")

    partidas = contadores.get("partidas", 0)
    convocatorias = contadores.get("convocatorias_exitosas", 0)
    embed = discord.Embed(
        title=f"🪪 Perfil de {miembro.display_name}",
        colour=discord.Colour(0x5865F2),
    )
    embed.set_thumbnail(url=miembro.display_avatar.url)
    embed.add_field(name="📈 Nivel", value=f"Nivel **{nivel_desde_xp(xp)}** · **{xp}** XP", inline=True)
    embed.add_field(
        name="🕰️ En el server",
        value=(f"**{dias}** días" if dias is not None else "Fecha desconocida") + f" · {rango}",
        inline=True,
    )
    embed.add_field(
        name="🏅 Distinciones",
        value="\n".join(distinciones) if distinciones else "Ninguna todavía",
        inline=False,
    )
    embed.add_field(
        name="🎮 Partidas jugadas",
        value=f"**{partidas}** · {ROL_SUPERVIVIENTE} {progreso_contador('partidas', partidas)}",
        inline=True,
    )
    embed.add_field(
        name="🎯 Convocatorias exitosas",
        value=(f"**{convocatorias}** · {ROL_CONVOCADOR} "
               f"{progreso_contador('convocatorias_exitosas', convocatorias)}"),
        inline=True,
    )
    minutos_voz = contadores.get("voz_minutos", 0)
    hoy_voz = contadores.get(f"voz_dia:{dia_contable()}", 0)
    embed.add_field(
        name="🎧 Tiempo en voz",
        value=(f"**{formato_horas(minutos_voz)}** · {ROL_VOZ_ACTIVA} {progreso_voz(minutos_voz)}\n"
               f"hoy: {formato_horas(hoy_voz)} / {TOPE_VOZ_DIARIO // 60} h"),
        inline=False,
    )
    await ctx.send(embed=embed)


@perfil.error
async def perfil_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ No encuentro a ese miembro.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ Este comando solo funciona en un servidor.")
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
        ("antiguedad", "`!antiguedad [@usuario]` — días en el server, rango y distinciones", None),
        ("perfil", "`!perfil [@usuario]` — nivel, antigüedad, distinciones y partidas", None),
        ("ayuda", "`!ayuda` — muestra esta lista", None),
    ]),
    ("📊 Utilidad", [
        ("encuesta", "`!encuesta <pregunta>` — crea una encuesta 👍👎", None),
        ("sugerencia", "`!sugerencia <texto>` — envía una sugerencia con votación", None),
        ("steam", "`!steam <enlace o SteamID>` — publica tu perfil de Steam", None),
        ("jugar", "`!jugar [mensaje]` — busca gente para jugar; los demás se apuntan con un botón", None),
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
        ("paneltickets", "`!paneltickets` — publica o actualiza el panel de tickets de soporte", None),
        ("presentaciones", "`!presentaciones` — publica o actualiza la plantilla de presentación", None),
        ("anuncio", "`!anuncio [everyone|here] <texto>` — publica un anuncio (con ping si pones everyone o here)", None),
        ("panelcochipuerco", "`!panelcochipuerco` — publica el panel del rol +18 y configura NSFW", None),
    ]),
    ("⚙️ Configurar y datos", [
        ("setup", "`!setup [confirmar]` — vista previa de lo que crearía; con `confirmar` crea canales, categorías y roles", None),
        ("setupsteam", "`!setupsteam` — reconfigura el canal de perfiles", None),
        ("setuprecompensas", "`!setuprecompensas` — reconfigura los canales de nivel", None),
        ("importarniveles", "`!importarniveles <YYYY-MM> [confirmar]` — importa la XP de un mes desde los avisos de nivel", None),
        ("exportarserver", "`!exportarserver` — exporta roles y canales a JSON por DM (dueño o DEVELOPER)", None),
        ("darnivel", "`!darnivel <nivel> [@usuario]` — asigna un nivel exacto (solo en server de pruebas)", None),
        ("setxp", "`!setxp @usuario <xp>` — fija la XP total de alguien (dueño o DEVELOPER)", None),
        ("resetxp", "`!resetxp @usuario` — pone en 0 la XP total de alguien (dueño o DEVELOPER)", None),
        ("fundadores", "`!fundadores [confirmar]` — da el rol Fundador a los 100 primeros miembros (dueño o DEVELOPER)", None),
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
