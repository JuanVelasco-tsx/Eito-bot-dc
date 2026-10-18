"""Planificador + ejecutor del perfil PSS contra un servidor FALSO (sin Discord ni BD).

La prueba clave es de punta a punta con el profiles/pss.toml real: se aplica sobre una
copia del estado actual de PSS (con el bot como administrador) y despues, con el bot ya
bajado al entero minimo de permisos, el plan debe dar todo en «omitir»."""

import itertools
import types
from pathlib import Path

import discord
import pytest

from profiles import pss_db
from profiles.pss_config import cargar
from profiles.pss_exec import ejecutar
from profiles.pss_plan import (
    Registro, SCanal, SMiembro, SRol, Snapshot, bits, calcular_plan, lineas_plan,
)

RUTA = Path(__file__).resolve().parent.parent / "profiles" / "pss.toml"
G, BOT, DUENO = 1420403964746268684, 900, 668148837579227137
DEVELOPER = 1561497283315638312
MINIMO_BOT = 1099780189270


# --- Servidor falso ---------------------------------------------------------------------
class FMensaje:
    def __init__(self, id, autor_id, embed, view):
        self.id, self.author, self.embed, self.view = id, types.SimpleNamespace(id=autor_id), embed, view

    async def edit(self, embed=None, view=None):
        self.embed = embed


class FRol:
    def __init__(self, id, nombre, permissions=0, position=1, managed=False, colour=0, hoist=False, mentionable=False):
        self.id, self.name, self.position, self.managed = id, nombre, position, managed
        self.permissions = discord.Permissions(permissions)
        self.colour, self.hoist, self.mentionable = discord.Colour(colour), hoist, mentionable

    async def edit(self, reason=None, **o):
        for k, v in o.items():
            setattr(self, {"name": "name", "colour": "colour", "permissions": "permissions"}.get(k, k), v)


class FCanal:
    def __init__(self, srv, id, nombre, tipo, categoria=None, overwrites=None, topic=None, slowmode=0, user_limit=0):
        self.srv, self.id, self.name, self.tipo, self.category = srv, id, nombre, tipo, categoria
        self.overwrites = dict(overwrites or {})
        self.topic, self.slowmode_delay, self.user_limit = topic, slowmode, user_limit
        self.mensajes = {}

    @property
    def category_id(self):
        return self.category.id if self.category else None

    async def edit(self, reason=None, **o):
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

    async def set_permissions(self, entidad, overwrite=None, reason=None):
        self.overwrites[entidad] = overwrite

    async def send(self, content=None, embed=None, view=None, allowed_mentions=None):
        m = FMensaje(self.srv.siguiente_id(), self.srv.me.id, embed, view)
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
    def __init__(self):
        self.id, self.owner_id = G, DUENO
        self._ids = itertools.count(5000)
        self.me = FMiembro(BOT)
        self.default_role = FRol(G, "@everyone", position=0)
        self.roles = [self.default_role, FRol(5, "EITO Setup Bot", 8, 1, managed=True),
                      FRol(DEVELOPER, "Developer", bits(["administrator"]), 1),
                      FRol(6, "Server Booster", 0, 2, managed=True)]
        self.canales = {}
        for id, n, t, cat in [(10, "Información", "categoria", None), (11, "Canales de texto", "categoria", None),
                              (12, "Canales de voz", "categoria", None), (20, "info-importante", "text", 10),
                              (21, "general", "text", 11), (22, "deberes-ayuda", "text", 11),
                              (23, "planificación-de-sesiones", "text", 11), (24, "no-relacionado", "text", 11),
                              (25, "frontend", "text", 11), (26, "backend", "text", 11), (30, "Reuniones", "voice", 12)]:
            self.canales[id] = FCanal(self, id, n, t, self.canales.get(cat))
        self.llamadas = []
        self.nuevos_arriba = False     # simula que Discord deja los roles nuevos en orden inverso

    def siguiente_id(self):
        return next(self._ids)

    def get_role(self, id):
        return next((r for r in self.roles if r.id == id), None)

    def get_channel(self, id):
        return self.canales.get(id)

    async def fetch_roles(self):
        return list(self.roles)

    async def create_role(self, name, permissions, colour, hoist, mentionable, reason=None):
        posicion = 1
        if self.nuevos_arriba:
            posicion = max(r.position for r in self.roles) + 1
        else:
            for r in self.roles:       # como Discord: el rol nuevo entra en la posicion 1
                if r.id != G:
                    r.position += 1
        rol = FRol(self.siguiente_id(), name, permissions.value, posicion, colour=colour.value, hoist=hoist, mentionable=mentionable)
        self.roles.append(rol)
        self.llamadas.append(("create_role", name))
        return rol

    async def edit_role_positions(self, mapa, reason=None):
        for rol, pos in mapa.items():
            rol.position = pos
        self.llamadas.append(("edit_role_positions", len(mapa)))

    async def _crear(self, nombre, tipo, category=None, overwrites=None, reason=None, topic=None,
                     slowmode_delay=0, user_limit=0):
        if tipo == "text":
            nombre = nombre.lower().replace(" ", "-")   # como hace Discord
        c = FCanal(self, self.siguiente_id(), nombre, tipo, category, overwrites, topic, slowmode_delay or 0, user_limit or 0)
        self.canales[c.id] = c
        self.llamadas.append(("create_" + tipo, nombre))
        return c

    async def create_category(self, nombre, overwrites=None, reason=None):
        return await self._crear(nombre, "categoria", None, overwrites)

    async def create_text_channel(self, nombre, **o):
        return await self._crear(nombre, "text", **o)

    async def create_voice_channel(self, nombre, **o):
        return await self._crear(nombre, "voice", **o)


