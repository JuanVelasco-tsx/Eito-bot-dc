"""Carga y validacion de profiles/pss.toml (perfil temporal Phantom Shadows Studios).

Solo lee el TOML con `tomllib` y comprueba que sea coherente: no habla con Discord.
`cargar()` devuelve un `Config` inmutable o lanza `ConfigInvalida` con TODOS los
errores encontrados (cada uno con la ruta del campo), no solo el primero.
"""

import difflib
import re
import tomllib
import datetime as dt
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import discord

# --- Limites de Discord ---------------------------------------------------------
MAX_ROLES = 250
MAX_CANALES = 500          # incluye las categorias
MAX_POR_CATEGORIA = 50
MAX_NOMBRE = 100
MAX_TEMA = 1024
MAX_SLOWMODE = 21600
MAX_LIMITE_VOZ = 99
MAX_EMBED_TITULO = 256
MAX_EMBED_DESCRIPCION = 4096
MAX_EMBED_CAMPOS = 25
MAX_CAMPO_NOMBRE = 256
MAX_CAMPO_VALOR = 1024
MAX_EMBED_PIE = 2048
MAX_EMBED_TOTAL = 6000
MAX_BOTONES = 25
MAX_ETIQUETA_BOTON = 80
LARGO_MENCION = 22         # "<#" + 18 digitos + ">" (estimacion al validar plantillas)

EVENTOS_BOOL = ("xp", "voz", "anti_multicuentas", "fundador_automatico")
TIPOS_CANAL = ("text", "voice", "news", "forum")
TIPOS_CON_MENSAJES = ("text", "news")       # donde el bot puede publicar mensajes

# Claves que el resolvedor del bot (rol_de / roles_de / canal_de / categoria_de en eito_setup_bot.py)
# acepta en [recursos], con True si admiten VARIOS roles. Un test comprueba que coincide con las
# tablas del bot. Lo que no este mapeado aqui, en PSS no existe (nunca se usan los IDs de EITO).
RECURSOS_ROLES = {
    "activo_mes": False, "fundador": False, "veterano": False, "leyenda": False, "og": False,
    "voz_activa": False, "superviviente": False, "convocador": False,
    "developer": True, "honor": True, "excluidos_activo_mes": True,
    "staff_tickets": True, "ping_tickets": True,
}
RECURSOS_CANALES = ("niveles", "logros", "anuncios", "soporte", "transcripciones")
RECURSOS_CATEGORIAS = ("tickets",)
REGEX_KEY = re.compile(r"[a-z0-9_]{1,64}")
REGEX_COLOR = re.compile(r"#?([0-9a-fA-F]{6})")
REGEX_PLACEHOLDER = re.compile(r"\{(canal|rol):([a-z0-9_]+)\}")
EVERYONE = "@everyone"

PERMISOS_VALIDOS = frozenset(discord.Permissions.VALID_FLAGS)
# Por valor de bit (no iterando Permissions): asi tambien entran los alias (view_channel).
_BITS_DE_CANAL = discord.Permissions.all_channel().value
PERMISOS_DE_CANAL = frozenset(
    nombre for nombre, bit in discord.Permissions.VALID_FLAGS.items() if bit & _BITS_DE_CANAL
)
# Permisos que un rol autoasignable nunca puede tener (cualquier "elevated" de discord.py).
PERMISOS_ELEVADOS = discord.Permissions.elevated().value


class ConfigInvalida(Exception):
    """El TOML no es valido. `errores` es la lista completa, una linea por problema."""

    def __init__(self, errores):
        self.errores = list(errores)
        super().__init__(
            "perfil PSS invalido:\n" + "\n".join(f"  - {e}" for e in self.errores)
        )


# --- Modelo ----------------------------------------------------------------------
@dataclass(frozen=True)
class Override:
    objetivo: str                     # "@everyone" o la key de un rol
    permitir: tuple = ()
    denegar: tuple = ()


@dataclass(frozen=True)
class Rol:
    key: str
    nombre: str
    color: int = 0
    hoist: bool = False
    mentionable: bool = False
    permisos: tuple = ()
    existing_id: int = 0
    adoptar: bool = False
    permitir_admin: bool = False
    autoasignable: bool = False
    por_encima_del_bot: bool = False   # el rol va (a mano) por encima del bot: no avisar de la jerarquia


@dataclass(frozen=True)
class Categoria:
    key: str
    nombre: str
    orden: int = 0
    existing_id: int = 0
    adoptar: bool = False
    overrides: tuple = ()


@dataclass(frozen=True)
class Canal:
    key: str
    nombre: str
    categoria: str
    tipo: str = "text"                # text | voice | news (anuncios) | forum
    nombre_actual: str | None = None   # como se llama hoy (para encontrarlo antes de renombrarlo)
    tema: str | None = None
    slowmode: int | None = None
    limite_usuarios: int | None = None
    reemplaza: str | None = None       # foro que sustituye a un canal de texto existente con ese nombre
    orden: int = 0
    existing_id: int = 0
    adoptar: bool = False
    mover: bool = False
    sincronizar_permisos: bool = False
    overrides: tuple = ()


@dataclass(frozen=True)
class Juego:
    """[juego]: datos del juego de Roblox. Con `nombre` vacio la categoria se llama «EL JUEGO» y la info
    omite el campo del juego; los enlaces son opcionales (https de roblox.com)."""
    nombre: str = ""
    enlace_juego: str = ""
    enlace_grupo: str = ""

    def titulo(self):
        """El nombre del juego, enlazado si hay enlace."""
        if self.nombre and self.enlace_juego:
            return f"[{self.nombre}]({self.enlace_juego})"
        return f"**{self.nombre}**" if self.nombre else ""


ESTILOS_BOTON = ("primary", "secondary", "success", "danger")
MAX_BOTONES_POR_FILA = 5


@dataclass(frozen=True)
class Boton:
    """Un boton de rol de un mensaje: estilo, fila (0-4, None = automatica) y emoji opcionales."""
    rol: str
    estilo: str = "secondary"
    fila: int | None = None
    emoji: str = ""


