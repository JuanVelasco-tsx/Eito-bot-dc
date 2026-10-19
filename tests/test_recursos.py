"""Resolvedor de roles, canales y categorias (rol_de, roles_de, ids_de, canal_de, categoria_de, recompensas_de).

- En EITO (o sin perfil) devuelve EXACTAMENTE lo de antes: se compara con la expresion antigua.
- Con el perfil PSS saca todo de [recursos] y NUNCA cae a los IDs ni a los nombres de EITO."""

import re
import types
from dataclasses import replace
from pathlib import Path

import discord
import pytest

from profiles import pss_db
from profiles.pss import PerfilPSS
from profiles.pss_config import (
    RECURSOS_CANALES, RECURSOS_CATEGORIAS, RECURSOS_ROLES, Recursos, cargar,
)

RUTA = Path(__file__).resolve().parent.parent / "profiles" / "pss.toml"
FUENTE = Path(__file__).resolve().parent.parent / "eito_setup_bot.py"
G_PSS, OTRO = 1420403964746268684, 5


# --- EITO: identico a antes ---------------------------------------------------------------------------
def guild_eito(mod, fakes):
    """Un servidor con TODOS los roles (por ID) y canales (por nombre) que usa EITO."""
    guild = fakes.Guild()
    ids = {mod.ROL_ACTIVO_MES_ID, mod.ROL_FUNDADOR_ID, mod.ROL_VETERANO_ID, mod.ROL_LEYENDA_ID, mod.ROL_OG_ID,
           mod.ROL_VOZ_ACTIVA_ID, mod.ROL_SUPERVIVIENTE_ID, mod.ROL_CONVOCADOR_ID, mod.ROL_DEVELOPER_ID,
           *mod.ROLES_STAFF_TICKETS, *mod.ROLES_PING_TICKETS, *mod.ROLES_HONOR_IDS}
    for ident in ids:
        guild.rol(ident, f"rol {ident}")
    for nombre in (mod.CANAL_NIVELES, mod.CANAL_LOGROS, mod.CANAL_ANUNCIOS, mod.CANAL_SOPORTE,
                   mod.CANAL_TRANSCRIPCIONES):
        guild.canal(nombre)
    guild.categories = [types.SimpleNamespace(name=mod.CATEGORIA_TICKETS), types.SimpleNamespace(name="otra")]
    return guild


def test_en_eito_cada_clave_de_rol_da_lo_mismo_que_la_expresion_antigua(mod, fakes):
    guild = guild_eito(mod, fakes)
    antiguo = {
        "activo_mes": mod.ROL_ACTIVO_MES_ID, "fundador": mod.ROL_FUNDADOR_ID, "veterano": mod.ROL_VETERANO_ID,
        "leyenda": mod.ROL_LEYENDA_ID, "og": mod.ROL_OG_ID, "voz_activa": mod.ROL_VOZ_ACTIVA_ID,
        "superviviente": mod.ROL_SUPERVIVIENTE_ID, "convocador": mod.ROL_CONVOCADOR_ID,
        "developer": mod.ROL_DEVELOPER_ID,
    }
    for clave, ident in antiguo.items():
        assert mod.rol_de(guild, clave) is guild.get_role(ident), clave
        assert mod.ids_de(guild, clave) == [ident], clave
    listas = {
        "honor": mod.ROLES_HONOR_IDS, "excluidos_activo_mes": [mod.ROL_DEVELOPER_ID],
        "staff_tickets": mod.ROLES_STAFF_TICKETS, "ping_tickets": mod.ROLES_PING_TICKETS,
    }
    for clave, ids in listas.items():
        assert mod.ids_de(guild, clave) == list(ids), clave
        esperado = [r for r in (guild.get_role(i) for i in ids) if r is not None]
        assert mod.roles_de(guild, clave) == esperado, clave
    # las funciones de siempre siguen dando lo mismo
    assert mod.roles_staff_tickets(guild) == mod.roles_de(guild, "staff_tickets")
    assert mod.roles_ping_tickets(guild) == mod.roles_de(guild, "ping_tickets")


