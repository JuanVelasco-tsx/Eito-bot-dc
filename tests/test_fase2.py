"""Fase 2 de PSS con el pss.toml DEFINITIVO: rangos por tiempo (contar_desde), Activo del mes, Fundador,
tickets y textos de logros. Todo con el cog de PSS cargado en el bot real de EITO y objetos falsos."""

import types
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import discord
import pytest

from profiles.pss_config import Rangos
from tests.test_recursos import (  # noqa: F401  (perfil, sin_bd son fixtures)
    FCategoria, FRol, FTexto, GuildPSS, perfil, sin_bd,
)

UTC = timezone.utc
G_PSS = 1420403964746268684


class RolJerarquia:
    """Rol que se puede comparar (guild.me.top_role <= rol) y asignar a un miembro."""

    def __init__(self, id, nombre="r", posicion=1, color=0):
        self.id, self.name, self.position = id, nombre, posicion
        self.colour = discord.Colour(color)
        self.members = []
        self.mention = f"<@&{id}>"

    def __le__(self, otro):
        return self.position <= otro.position


class Miembro:
    def __init__(self, id, joined_at=None, roles=(), bot=False, guild=None):
        self.id, self.joined_at, self.bot, self.guild = id, joined_at, bot, guild
        self.roles = list(roles)
        self.mention = f"<@{id}>"
        self.display_name = f"m{id}"
        self.display_avatar = types.SimpleNamespace(url="https://cdn/a.png")
        self.agregados, self.quitados = [], []

    async def add_roles(self, *roles, reason=None):
        self.agregados.extend(roles)
        self.roles.extend(roles)

    async def remove_roles(self, *roles, reason=None):
        self.quitados.extend(roles)


def guild_con_roles(perfil, ids_por_key, posicion_bot=100):
    """Servidor de PSS con los roles del TOML (por key) ya creados y mapeados en perfil_recursos."""
    guild = GuildPSS()
    guild.me = types.SimpleNamespace(top_role=RolJerarquia(1, "bot", posicion_bot))
    guild.members = []
    for key, ident in ids_por_key.items():
        rol = RolJerarquia(ident, perfil.config.rol(key).nombre, 1)
        guild.roles.append(rol)
    perfil.ids = dict(ids_por_key)
    return guild


# --- Ajuste A: [rangos] contar_desde -----------------------------------------------------------------------------
def test_inicio_rangos_en_pss_es_la_mas_tardia_entre_la_entrada_y_contar_desde(mod, perfil):
    assert perfil.config.rangos.contar_desde == datetime(2026, 10, 19, tzinfo=UTC)
    guild = GuildPSS()
    antes, despues = datetime(2025, 9, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)
    assert mod.inicio_rangos(guild, antes) == datetime(2026, 10, 19, tzinfo=UTC)      # entro antes: cuenta desde la fecha
    assert mod.inicio_rangos(guild, despues) == despues                               # entro despues: su entrada
    # en EITO (otro servidor) o sin la clave, la fecha de entrada tal cual
    assert mod.inicio_rangos(GuildPSS(5), antes) == antes
    perfil.config = replace(perfil.config, rangos=Rangos())
    assert mod.inicio_rangos(guild, antes) == antes


def test_inicio_rangos_sin_perfil_es_la_entrada(mod, fakes):
    fecha = datetime(2025, 9, 1, tzinfo=UTC)
    assert mod._perfil_de(fakes.Guild()) is None and mod.inicio_rangos(fakes.Guild(), fecha) is fecha


async def test_los_rangos_de_pss_cuentan_desde_contar_desde(mod, perfil, capsys):
    ahora = datetime.now(UTC)
    perfil.config = replace(perfil.config, rangos=Rangos(ahora - timedelta(days=100)))
    guild = guild_con_roles(perfil, {"veterano": 71, "leyenda": 72})
    viejo = Miembro(1, ahora - timedelta(days=400))          # 400 dias en el servidor, pero 100 contados
    nuevo = Miembro(2, ahora - timedelta(days=10))
    guild.members = [viejo, nuevo]
    veteranos, leyendas = await mod.actualizar_rangos_guild(guild)
    assert [m.id for m in veteranos] == [1] and leyendas == []            # 100 dias: Veterano, no Leyenda
    assert [r.id for r in viejo.agregados] == [71] and nuevo.agregados == []
    # con contar_desde hace 200 dias, el mismo miembro es Leyenda
    perfil.config = replace(perfil.config, rangos=Rangos(ahora - timedelta(days=200)))
    viejo.roles, viejo.agregados = [], []
    veteranos, leyendas = await mod.actualizar_rangos_guild(guild)
    assert [m.id for m in leyendas] == [1] and [r.id for r in viejo.agregados] == [72]