@dataclass(frozen=True)
class Mensaje:
    key: str
    canal: str
    titulo: str = ""
    descripcion: str = ""
    color: int = 0x5865F2
    campos: tuple = ()                # ((nombre, valor, inline), ...)
    pie: str = ""
    publicar: bool = True
    botones_roles: tuple = ()         # keys de rol (en el orden de los botones)
    botones: tuple = ()               # lo mismo con estilo/fila/emoji: tuple de Boton


@dataclass(frozen=True)
class EntradaAyuda:
    comando: str                      # nombre del comando de EITO (sin «!»)
    texto: str                        # que hace (admite {canal:key} y {rol:key})
    uso: str = ""                     # como se escribe, p. ej. "!avatar [@usuario]" (por defecto "!comando")
    solo_moderadores: bool = False    # ademas de can_run: solo quien puede kick_members o moderate_members

    def linea(self):
        return f"`{self.uso or '!' + self.comando}` — {self.texto}"


@dataclass(frozen=True)
class SeccionAyuda:
    titulo: str
    entradas: tuple


@dataclass(frozen=True)
class Ayuda:
    titulo: str
    descripcion: str = ""
    pie: str = ""
    secciones: tuple = ()


@dataclass(frozen=True)
class Bienvenida:
    """[bienvenida]: embed que se manda al canal de bienvenida cuando entra alguien.
    Admite {usuario}, {servidor}, {numero} (miembros del servidor), {canal:key} y {rol:key}."""
    titulo: str
    descripcion: str
    color: int = 0x2ECC71


@dataclass(frozen=True)
class DestinoRelease:
    """[webhook.<destino>]: a donde va un aviso de release cuando el POST trae {"destino": "<destino>"}."""
    canal: str      # key de [[canales]]
    rol: str        # key de [[roles]] que se menciona


@dataclass(frozen=True)
class Rangos:
    """[rangos]: los dias para Veterano/Leyenda cuentan desde max(entrada, contar_desde) (UTC)."""
    contar_desde: dt.datetime | None = None


@dataclass(frozen=True)
class Recursos:
    """[recursos]: clave de un sistema de EITO -> key(s) de [[roles]] / [[canales]] / [[categorias]]."""
    roles: dict = field(default_factory=dict)        # clave -> tuple de keys de rol
    canales: dict = field(default_factory=dict)      # clave -> key de canal
    categorias: dict = field(default_factory=dict)   # clave -> key de categoria


@dataclass(frozen=True)
class Eventos:
    xp: bool = False
    voz: bool = False
    anti_multicuentas: bool = False
    fundador_automatico: bool = False      # quien entra recibe 🌱 Fundador mientras haya menos de 100
    rol_al_entrar: str = ""
    bienvenida: str = ""
    canal_logs: str = ""


@dataclass(frozen=True)
class Config:
    nombre: str
    guild_id: int
    owner_id: int
    gestores: tuple
    eventos: Eventos
    comandos_bloqueados: frozenset
    roles: tuple
    categorias: tuple
    canales: tuple
    mensajes: tuple
    _indice: dict = field(default_factory=dict, repr=False, compare=False)
    ayuda: Ayuda | None = None
    recursos: Recursos = field(default_factory=Recursos)
    bienvenida: Bienvenida | None = None
    rangos: Rangos = field(default_factory=Rangos)
    webhook: dict = field(default_factory=dict)      # destino -> DestinoRelease
    juego: Juego = field(default_factory=Juego)

    def rol(self, key):
        return self._indice.get(("rol", key))

    def categoria(self, key):
        return self._indice.get(("categoria", key))

    def canal(self, key):
        return self._indice.get(("canal", key))

    def mensaje(self, key):
        return self._indice.get(("mensaje", key))

    def roles_autoasignables(self):
        return tuple(r for r in self.roles if r.autoasignable)


# --- Utilidades de validacion ----------------------------------------------------
# Nombres que se suelen escribir mal y que difflib no adivina.
SINONIMOS = {"manage_server": "manage_guild", "kick": "kick_members", "ban": "ban_members",
             "manage_emojis": "manage_expressions", "read_messages": "view_channel"}


def _sugerir(nombre, validos):
    if SINONIMOS.get(nombre) in validos:
        return f" (¿'{SINONIMOS[nombre]}'?)"
    cercanos = difflib.get_close_matches(nombre, sorted(validos), n=1)
    return f" (¿'{cercanos[0]}'?)" if cercanos else ""