def test_en_eito_cada_clave_de_canal_y_categoria_da_lo_mismo_que_antes(mod, fakes):
    guild = guild_eito(mod, fakes)
    antiguo = {"niveles": mod.CANAL_NIVELES, "logros": mod.CANAL_LOGROS, "anuncios": mod.CANAL_ANUNCIOS,
               "soporte": mod.CANAL_SOPORTE, "transcripciones": mod.CANAL_TRANSCRIPCIONES}
    for clave, nombre in antiguo.items():
        assert mod.canal_de(guild, clave) is mod.buscar_canal(guild, nombre), clave
        assert mod.canal_de(guild, clave) is not None
    assert mod.categoria_de(guild, "tickets").name == mod.CATEGORIA_TICKETS
    assert mod.recompensas_de(guild) is mod.NIVEL_RECOMPENSAS
    assert mod._perfil_de(guild) is None


def test_en_eito_un_rol_o_canal_que_no_existe_da_none_o_lista_vacia(mod, fakes):
    guild = fakes.Guild()
    guild.categories = []
    assert mod.rol_de(guild, "activo_mes") is None and mod.roles_de(guild, "staff_tickets") == []
    assert mod.canal_de(guild, "niveles") is None and mod.categoria_de(guild, "tickets") is None
    # sin guild (p. ej. un miembro sin atributo guild) las listas son las de EITO
    assert mod.ids_de(None, "staff_tickets") == list(mod.ROLES_STAFF_TICKETS)


def test_el_resolvedor_lee_las_constantes_al_llamar_no_al_importar(mod, fakes, monkeypatch):
    guild = fakes.Guild()
    monkeypatch.setattr(mod, "ROL_FUNDADOR_ID", 4242)
    monkeypatch.setattr(mod, "ROLES_STAFF_TICKETS", [7, 8])
    monkeypatch.setattr(mod, "CANAL_NIVELES", "otro-nombre")
    rol, canal = guild.rol(4242, "f"), guild.canal("otro-nombre")
    assert mod.rol_de(guild, "fundador") is rol and mod.ids_de(guild, "staff_tickets") == [7, 8]
    assert mod.canal_de(guild, "niveles") is canal


def test_canal_de_tolerante_acepta_el_nombre_sin_selector_de_emoji(mod, fakes, monkeypatch):
    guild = fakes.Guild()
    monkeypatch.setattr(mod, "CANAL_LOGROS", "🏅️・logros")
    canal = guild.canal("🏅・logros")                      # Discord guardo el nombre sin U+FE0F
    assert mod.canal_de(guild, "logros", tolerante=True) is canal
    assert mod.canal_de(guild, "logros") is None            # exacto, como buscar_canal de siempre


def test_el_vocabulario_del_validador_coincide_con_las_tablas_del_bot(mod):
    assert set(RECURSOS_ROLES) == set(mod.IDS_ROLES_EITO)
    assert set(RECURSOS_CANALES) == set(mod.NOMBRES_CANALES_EITO)
    assert set(RECURSOS_CATEGORIAS) == set(mod.NOMBRES_CATEGORIAS_EITO)
    for clave, admite_lista in RECURSOS_ROLES.items():
        if not admite_lista:
            assert len(mod.IDS_ROLES_EITO[clave]()) == 1, clave     # las de un solo rol son de un solo ID
    assert set(mod.CLAVE_ROL_CONTADOR.values()) <= set(mod.IDS_ROLES_EITO)


def test_no_quedan_ids_de_eito_usados_directamente_fuera_de_las_tablas():
    codigo = FUENTE.read_text(encoding="utf-8")
    inicio = codigo.index("# --- RESOLVEDOR de roles")
    fin = codigo.index("def recompensas_de(guild):")
    fuera = codigo[:inicio] + codigo[fin:]
    ids = ("ROL_ACTIVO_MES_ID", "ROL_FUNDADOR_ID", "ROL_VETERANO_ID", "ROL_LEYENDA_ID", "ROL_OG_ID",
           "ROL_VOZ_ACTIVA_ID", "ROL_SUPERVIVIENTE_ID", "ROL_CONVOCADOR_ID")
    for nombre in ids:
        assert not re.search(rf"get_role\(\s*{nombre}\s*\)", fuera), nombre
    assert "== ROL_DEVELOPER_ID" not in fuera                 # es_excluido_activo / es_dueno_o_developer
    assert not re.search(r"in (ROLES_STAFF_TICKETS|ROLES_HONOR_IDS)\b", fuera)
    assert not re.search(r"for \w+ in (ROLES_STAFF_TICKETS|ROLES_PING_TICKETS)", fuera)