def foto(srv, admin=True, permisos=8):
    """Snapshot hecho desde el servidor falso (lo que hace construir_snapshot con el real)."""
    canales = [
        SCanal(c.id, c.name, c.tipo, c.category_id, c.topic, c.slowmode_delay, c.user_limit,
               {e.id: tuple(p.value for p in ow.pair()) for e, ow in c.overwrites.items()})
        for c in srv.canales.values()
    ]
    roles = [SRol(r.id, r.name, r.position, r.permissions.value, r.colour.value, r.hoist, r.mentionable, r.managed)
             for r in srv.roles]
    miembros = [SMiembro(i, frozenset()) for i in range(1, 6)]
    return Snapshot(G, DUENO, BOT, permisos, admin, (3, 5), roles, canales, miembros)


@pytest.fixture
def guardado(monkeypatch):
    """Sustituye pss_db.guardar por un diccionario en memoria: {key: Registro}."""
    estado = {}

    async def guardar(guild_id, key, tipo, discord_id, canal_id=None, hash_contenido=None, creado=False):
        previo = estado.get(key)
        mantiene = previo is not None and previo.discord_id == discord_id and previo.creado
        estado[key] = Registro(tipo, discord_id, canal_id, hash_contenido, creado or mantiene)

    monkeypatch.setattr(pss_db, "guardar", guardar)
    return estado


def estado_mensajes(srv, config, estado):
    resultado = {}
    for m in config.mensajes:
        reg = estado.get(m.key)
        if reg is not None and reg.tipo == "mensaje":
            canal = srv.get_channel(reg.canal_id)
            resultado[m.key] = "existe" if canal and reg.discord_id in canal.mensajes else "falta"
    return resultado


async def aplicar(srv, config, estado, admin=True, permisos=8):
    plan = calcular_plan(config, foto(srv, admin, permisos), estado, estado_mensajes(srv, config, estado))
    res = await ejecutar(srv, plan, config, estado, lambda keys: object())
    return plan, res