async def test_los_rangos_de_eito_siguen_contando_desde_la_entrada(mod, fakes):
    guild = fakes.Guild()
    veterano, leyenda = RolJerarquia(mod.ROL_VETERANO_ID, "V", 1), RolJerarquia(mod.ROL_LEYENDA_ID, "L", 1)
    guild.roles += [veterano, leyenda]
    guild.me = types.SimpleNamespace(top_role=RolJerarquia(1, "bot", 100))
    miembro = Miembro(1, datetime.now(UTC) - timedelta(days=400))
    guild.members = [miembro]
    veteranos, leyendas = await mod.actualizar_rangos_guild(guild)
    assert [m.id for m in leyendas] == [1] and miembro.agregados == [leyenda]


# --- Ajuste D: Activo del mes con 0 candidatos ---------------------------------------------------------------------
async def preparar_activo_mes(mod, perfil, monkeypatch, top):
    guild = guild_con_roles(perfil, {"activo_mes": 81, "developer": 82})
    guild.owner_id = 1
    guild.canales = {31: FTexto(31, "📈・niveles")}
    perfil.ids["niveles"] = 31
    miembros = {1: Miembro(1, guild=guild),                                        # el dueño
                2: Miembro(2, roles=[guild.get_role(82)], guild=guild),            # Developer
                3: Miembro(3, guild=guild), 4: Miembro(4, bot=True, guild=guild)}
    guardados = []

    async def no_premiado(*a):
        return False

    async def top_xp(guild_id, mes, limite):
        return top

    async def obtener(g, uid):
        return miembros.get(uid)

    async def guardar(guild_id, mes, lista):
        guardados.append(lista)

    monkeypatch.setattr(mod, "mes_ya_premiado", no_premiado)
    monkeypatch.setattr(mod, "top_xp_mensual", top_xp)
    monkeypatch.setattr(mod, "obtener_miembro", obtener)
    monkeypatch.setattr(mod, "guardar_ganadores", guardar)
    return guild, miembros, guardados


async def test_activo_del_mes_en_pss_con_todos_excluidos_no_publica_ni_lanza_errores(mod, perfil, monkeypatch, capsys):
    guild, miembros, guardados = await preparar_activo_mes(
        mod, perfil, monkeypatch, [("1", 500), ("2", 400), ("4", 300), ("99", 200)])   # dueño, Developer, bot, ya no esta
    capsys.readouterr()
    assert await mod.premiar_activo_mes_guild(guild, "2026-11") is None            # no lanza
    assert guild.canales[31].enviados == [] and guardados == []                      # no publica ni guarda el mes
    assert all(m.agregados == [] for m in miembros.values())
    assert "Error" not in capsys.readouterr().out


async def test_activo_del_mes_en_pss_premia_a_quien_no_esta_excluido(mod, perfil, monkeypatch):
    guild, miembros, guardados = await preparar_activo_mes(
        mod, perfil, monkeypatch, [("1", 500), ("2", 400), ("3", 300)])
    await mod.premiar_activo_mes_guild(guild, "2026-11")
    assert [r.id for r in miembros[3].agregados] == [81] and miembros[1].agregados == [] == miembros[2].agregados
    assert guardados == [[(3, 1, 300)]]
    assert len(guild.canales[31].enviados) == 1 and "<@3>" in guild.canales[31].enviados[0][0]


# --- Fundador ------------------------------------------------------------------------------------------------------
async def test_el_fundador_que_vuelve_recupera_su_rol_en_pss_y_en_eito(mod, perfil, monkeypatch, fakes):
    guild = guild_con_roles(perfil, {"fundador": 91})
    miembro = Miembro(7, guild=guild)

    async def es_fundador(guild_id, user_id):
        return 3

    monkeypatch.setattr(mod, "get_fundador", es_fundador)
    await mod.devolver_fundador(miembro)
    assert [r.id for r in miembro.agregados] == [91]
    # en EITO, con su propio rol por ID
    g2 = fakes.Guild()
    rol = g2.rol(mod.ROL_FUNDADOR_ID, "🌱 Fundador")
    otro = Miembro(8, guild=g2)
    await mod.devolver_fundador(otro)
    assert otro.agregados == [rol]
    # si no es fundador, nada
    async def no_es(guild_id, user_id):
        return None

    monkeypatch.setattr(mod, "get_fundador", no_es)
    ajeno = Miembro(9, guild=guild)
    await mod.devolver_fundador(ajeno)
    assert ajeno.agregados == []