class _Validador:
    def __init__(self):
        self.errores = []

    def error(self, ruta, texto):
        self.errores.append(f"{ruta}: {texto}")

    def tabla(self, valor, ruta):
        if not isinstance(valor, dict):
            self.error(ruta, "debe ser una tabla")
            return {}
        return valor

    def lista_de_tablas(self, valor, ruta):
        if valor is None:
            return []
        if not isinstance(valor, list) or not all(isinstance(v, dict) for v in valor):
            self.error(ruta, "debe ser una lista de tablas ([[...]])")
            return []
        return valor

    def desconocidas(self, datos, permitidas, ruta):
        for clave in datos:
            if clave not in permitidas:
                self.error(f"{ruta}.{clave}", f"clave desconocida{_sugerir(clave, permitidas)}")

    def texto(self, datos, clave, ruta, *, requerido=False, maximo=None, defecto=""):
        valor = datos.get(clave, None)
        if valor is None:
            if requerido:
                self.error(f"{ruta}.{clave}", "es obligatorio")
            return defecto
        if not isinstance(valor, str):
            self.error(f"{ruta}.{clave}", "debe ser un texto")
            return defecto
        if requerido and not valor.strip():
            self.error(f"{ruta}.{clave}", "no puede estar vacio")
        if maximo is not None and len(valor) > maximo:
            self.error(f"{ruta}.{clave}", f"tiene {len(valor)} caracteres (maximo {maximo})")
        return valor

    def entero(self, datos, clave, ruta, *, minimo=0, maximo=None, defecto=0, requerido=False):
        valor = datos.get(clave, None)
        if valor is None:
            if requerido:
                self.error(f"{ruta}.{clave}", "es obligatorio")
            return defecto
        if isinstance(valor, bool) or not isinstance(valor, int):
            self.error(f"{ruta}.{clave}", "debe ser un numero entero")
            return defecto
        if valor < minimo or (maximo is not None and valor > maximo):
            rango = f"entre {minimo} y {maximo}" if maximo is not None else f"al menos {minimo}"
            self.error(f"{ruta}.{clave}", f"vale {valor} (debe estar {rango})")
        return valor

    def booleano(self, datos, clave, ruta, defecto=False):
        valor = datos.get(clave, defecto)
        if not isinstance(valor, bool):
            self.error(f"{ruta}.{clave}", "debe ser true o false")
            return defecto
        return valor

    def color(self, datos, clave, ruta, defecto=0):
        valor = datos.get(clave, None)
        if valor is None:
            return defecto
        if isinstance(valor, int) and not isinstance(valor, bool) and 0 <= valor <= 0xFFFFFF:
            return valor
        if isinstance(valor, str) and REGEX_COLOR.fullmatch(valor):
            return int(REGEX_COLOR.fullmatch(valor).group(1), 16)
        self.error(f"{ruta}.{clave}", f"color invalido {valor!r} (usa \"#RRGGBB\")")
        return defecto

    def permisos(self, datos, clave, ruta, validos):
        valor = datos.get(clave, [])
        if not isinstance(valor, list) or not all(isinstance(p, str) for p in valor):
            self.error(f"{ruta}.{clave}", "debe ser una lista de nombres de permisos")
            return ()
        for permiso in valor:
            if permiso not in validos:
                self.error(f"{ruta}.{clave}", f"permiso invalido '{permiso}'{_sugerir(permiso, validos)}")
        if len(set(valor)) != len(valor):
            self.error(f"{ruta}.{clave}", "tiene permisos repetidos")
        return tuple(dict.fromkeys(valor))

    def lista_texto(self, datos, clave, ruta):
        valor = datos.get(clave, [])
        if not isinstance(valor, list) or not all(isinstance(x, str) for x in valor):
            self.error(f"{ruta}.{clave}", "debe ser una lista de textos")
            return ()
        return tuple(valor)


def _parsear_overrides(v, datos, ruta):
    brutos = datos.get("overrides", [])
    if not isinstance(brutos, list) or not all(isinstance(o, dict) for o in brutos):
        v.error(f"{ruta}.overrides", "debe ser una lista de tablas")
        return ()
    resultado, vistos = [], set()
    for i, o in enumerate(brutos):
        r = f"{ruta}.overrides[{i}]"
        v.desconocidas(o, {"objetivo", "permitir", "denegar"}, r)
        objetivo = v.texto(o, "objetivo", r, requerido=True)
        permitir = v.permisos(o, "permitir", r, PERMISOS_DE_CANAL)
        denegar = v.permisos(o, "denegar", r, PERMISOS_DE_CANAL)
        choque = set(permitir) & set(denegar)
        if choque:
            v.error(r, f"permisos en permitir y denegar a la vez: {', '.join(sorted(choque))}")
        if objetivo in vistos:
            v.error(r, f"el objetivo '{objetivo}' ya tiene otro override en esta lista")
        vistos.add(objetivo)
        resultado.append(Override(objetivo, permitir, denegar))
    return tuple(resultado)


MAX_AYUDA_USO = 100
MAX_AYUDA_TEXTO = 300
REGEX_COMANDO = re.compile(r"[a-z0-9_]+")


def _largo_con_menciones(texto):
    return len(REGEX_PLACEHOLDER.sub("x" * LARGO_MENCION, texto))


def _parsear_ayuda(v, bruto, bloqueados, claves_canales, claves_roles):
    """[ayuda]: titulo, descripcion, pie y [[ayuda.secciones]] con la lista de comandos.

    Aqui solo se valida lo que se puede sin el bot (formato, limites, no repetir, que no esten en
    [comandos].bloquear y las menciones); que cada comando EXISTA en el bot lo comprueba
    `comandos_de_ayuda_inexistentes` al cargar la extension."""
    if bruto is None:
        return None
    a = v.tabla(bruto, "ayuda")
    v.desconocidas(a, {"titulo", "descripcion", "pie", "secciones"}, "ayuda")
    titulo = v.texto(a, "titulo", "ayuda", requerido=True, maximo=MAX_EMBED_TITULO)
    descripcion = v.texto(a, "descripcion", "ayuda", maximo=MAX_EMBED_DESCRIPCION)
    pie = v.texto(a, "pie", "ayuda", maximo=MAX_EMBED_PIE)
    secciones, vistos = [], {}
    brutas = v.lista_de_tablas(a.get("secciones"), "ayuda.secciones")
    if not brutas:
        v.error("ayuda.secciones", "pon al menos una seccion ([[ayuda.secciones]])")
    if len(brutas) > MAX_EMBED_CAMPOS:
        v.error("ayuda.secciones", f"hay {len(brutas)} secciones (maximo {MAX_EMBED_CAMPOS})")
    total = _largo_con_menciones(titulo) + _largo_con_menciones(descripcion) + _largo_con_menciones(pie)
    for i, s in enumerate(brutas):
        ruta = f"ayuda.secciones[{i}]"
        v.desconocidas(s, {"titulo", "comandos"}, ruta)
        nombre = v.texto(s, "titulo", ruta, requerido=True, maximo=MAX_CAMPO_NOMBRE)
        ruta = f"ayuda.secciones[{i}] '{nombre}'"
        entradas = []
        crudas = v.lista_de_tablas(s.get("comandos"), f"{ruta}.comandos")
        if not crudas:
            v.error(f"{ruta}.comandos", "pon al menos un comando")
        for j, c in enumerate(crudas):
            rc = f"{ruta}.comandos[{j}]"
            v.desconocidas(c, {"comando", "uso", "texto", "solo_moderadores"}, rc)
            comando = v.texto(c, "comando", rc, requerido=True)
            if comando:
                rc = f"{ruta}.comandos[{j}] '{comando}'"
                if not REGEX_COMANDO.fullmatch(comando):
                    v.error(rc, "el nombre del comando va sin «!» y en minusculas ([a-z0-9_])")
                if comando in bloqueados:
                    v.error(rc, "esta en [comandos] bloquear: no puede salir en la ayuda")
                if comando in vistos:
                    v.error(rc, f"repetido (ya sale en la seccion '{vistos[comando]}')")
                vistos.setdefault(comando, nombre)
            entrada = EntradaAyuda(
                comando=comando, texto=v.texto(c, "texto", rc, requerido=True, maximo=MAX_AYUDA_TEXTO),
                uso=v.texto(c, "uso", rc, maximo=MAX_AYUDA_USO),
                solo_moderadores=v.booleano(c, "solo_moderadores", rc),
            )
            for tipo_ref, key_ref in REGEX_PLACEHOLDER.findall(entrada.texto):
                if tipo_ref == "canal" and key_ref not in claves_canales:
                    v.error(rc, f"{{canal:{key_ref}}} no existe en [[canales]]")
                if tipo_ref == "rol" and key_ref not in claves_roles:
                    v.error(rc, f"{{rol:{key_ref}}} no existe en [[roles]]")
            entradas.append(entrada)
        largo_campo = _largo_con_menciones("\n".join(e.linea() for e in entradas))
        if largo_campo > MAX_CAMPO_VALOR:
            v.error(ruta, f"la lista suma {largo_campo} caracteres (maximo {MAX_CAMPO_VALOR} por seccion)")
        total += _largo_con_menciones(nombre) + largo_campo
        secciones.append(SeccionAyuda(nombre, tuple(entradas)))
    if total > MAX_EMBED_TOTAL:
        v.error("ayuda", f"el embed suma {total} caracteres (maximo {MAX_EMBED_TOTAL})")
    return Ayuda(titulo, descripcion, pie, tuple(secciones))