def test_las_claves_que_usa_el_codigo_existen_en_las_tablas(mod):
    codigo = FUENTE.read_text(encoding="utf-8")
    usadas = {(f, c) for f, c in re.findall(r"\b(rol_de|roles_de|ids_de|canal_de|categoria_de)\([^,()]+(?:\([^()]*\))?,\s*\"(\w+)\"", codigo)}
    assert usadas
    tablas = {"rol_de": mod.IDS_ROLES_EITO, "roles_de": mod.IDS_ROLES_EITO, "ids_de": mod.IDS_ROLES_EITO,
              "canal_de": mod.NOMBRES_CANALES_EITO, "categoria_de": mod.NOMBRES_CATEGORIAS_EITO}
    for funcion, clave in usadas:
        assert clave in tablas[funcion], (funcion, clave)


# --- PSS: todo sale de [recursos] y no cae a EITO -------------------------------------------------------------
class FTexto(discord.TextChannel):
    def __init__(self, id, nombre):
        self.id, self.name, self.enviados = id, nombre, []

    async def send(self, content=None, **kwargs):
        self.enviados.append((content, kwargs))


class FCategoria(discord.CategoryChannel):
    def __init__(self, id, nombre):
        self.id, self.name = id, nombre


class FRol:
    def __init__(self, id, nombre="rol"):
        self.id, self.name = id, nombre
        self.mention = f"<@&{id}>"


class GuildPSS:
    def __init__(self, id=G_PSS):
        self.id, self.name, self.owner_id = id, "PSS", 1
        self.roles, self.canales, self.categories = [], {}, []

    @property
    def text_channels(self):
        return [c for c in self.canales.values() if isinstance(c, discord.TextChannel)]

    def get_role(self, ident):
        return next((r for r in self.roles if r.id == ident), None)

    def get_channel(self, ident):
        return self.canales.get(ident)


@pytest.fixture
def sin_bd(monkeypatch):
    async def nada(*a, **k):
        return None

    async def mapa(guild_id):
        return {}

    monkeypatch.setattr(pss_db, "asegurar_tabla", nada)
    monkeypatch.setattr(pss_db, "cargar_mapa", mapa)


@pytest.fixture
async def perfil(mod, sin_bd):
    cog = PerfilPSS(mod.bot, cargar(RUTA), RUTA)
    await mod.bot.add_cog(cog)
    yield cog
    await mod.bot.remove_cog("PerfilPSS")


def con_recursos(perfil, roles=None, canales=None, categorias=None, ids=None):
    perfil.config = replace(perfil.config, recursos=Recursos(roles or {}, canales or {}, categorias or {}))
    perfil.ids = ids or {}


def guild_pss_con_todo_de_eito(mod):
    """Servidor de PSS que, por casualidad, tiene los IDs y los nombres de EITO: NO deben usarse."""
    guild = GuildPSS()
    ids = {mod.ROL_ACTIVO_MES_ID, mod.ROL_FUNDADOR_ID, mod.ROL_VETERANO_ID, mod.ROL_LEYENDA_ID, mod.ROL_OG_ID,
           mod.ROL_VOZ_ACTIVA_ID, mod.ROL_DEVELOPER_ID, *mod.ROLES_STAFF_TICKETS}
    guild.roles = [FRol(i) for i in ids]
    for n, nombre in enumerate((mod.CANAL_NIVELES, mod.CANAL_LOGROS, mod.CANAL_ANUNCIOS, mod.CANAL_SOPORTE,
                                mod.CANAL_TRANSCRIPCIONES), start=100):
        guild.canales[n] = FTexto(n, nombre)
    guild.canales[200] = FCategoria(200, mod.CATEGORIA_TICKETS)
    guild.categories = [guild.canales[200]]
    return guild


def test_en_pss_una_clave_sin_mapear_no_cae_a_los_ids_ni_nombres_de_eito(mod, perfil):
    con_recursos(perfil)
    guild = guild_pss_con_todo_de_eito(mod)
    assert mod._perfil_de(guild) is perfil
    for clave in mod.IDS_ROLES_EITO:
        assert mod.ids_de(guild, clave) == [] and mod.roles_de(guild, clave) == [], clave
        assert mod.rol_de(guild, clave) is None, clave
    for clave in mod.NOMBRES_CANALES_EITO:
        assert mod.canal_de(guild, clave) is None and mod.canal_de(guild, clave, tolerante=True) is None, clave
    assert mod.categoria_de(guild, "tickets") is None
    assert mod.recompensas_de(guild) == ()