def test_fundadores_ya_no_esta_bloqueado_y_el_dueno_lo_puede_usar(mod, perfil):
    assert "fundadores" not in perfil.config.comandos_bloqueados
    guild = guild_con_roles(perfil, {"fundador": 91})
    assert mod.rol_de(guild, "fundador").id == 91
    ctx = types.SimpleNamespace(guild=guild, author=types.SimpleNamespace(id=1, roles=[]))
    assert mod.es_dueno_o_developer(ctx) is True


# --- Textos de logros ----------------------------------------------------------------------------------------------
async def test_el_logro_de_og_en_pss_usa_el_nombre_del_servidor_y_apunta_a_antiguedad(mod, perfil):
    guild = guild_con_roles(perfil, {"og": 55})
    guild.name = "Phantom Shadows Studios"
    guild.canales = {31: FTexto(31, "📈・niveles")}
    perfil.ids["niveles"] = 31
    rol = guild.get_role(55)
    miembro = Miembro(9, guild=guild)
    assert await mod.anunciar_logro(miembro, rol, "Reconocido por el staff") is True
    _contenido, kw = guild.canales[31].enviados[0]
    assert kw["embed"].title == "🥇 Nuevo OG de Phantom Shadows Studios"
    assert "EITO" not in kw["embed"].title and "!antiguedad" in kw["embed"].footer.text and "!perfil" not in kw["embed"].footer.text


async def test_el_logro_en_eito_sigue_igual(mod, fakes):
    guild = fakes.Guild()
    guild.canal(mod.CANAL_NIVELES)
    rol = guild.rol(mod.ROL_OG_ID, "🥇 OG")
    rol.members = []
    miembro = fakes.Usuario(9, "Ana")
    miembro.guild = guild
    assert await mod.anunciar_logro(miembro, rol, "x") is True
    embed = guild.text_channels[0].enviados[0][1]["embed"]
    assert embed.title == "🥇 Nuevo OG de EITO" and "Mira tus logros con !perfil" in embed.footer.text


def test_el_resumen_de_rangos_nombra_el_servidor(mod):
    a = types.SimpleNamespace(display_name="A")
    assert "¡Gracias por seguir en EITO!" in mod.texto_resumen_rangos([a], [])               # el de siempre
    assert "¡Gracias por seguir en PSS!" in mod.texto_resumen_rangos([a], [], "PSS")


# --- Tickets ----------------------------------------------------------------------------------------------------------
class Ent:
    """Objeto hashable (los overwrites de un canal usan roles y miembros como claves)."""

    def __init__(self, **datos):
        self.__dict__.update(datos)


class GuildTickets(GuildPSS):
    def __init__(self):
        super().__init__()
        self.default_role = Ent(id=self.id, name="@everyone")
        self.me = Ent(id=1000, top_role=RolJerarquia(1, "bot", 100))
        self.creados = []

    async def create_text_channel(self, nombre, category=None, topic=None, overwrites=None, reason=None):
        canal = FTexto(5000 + len(self.creados), nombre)
        canal.creado_en, canal.tema_creado, canal.overwrites_creados = category, topic, overwrites
        self.creados.append(canal)
        self.canales[canal.id] = canal
        return canal


class Interaccion:
    def __init__(self, guild, usuario):
        self.guild, self.user, self.respuestas = guild, usuario, []
        self.response = types.SimpleNamespace(defer=self._defer)
        self.followup = types.SimpleNamespace(send=self._send)

    async def _defer(self, **kw):
        pass

    async def _send(self, texto, **kw):
        self.respuestas.append(texto)