# --- pruebas ------------------------------------------------------------------------------------
async def test_aplicar_crea_lo_que_falta_y_el_plan_posterior_da_todo_omitir(guardado):
    config, srv = cargar(RUTA), FServidor()
    plan, res = await aplicar(srv, config, guardado)
    assert res.fallos == [] and res.bloqueadas == []

    nombres_roles = {r.name for r in srv.roles}
    assert {"Propietario", "Administrador", "Colaborador", "Miembro", "Scripter", "Builder", "UI"} <= nombres_roles
    propietario = next(r for r in srv.roles if r.name == "Propietario")
    assert propietario.permissions.value == 0 and propietario.hoist       # sin administrator
    assert srv.get_role(DEVELOPER).permissions.administrator               # Developer intacto
    assert srv.get_role(DEVELOPER).name == "Developer"

    por_nombre = {c.name: c for c in srv.canales.values()}
    assert por_nombre["📌 Estudio"].tipo == "categoria"
    assert "📂 Proyectos" not in por_nombre
    # Existentes que pasan a Equipo (privada): movidos y sincronizados, sin adoptar
    equipo = por_nombre["🔒 Equipo"]
    for n in ("info-importante", "planificación-de-sesiones"):
        assert por_nombre[n].category is equipo and por_nombre[n].overwrites == equipo.overwrites
    assert por_nombre["info-importante"].topic is None                      # no se cambia su tema
    # Equipo: @everyone sin ver, developer y colaborador con acceso y override explicito del bot
    por_id = {getattr(e, "id", None): ow for e, ow in equipo.overwrites.items()}
    administrador = next(r for r in srv.roles if r.name == "Administrador")
    assert por_id[administrador.id].pair()[0].view_channel is True        # Administrador tambien ve Equipo
    assert por_id[G].pair()[1].view_channel is True
    assert por_id[DEVELOPER].pair()[0].view_channel is True
    assert por_id[BOT].pair()[0].view_channel and por_id[BOT].pair()[0].send_messages
    colaborador = next(r for r in srv.roles if r.name == "Colaborador")
    assert por_id[colaborador.id].pair()[0].view_channel is True
    # Canales publicos: movidos pero con los permisos que tenian (ninguno propio)
    assert por_nombre["general"].category.name == "💬 Comunidad" and por_nombre["general"].overwrites == {}
    for n in ("frontend", "backend"):
        assert por_nombre[n].category.name == "💻 Desarrollo" and por_nombre[n].overwrites == {}
    assert por_nombre["💻 Desarrollo"].overwrites == {} and por_nombre["🟥 Roblox"].overwrites == {}
    # #deberes-ayuda se renombro a #ayuda: es el MISMO canal (id 22), no uno nuevo
    assert "deberes-ayuda" not in por_nombre and por_nombre["ayuda"].id == 22
    assert por_nombre["ayuda"].category.name == "🛠️ Soporte" and por_nombre["ayuda"].overwrites == {}
    # Reuniones: movido a Equipo y sincronizado (privado); la voz publica nueva es "🔊 General" en Voz
    assert por_nombre["Reuniones"].category is equipo and por_nombre["Reuniones"].overwrites == equipo.overwrites
    assert por_nombre["Reuniones"].id == 30
    assert por_nombre["🔊 General"].tipo == "voice" and por_nombre["🔊 General"].category.name == "🔊 Voz"
    assert por_nombre["🔊 General"].overwrites == {} and por_nombre["🔊 Voz"].overwrites == {}
    assert por_nombre["showcase"].category.name == "💬 Comunidad" and por_nombre["showcase"].overwrites == {}
    # Los canales viejos se movieron, nada se borro
    assert {"Información", "Canales de texto", "Canales de voz"} <= set(por_nombre)
    # Anuncios y Estudio: solo lectura para @everyone; escriben developer y administrador
    for nombre in ("📢 Anuncios", "📌 Estudio"):
        ow = {getattr(e, "id", None): o for e, o in por_nombre[nombre].overwrites.items()}
        assert ow[G].pair()[1].send_messages is True and ow[G].pair()[1].view_channel is False
        assert ow[DEVELOPER].pair()[0].send_messages is True
        assert BOT in ow                                                      # el bot sigue pudiendo escribir
    assert por_nombre["anuncios"].overwrites == por_nombre["📢 Anuncios"].overwrites
    assert por_nombre["reglas"].overwrites == por_nombre["📌 Estudio"].overwrites
    # Staff: canal nuevo creado con los overrides de su categoria
    assert por_nombre["registros"].overwrites == por_nombre["🛡️ Staff"].overwrites
    # Mensajes: los 4 en #reglas, en orden
    textos = [m.embed.title for m in por_nombre["reglas"].mensajes.values()]
    assert textos == ["👻 Phantom Shadows Studios", "📜 Reglas", "🧭 Guía para nuevos integrantes", "🎭 Tus especialidades"]
    reglas_msg = list(por_nombre["reglas"].mensajes.values())[1]
    assert "<#" in reglas_msg.embed.description                              # menciones resueltas
    assert list(por_nombre["reglas"].mensajes.values())[3].view is not None   # panel con botones
    assert not por_nombre["info-importante"].mensajes                        # ya no se publica en Equipo
    assert set(guardado) >= {"propietario", "frontend", "msg_reglas", "cat_staff", "cat_equipo"}

    # --- (c) el bot baja al entero minimo y (d) el plan da todo en omitir ---
    plan2, res2 = await aplicar(srv, config, guardado, admin=False, permisos=MINIMO_BOT)
    assert [a for a in plan2.acciones if a.op != "omitir"] == [], "\n".join(lineas_plan(plan2))
    assert res2.hechos == []