def test_en_pss_las_claves_mapeadas_salen_de_perfil_recursos(mod, perfil):
    con_recursos(
        perfil,
        roles={"veterano": ("vet",), "staff_tickets": ("prop", "admin"), "ping_tickets": ("admin",)},
        canales={"niveles": "niv", "anuncios": "anu"}, categorias={"tickets": "cat_t"},
        ids={"vet": 11, "prop": 21, "admin": 22, "niv": 31, "anu": 32, "cat_t": 41})
    guild = GuildPSS()
    guild.roles = [FRol(11), FRol(21), FRol(22)]
    guild.canales = {31: FTexto(31, "x"), 32: FTexto(32, "y"), 41: FCategoria(41, "t")}
    assert mod.rol_de(guild, "veterano") is guild.get_role(11)
    assert mod.ids_de(guild, "staff_tickets") == [21, 22]
    assert [r.id for r in mod.roles_de(guild, "ping_tickets")] == [22]
    assert mod.canal_de(guild, "niveles") is guild.canales[31] and mod.canal_de(guild, "anuncios") is guild.canales[32]
    assert mod.categoria_de(guild, "tickets") is guild.canales[41]
    assert mod.rol_de(guild, "leyenda") is None                              # lo no mapeado, None
    # aun no creado (sin ID en perfil_recursos) o de otro tipo: None
    perfil.ids.pop("vet")
    assert mod.rol_de(guild, "veterano") is None
    guild.canales[31] = FCategoria(31, "no es un canal de texto")
    assert mod.canal_de(guild, "niveles") is None
    # y en otro servidor (EITO) el perfil no interviene
    assert mod.ids_de(GuildPSS(OTRO), "staff_tickets") == list(mod.ROLES_STAFF_TICKETS)


def test_los_logros_de_pss_caen_al_canal_de_niveles(mod, perfil):
    """B: PSS no tiene 🏅・logros; el respaldo que ya existe manda los logros a 📈・niveles."""
    con_recursos(perfil, canales={"niveles": "niv"}, ids={"niv": 31})
    guild = guild_pss_con_todo_de_eito(mod)           # incluye un canal llamado como el de logros de EITO
    niveles = FTexto(31, "📈・niveles")
    guild.canales[31] = niveles
    assert mod.canal_logros(guild) is niveles          # no el canal "🏅・logros" por nombre
    # con un canal de logros mapeado, ese manda
    con_recursos(perfil, canales={"niveles": "niv", "logros": "log"}, ids={"niv": 31, "log": 32})
    guild.canales[32] = FTexto(32, "🏅・logros")
    assert mod.canal_logros(guild) is guild.canales[32]


async def test_un_logro_en_pss_se_anuncia_en_el_canal_de_niveles(mod, perfil):
    con_recursos(perfil, canales={"niveles": "niv"}, ids={"niv": 31})
    guild = GuildPSS()
    niveles = guild.canales[31] = FTexto(31, "📈・niveles")
    miembro = types.SimpleNamespace(
        guild=guild, mention="<@9>", id=9, display_avatar=types.SimpleNamespace(url="https://cdn/a.png"))
    rol = types.SimpleNamespace(id=555, name="🥉 Veterano", colour=discord.Colour(0xCD7F32), members=[])
    assert await mod.anunciar_logro(miembro, rol, "motivo") is True
    assert len(niveles.enviados) == 1 and "Felicidades" in niveles.enviados[0][0]


# --- Gates: en PSS los sistemas sin mapear no hacen nada, ni avisan en consola --------------------------------
async def test_los_loops_de_rangos_y_activo_del_mes_no_hacen_nada_en_pss_sin_mapear(mod, perfil, monkeypatch, capsys):
    con_recursos(perfil)
    guild = guild_pss_con_todo_de_eito(mod)
    capsys.readouterr()                                   # descarta lo que imprimio la carga del cog

    async def no_premiado(*a):
        return False

    monkeypatch.setattr(mod, "mes_ya_premiado", no_premiado)
    assert await mod.actualizar_rangos_guild(guild) == ([], [])
    assert await mod.premiar_activo_mes_guild(guild, "2026-09") is None
    for tipo, _umbral, rol_id in mod.RANGOS_POR_CONTADOR:
        assert mod.rol_de_contador(guild, tipo, rol_id) is None
    await mod.revisar_umbrales_guild(guild)
    assert capsys.readouterr().out == ""                  # ni un aviso por roles que no existen en PSS


