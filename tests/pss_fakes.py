"""Servidor de Discord FALSO para probar el planificador y el ejecutor del perfil PSS.

Modela lo justo de Discord: roles con posicion, categorias y canales (texto, anuncios, foros
y voz) con posicion, overwrites, mensajes, la funcion COMMUNITY y el comportamiento que se
observo en PSS: cada categoria o canal NUEVO aparece ARRIBA del todo (de ahi el orden
invertido Staff, Equipo, Desarrollo, Estudio…)."""

import itertools
import json
import types
from pathlib import Path

import discord

from profiles.pss_plan import SCanal, SMiembro, SRol, Snapshot, bits

G, BOT, DUENO = 1420403964746268684, 900, 668148837579227137
DEVELOPER = 1561497283315638312
MINIMO_BOT = 1099780320342

_TIPOS = {
    "categoria": discord.ChannelType.category, "text": discord.ChannelType.text,
    "news": discord.ChannelType.news, "forum": discord.ChannelType.forum,
    "voice": discord.ChannelType.voice,
}


def bucket(tipo):
    return "categoria" if tipo == "categoria" else ("voz" if tipo == "voice" else "texto")


class FMensaje:
    def __init__(self, canal, id, autor_id, embed, view):
        self.canal, self.id, self.author = canal, id, types.SimpleNamespace(id=autor_id)
        self.embed, self.view = embed, view

    async def edit(self, embed=None, view=None):
        self.embed = embed
        if view is not None:
            self.view = view

    async def delete(self):
        del self.canal.mensajes[self.id]


class FRol:
    def __init__(self, id, nombre, permissions=0, position=1, managed=False, colour=0, hoist=False, mentionable=False):
        self.id, self.name, self.position, self.managed = id, nombre, position, managed
        self.permissions = discord.Permissions(permissions)
        self.colour, self.hoist, self.mentionable = discord.Colour(colour), hoist, mentionable

    async def edit(self, reason=None, **o):
        for k, v in o.items():
            setattr(self, k, v)


class FCanal:
    def __init__(self, srv, id, nombre, tipo, categoria=None, overwrites=None, topic=None, slowmode=0,
                 user_limit=0, position=0):
        self.srv, self.id, self.name, self.tipo, self.category = srv, id, nombre, tipo, categoria
        self.overwrites = dict(overwrites or {})
        self.topic, self.slowmode_delay, self.user_limit, self.position = topic, slowmode, user_limit, position
        self.mensajes = {}

    @property
    def type(self):
        return _TIPOS[self.tipo]

    @property
    def category_id(self):
        return self.category.id if self.category else None

    async def edit(self, reason=None, **o):
        if "type" in o:
            if "COMMUNITY" not in self.srv.features:
                raise discord.HTTPException(types.SimpleNamespace(status=400, reason="x"), "requiere Comunidad")
            self.tipo = "news" if o["type"] == discord.ChannelType.news else "text"
        if "name" in o:
            self.name = o["name"]
        if "topic" in o:
            self.topic = o["topic"]
        if "slowmode_delay" in o:
            self.slowmode_delay = o["slowmode_delay"]
        if "user_limit" in o:
            self.user_limit = o["user_limit"]
        if "category" in o:
            self.category = o["category"]
        if o.get("sync_permissions") and self.category is not None:
            self.overwrites = dict(self.category.overwrites)
        self.srv.llamadas.append(("edit_channel", self.name, tuple(sorted(o))))

    async def set_permissions(self, entidad, overwrite=None, reason=None):
        self.overwrites[entidad] = overwrite

    async def send(self, content=None, embed=None, view=None, allowed_mentions=None):
        m = FMensaje(self, self.srv.siguiente_id(), self.srv.me.id, embed, view)
        self.mensajes[m.id] = m
        return m

    async def fetch_message(self, id):
        if id not in self.mensajes:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="x"), "no existe")
        return self.mensajes[id]


class FMiembro:
    def __init__(self, id):
        self.id = id


