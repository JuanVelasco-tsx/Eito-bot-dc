"""Calculo del plan (dry-run) del perfil PSS: compara el TOML con una "foto" del servidor.

Aqui no hay llamadas a Discord: `calcular_plan` recibe objetos simples (Snapshot,
Registro...) y devuelve un Plan. El cog construye el Snapshot desde el guild real y
las pruebas lo construyen a mano, asi que todo el calculo se prueba sin conectar.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

import discord

from profiles.pss_config import (
    EVERYONE, MAX_CANALES, MAX_POR_CATEGORIA, MAX_ROLES, REGEX_PLACEHOLDER,
)

# Permisos que el bot necesita para aplicar el perfil (los pedidos en el encargo).
PERMISOS_BOT_REQUERIDOS = (
    "manage_roles", "manage_channels", "manage_messages",
    "embed_links", "read_message_history", "send_messages",
)
# Lo que se le da al bot en un override propio cuando @everyone pierde ver/escribir:
# sin esto, al quitarle administrator no veria ni podria escribir en ese canal.
PERMISOS_OVERRIDE_BOT = ("view_channel", "send_messages", "embed_links",
                         "read_message_history", "attach_files")

ORDEN_DESPLIEGUE = (
    "**Orden de despliegue**\n"
    "0) Activa Comunidad (anuncios y foros la exigen; sin ella salen «bloqueado»).\n"
    "a) Sube el rol del bot por encima de los roles que va a gestionar.\n"
    "b) `!pss aplicar`: basta el entero mínimo de permisos `1099780320342` (no hace falta ser administrador).\n"
    "c) Solo si el plan marca «bloqueado: el bot no tiene X» (p. ej. al crear un rol con permisos que el bot "
    "no tiene), dale ese permiso un momento y repite; después vuelve al entero mínimo.\n"
    "d) `!pss plan` otra vez: debe dar todo en «omitir»."
)

MENSAJE_COINCIDE = "✅ El servidor coincide con la configuración"


def bits(nombres):
    """Valor entero de una lista de nombres de permisos de discord.Permissions."""
    return discord.Permissions(**{n: True for n in nombres}).value


def nombres_de_bits(valor):
    """Nombres de los permisos activos en `valor`."""
    return [n for n, activo in discord.Permissions(valor) if activo]


def normalizar(texto):
    """Nombre comparable: sin acentos, emojis ni separadores ("📂 Proyectos" -> "proyectos")."""
    sin_marcas = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "-", sin_marcas.casefold()).strip("-")


def nombre_igual(a, b):
    """Compara nombres ignorando el selector de emoji U+FE0F, que Discord a veces quita o añade."""
    return a.replace("️", "") == b.replace("️", "")


def nombre_en_discord(texto, tipo):
    """Como queda un nombre al crearlo: texto, anuncios y foros van en minusculas con guiones."""
    return re.sub(r"\s+", "-", texto.strip().lower()) if tipo != "voice" else texto


# --- Foto del servidor y estado guardado -------------------------------------------
@dataclass
class SRol:
    id: int
    name: str
    position: int = 1
    permissions: int = 0
    colour: int = 0
    hoist: bool = False
    mentionable: bool = False
    managed: bool = False


@dataclass
class SCanal:
    id: int
    name: str
    tipo: str                    # categoria | text | news | forum | voice | stage | otro
    category_id: int | None = None
    topic: str | None = None
    slowmode: int = 0
    user_limit: int = 0
    position: int = 0
    overwrites: dict = field(default_factory=dict)   # id del objetivo -> (allow, deny)


@dataclass
class SMiembro:
    id: int
    roles: frozenset = frozenset()
    bot: bool = False


@dataclass
class Snapshot:
    guild_id: int
    owner_id: int
    bot_id: int
    bot_permisos: int
    bot_admin: bool
    bot_top: tuple                # (position, id) del rol mas alto del bot
    roles: list
    canales: list
    miembros: list = field(default_factory=list)
    features: frozenset = frozenset()    # guild.features (p. ej. "COMMUNITY")

    def rol_bajo_el_bot(self, rol):
        """Misma regla que Role.__lt__ de discord.py: a igual posicion manda el ID mas bajo."""
        return (rol.position, -rol.id) < (self.bot_top[0], -self.bot_top[1])


@dataclass
class Registro:
    tipo: str                     # rol | categoria | canal | mensaje
    discord_id: int
    canal_id: int | None = None
    hash: str | None = None
    creado: bool = False


# --- Resultado -----------------------------------------------------------------------
@dataclass
class Accion:
    tipo: str                     # rol | categoria | canal | mensaje | orden
    key: str
    op: str                       # crear | actualizar | vincular | omitir | bloqueado
    detalle: str = ""
    destino_id: int | None = None
    via: str = ""
    cambios: dict = field(default_factory=dict)
    razon: str = ""


@dataclass
class Plan:
    acciones: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)
    manuales: list = field(default_factory=list)  # cosas que el bot NO hace y debes hacer a mano
    ids: dict = field(default_factory=dict)       # key -> id ya existente en Discord

    def con_op(self, *ops):
        return [a for a in self.acciones if a.op in ops]

    def pendientes(self):
        return self.con_op("crear", "actualizar", "vincular")

    def bloqueadas(self):
        return self.con_op("bloqueado")

    def coincide(self):
        """Todo en «omitir»: no hay nada que crear, actualizar, vincular ni desbloquear."""
        return bool(self.acciones) and not self.con_op("crear", "actualizar", "vincular", "bloqueado")

    def resumen(self):
        cuenta = {op: 0 for op in ("crear", "actualizar", "vincular", "omitir", "bloqueado")}
        for a in self.acciones:
            cuenta[a.op] += 1
        return cuenta

    def huella(self):
        """Identifica lo que haria el plan: si cambia entre `aplicar` y el boton, se aborta."""
        base = [(a.tipo, a.key, a.op, a.destino_id, a.cambios) for a in self.pendientes()]
        crudo = json.dumps(base, sort_keys=True, default=str)
        return hashlib.sha256(crudo.encode()).hexdigest()[:16]


# --- Mensajes --------------------------------------------------------------------------
class PendienteDeId(Exception):
    """El mensaje menciona un recurso que todavia no existe."""


def referencias(mensaje):
    """Keys (canal/rol) que menciona la plantilla del mensaje."""
    texto = " ".join([mensaje.titulo, mensaje.descripcion, mensaje.pie,
                      *[f"{n} {v}" for n, v, _ in mensaje.campos]])
    return {key for _tipo, key in REGEX_PLACEHOLDER.findall(texto)}


def renderizar(mensaje, ids):
    """Embed con las menciones ya resueltas a IDs (esto es lo que se hashea).

    Lanza PendienteDeId si menciona algo que aun no tiene ID."""
    def sustituir(texto):
        def una(m):
            tipo, key = m.group(1), m.group(2)
            if key not in ids:
                raise PendienteDeId(key)
            return f"<#{ids[key]}>" if tipo == "canal" else f"<@&{ids[key]}>"
        return REGEX_PLACEHOLDER.sub(una, texto)

    embed = {"color": mensaje.color}
    if mensaje.titulo:
        embed["title"] = sustituir(mensaje.titulo)
    if mensaje.descripcion:
        embed["description"] = sustituir(mensaje.descripcion)
    if mensaje.campos:
        embed["fields"] = [
            {"name": sustituir(n), "value": sustituir(v), "inline": i} for n, v, i in mensaje.campos
        ]
    if mensaje.pie:
        embed["footer"] = {"text": sustituir(mensaje.pie)}
    return {"embed": embed, "botones": list(mensaje.botones_roles)}


def hash_contenido(renderizado):
    crudo = json.dumps(renderizado, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(crudo.encode()).hexdigest()


# --- Overrides ---------------------------------------------------------------------------
def overrides_efectivos(categoria, canal=None):
    """Overrides de la categoria con los del canal encima (el del canal sustituye al del mismo objetivo)."""
    mezcla = {o.objetivo: o for o in categoria.overrides}
    if canal is not None and not canal.sincronizar_permisos:
        mezcla.update({o.objetivo: o for o in canal.overrides})
    return tuple(mezcla.values())


def overwrites_deseados(overrides, ids_roles, guild_id, bot_id):
    """-> ({id_objetivo: (allow, deny)}, pendiente). `pendiente` es True si algun rol aun no existe."""
    resultado, pendiente = {}, False
    for o in overrides:
        objetivo = guild_id if o.objetivo == EVERYONE else ids_roles.get(o.objetivo)
        if objetivo is None:
            pendiente = True
            continue
        resultado[objetivo] = (bits(o.permitir), bits(o.denegar))
    restringe = any(
        o.objetivo == EVERYONE and {"view_channel", "send_messages"} & set(o.denegar) for o in overrides
    )
    if restringe:
        resultado[bot_id] = (bits(PERMISOS_OVERRIDE_BOT), 0)
    return resultado, pendiente


def _faltan(snap, valor):
    """Permisos de `valor` que el bot no tiene (nada si es administrador)."""
    if snap.bot_admin:
        return []
    return nombres_de_bits(valor & ~snap.bot_permisos)


def _sin_permiso(snap, *requeridos):
    return _faltan(snap, bits(requeridos))


def _unir(*listas):
    """Concatena listas sin repetir elementos (conserva el orden)."""
    return list(dict.fromkeys(x for lista in listas for x in lista))


def _bloqueo_por_permisos(faltan):
    return f"el bot no tiene {', '.join(faltan)}"


# --- Orden de categorias y canales --------------------------------------------------------
def bucket_de(tipo):
    """Los canales se ordenan por separado: categorias, texto/anuncios/foros y voz."""
    if tipo == "categoria":
        return "categoria"
    return "voz" if tipo in ("voice", "stage") else "texto"


def calcular_orden_payload(canales, categorias_deseadas, canales_deseados):
    """Posiciones que dejan categorias y canales en el orden del TOML.

    `canales`: [(id, tipo, category_id, position)] de TODO el servidor, con datos frescos.
    `categorias_deseadas`: ids de categorias en el orden que deben quedar (arriba).
    `canales_deseados`: {id_categoria: [ids de canal en el orden del TOML]}.
    Lo que no esta en el TOML conserva su orden relativo y queda DESPUES (abajo).
    Devuelve [{"id": ..., "position": ...}] listo para el PATCH /guilds/{id}/channels."""
    ordenados = sorted(canales, key=lambda c: (c[3], c[0]))
    por_id = {c[0]: c for c in ordenados}
    payload = []
    for bucket in ("categoria", "texto", "voz"):
        del_bucket = [c[0] for c in ordenados if bucket_de(c[1]) == bucket]
        if bucket == "categoria":
            primeros = [i for i in categorias_deseadas if i in por_id and bucket_de(por_id[i][1]) == bucket]
        else:
            primeros = [i for cat in categorias_deseadas for i in canales_deseados.get(cat, [])
                        if i in por_id and bucket_de(por_id[i][1]) == bucket]
        vistos = set(primeros)
        final = primeros + [i for i in del_bucket if i not in vistos]
        payload.extend({"id": i, "position": pos} for pos, i in enumerate(final))
    return payload


def orden_ya_correcto(canales, categorias_deseadas, canales_deseados):
    """True si, entre lo que el TOML menciona, el orden actual ya es el deseado.

    Compara solo posiciones relativas (entre categorias, y entre canales de una categoria
    del mismo tipo de ordenacion): no le importa lo que el TOML no menciona."""
    por_id = {c[0]: c for c in canales}

    def clave(i):
        return (por_id[i][3], i)

    presentes = [i for i in categorias_deseadas if i in por_id]
    if [clave(i) for i in presentes] != sorted(clave(i) for i in presentes):
        return False
    for cat, ids in canales_deseados.items():
        for bucket in ("texto", "voz"):
            grupo = [i for i in ids if i in por_id and por_id[i][2] == cat and bucket_de(por_id[i][1]) == bucket]
            if [clave(i) for i in grupo] != sorted(clave(i) for i in grupo):
                return False
    return True


def tiene_comunidad(snap):
    return "COMMUNITY" in snap.features


MOTIVO_COMUNIDAD = "activa Comunidad (Ajustes del servidor → Habilitar la comunidad)"
MOTIVO_NO_ENCONTRADO = "no encontrado (adoptar): no existe ni por ID ni por nombre; quita adoptar para crearlo"


# --- Resolucion ----------------------------------------------------------------------------
def _resolver(tipo, key, nombre, existing_id, candidatos, estado, reclamados, nombrables=None, alias=()):
    """-> (objeto | None, via, ambiguos). Orden: ID guardado, existing_id, nombre normalizado.

    `reclamados`: IDs que ya son de otro recurso (no se enlazan por nombre).
    `nombrables`: subconjunto de `candidatos` que puede enlazarse por nombre.
    `alias`: otros nombres con los que puede llamarse hoy (para renombrar un recurso existente)."""
    reg = estado.get(key)
    if reg is not None and reg.tipo == tipo and reg.discord_id in candidatos:
        return candidatos[reg.discord_id], "guardado", []
    if existing_id and existing_id in candidatos:
        return candidatos[existing_id], "existing_id", []
    objetivos = {normalizar(n) for n in (nombre, *alias)} - {""}
    if objetivos:
        coincidentes = [
            c for c in (candidatos if nombrables is None else nombrables).values()
            if c.id not in reclamados and normalizar(c.name) in objetivos
        ]
        if len(coincidentes) == 1:
            return coincidentes[0], "nombre", []
        if len(coincidentes) > 1:
            return None, "", [c.id for c in coincidentes]
    return None, "", []


def calcular_plan(config, snap, estado, mensajes_estado):
    """Compara `config` con el servidor `snap` y lo guardado en `estado` ({key: Registro}).

    `mensajes_estado` = {key: "existe" | "falta" | "ajeno" | "error"} para los mensajes ya guardados.
    No modifica nada: devuelve el Plan con una Accion por recurso."""
    plan = Plan()
    ac = plan.acciones
    roles_por_id = {r.id: r for r in snap.roles if r.id != snap.guild_id}
    cats_por_id = {c.id: c for c in snap.canales if c.tipo == "categoria"}
    candidatos_canal = {
        "text": {c.id: c for c in snap.canales if c.tipo == "text"},
        # un canal de texto puede convertirse en anuncios; un anuncio ya lo es
        "news": {c.id: c for c in snap.canales if c.tipo in ("text", "news")},
        # un canal de texto NO se convierte en foro: solo cuentan los foros que ya existan
        "forum": {c.id: c for c in snap.canales if c.tipo == "forum"},
        "voice": {c.id: c for c in snap.canales if c.tipo == "voice"},
    }
    reclamados = set()
    for k, reg in estado.items():
        reclamados.add(reg.discord_id)
    for el in (*config.roles, *config.categorias, *config.canales):
        if el.existing_id:
            reclamados.add(el.existing_id)

    # Los roles administrados (el del propio bot, boosters) no se enlazan por nombre.
    roles_nombrables = {i: r for i, r in roles_por_id.items() if not r.managed}
    res = {}   # key -> (objeto, via, ambiguos)

    def resolver(tipo, el, candidatos, nombrables=None):
        propios = {el.existing_id} if el.existing_id else set()
        if el.key in estado:
            propios.add(estado[el.key].discord_id)
        alias = (el.nombre_actual,) if getattr(el, "nombre_actual", None) else ()
        obj, via, amb = _resolver(tipo, el.key, el.nombre, el.existing_id, candidatos,
                                  estado, reclamados - propios, nombrables, alias)
        if obj is not None:
            reclamados.add(obj.id)
        res[el.key] = (obj, via, amb)

    for r in config.roles:
        resolver("rol", r, roles_por_id, roles_nombrables)
    for c in config.categorias:
        resolver("categoria", c, cats_por_id)
    for c in config.canales:
        resolver("canal", c, candidatos_canal[c.tipo])

    ids_roles = {r.key: res[r.key][0].id for r in config.roles if res[r.key][0] is not None}
    ids_cats = {c.key: res[c.key][0].id for c in config.categorias if res[c.key][0] is not None}
    ids_canales = {c.key: res[c.key][0].id for c in config.canales if res[c.key][0] is not None}
    plan.ids = {**ids_roles, **ids_cats, **ids_canales}
    bloqueadas = set()   # keys cuya accion quedo bloqueada (los dependientes se bloquean tambien)

    def hay_registro(key, obj):
        reg = estado.get(key)
        return reg is not None and reg.discord_id == obj.id

    def adoptable_perdido(el):
        """adoptar = true significa «ya existe, usalo»: si no aparece (ni por ID ni por nombre) NO se
        crea uno nuevo. Solo se recrea si lo creo el bot antes (y alguien lo borro a mano)."""
        reg = estado.get(el.key)
        return el.adoptar and not (reg is not None and reg.creado)

    def anotar(tipo, key, op, detalle="", obj=None, via="", cambios=None, razon=""):
        accion = Accion(tipo, key, op, detalle, obj.id if obj is not None else None,
                        via, cambios or {}, razon)
        ac.append(accion)
        if op == "bloqueado":
            bloqueadas.add(key)
        return accion

    # ---- roles ----------------------------------------------------------------------------
    n_roles = len(snap.roles)
    for r in config.roles:
        obj, via, amb = res[r.key]
        deseado = bits(r.permisos)
        if amb:
            anotar("rol", r.key, "bloqueado", r.nombre,
                   razon=f"el nombre coincide con varios roles ({', '.join(map(str, amb))}); fija existing_id")
            continue
        if obj is None:
            faltan = _unir(_sin_permiso(snap, "manage_roles"), _faltan(snap, deseado))
            if adoptable_perdido(r):
                anotar("rol", r.key, "bloqueado", r.nombre, razon=MOTIVO_NO_ENCONTRADO)
            elif faltan:
                anotar("rol", r.key, "bloqueado", r.nombre, razon=_bloqueo_por_permisos(faltan))
            elif n_roles + 1 > MAX_ROLES:
                anotar("rol", r.key, "bloqueado", r.nombre, razon=f"límite de {MAX_ROLES} roles")
            else:
                n_roles += 1
                anotar("rol", r.key, "crear", r.nombre)
            continue
        reg = estado.get(r.key)
        cambios = {}
        if (reg is not None and reg.creado and reg.discord_id == obj.id) or r.adoptar:
            for campo, actual, nuevo in (
                ("nombre", obj.name, r.nombre), ("color", obj.colour, r.color),
                ("hoist", obj.hoist, r.hoist), ("mentionable", obj.mentionable, r.mentionable),
                ("permisos", obj.permissions, deseado),
            ):
                distinto = not nombre_igual(actual, nuevo) if campo == "nombre" else actual != nuevo
                if distinto:
                    cambios[campo] = nuevo
        if cambios:
            faltan = _sin_permiso(snap, "manage_roles")
            if "permisos" in cambios:
                faltan = _unir(faltan, _faltan(snap, obj.permissions ^ deseado))
            if obj.managed:
                anotar("rol", r.key, "bloqueado", r.nombre, obj, via, razon="es un rol administrado por una integración")
            elif not snap.rol_bajo_el_bot(obj):
                anotar("rol", r.key, "bloqueado", r.nombre, obj, via,
                       razon="el rol del bot no está por encima de este rol (jerarquía)")
            elif faltan:
                anotar("rol", r.key, "bloqueado", r.nombre, obj, via, razon=_bloqueo_por_permisos(faltan))
            else:
                anotar("rol", r.key, "actualizar", f"{r.nombre}: {', '.join(cambios)}", obj, via, cambios)
        elif not hay_registro(r.key, obj):
            anotar("rol", r.key, "vincular", r.nombre, obj, via)
        else:
            anotar("rol", r.key, "omitir", r.nombre, obj, via)

    # ---- categorias --------------------------------------------------------------------------
    n_canales = len(snap.canales)
    for c in sorted(config.categorias, key=lambda x: x.orden):
        obj, via, amb = res[c.key]
        deseados, pendiente = overwrites_deseados(c.overrides, ids_roles, snap.guild_id, snap.bot_id)
        if amb:
            anotar("categoria", c.key, "bloqueado", c.nombre,
                   razon=f"el nombre coincide con varias categorías ({', '.join(map(str, amb))}); fija existing_id")
            continue
        if obj is None:
            faltan = _unir(_sin_permiso(snap, "manage_channels", *(("manage_roles",) if c.overrides else ())),
                           _faltan(snap, _bits_allow(deseados)))
            if adoptable_perdido(c):
                anotar("categoria", c.key, "bloqueado", c.nombre, razon=MOTIVO_NO_ENCONTRADO)
            elif faltan:
                anotar("categoria", c.key, "bloqueado", c.nombre, razon=_bloqueo_por_permisos(faltan))
            elif n_canales + 1 > MAX_CANALES:
                anotar("categoria", c.key, "bloqueado", c.nombre, razon=f"límite de {MAX_CANALES} canales")
            else:
                n_canales += 1
                anotar("categoria", c.key, "crear", c.nombre)
            continue
        reg = estado.get(c.key)
        cambios = {}
        if (reg is not None and reg.creado and reg.discord_id == obj.id) or c.adoptar:
            if not nombre_igual(obj.name, c.nombre):
                cambios["nombre"] = c.nombre
            if pendiente or _difieren(obj.overwrites, deseados):
                cambios["overwrites"] = True
        if cambios:
            faltan = _sin_permiso(snap, "manage_channels", *(("manage_roles",) if "overwrites" in cambios else ()))
            if faltan:
                anotar("categoria", c.key, "bloqueado", c.nombre, obj, via, razon=_bloqueo_por_permisos(faltan))
            else:
                anotar("categoria", c.key, "actualizar", f"{c.nombre}: {', '.join(cambios)}", obj, via, cambios)
        elif not hay_registro(c.key, obj):
            anotar("categoria", c.key, "vincular", c.nombre, obj, via)
        else:
            anotar("categoria", c.key, "omitir", c.nombre, obj, via)

    # ---- canales ---------------------------------------------------------------------------------
    orden_cat = {c.key: i for i, c in enumerate(sorted(config.categorias, key=lambda x: x.orden))}
    ocupacion = {}
    for c in snap.canales:
        if c.category_id is not None:
            ocupacion[c.category_id] = ocupacion.get(c.category_id, 0) + 1
    nuevos_por_cat = {}

    def cabe(destino):
        previos = ocupacion.get(destino, 0) if isinstance(destino, int) else 0
        return previos + nuevos_por_cat.get(destino, 0) + 1 <= MAX_POR_CATEGORIA

    perdedores = {}   # key del canal -> miembros que dejan de verlo

    for c in sorted(config.canales, key=lambda x: (orden_cat.get(x.categoria, 0), x.orden)):
        obj, via, amb = res[c.key]
        cat = config.categoria(c.categoria)
        cat_id = ids_cats.get(c.categoria)
        if amb:
            anotar("canal", c.key, "bloqueado", c.nombre,
                   razon=f"el nombre coincide con varios canales ({', '.join(map(str, amb))}); fija existing_id")
            continue
        if c.categoria in bloqueadas:
            anotar("canal", c.key, "bloqueado", c.nombre, razon=f"depende de la categoría '{c.categoria}', que está bloqueada")
            continue
        efectivos = overrides_efectivos(cat, c)
        deseados, pendiente = overwrites_deseados(efectivos, ids_roles, snap.guild_id, snap.bot_id)

        destino_clave = cat_id if cat_id is not None else c.categoria
        necesita_comunidad = c.tipo in ("news", "forum")
        if obj is None:
            faltan = _unir(_sin_permiso(snap, "manage_channels", "manage_roles"),
                           _faltan(snap, _bits_allow(deseados)))
            if adoptable_perdido(c):
                anotar("canal", c.key, "bloqueado", c.nombre, razon=MOTIVO_NO_ENCONTRADO)
            elif necesita_comunidad and not tiene_comunidad(snap):
                anotar("canal", c.key, "bloqueado", c.nombre, razon=MOTIVO_COMUNIDAD)
            elif faltan:
                anotar("canal", c.key, "bloqueado", c.nombre, razon=_bloqueo_por_permisos(faltan))
            elif n_canales + 1 > MAX_CANALES:
                anotar("canal", c.key, "bloqueado", c.nombre, razon=f"límite de {MAX_CANALES} canales")
            elif not cabe(destino_clave):
                anotar("canal", c.key, "bloqueado", c.nombre, razon=f"la categoría '{c.categoria}' tendría más de {MAX_POR_CATEGORIA} canales")
            else:
                n_canales += 1
                nuevos_por_cat[destino_clave] = nuevos_por_cat.get(destino_clave, 0) + 1
                anotar("canal", c.key, "crear", f"{c.nombre} ({_TIPOS_TEXTO[c.tipo]}) → {cat.nombre}")
            continue

        reg = estado.get(c.key)
        propio = reg is not None and reg.creado and reg.discord_id == obj.id
        cambios = {}
        if propio or c.adoptar:
            if not nombre_igual(obj.name, nombre_en_discord(c.nombre, c.tipo)):
                cambios["nombre"] = c.nombre
            if c.tema is not None and (obj.topic or "") != c.tema:
                cambios["tema"] = c.tema
            if c.slowmode is not None and obj.slowmode != c.slowmode:
                cambios["slowmode"] = c.slowmode
            if c.limite_usuarios is not None and obj.user_limit != c.limite_usuarios:
                cambios["limite_usuarios"] = c.limite_usuarios
            if c.overrides and (pendiente or _difieren(obj.overwrites, deseados)):
                cambios["overwrites"] = True
            if c.tipo == "news" and obj.tipo == "text":
                cambios["tipo"] = "news"
        mueve = c.mover and (cat_id is None or obj.category_id != cat_id)
        if mueve:
            cambios["mover"] = c.categoria
        if c.sincronizar_permisos:
            categoria_real = cats_por_id.get(cat_id)
            if mueve:
                cambios["sincronizar"] = True
            elif (categoria_real is not None and obj.category_id == cat_id
                  and obj.overwrites != categoria_real.overwrites):
                cambios["sincronizar"] = True
        if cambios:
            necesita_roles = {"overwrites", "sincronizar"} & set(cambios)
            faltan = _sin_permiso(snap, "manage_channels", *(("manage_roles",) if necesita_roles else ()))
            if "tipo" in cambios and not tiene_comunidad(snap):
                anotar("canal", c.key, "bloqueado", c.nombre, obj, via, razon=MOTIVO_COMUNIDAD)
            elif mueve and not cabe(destino_clave):
                anotar("canal", c.key, "bloqueado", c.nombre, obj, via,
                       razon=f"la categoría '{c.categoria}' tendría más de {MAX_POR_CATEGORIA} canales")
            elif faltan:
                anotar("canal", c.key, "bloqueado", c.nombre, obj, via, razon=_bloqueo_por_permisos(faltan))
            else:
                if mueve:
                    nuevos_por_cat[destino_clave] = nuevos_por_cat.get(destino_clave, 0) + 1
                partes = [_texto_cambio(k, v, cat) for k, v in cambios.items()]
                anotar("canal", c.key, "actualizar", f"{c.nombre}: {'; '.join(partes)}", obj, via, cambios)
                if "sincronizar" in cambios:
                    perdedores[c.key] = _pierden_acceso(snap, cat, ids_roles)
        elif not hay_registro(c.key, obj):
            anotar("canal", c.key, "vincular", c.nombre, obj, via)
        else:
            anotar("canal", c.key, "omitir", c.nombre, obj, via)

    # ---- mensajes -----------------------------------------------------------------------------------
    permisos_msg = _sin_permiso(snap, "send_messages", "embed_links", "read_message_history")
    for m in config.mensajes:
        if not m.publicar:
            anotar("mensaje", m.key, "omitir", m.key, razon="publicar = false")
            continue
        if m.canal in bloqueadas:
            anotar("mensaje", m.key, "bloqueado", m.key, razon=f"depende del canal '{m.canal}', que está bloqueado")
            continue
        if permisos_msg:
            anotar("mensaje", m.key, "bloqueado", m.key, razon=_bloqueo_por_permisos(permisos_msg))
            continue
        canal_id = ids_canales.get(m.canal)
        reg = estado.get(m.key)
        estado_msg = mensajes_estado.get(m.key) if reg is not None else None
        existe = reg is not None and estado_msg == "existe"
        if estado_msg == "ajeno":
            anotar("mensaje", m.key, "bloqueado", m.key, razon="el mensaje guardado no es del bot; no lo toco")
            continue
        if estado_msg == "error":
            anotar("mensaje", m.key, "bloqueado", m.key, razon="no pude leer el mensaje guardado (permisos o error de Discord)")
            continue
        # Si menciona algo que no se puede crear (bloqueado), no se publica a medias.
        bloqueados_mencionados = sorted(k for k in referencias(m) if k not in plan.ids and k in bloqueadas)
        if bloqueados_mencionados:
            anotar("mensaje", m.key, "bloqueado", m.key,
                   razon=f"menciona «{bloqueados_mencionados[0]}», que está bloqueado; se publica cuando exista")
            continue
        try:
            renderizado = renderizar(m, plan.ids)
        except PendienteDeId as e:
            cambios_pend = {}
            if existe and reg.canal_id != canal_id:
                cambios_pend = {"republicar": True, "borrar_antiguo": True}
            anotar("mensaje", m.key, "actualizar" if existe else "crear", m.key, cambios=cambios_pend,
                   razon=f"pendiente: menciona «{e.args[0]}», que aún no existe")
            continue
        h = hash_contenido(renderizado)
        if canal_id is None and existe:
            anotar("mensaje", m.key, "actualizar", m.key,
                   cambios={"republicar": True, "borrar_antiguo": True},
                   razon=f"el canal '{m.canal}' aún no existe: se publica allí y se borra el antiguo (mensaje del bot)")
        elif canal_id is None:
            anotar("mensaje", m.key, "crear", m.key, razon=f"el canal '{m.canal}' aún no existe")
        elif not existe:
            anotar("mensaje", m.key, "crear", m.key,
                   razon="se publicó antes pero ya no existe: se vuelve a publicar" if reg is not None else "")
        elif reg.hash != h or reg.canal_id != canal_id:
            cambia_canal = reg.canal_id != canal_id
            anotar("mensaje", m.key, "actualizar", m.key,
                   cambios={"republicar": True, "borrar_antiguo": True} if cambia_canal else {"republicar": False},
                   razon=("cambió de canal: se publica en el nuevo y se borra el antiguo (mensaje del bot)"
                          if cambia_canal else "contenido distinto"))
        else:
            anotar("mensaje", m.key, "omitir", m.key)

    _orden(config, snap, ids_cats, ids_canales, plan)
    _manuales(config, snap, estado, ids_cats, ids_canales, plan)
    _advertencias(config, snap, res, ids_roles, perdedores, plan)
    return plan


# --- Orden, vacias y reemplazados ---------------------------------------------------------------------------
def _deseado_orden(config, ids_cats, ids_canales):
    """(categorias_deseadas, canales_deseados) con los IDs ya resueltos, en el orden del TOML."""
    cats = [ids_cats[c.key] for c in sorted(config.categorias, key=lambda x: x.orden) if c.key in ids_cats]
    canales = {}
    for cat in config.categorias:
        if cat.key not in ids_cats:
            continue
        hijos = sorted((c for c in config.canales if c.categoria == cat.key), key=lambda x: x.orden)
        canales[ids_cats[cat.key]] = [ids_canales[c.key] for c in hijos if c.key in ids_canales]
    return cats, canales


def _orden(config, snap, ids_cats, ids_canales, plan):
    """Una accion «orden»: deja categorias y canales en el orden del TOML (si no lo estan ya).

    Discord pone cada categoria o canal nuevo arriba, asi que tras crear cosas el orden sale
    invertido; esta accion lo corrige con una sola peticion."""
    if len(config.categorias) < 2:
        return
    cambia_estructura = any(
        (a.tipo in ("categoria", "canal") and a.op == "crear")
        or (a.tipo == "canal" and a.op == "actualizar" and "mover" in a.cambios)
        for a in plan.acciones
    )
    cats, canales = _deseado_orden(config, ids_cats, ids_canales)
    datos = [(c.id, c.tipo, c.category_id, c.position) for c in snap.canales]
    if cambia_estructura:
        plan.acciones.append(Accion("orden", "@orden", "actualizar",
                                    "reordenar categorías y canales según el TOML",
                                    razon="tras crear o mover recursos"))
    elif not orden_ya_correcto(datos, cats, canales):
        plan.acciones.append(Accion("orden", "@orden", "actualizar",
                                    "reordenar categorías y canales según el TOML",
                                    razon="el orden actual no coincide"))
    else:
        plan.acciones.append(Accion("orden", "@orden", "omitir", "orden de categorías y canales"))


def _manuales(config, snap, estado, ids_cats, ids_canales, plan):
    """Lo que el bot nunca hace (borrar/archivar) y debes hacer a mano."""
    ids_config = set(ids_canales.values()) | {c.existing_id for c in config.canales if c.existing_id}
    por_id = {c.id: c for c in snap.canales}
    # Foros que sustituyen a un canal de texto: el de texto no se toca.
    reemplazados = {}   # id del canal de texto -> nombre del foro
    bloqueadas = {a.key for a in plan.bloqueadas()}
    for c in config.canales:
        if not c.reemplaza or c.key in bloqueadas:
            continue
        objetivo = normalizar(c.reemplaza)
        for o in snap.canales:
            if o.tipo in ("text", "news") and o.id not in ids_config and normalizar(o.name) == objetivo:
                reemplazados[o.id] = c.nombre
    for canal_id, foro in reemplazados.items():
        plan.manuales.append(
            f"«{por_id[canal_id].name}» queda **reemplazado** por el foro «{foro}»: no lo toco; "
            "archívalo o bórralo a mano"
        )
    # Categorias que se quedan sin canales (no se borran).
    salen = {}
    for a in plan.acciones:
        if a.tipo == "canal" and a.op == "actualizar" and "mover" in a.cambios and a.destino_id in por_id:
            origen = por_id[a.destino_id].category_id
            if origen is not None:
                salen[origen] = salen.get(origen, 0) + 1
    ids_categorias_config = set(ids_cats.values())
    mapeadas = {r.discord_id for r in estado.values() if r.tipo == "categoria"}
    for cat in snap.canales:
        if cat.tipo != "categoria" or cat.id in ids_categorias_config:
            continue
        hijos = [c for c in snap.canales if c.category_id == cat.id]
        quedan = len(hijos) - salen.get(cat.id, 0)
        solo_reemplazados = sum(1 for c in hijos if c.id in reemplazados)
        if quedan - solo_reemplazados > 0:
            continue
        if not hijos and cat.id not in mapeadas:
            continue          # una categoria vacia ajena al perfil: no es asunto suyo
        nota = " (solo queda el canal reemplazado: bórralo antes)" if quedan else ""
        plan.manuales.append(f"Categoría «{cat.name}»: queda **vacía**{nota}; bórrala a mano")


# --- Utilidades del plan -----------------------------------------------------------------------------------
def _bits_allow(deseados):
    total = 0
    for allow, _deny in deseados.values():
        total |= allow
    return total


def _difieren(actuales, deseados):
    """True si algun objetivo deseado no esta igual en `actuales` (los extras no cuentan)."""
    return any(tuple(actuales.get(t, (0, 0))) != tuple(par) for t, par in deseados.items())


_TIPOS_TEXTO = {"text": "texto", "voice": "voz", "news": "anuncios", "forum": "foro"}


def _texto_cambio(clave, valor, categoria):
    if clave == "mover":
        return f"mover a «{categoria.nombre}»"
    if clave == "sincronizar":
        return "sincronizar permisos con su categoría"
    if clave == "overwrites":
        return "overrides"
    if clave == "nombre":
        return f"renombrar a «{valor}»"
    if clave == "tipo":
        return "convertir a canal de anuncios"
    return {"tema": "actualizar el tema", "slowmode": "ajustar el slowmode",
            "limite_usuarios": "ajustar el límite de usuarios"}.get(clave, clave)


def _pierden_acceso(snap, categoria, ids_roles):
    """Miembros (no bots, no el dueño) que no tienen ningun rol con acceso a la categoria."""
    if not any(o.objetivo == EVERYONE and "view_channel" in o.denegar for o in categoria.overrides):
        return []
    con_acceso = {
        ids_roles[o.objetivo] for o in categoria.overrides
        if o.objetivo != EVERYONE and "view_channel" in o.permitir and o.objetivo in ids_roles
    }
    return [m.id for m in snap.miembros
            if not m.bot and m.id != snap.owner_id and not (m.roles & con_acceso)]


def _advertencias(config, snap, res, ids_roles, perdedores, plan):
    avisos = plan.advertencias
    faltan = [p for p in PERMISOS_BOT_REQUERIDOS if not snap.bot_admin and not (snap.bot_permisos & bits([p]))]
    if faltan:
        avisos.append(f"El bot no tiene: {', '.join(faltan)}. Lo que lo necesite saldrá como «bloqueado».")
    if config.owner_id and config.owner_id != snap.owner_id:
        avisos.append(f"`owner_id` del TOML ({config.owner_id}) no coincide con el dueño real ({snap.owner_id}).")
    for r in config.roles:
        obj = res[r.key][0]
        if obj is None:
            continue
        if obj.permissions & bits(["administrator"]):
            miembros = sum(1 for m in snap.miembros if obj.id in m.roles)
            avisos.append(
                f"«{obj.name}» tiene `administrator` ({miembros} miembro(s)): quien lo reciba ignora "
                "todos los overrides (Equipo, Staff…). No lo toco; cámbialo tú si quieres."
            )
        if not r.por_encima_del_bot and not snap.rol_bajo_el_bot(obj):
            avisos.append(f"El rol del bot no está por encima de «{obj.name}»: no podré editarlo ni asignarlo.")
    if any(a.op == "crear" and a.tipo == "rol" for a in plan.acciones):
        nombres = [r.nombre for r in config.roles if r.key == "propietario"]
        extra = f" (p. ej. «{nombres[0]}»)" if nombres else ""
        avisos.append(
            "Los roles nuevos se crean por debajo del rol del bot. Si quieres alguno por encima"
            f"{extra}, arrástralo a mano tras crearlo."
        )
    for key, ids in perdedores.items():
        if ids:
            menciones = ", ".join(f"<@{i}>" for i in ids[:10]) + (f" +{len(ids) - 10}" if len(ids) > 10 else "")
            avisos.append(
                f"«{config.canal(key).nombre}» pasará a ser privado: {len(ids)} miembro(s) no tienen "
                f"ningún rol con acceso y dejarán de verlo hasta que les des uno: {menciones}"
            )


# --- Texto del plan -----------------------------------------------------------------------------------------
ICONOS = {"crear": "🆕", "actualizar": "✏️", "vincular": "🔗", "omitir": "⏭️", "bloqueado": "⛔"}


def lineas_plan(plan):
    """Lineas de texto del plan (una por recurso, ordenadas por operacion) para mostrarlas."""
    lineas = []
    resumen = plan.resumen()
    lineas.append(
        "**Resumen:** " + " · ".join(f"{ICONOS[op]} {op} {n}" for op, n in resumen.items())
    )
    for op in ("crear", "actualizar", "vincular", "bloqueado", "omitir"):
        grupo = plan.con_op(op)
        if not grupo:
            continue
        lineas.append("")
        lineas.append(f"**{ICONOS[op]} {op.capitalize()} ({len(grupo)})**")
        for a in grupo:
            extra = ""
            if op == "bloqueado":
                extra = f" — bloqueado: {a.razon}"
            elif a.razon:
                extra = f" — {a.razon}"
            elif op == "omitir" and a.via and a.via != "guardado":
                extra = f" — reutilizado (por {a.via})"
            lineas.append(f"• `{a.tipo}` {a.key}: {a.detalle}{extra}")
    if plan.manuales:
        lineas.append("")
        lineas.append("**🧹 A mano (el bot nunca borra)**")
        lineas.extend(f"• {m}" for m in plan.manuales)
    if plan.advertencias:
        lineas.append("")
        lineas.append("**⚠️ Advertencias**")
        lineas.extend(f"• {a}" for a in plan.advertencias)
    return lineas