class _Rol:
    """Rol con posicion para comparar jerarquia (guild.me.top_role <= rol)."""

    def __init__(self, id, nombre="r", posicion=0):
        self.id, self.name, self.position = id, nombre, posicion

    def __le__(self, otro):
        return self.position <= otro.position


def test_rol_de_contador_en_pss_usa_el_rol_mapeado_y_respeta_la_jerarquia(mod, perfil, capsys):
    con_recursos(perfil, roles={"voz_activa": ("voz",)}, ids={"voz": 61})
    guild = GuildPSS()
    guild.roles = [_Rol(61, "🎧 Voz activa", 10)]
    guild.me = types.SimpleNamespace(top_role=_Rol(100, "bot", 100))
    # el ID de EITO (ROL_VOZ_ACTIVA_ID) que llega como argumento se ignora: manda el mapeado
    assert mod.rol_de_contador(guild, "voz_minutos", mod.ROL_VOZ_ACTIVA_ID).id == 61
    assert mod.rol_de_contador(guild, "partidas", mod.ROL_SUPERVIVIENTE_ID) is None     # sin mapear: no aplica
    guild.me = types.SimpleNamespace(top_role=_Rol(100, "bot", 5))                      # el bot queda por debajo
    capsys.readouterr()
    assert mod.rol_de_contador(guild, "voz_minutos", 0) is None
    assert "debe estar por encima" in capsys.readouterr().out


async def test_xp_en_pss_a_nivel_10_sin_recompensas_mapeadas_no_anuncia_ni_asigna_nada(mod, perfil, monkeypatch):
    """C, con el pss.toml DEFINITIVO: xp = true, niveles mapeado y ninguna recompensa. Cruzar el nivel 10
    solo da el aviso de nivel en 📈・niveles; ni rol ni canal ni anuncio de «desbloqueó»."""
    assert perfil.config.eventos.xp is True and perfil.config.recursos.canales["niveles"] == "niveles"
    perfil.ids = {"niveles": 31}                                       # lo unico que añade el aplicar
    guild = guild_pss_con_todo_de_eito(mod)
    niveles = guild.canales[31] = FTexto(31, "📈・niveles")
    guild.roles.append(FRol(900, "🔓 Nivel 10"))                     # existen, con los nombres de EITO
    canal_nivel = guild.canales[901] = FTexto(901, "🔓・nivel-10")
    asignados = []

    async def add_roles(*roles, **kw):
        asignados.extend(roles)

    miembro = types.SimpleNamespace(guild=guild, id=9, mention="<@9>", roles=[], add_roles=add_roles)

    async def get_xp(g, u):
        return mod.xp_acumulada(10) - 1

    async def add_xp(g, u, cantidad):
        return mod.xp_acumulada(10) + 20

    async def sin_efecto(*a, **k):
        return None

    monkeypatch.setattr(mod, "get_user_xp", get_xp)
    monkeypatch.setattr(mod, "add_user_xp", add_xp)
    monkeypatch.setattr(mod, "add_xp_mensual", sin_efecto)
    assert mod.evento_permitido(guild, "xp") is True
    assert await mod.sumar_xp(miembro, 21) == mod.xp_acumulada(10) + 20
    assert [c for c, _kw in niveles.enviados] == [mod.AVISO_NIVEL.format(mencion="<@9>", nivel=10)]
    assert asignados == [] and canal_nivel.enviados == []            # ni rol ni anuncio de «desbloqueó»


async def test_en_eito_el_mismo_cruce_de_nivel_sigue_dando_el_rol_y_el_anuncio(mod):
    rol_nivel, canal_nivel = FRol(900, "🔓 Nivel 10"), FTexto(901, "🔓・nivel-10")
    guild = types.SimpleNamespace(id=OTRO, roles=[rol_nivel], text_channels=[canal_nivel])
    asignados = []

    async def add_roles(*roles, **kw):
        asignados.extend(roles)

    miembro = types.SimpleNamespace(id=9, mention="<@9>", roles=[], add_roles=add_roles)
    await mod.otorgar_recompensas(guild, miembro, 9, 10, None)
    assert asignados == [rol_nivel] and len(canal_nivel.enviados) == 1
    assert "desbloqueó" in canal_nivel.enviados[0][0]