async def test_reaplicar_no_repite_llamadas_ni_duplica(guardado):
    config, srv = cargar(RUTA), FServidor()
    await aplicar(srv, config, guardado)
    antes = list(srv.llamadas)
    mensajes_antes = sum(len(c.mensajes) for c in srv.canales.values())
    await aplicar(srv, config, guardado)
    assert srv.llamadas == antes
    assert sum(len(c.mensajes) for c in srv.canales.values()) == mensajes_antes


async def test_se_crean_en_orden_los_roles_nuevos(guardado):
    config, srv = cargar(RUTA), FServidor()
    await aplicar(srv, config, guardado)
    orden = [r.name for r in sorted((r for r in srv.roles if r.name in {"Propietario", "Administrador", "Colaborador", "Miembro"}),
                                     key=lambda r: -r.position)]
    assert orden == ["Propietario", "Administrador", "Colaborador", "Miembro"]


async def test_si_discord_deja_los_roles_nuevos_al_reves_se_reordenan_entre_ellos(guardado):
    config, srv = cargar(RUTA), FServidor()
    srv.nuevos_arriba = True
    antes = {r.id: r.position for r in srv.roles}
    await aplicar(srv, config, guardado)
    nuevos = ["Propietario", "Administrador", "Colaborador", "Miembro"]
    orden = [r.name for r in sorted((r for r in srv.roles if r.name in nuevos), key=lambda r: -r.position)]
    assert orden == nuevos
    assert any(llamada[0] == "edit_role_positions" for llamada in srv.llamadas)
    # nunca se mueven los roles que ya existian (Developer, bot, booster)
    assert all(r.position == antes[r.id] for r in srv.roles if r.id in antes)


async def test_con_el_bot_minimo_el_rol_con_permisos_ajenos_sale_bloqueado(guardado):
    config, srv = cargar(RUTA), FServidor()
    plan, res = await aplicar(srv, config, guardado, admin=False, permisos=MINIMO_BOT)
    a = next(a for a in plan.acciones if a.key == "administrador")
    assert a.op == "bloqueado" and "manage_guild" in a.razon
    assert "administrador" not in {r.key for r in plan.con_op("crear")}
    assert "Administrador" not in {r.name for r in srv.roles}
    # Lo que depende del rol bloqueado no se crea a medias: una categoria con overrides para
    # un rol que no existe falla entera en vez de quedar mal protegida.
    assert any("cat_staff" in f and "faltan roles" in f for f in res.fallos)
    assert not any(c.name == "🛡️ Staff" for c in srv.canales.values())
    # Lo que cabe en el minimo si se aplico
    assert any(c.name == "💬 Comunidad" for c in srv.canales.values())


async def test_un_mensaje_borrado_se_vuelve_a_publicar_y_uno_cambiado_se_edita(guardado):
    config, srv = cargar(RUTA), FServidor()
    await aplicar(srv, config, guardado)
    reglas = next(c for c in srv.canales.values() if c.name == "reglas")
    otros = {i for i in reglas.mensajes if i != guardado["msg_reglas"].discord_id}
    del reglas.mensajes[guardado["msg_reglas"].discord_id]   # alguien borra solo ese mensaje
    plan, _ = await aplicar(srv, config, guardado)
    assert {a.key: a.op for a in plan.acciones if a.tipo == "mensaje"}["msg_reglas"] == "crear"
    assert len(reglas.mensajes) == 4 and otros < set(reglas.mensajes)       # los demas no se tocaron
    # el TOML cambia: se edita el mismo mensaje, no se publica otro
    ids_antes = set(reglas.mensajes)
    from dataclasses import replace
    nuevo = replace(config.mensaje("msg_reglas"), titulo="📜 Reglas (v2)")
    config2 = replace(config, mensajes=tuple(nuevo if m.key == "msg_reglas" else m for m in config.mensajes),
                      _indice={**config._indice, ("mensaje", "msg_reglas"): nuevo})
    plan, _ = await aplicar(srv, config2, guardado)
    assert {a.key: a.op for a in plan.acciones if a.tipo == "mensaje"}["msg_reglas"] == "actualizar"
    assert set(reglas.mensajes) == ids_antes
    assert reglas.mensajes[guardado["msg_reglas"].discord_id].embed.title == "📜 Reglas (v2)"