VARIABLES_BIENVENIDA = ("usuario", "servidor", "numero")
REGEX_LLAVES = re.compile(r"\{([^{}]*)\}")


def _parsear_bienvenida(v, bruto, claves_canales, claves_roles):
    if bruto is None:
        return None
    b = v.tabla(bruto, "bienvenida")
    v.desconocidas(b, {"titulo", "descripcion", "color"}, "bienvenida")
    titulo = v.texto(b, "titulo", "bienvenida", requerido=True, maximo=MAX_EMBED_TITULO)
    descripcion = v.texto(b, "descripcion", "bienvenida", requerido=True, maximo=MAX_EMBED_DESCRIPCION)
    for campo, texto in (("titulo", titulo), ("descripcion", descripcion)):
        for contenido in REGEX_LLAVES.findall(texto):
            ruta = f"bienvenida.{campo}"
            tipo, _, key = contenido.partition(":")
            if contenido in VARIABLES_BIENVENIDA:
                continue
            if tipo == "canal" and key in claves_canales or tipo == "rol" and key in claves_roles:
                continue
            if tipo in ("canal", "rol") and key:
                v.error(ruta, f"{{{contenido}}} no existe en [[{'canales' if tipo == 'canal' else 'roles'}]]")
            else:
                v.error(ruta, f"{{{contenido}}} no es una variable valida (usa {', '.join('{' + n + '}' for n in VARIABLES_BIENVENIDA)}, {{canal:key}} o {{rol:key}})")
    return Bienvenida(titulo, descripcion, v.color(b, "color", "bienvenida", defecto=0x2ECC71))


CAMPOS_JUEGO = ("juego.nombre", "juego.enlace_juego", "juego.enlace_grupo")


def _url_de_roblox(valor):
    try:
        u = urllib.parse.urlparse(valor)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return (u.scheme == "https" and (host == "roblox.com" or host.endswith(".roblox.com"))
            and not u.username and not u.password and not any(c.isspace() for c in valor))


def _parsear_juego(v, bruto):
    if bruto is None:
        return Juego()
    j = v.tabla(bruto, "juego")
    v.desconocidas(j, {"nombre", "enlace_juego", "enlace_grupo"}, "juego")
    nombre = v.texto(j, "nombre", "juego", maximo=50).strip()
    if nombre and any(c in nombre for c in "{}\n"):
        v.error("juego.nombre", "no puede llevar llaves ni saltos de linea")
    enlaces = {}
    for clave in ("enlace_juego", "enlace_grupo"):
        valor = v.texto(j, clave, "juego", maximo=300).strip()
        if valor and not _url_de_roblox(valor):
            v.error(f"juego.{clave}", "debe ser una URL https de roblox.com (p. ej. https://www.roblox.com/games/123)")
        enlaces[clave] = valor
    return Juego(nombre, enlaces["enlace_juego"], enlaces["enlace_grupo"])


def _parsear_botones(v, bruto, ruta):
    """botones_roles: lista de keys de rol o de tablas {rol, estilo, fila, emoji}."""
    if bruto is None:
        return ()
    if not isinstance(bruto, list):
        v.error(ruta, "debe ser una lista de keys de rol o de tablas {rol, estilo, fila, emoji}")
        return ()
    botones, por_fila = [], {}
    for i, b in enumerate(bruto):
        rb = f"{ruta}[{i}]"
        if isinstance(b, str):
            botones.append(Boton(b))
            continue
        if not isinstance(b, dict):
            v.error(rb, "debe ser la key de un rol o una tabla {rol, estilo, fila, emoji}")
            continue
        v.desconocidas(b, {"rol", "estilo", "fila", "emoji"}, rb)
        estilo = v.texto(b, "estilo", rb, defecto="secondary") or "secondary"
        if estilo not in ESTILOS_BOTON:
            v.error(f"{rb}.estilo", f"debe ser uno de: {', '.join(ESTILOS_BOTON)}")
        fila = v.entero(b, "fila", rb, minimo=0, maximo=4, defecto=-1) if "fila" in b else None
        emoji = v.texto(b, "emoji", rb, maximo=64)
        if emoji and (re.fullmatch(r"[\w ]+", emoji, flags=re.ASCII) or not discord.PartialEmoji.from_str(emoji).name):
            v.error(f"{rb}.emoji", "emoji no valido (usa un emoji o <:nombre:id>)")
        botones.append(Boton(v.texto(b, "rol", rb, requerido=True), estilo, fila, emoji))
    for b in botones:
        if b.fila is not None:
            por_fila[b.fila] = por_fila.get(b.fila, 0) + 1
    for fila, n in por_fila.items():
        if n > MAX_BOTONES_POR_FILA:
            v.error(ruta, f"la fila {fila} tiene {n} botones (maximo {MAX_BOTONES_POR_FILA})")
    return tuple(botones)