class FServidor:
    """Copia del estado de PSS antes del perfil: 3 categorias de Discord y 8 canales."""

    def __init__(self, features=("COMMUNITY",)):
        self.id, self.owner_id = G, DUENO
        self.features = set(features)
        self._ids = itertools.count(5000)
        self.me = FMiembro(BOT)
        self.default_role = FRol(G, "@everyone", position=0)
        self.roles = [self.default_role, FRol(5, "EITO Setup Bot", 8, 1, managed=True),
                      FRol(DEVELOPER, "Developer", bits(["administrator"]), 1),
                      FRol(6, "Server Booster", 0, 2, managed=True)]
        self.rol_del_bot = 5                               # su rol mas alto (el que manda en la jerarquia)
        self.canales = {}
        self.llamadas = []
        self.nuevos_arriba = False        # roles nuevos al reves (ver pss_exec)
        self.canales_arriba = True        # categorias/canales nuevos ARRIBA (el bug observado)
        self._state = types.SimpleNamespace(http=types.SimpleNamespace(bulk_channel_update=self._bulk))
        for id, n, t, cat in [(10, "Información", "categoria", None), (11, "Canales de texto", "categoria", None),
                              (12, "Canales de voz", "categoria", None), (20, "info-importante", "text", 10),
                              (21, "general", "text", 11), (22, "deberes-ayuda", "text", 11),
                              (23, "planificación-de-sesiones", "text", 11), (24, "no-relacionado", "text", 11),
                              (25, "frontend", "text", 11), (26, "backend", "text", 11), (30, "Reuniones", "voice", 12)]:
            pos = sum(1 for c in self.canales.values() if bucket(c.tipo) == bucket(t))
            self.canales[id] = FCanal(self, id, n, t, self.canales.get(cat), position=pos)

    # ---- utilidades ----
    @property
    def bot_top(self):
        return (self.get_role(self.rol_del_bot).position, self.rol_del_bot)

    def siguiente_id(self):
        return next(self._ids)

    @property
    def channels(self):
        return list(self.canales.values())

    def get_role(self, id):
        return next((r for r in self.roles if r.id == id), None)

    def get_channel(self, id):
        return self.canales.get(id)

    async def fetch_roles(self):
        return list(self.roles)

    async def fetch_channels(self):
        return self.channels

    async def _bulk(self, guild_id, payload, reason=None):
        self.llamadas.append(("bulk_channel_update", len(payload)))
        for item in payload:
            self.canales[item["id"]].position = item["position"]

    # ---- roles ----
    async def create_role(self, name, permissions, colour, hoist, mentionable, reason=None):
        posicion = 1
        if self.nuevos_arriba:
            posicion = max(r.position for r in self.roles) + 1
        else:
            for r in self.roles:       # como Discord: el rol nuevo entra en la posicion 1
                if r.id != G:
                    r.position += 1
        rol = FRol(self.siguiente_id(), name, permissions.value, posicion, colour=colour.value,
                   hoist=hoist, mentionable=mentionable)
        self.roles.append(rol)
        self.llamadas.append(("create_role", name))
        return rol

    async def edit_role_positions(self, mapa, reason=None):
        for rol, pos in mapa.items():
            rol.position = pos
        self.llamadas.append(("edit_role_positions", len(mapa)))

    # ---- canales ----
    async def _crear(self, nombre, tipo, category=None, overwrites=None, topic=None,
                     slowmode_delay=0, user_limit=0, reason=None):
        if tipo in ("text", "news", "forum"):
            nombre = nombre.lower().replace(" ", "-")      # como hace Discord con los canales de texto
        mismos = [c.position for c in self.canales.values() if bucket(c.tipo) == bucket(tipo)]
        if self.canales_arriba:
            pos = (min(mismos) - 1) if mismos else 0
        else:
            pos = (max(mismos) + 1) if mismos else 0
        c = FCanal(self, self.siguiente_id(), nombre, tipo, category, overwrites, topic,
                   slowmode_delay or 0, user_limit or 0, pos)
        self.canales[c.id] = c
        self.llamadas.append(("create_" + tipo, nombre))
        return c

    async def create_category(self, nombre, overwrites=None, reason=None):
        return await self._crear(nombre, "categoria", None, overwrites)

    async def create_text_channel(self, nombre, news=False, **o):
        if news and "COMMUNITY" not in self.features:
            raise discord.HTTPException(types.SimpleNamespace(status=400, reason="x"), "requiere Comunidad")
        return await self._crear(nombre, "news" if news else "text", **o)

    async def create_forum(self, nombre, **o):
        if "COMMUNITY" not in self.features:
            raise discord.HTTPException(types.SimpleNamespace(status=400, reason="x"), "requiere Comunidad")
        return await self._crear(nombre, "forum", **o)

    async def create_voice_channel(self, nombre, **o):
        return await self._crear(nombre, "voice", **o)


def foto(srv, admin=True, permisos=8):
    """Snapshot hecho desde el servidor falso (lo que hace construir_snapshot con el real)."""
    canales = [
        SCanal(c.id, c.name, c.tipo, c.category_id, c.topic, c.slowmode_delay, c.user_limit, c.position,
               {e.id: tuple(p.value for p in ow.pair()) for e, ow in c.overwrites.items()})
        for c in srv.canales.values()
    ]
    roles = [SRol(r.id, r.name, r.position, r.permissions.value, r.colour.value, r.hoist, r.mentionable, r.managed)
             for r in srv.roles]
    miembros = getattr(srv, "miembros", None) or [SMiembro(i, frozenset()) for i in range(1, 6)]
    return Snapshot(srv.id, srv.owner_id, srv.me.id, permisos, admin, srv.bot_top, roles, canales, miembros,
                    features=frozenset(srv.features))


def estado_mensajes(srv, config, estado):
    resultado = {}
    for m in config.mensajes:
        reg = estado.get(m.key)
        if reg is not None and reg.tipo == "mensaje":
            canal = srv.get_channel(reg.canal_id)
            if not canal or reg.discord_id not in canal.mensajes:
                resultado[m.key] = "falta"
            else:
                resultado[m.key] = "existe" if canal.mensajes[reg.discord_id].author.id == srv.me.id else "ajeno"
    return resultado