async def test_un_fallo_por_recurso_no_detiene_el_resto(guardado, monkeypatch):
    config, srv = cargar(RUTA), FServidor()
    original = srv.create_text_channel

    async def falla_en_reglas(nombre, **o):
        if nombre == "reglas":
            raise discord.Forbidden(types.SimpleNamespace(status=403, reason="x"), "sin permiso")
        return await original(nombre, **o)

    monkeypatch.setattr(srv, "create_text_channel", falla_en_reglas)
    plan, res = await aplicar(srv, config, guardado)
    assert any("canal reglas" in f and "sin permisos" in f for f in res.fallos)
    assert any("canal scripting_luau" in h or "scripting-luau" in h for h in res.hechos)
    # el mensaje que iba en ese canal no se intenta publicar
    assert any("msg_reglas" in f for f in res.fallos)
    assert "reglas" not in guardado


# --- construir_snapshot / reunir_estado_mensajes con las clases reales de discord.py ---------------------
def test_construir_snapshot_lee_roles_canales_y_overwrites_reales():
    from discord.abc import _Overwrites
    from discord.channel import CategoryChannel, TextChannel, VoiceChannel

    from profiles.pss_exec import construir_snapshot

    class Rol:
        def __init__(self, id, name, pos, perm=0, managed=False):
            self.id, self.name, self.position, self.managed = id, name, pos, managed
            self.permissions, self.colour = discord.Permissions(perm), discord.Colour(0x112233)
            self.hoist = self.mentionable = False

    class Guild:
        id, owner_id = 1, 2

        def __init__(self):
            self.bot_rol = Rol(5, "bot", 3, 8)
            self.roles = [Rol(1, "@everyone", 0), self.bot_rol, Rol(6, "dev", 1, 8)]
            self.me = types.SimpleNamespace(id=9, guild_permissions=discord.Permissions(administrator=True),
                                            top_role=self.bot_rol)
            self.channels, self.members = [], []

        def get_role(self, i):
            return next((r for r in self.roles if r.id == i), None)

        def get_member(self, i):
            return None

    g = Guild()

    def canal(cls, id, name, ows=(), **kw):
        c = object.__new__(cls)
        c.id, c.name, c.guild = id, name, g
        c._overwrites = [_Overwrites({"id": i, "type": t, "allow": a, "deny": d}) for i, t, a, d in ows]
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    cat = canal(CategoryChannel, 10, "Cat", [(1, 0, 0, 1024), (9, 1, 1024, 0)])
    cat.category_id = None
    g.channels = [cat,
                  canal(TextChannel, 11, "general", category_id=10, topic="x", slowmode_delay=3),
                  canal(VoiceChannel, 12, "Voz", category_id=10, user_limit=4)]
    s = construir_snapshot(g)
    por_id = {c.id: c for c in s.canales}
    assert por_id[10].tipo == "categoria" and por_id[10].overwrites == {1: (0, 1024), 9: (1024, 0)}
    assert (por_id[11].tipo, por_id[11].category_id, por_id[11].topic, por_id[11].slowmode) == ("text", 10, "x", 3)
    assert (por_id[12].tipo, por_id[12].user_limit) == ("voice", 4)
    assert s.bot_admin and s.bot_top == (3, 5) and s.bot_id == 9 and s.owner_id == 2
    assert {r.id: r.colour for r in s.roles}[6] == 0x112233


async def test_reunir_estado_de_mensajes():
    from profiles.pss_exec import reunir_estado_mensajes

    config = cargar(RUTA)
    srv = FServidor()
    canal = srv.canales[20]
    propio = await canal.send(embed=None)
    ajeno = FMensaje(77, 12345, None, None)
    canal.mensajes[ajeno.id] = ajeno
    estado = {"msg_info_estudio": Registro("mensaje", propio.id, 20),
              "msg_reglas": Registro("mensaje", ajeno.id, 20),
              "msg_guia": Registro("mensaje", 999, 20),                  # borrado
              "msg_especialidades": Registro("mensaje", 1, 404)}        # el canal ya no existe
    assert await reunir_estado_mensajes(srv, config, estado) == {
        "msg_info_estudio": "existe", "msg_reglas": "ajeno", "msg_guia": "falta", "msg_especialidades": "falta"}