def _parsear_webhook(v, bruto, canales, claves_roles):
    if bruto is None:
        return {}
    w = v.tabla(bruto, "webhook")
    destinos = {}
    for nombre, cfg in w.items():
        ruta = f"webhook.{nombre}"
        if not REGEX_COMANDO.fullmatch(nombre):
            v.error(ruta, "el nombre del destino va en minusculas ([a-z0-9_])")
        d = v.tabla(cfg, ruta)
        v.desconocidas(d, {"canal", "rol"}, ruta)
        canal = v.texto(d, "canal", ruta, requerido=True)
        rol = v.texto(d, "rol", ruta, requerido=True)
        if canal and canal not in canales:
            v.error(f"{ruta}.canal", f"'{canal}' no es una key de [[canales]]")
        elif canal and canales[canal].tipo not in TIPOS_CON_MENSAJES:
            v.error(f"{ruta}.canal", f"'{canal}' es de tipo '{canales[canal].tipo}': debe ser un canal de texto o de anuncios")
        if rol and rol not in claves_roles:
            v.error(f"{ruta}.rol", f"'{rol}' no es una key de [[roles]]")
        destinos[nombre] = DestinoRelease(canal, rol)
    return destinos


def _parsear_rangos(v, bruto):
    if bruto is None:
        return Rangos()
    r = v.tabla(bruto, "rangos")
    v.desconocidas(r, {"contar_desde"}, "rangos")
    valor = r.get("contar_desde")
    if valor is None:
        return Rangos()
    try:
        if isinstance(valor, dt.datetime):
            fecha = valor if valor.tzinfo else valor.replace(tzinfo=dt.timezone.utc)
        elif isinstance(valor, dt.date):
            fecha = dt.datetime(valor.year, valor.month, valor.day, tzinfo=dt.timezone.utc)
        elif isinstance(valor, str):
            fecha = dt.datetime.strptime(valor, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        else:
            raise ValueError
    except ValueError:
        v.error("rangos.contar_desde", "debe ser una fecha AAAA-MM-DD (UTC), p. ej. \"2026-10-19\"")
        return Rangos()
    return Rangos(fecha)


def _parsear_recursos(v, bruto, roles, categorias, canales):
    """[recursos.roles|canales|categorias]: cada clave debe ser una que el bot conozca y apuntar a
    una key existente y del tipo correcto (rol, canal de texto o anuncios, categoria)."""
    if bruto is None:
        return Recursos()
    r = v.tabla(bruto, "recursos")
    v.desconocidas(r, {"roles", "canales", "categorias"}, "recursos")
    claves_roles = {x.key for x in roles}
    claves_canales = {x.key: x for x in canales}
    claves_categorias = {x.key for x in categorias}

    def clave_valida(clave, validas, ruta):
        if clave not in validas:
            v.error(f"{ruta}.{clave}", f"clave desconocida{_sugerir(clave, validas)}; el bot conoce: "
                                       + ", ".join(sorted(validas)))
            return False
        return True

    roles_mapa = {}
    tabla = v.tabla(r.get("roles", {}), "recursos.roles")
    for clave, valor in tabla.items():
        ruta = f"recursos.roles.{clave}"
        if not clave_valida(clave, RECURSOS_ROLES, "recursos.roles"):
            continue
        keys = [valor] if isinstance(valor, str) else valor
        if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
            v.error(ruta, "debe ser la key de un rol o una lista de keys")
            continue
        if len(keys) > 1 and not RECURSOS_ROLES[clave]:
            v.error(ruta, "esta clave admite un solo rol, no una lista")
        for k in keys:
            if k not in claves_roles:
                v.error(ruta, f"'{k}' no es una key de [[roles]]")
        roles_mapa[clave] = tuple(keys)

    canales_mapa = {}
    tabla = v.tabla(r.get("canales", {}), "recursos.canales")
    for clave, valor in tabla.items():
        ruta = f"recursos.canales.{clave}"
        if not clave_valida(clave, RECURSOS_CANALES, "recursos.canales"):
            continue
        canal = claves_canales.get(valor) if isinstance(valor, str) else None
        if not isinstance(valor, str):
            v.error(ruta, "debe ser la key de un canal")
        elif canal is None:
            v.error(ruta, f"'{valor}' no es una key de [[canales]]")
        elif canal.tipo not in TIPOS_CON_MENSAJES:
            v.error(ruta, f"'{valor}' es de tipo '{canal.tipo}': debe ser un canal de texto o de anuncios")
        canales_mapa[clave] = valor

    categorias_mapa = {}
    tabla = v.tabla(r.get("categorias", {}), "recursos.categorias")
    for clave, valor in tabla.items():
        ruta = f"recursos.categorias.{clave}"
        if not clave_valida(clave, RECURSOS_CATEGORIAS, "recursos.categorias"):
            continue
        if not isinstance(valor, str):
            v.error(ruta, "debe ser la key de una categoria")
        elif valor not in claves_categorias:
            v.error(ruta, f"'{valor}' no es una key de [[categorias]]")
        categorias_mapa[clave] = valor
    return Recursos(roles_mapa, canales_mapa, categorias_mapa)


def comandos_de_ayuda_inexistentes(config, bot):
    """Errores (lista de textos) por cada comando de [ayuda] que el bot no tiene."""
    errores = []
    if config.ayuda is not None:
        for s in config.ayuda.secciones:
            for e in s.entradas:
                if bot.get_command(e.comando) is None:
                    errores.append(f"ayuda.secciones '{s.titulo}': el comando '{e.comando}' no existe en el bot")
    return errores


def _estimar_largo_embed(m):
    def largo(texto):
        return len(REGEX_PLACEHOLDER.sub("x" * LARGO_MENCION, texto))

    total = largo(m.titulo) + largo(m.descripcion) + largo(m.pie)
    for nombre, valor, _inline in m.campos:
        total += largo(nombre) + largo(valor)
    return total


def parsear(datos):
    """Valida el dict del TOML y devuelve un Config; lanza ConfigInvalida si hay errores."""
    v = _Validador()
    raiz = v.tabla(datos, "(raiz)")
    v.desconocidas(raiz, {"perfil", "eventos", "comandos", "ayuda", "recursos", "bienvenida", "rangos", "webhook", "juego", "roles", "categorias", "canales", "mensajes"}, "(raiz)")

    # --- [juego] (antes que nada: los nombres de categoria y los mensajes lo usan) ---
    juego = _parsear_juego(v, raiz.get("juego"))
    nombre_juego = juego.nombre.upper() or "EL JUEGO"

    # --- [perfil] ---
    p = v.tabla(raiz.get("perfil", {}), "perfil")
    v.desconocidas(p, {"nombre", "guild_id", "owner_id", "gestores"}, "perfil")
    nombre_perfil = v.texto(p, "nombre", "perfil", defecto="Perfil")
    guild_id = v.entero(p, "guild_id", "perfil", minimo=1, requerido=True)
    owner_id = v.entero(p, "owner_id", "perfil", minimo=0)
    gestores = v.lista_texto(p, "gestores", "perfil")

    # --- roles ---
    roles = []
    for i, r in enumerate(v.lista_de_tablas(raiz.get("roles"), "roles")):
        ruta = f"roles[{i}]"
        v.desconocidas(r, {"key", "nombre", "color", "hoist", "mentionable", "permisos",
                           "existing_id", "adoptar", "permitir_admin", "autoasignable", "por_encima_del_bot"}, ruta)
        key = v.texto(r, "key", ruta, requerido=True)
        ruta = f"roles[{i}] '{key}'"
        permisos = v.permisos(r, "permisos", ruta, PERMISOS_VALIDOS)
        permitir_admin = v.booleano(r, "permitir_admin", ruta)
        if "administrator" in permisos and not permitir_admin:
            v.error(ruta, "tiene 'administrator' sin 'permitir_admin = true'")
        autoasignable = v.booleano(r, "autoasignable", ruta)
        existing_id = v.entero(r, "existing_id", ruta)
        if autoasignable:
            if existing_id:
                v.error(ruta, "un rol autoasignable no puede reutilizar un rol existente (existing_id)")
            elevados = [
                p_ for p_ in permisos
                if p_ in PERMISOS_VALIDOS and discord.Permissions(**{p_: True}).value & PERMISOS_ELEVADOS
            ]
            if elevados:
                v.error(ruta, f"un rol autoasignable no puede tener permisos elevados: {', '.join(elevados)}")
        roles.append(Rol(
            key=key, nombre=v.texto(r, "nombre", ruta, requerido=True, maximo=MAX_NOMBRE),
            color=v.color(r, "color", ruta), hoist=v.booleano(r, "hoist", ruta),
            mentionable=v.booleano(r, "mentionable", ruta), permisos=permisos,
            existing_id=existing_id, adoptar=v.booleano(r, "adoptar", ruta),
            permitir_admin=permitir_admin, autoasignable=autoasignable,
            por_encima_del_bot=v.booleano(r, "por_encima_del_bot", ruta),
        ))

    # --- categorias ---
    categorias = []
    for i, c in enumerate(v.lista_de_tablas(raiz.get("categorias"), "categorias")):
        ruta = f"categorias[{i}]"
        v.desconocidas(c, {"key", "nombre", "orden", "existing_id", "adoptar", "overrides"}, ruta)
        key = v.texto(c, "key", ruta, requerido=True)
        ruta = f"categorias[{i}] '{key}'"
        categorias.append(Categoria(
            key=key,
            nombre=v.texto(c, "nombre", ruta, requerido=True, maximo=MAX_NOMBRE).replace("{juego}", nombre_juego),
            orden=v.entero(c, "orden", ruta), existing_id=v.entero(c, "existing_id", ruta),
            adoptar=v.booleano(c, "adoptar", ruta), overrides=_parsear_overrides(v, c, ruta),
        ))

    # --- canales ---
    canales = []
    for i, c in enumerate(v.lista_de_tablas(raiz.get("canales"), "canales")):
        ruta = f"canales[{i}]"
        v.desconocidas(c, {"key", "nombre", "nombre_actual", "tipo", "categoria", "tema", "slowmode", "limite_usuarios",
                           "reemplaza", "orden", "existing_id", "adoptar", "mover", "sincronizar_permisos",
                           "overrides"}, ruta)
        key = v.texto(c, "key", ruta, requerido=True)
        ruta = f"canales[{i}] '{key}'"
        tipo = v.texto(c, "tipo", ruta, defecto="text") or "text"
        if tipo not in TIPOS_CANAL:
            v.error(f"{ruta}.tipo", f"debe ser uno de {', '.join(TIPOS_CANAL)} (vale {tipo!r})")
        if tipo == "voice" and "tema" in c:
            v.error(f"{ruta}.tema", "un canal de voz no tiene tema")
        if tipo in ("voice", "news") and "slowmode" in c:
            v.error(f"{ruta}.slowmode", "solo aplica a canales de texto y foros")
        if tipo != "voice" and "limite_usuarios" in c:
            v.error(f"{ruta}.limite_usuarios", "solo aplica a canales de voz")
        if "reemplaza" in c and tipo != "forum":
            v.error(f"{ruta}.reemplaza", "solo aplica a foros (un canal de texto no se convierte en foro)")
        if "nombre_actual" in c and not c.get("adoptar"):
            v.error(f"{ruta}.nombre_actual", "solo tiene sentido con adoptar = true (es para renombrar un canal existente)")
        if "nombre_actual" in c and tipo == "forum":
            v.error(f"{ruta}.nombre_actual", "un canal de texto no se convierte en foro: usa 'reemplaza' y se crea un foro nuevo")
        canales.append(Canal(
            key=key, nombre=v.texto(c, "nombre", ruta, requerido=True, maximo=MAX_NOMBRE),
            nombre_actual=(v.texto(c, "nombre_actual", ruta, requerido=True, maximo=MAX_NOMBRE)
                           if "nombre_actual" in c else None),
            categoria=v.texto(c, "categoria", ruta, requerido=True), tipo=tipo,
            tema=(v.texto(c, "tema", ruta, maximo=MAX_TEMA) if "tema" in c else None),
            slowmode=(v.entero(c, "slowmode", ruta, maximo=MAX_SLOWMODE) if "slowmode" in c else None),
            limite_usuarios=(v.entero(c, "limite_usuarios", ruta, maximo=MAX_LIMITE_VOZ)
                             if "limite_usuarios" in c else None),
            reemplaza=(v.texto(c, "reemplaza", ruta, requerido=True, maximo=MAX_NOMBRE)
                       if "reemplaza" in c else None),
            orden=v.entero(c, "orden", ruta), existing_id=v.entero(c, "existing_id", ruta),
            adoptar=v.booleano(c, "adoptar", ruta), mover=v.booleano(c, "mover", ruta),
            sincronizar_permisos=v.booleano(c, "sincronizar_permisos", ruta),
            overrides=_parsear_overrides(v, c, ruta),
        ))

    # --- mensajes ---
    def sub_juego(texto):
        """Sustituye {juego.nombre}, {juego.titulo}, {juego.enlace_juego} y {juego.enlace_grupo}."""
        return (texto.replace("{juego.nombre}", juego.nombre).replace("{juego.titulo}", juego.titulo())
                .replace("{juego.enlace_juego}", juego.enlace_juego).replace("{juego.enlace_grupo}", juego.enlace_grupo))

    mensajes = []
    for i, m in enumerate(v.lista_de_tablas(raiz.get("mensajes"), "mensajes")):
        ruta = f"mensajes[{i}]"
        v.desconocidas(m, {"key", "canal", "publicar", "titulo", "descripcion", "color", "campos",
                           "pie", "botones_roles"}, ruta)
        key = v.texto(m, "key", ruta, requerido=True)
        ruta = f"mensajes[{i}] '{key}'"
        campos = []
        brutos = m.get("campos", [])
        if not isinstance(brutos, list) or not all(isinstance(x, dict) for x in brutos):
            v.error(f"{ruta}.campos", "debe ser una lista de tablas")
            brutos = []
        if len(brutos) > MAX_EMBED_CAMPOS:
            v.error(f"{ruta}.campos", f"tiene {len(brutos)} campos (maximo {MAX_EMBED_CAMPOS})")
        for j, campo in enumerate(brutos):
            rc = f"{ruta}.campos[{j}]"
            v.desconocidas(campo, {"nombre", "valor", "inline", "solo_si"}, rc)
            solo_si = v.texto(campo, "solo_si", rc)
            if solo_si and solo_si not in CAMPOS_JUEGO:
                v.error(f"{rc}.solo_si", f"debe ser uno de: {', '.join(sorted(CAMPOS_JUEGO))}")
            elif solo_si and not getattr(juego, solo_si.split(".", 1)[1]):
                continue                          # el dato del juego no esta configurado: el campo se omite
            campos.append((
                sub_juego(v.texto(campo, "nombre", rc, requerido=True, maximo=MAX_CAMPO_NOMBRE)),
                sub_juego(v.texto(campo, "valor", rc, requerido=True, maximo=MAX_CAMPO_VALOR)).strip(),
                v.booleano(campo, "inline", rc),
            ))
        botones = _parsear_botones(v, m.get("botones_roles"), f"{ruta}.botones_roles")
        mensaje = Mensaje(
            key=key, canal=v.texto(m, "canal", ruta, requerido=True),
            titulo=sub_juego(v.texto(m, "titulo", ruta, maximo=MAX_EMBED_TITULO)),
            descripcion=sub_juego(v.texto(m, "descripcion", ruta, maximo=MAX_EMBED_DESCRIPCION)),
            color=v.color(m, "color", ruta, defecto=0x5865F2), campos=tuple(campos),
            pie=sub_juego(v.texto(m, "pie", ruta, maximo=MAX_EMBED_PIE)),
            publicar=v.booleano(m, "publicar", ruta, defecto=True),
            botones_roles=tuple(b.rol for b in botones), botones=botones,
        )
        if not (mensaje.titulo or mensaje.descripcion or mensaje.campos):
            v.error(ruta, "el mensaje esta vacio (pon titulo, descripcion o campos)")
        if len(mensaje.botones_roles) > MAX_BOTONES:
            v.error(f"{ruta}.botones_roles", f"tiene {len(mensaje.botones_roles)} botones (maximo {MAX_BOTONES})")
        total = _estimar_largo_embed(mensaje)
        if total > MAX_EMBED_TOTAL:
            v.error(ruta, f"el embed suma {total} caracteres (maximo {MAX_EMBED_TOTAL})")
        mensajes.append(mensaje)

    # --- [eventos] ---
    e = v.tabla(raiz.get("eventos", {}), "eventos")
    v.desconocidas(e, set(EVENTOS_BOOL) | {"rol_al_entrar", "bienvenida", "canal_logs"}, "eventos")
    eventos = Eventos(
        **{nombre: v.booleano(e, nombre, "eventos") for nombre in EVENTOS_BOOL},
        rol_al_entrar=v.texto(e, "rol_al_entrar", "eventos"),
        bienvenida=v.texto(e, "bienvenida", "eventos"),
        canal_logs=v.texto(e, "canal_logs", "eventos"),
    )

    # --- [comandos] ---
    cm = v.tabla(raiz.get("comandos", {}), "comandos")
    v.desconocidas(cm, {"bloquear"}, "comandos")
    bloqueados = frozenset(v.lista_texto(cm, "bloquear", "comandos"))
    if "pss" in bloqueados:
        v.error("comandos.bloquear", "no se puede bloquear 'pss' (es el propio perfil)")

    # --- [ayuda] ---
    ayuda = _parsear_ayuda(v, raiz.get("ayuda"), bloqueados,
                           {c.key for c in canales}, {r.key for r in roles})

    # --- [bienvenida] ---
    bienvenida = _parsear_bienvenida(v, raiz.get("bienvenida"), {c.key for c in canales}, {r.key for r in roles})

    # --- [rangos] ---
    rangos = _parsear_rangos(v, raiz.get("rangos"))

    # --- [webhook.<destino>] ---
    webhook = _parsear_webhook(v, raiz.get("webhook"), {c.key: c for c in canales}, {r.key for r in roles})

    # --- [recursos] ---
    recursos = _parsear_recursos(v, raiz.get("recursos"), roles, categorias, canales)

    # --- claves unicas globales ---
    indice = {}
    vistas = {}
    for tipo, elementos in (("rol", roles), ("categoria", categorias), ("canal", canales), ("mensaje", mensajes)):
        for el in elementos:
            if not REGEX_KEY.fullmatch(el.key or ""):
                v.error(f"{tipo} '{el.key}'", "la key debe ser [a-z0-9_] de 1 a 64 caracteres")
            if el.key in vistas:
                v.error(f"{tipo} '{el.key}'", f"key duplicada (ya la usa un/a {vistas[el.key]})")
            else:
                vistas[el.key] = tipo
                indice[(tipo, el.key)] = el
    ids_existentes = {}
    for tipo, elementos in (("rol", roles), ("categoria", categorias), ("canal", canales)):
        for el in elementos:
            if el.existing_id:
                clave = (tipo if tipo == "rol" else "canal", el.existing_id)
                if clave in ids_existentes:
                    v.error(f"{tipo} '{el.key}'", f"existing_id {el.existing_id} repetido en '{ids_existentes[clave]}'")
                ids_existentes[clave] = el.key

    # --- referencias ---
    claves_roles = {r.key for r in roles}
    claves_canales_texto = {c.key for c in canales if c.tipo in TIPOS_CON_MENSAJES}
    claves_categorias = {c.key for c in categorias}

    def referencia_rol(valor, ruta):
        if valor and valor not in claves_roles:
            v.error(ruta, f"referencia al rol '{valor}', que no existe en [[roles]]")

    def referencia_canal(valor, ruta):
        if valor and valor not in claves_canales_texto:
            v.error(ruta, f"referencia al canal de texto '{valor}', que no existe en [[canales]]")

    for g in gestores:
        referencia_rol(g, "perfil.gestores")
    referencia_rol(eventos.rol_al_entrar, "eventos.rol_al_entrar")
    referencia_canal(eventos.bienvenida, "eventos.bienvenida")
    referencia_canal(eventos.canal_logs, "eventos.canal_logs")
    for el in (*categorias, *canales):
        for o in el.overrides:
            if o.objetivo != EVERYONE and o.objetivo not in claves_roles:
                v.error(f"{type(el).__name__.lower()} '{el.key}'.overrides",
                        f"objetivo '{o.objetivo}' no es '@everyone' ni un rol de [[roles]]")
    por_categoria = {}
    for c in canales:
        if c.categoria not in claves_categorias:
            v.error(f"canal '{c.key}'.categoria", f"la categoria '{c.categoria}' no existe en [[categorias]]")
        por_categoria[c.categoria] = por_categoria.get(c.categoria, 0) + 1
        if c.sincronizar_permisos and c.overrides:
            v.error(f"canal '{c.key}'", "sincronizar_permisos y overrides propios se contradicen")
    for m in mensajes:
        referencia_canal(m.canal, f"mensaje '{m.key}'.canal")
        for rk in m.botones_roles:
            rol = indice.get(("rol", rk))
            if rol is None:
                v.error(f"mensaje '{m.key}'.botones_roles", f"el rol '{rk}' no existe en [[roles]]")
            elif not rol.autoasignable:
                v.error(f"mensaje '{m.key}'.botones_roles", f"el rol '{rk}' no es autoasignable")
            elif len(rol.nombre) > MAX_ETIQUETA_BOTON:
                v.error(f"mensaje '{m.key}'.botones_roles", f"el nombre del rol '{rk}' no cabe en un boton")
        texto_total = " ".join([m.titulo, m.descripcion, m.pie, *[f"{n} {val}" for n, val, _ in m.campos]])
        for tipo_ref, key_ref in REGEX_PLACEHOLDER.findall(texto_total):
            if tipo_ref == "canal" and key_ref not in {c.key for c in canales}:
                v.error(f"mensaje '{m.key}'", f"{{canal:{key_ref}}} no existe en [[canales]]")
            if tipo_ref == "rol" and key_ref not in claves_roles:
                v.error(f"mensaje '{m.key}'", f"{{rol:{key_ref}}} no existe en [[roles]]")

    # --- limites globales ---
    if len(roles) > MAX_ROLES:
        v.error("roles", f"hay {len(roles)} roles (maximo {MAX_ROLES} por servidor)")
    if len(canales) + len(categorias) > MAX_CANALES:
        v.error("canales", f"hay {len(canales) + len(categorias)} canales y categorias (maximo {MAX_CANALES})")
    for cat, total in por_categoria.items():
        if total > MAX_POR_CATEGORIA:
            v.error(f"categoria '{cat}'", f"tiene {total} canales (maximo {MAX_POR_CATEGORIA})")

    if v.errores:
        raise ConfigInvalida(v.errores)
    return Config(
        nombre=nombre_perfil, guild_id=guild_id, owner_id=owner_id, gestores=gestores,
        eventos=eventos, comandos_bloqueados=bloqueados,
        roles=tuple(roles), categorias=tuple(categorias), canales=tuple(canales),
        mensajes=tuple(mensajes), _indice=indice, ayuda=ayuda, recursos=recursos,
        bienvenida=bienvenida, rangos=rangos, webhook=webhook, juego=juego,
    )


def cargar(ruta):
    """Lee y valida el TOML en `ruta` (str o Path). Lanza ConfigInvalida si hay problemas."""
    ruta = Path(ruta)
    try:
        with ruta.open("rb") as f:
            datos = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigInvalida([f"no existe el archivo {ruta}"]) from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigInvalida([f"{ruta.name} no es un TOML valido: {e}"]) from None
    return parsear(datos)