def guild_de_tickets(perfil, con_categoria=True):
    guild = GuildTickets()
    guild.roles = [FRol(21, "Propietario"), FRol(22, "Administrador")]
    perfil.ids = {"propietario": 21, "administrador": 22, "tickets_log": 33, "registros": 34}
    guild.canales[33], guild.canales[34] = FTexto(33, "📁・tickets-log"), FTexto(34, "🛡️・registros")
    if con_categoria:
        guild.canales[41] = FCategoria(41, "🎫 » TICKETS")
        perfil.ids["cat_tickets"] = 41
    return guild


async def test_abrir_un_ticket_en_pss_usa_la_categoria_y_el_staff_del_toml(mod, perfil):
    guild = guild_de_tickets(perfil)
    usuario = Ent(id=9, name="Ana", mention="<@9>")
    inter = Interaccion(guild, usuario)
    await mod.ticket_abrir(inter)
    canal = guild.creados[0]
    assert canal.name == "ticket-ana" and canal.creado_en is guild.canales[41] and canal.tema_creado == "ticket:9"
    ids = {getattr(k, "id", None) for k in canal.overwrites_creados}
    assert {21, 22, 9, 1000, G_PSS} <= ids                                  # Propietario, Administrador, la persona, el bot, @everyone
    contenido, kw = canal.enviados[0]
    assert "<@&21>" in contenido and "<@&22>" in contenido                  # el ping va a los dos roles del TOML
    assert {r.id for r in kw["allowed_mentions"].roles} == {21, 22}
    assert inter.respuestas == [f"✅ Tu ticket está listo: {canal.mention}"]
    assert guild.canales[34].enviados and "abrió el ticket" in guild.canales[34].enviados[0][0]   # al registro de PSS


async def test_abrir_un_ticket_en_pss_sin_la_categoria_avisa_y_no_crea_nada(mod, perfil):
    guild = guild_de_tickets(perfil, con_categoria=False)
    inter = Interaccion(guild, Ent(id=9, name="Ana", mention="<@9>"))
    await mod.ticket_abrir(inter)
    assert guild.creados == [] and "falta `!pss aplicar`" in inter.respuestas[0]
    assert getattr(guild, "categorias_creadas", []) == []                    # no se inventa una «🎫 TICKETS» de EITO


async def test_cerrar_un_ticket_en_pss_guarda_la_transcripcion_en_tickets_log(mod, perfil, monkeypatch):
    guild = guild_de_tickets(perfil)
    log = guild.canales[33]
    log.permissions_for = lambda rol: types.SimpleNamespace(view_channel=False)
    log.enviados.clear()
    ticket = FTexto(60, "ticket-ana")
    ticket.topic = "ticket:9"

    async def historia(**kw):
        return
        yield

    ticket.history = historia
    ticket.delete = lambda reason=None: _nada()
    guild.canales[60] = ticket
    staff = Ent(id=8, mention="<@8>", guild=guild, roles=[Ent(id=22)])
    inter = Interaccion(guild, staff)
    inter.channel = ticket
    monkeypatch.setattr(mod.asyncio, "sleep", lambda s: _nada())
    await mod.ticket_cerrar(inter)
    assert len(log.enviados) == 1 and "Ticket **ticket-ana**" in log.enviados[0][0]      # transcripcion guardada
    assert "Cerrando el ticket" in inter.respuestas[0]


async def _nada():
    return None


async def test_en_pss_paneltickets_no_toca_los_permisos_de_soporte_ni_transcripciones(mod, perfil, fakes):
    guild = guild_de_tickets(perfil)
    perfil.ids["soporte"] = 35
    soporte = guild.canales[35] = FTexto(35, "🎫・soporte")
    cambios = []

    async def set_permissions(*a, **k):
        cambios.append(a)

    for canal in (soporte, guild.canales[33]):
        canal.set_permissions = set_permissions
    ctx = fakes.Ctx(guild=guild)
    await mod.configurar_canal_soporte(ctx)
    await mod.configurar_canal_transcripciones(ctx)
    assert cambios == [] and ctx.respuestas == []


async def test_en_eito_paneltickets_si_reconfigura_soporte(mod, fakes):
    guild = fakes.Guild()
    soporte = guild.canal(mod.CANAL_SOPORTE)
    llamadas = []

    async def set_permissions(*a, **k):
        llamadas.append(a)

    soporte.set_permissions = set_permissions
    guild.me = types.SimpleNamespace()
    ctx = fakes.Ctx(guild=guild)
    await mod.configurar_canal_soporte(ctx)
    assert llamadas                                                               # EITO: como siempre