def orden_actual(srv):
    """(nombres de categorias de arriba a abajo, {categoria: nombres de canales de arriba a abajo})."""
    cats = sorted((c for c in srv.canales.values() if c.tipo == "categoria"), key=lambda c: (c.position, c.id))
    hijos = {}
    for cat in cats:
        hs = [c for c in srv.canales.values() if c.category_id == cat.id]
        # el cliente de Discord muestra primero los de texto y luego los de voz
        hs.sort(key=lambda c: (bucket(c.tipo) == "voz", c.position, c.id))
        hijos[cat.name] = [c.name for c in hs]
    return [c.name for c in cats], hijos


# --- PSS REAL: el export del servidor tras el primer !pss aplicar ----------------------------------------------
EXPORT_REAL = Path(__file__).resolve().parent / "fixtures" / "pss_export_real.json"
BOT_REAL = 1546632560057000046         # el usuario del bot (aparece en los overrides del export)
_TIPOS_EXPORT = {"category": "categoria", "text": "text", "news": "news", "forum": "forum", "voice": "voice"}


def _permisos(nombres):
    return discord.Permissions(**{n: True for n in nombres}).value


def cargar_export_real(ruta=EXPORT_REAL):
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


class FServidorReal(FServidor):
    """Copia EXACTA del PSS real (roles, categorias, canales, overwrites y posiciones del export).

    Los miembros no vienen en el export, solo el recuento (6, 5 con Developer): se reconstruyen con
    el bot, el dueño y cuatro personas mas con Developer, y una sin ningun rol."""

    def __init__(self, export=None, features=("COMMUNITY",)):
        export = export or cargar_export_real()
        sv = export["servidor"]
        self.id, self.owner_id = sv["id"], sv["owner_id"]
        self.features = set(features)
        self._ids = itertools.count(1800000000000000000)
        self.me = FMiembro(BOT_REAL)
        self.llamadas = []
        self.nuevos_arriba = False
        self.canales_arriba = True
        self._state = types.SimpleNamespace(http=types.SimpleNamespace(bulk_channel_update=self._bulk))
        self.roles = []
        for r in export["roles"]:
            rol = FRol(r["id"], r["nombre"], _permisos(r["permisos"]), r["posicion"], managed=r["managed"],
                       colour=int(r["color"].lstrip("#"), 16), hoist=r["hoist"], mentionable=r["mencionable"])
            self.roles.append(rol)
        self.default_role = self.get_role(self.id)
        self.rol_del_bot = export["rol_mas_alto_del_bot"]["id"]
        self.canales = {}
        for cat in export["categorias"]:
            self.canales[cat["id"]] = FCanal(self, cat["id"], cat["nombre"], "categoria",
                                            overwrites=self._overwrites(cat), position=cat["posicion"])
        for cat in export["categorias"]:
            for ch in cat["canales"]:
                self.canales[ch["id"]] = FCanal(
                    self, ch["id"], ch["nombre"], _TIPOS_EXPORT[ch["tipo"]], self.canales[cat["id"]],
                    self._overwrites(ch), ch.get("tema"), ch.get("slowmode") or 0, ch.get("limite_usuarios") or 0,
                    ch["posicion"])
        for ch in export["canales_sin_categoria"]:
            self.canales[ch["id"]] = FCanal(self, ch["id"], ch["nombre"], _TIPOS_EXPORT[ch["tipo"]],
                                           overwrites=self._overwrites(ch), position=ch["posicion"])
        developer = {r["nombre"]: r["id"] for r in export["roles"]}["Developer"]
        self.miembros = [SMiembro(BOT_REAL, frozenset({developer}), True), SMiembro(self.owner_id, frozenset({developer}))]
        self.miembros += [SMiembro(1900 + i, frozenset({developer})) for i in range(3)]
        self.miembros.append(SMiembro(1999, frozenset()))
        assert len(self.miembros) == sv["miembros"]

    def _overwrites(self, obj):
        resultado = {}
        for o in obj["overrides"]:
            if o["tipo"] == "rol":
                entidad = self.get_role(o["id"])
            else:
                entidad = self.me if o["id"] == self.me.id else types.SimpleNamespace(id=o["id"])
            resultado[entidad] = discord.PermissionOverwrite.from_pair(
                discord.Permissions(_permisos(o["permite"])), discord.Permissions(_permisos(o["niega"])))
        return resultado


def estado_real(export=None):
    """El contenido de perfil_recursos tras el primer aplicar: {key: Registro}, y los mensajes (del bot)
    puestos en su canal del servidor falso."""
    export = export or cargar_export_real()
    from profiles.pss_plan import Registro
    return {k: Registro(f["tipo"], f["discord_id"], f.get("canal_id"), f.get("hash"), f["creado"])
            for k, f in export["perfil_recursos"].items()}


def publicar_mensajes_reales(srv, estado):
    """Los mensajes que dejo el primer aplicar (sus IDs son sinteticos) existen y son del bot."""
    for reg in estado.values():
        if reg.tipo == "mensaje":
            srv.canales[reg.canal_id].mensajes[reg.discord_id] = FMensaje(
                srv.canales[reg.canal_id], reg.discord_id, srv.me.id, None, None)