def test_es_excluido_activo_en_pss_usa_la_lista_del_toml(mod, perfil):
    con_recursos(perfil, roles={"excluidos_activo_mes": ("developer",)}, ids={"developer": 77})
    guild = GuildPSS()

    def miembro(id, *roles, bot=False):
        return types.SimpleNamespace(id=id, bot=bot, roles=[types.SimpleNamespace(id=r) for r in roles])

    assert mod.es_excluido_activo(guild, miembro(1))                          # el dueño
    assert mod.es_excluido_activo(guild, miembro(2, 77))                      # el rol del TOML
    assert mod.es_excluido_activo(guild, miembro(3, bot=True))
    assert not mod.es_excluido_activo(guild, miembro(4, mod.ROL_DEVELOPER_ID))   # el de EITO no cuenta en PSS
    assert not mod.es_excluido_activo(guild, miembro(5))


def test_es_dueno_o_developer_en_pss_solo_el_dueno_si_developer_no_esta_mapeado(mod, perfil):
    con_recursos(perfil)
    guild = GuildPSS()

    def ctx(id, *roles):
        return types.SimpleNamespace(guild=guild, author=types.SimpleNamespace(
            id=id, roles=[types.SimpleNamespace(id=r) for r in roles]))

    assert mod.es_dueno_o_developer(ctx(1)) is True
    assert mod.es_dueno_o_developer(ctx(2, mod.ROL_DEVELOPER_ID)) is False
    con_recursos(perfil, roles={"developer": ("developer",)}, ids={"developer": 77})
    assert mod.es_dueno_o_developer(ctx(2, 77)) is True


def test_es_staff_ticket_usa_el_servidor_del_miembro(mod, perfil):
    guild = GuildPSS()
    con_recursos(perfil, roles={"staff_tickets": ("prop", "admin")}, ids={"prop": 21, "admin": 22})
    miembro = types.SimpleNamespace(guild=guild, roles=[types.SimpleNamespace(id=22)])
    assert mod.es_staff_ticket(miembro) is True
    assert mod.es_staff_ticket(types.SimpleNamespace(guild=guild, roles=[types.SimpleNamespace(id=mod.ROLES_STAFF_TICKETS[0])])) is False
    # sin guild en el miembro (o en otro servidor) valen los de EITO, como siempre
    assert mod.es_staff_ticket(types.SimpleNamespace(roles=[types.SimpleNamespace(id=mod.ROLES_STAFF_TICKETS[0])])) is True


async def test_anuncio_en_pss_publica_en_el_canal_mapeado(mod, fakes, perfil):
    con_recursos(perfil, canales={"anuncios": "anu"}, ids={"anu": 32})
    guild = GuildPSS()
    anuncios = guild.canales[32] = FTexto(32, "📣・anuncios")
    anuncios.permissions_for = lambda m: types.SimpleNamespace(mention_everyone=False)
    ctx = fakes.Ctx(guild=guild)
    await mod.anuncio.callback(ctx, texto="hola")
    assert len(anuncios.enviados) == 1 and anuncios.enviados[0][1]["embed"].description == "hola"
    # sin el canal mapeado: no lo busca por nombre, avisa
    con_recursos(perfil)
    ctx = fakes.Ctx(guild=guild)
    await mod.anuncio.callback(ctx, texto="hola")
    assert "No encuentro el canal" in ctx.respuestas[0][0]


# --- El perfil: metodos del resolvedor y el TOML real -------------------------------------------------------------
def test_el_toml_real_mapea_los_recursos_de_la_fase_2():
    recursos = cargar(RUTA).recursos
    assert recursos.canales == {"anuncios": "anuncios", "niveles": "niveles", "soporte": "soporte",
                                "transcripciones": "tickets_log"}
    assert recursos.categorias == {"tickets": "cat_tickets"}
    assert set(recursos.roles) == {"activo_mes", "fundador", "veterano", "leyenda", "og", "honor",
                                   "excluidos_activo_mes", "staff_tickets", "ping_tickets"}


def test_recompensas_del_perfil_son_ninguna_por_ahora(perfil):
    assert perfil.recompensas(GuildPSS()) == ()
