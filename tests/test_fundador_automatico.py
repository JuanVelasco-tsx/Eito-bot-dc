"""Fundador automatico en PSS y su convivencia con `!fundadores confirmar`.

La BD se sustituye por una tabla en memoria con el MISMO algoritmo que database.registrar_fundadores_con_cupo
(las pruebas con PostgreSQL real, incluida la concurrencia, estan en test_fundadores_cupo.py)."""

import types
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_fase2 import Miembro, RolJerarquia, guild_con_roles
from tests.test_recursos import GuildPSS, perfil, sin_bd  # noqa: F401

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


class Tabla:
    """fundadores en memoria: {guild_id: {user_id (texto): puesto}}."""

    def __init__(self):
        self.filas = {}
        self.llamadas = []

    async def listar(self, guild_id):
        self.llamadas.append("listar")
        return dict(self.filas.get(guild_id, {}))

    async def registrar(self, guild_id, lista, maximo):
        self.llamadas.append("registrar")
        existentes = self.filas.setdefault(guild_id, {})
        puesto, libres, nuevos = max(existentes.values(), default=0), maximo - len(existentes), {}
        for user_id, _joined in lista:
            uid = str(user_id)
            if libres <= 0:
                break
            if uid in existentes or uid in nuevos:
                continue
            puesto += 1
            libres -= 1
            existentes[uid] = nuevos[uid] = puesto
        return nuevos

    async def guardar(self, guild_id, lista):
        self.llamadas.append("guardar")
        existentes = self.filas.setdefault(guild_id, {})
        for user_id, puesto, _joined in lista:
            existentes.setdefault(str(user_id), puesto)

    async def hay(self, guild_id):
        return bool(self.filas.get(guild_id))

    async def get(self, guild_id, user_id):
        return self.filas.get(guild_id, {}).get(str(user_id))


@pytest.fixture
def tabla(mod, monkeypatch):
    t = Tabla()
    monkeypatch.setattr(mod, "listar_fundadores", t.listar)
    monkeypatch.setattr(mod, "registrar_fundadores_con_cupo", t.registrar)
    monkeypatch.setattr(mod, "guardar_fundadores", t.guardar)
    monkeypatch.setattr(mod, "hay_fundadores", t.hay)
    monkeypatch.setattr(mod, "get_fundador", t.get)
    return t


def entrada_pss(mod, perfil, tabla):
    """Servidor de PSS con el rol Fundador, y el perfil sin anti-multicuentas ni bienvenida (solo el rol)."""
    from dataclasses import replace
    guild = guild_con_roles(perfil, {"fundador": 91})
    guild.id = perfil.config.guild_id
    perfil.config = replace(perfil.config, eventos=replace(
        perfil.config.eventos, anti_multicuentas=False, rol_al_entrar="", bienvenida=""))
    return guild


def nuevo(guild, ident, bot=False, dias=0):
    return Miembro(ident, BASE + timedelta(days=dias), bot=bot, guild=guild)


# --- Al entrar --------------------------------------------------------------------------------------------------
async def test_quien_entra_recibe_fundador_con_el_siguiente_puesto(mod, perfil, tabla):
    guild = entrada_pss(mod, perfil, tabla)
    a, b = nuevo(guild, 1), nuevo(guild, 2)
    await mod.on_member_join(a)
    await mod.on_member_join(b)
    assert [r.id for r in a.agregados] == [91] and [r.id for r in b.agregados] == [91]
    assert tabla.filas[guild.id] == {"1": 1, "2": 2}


async def test_al_llegar_a_100_se_cierra_solo(mod, perfil, tabla):
    guild = entrada_pss(mod, perfil, tabla)
    tabla.filas[guild.id] = {str(1000 + i): i + 1 for i in range(99)}          # ya hay 99
    centesimo, siguiente = nuevo(guild, 1), nuevo(guild, 2)
    await mod.on_member_join(centesimo)
    await mod.on_member_join(siguiente)
    assert [r.id for r in centesimo.agregados] == [91] and tabla.filas[guild.id]["1"] == 100
    assert siguiente.agregados == [] and "2" not in tabla.filas[guild.id] and len(tabla.filas[guild.id]) == 100


async def test_no_lo_reciben_los_bots_los_expulsados_ni_si_el_evento_esta_apagado(mod, perfil, tabla, monkeypatch):
    from dataclasses import replace
    guild = entrada_pss(mod, perfil, tabla)
    bot = nuevo(guild, 1, bot=True)
    await mod.on_member_join(bot)
    # el anti-multicuentas expulsa: al_entrar devuelve False y no se guarda nada
    perfil.config = replace(perfil.config, eventos=replace(perfil.config.eventos, anti_multicuentas=True))

    class Anti:
        async def filtrar_miembro(self, m):
            return False

    original = mod.bot.get_cog
    monkeypatch.setattr(mod.bot, "get_cog", lambda n: Anti() if n == "AntiMulticuentas" else original(n))
    expulsado = nuevo(guild, 2)
    await mod.on_member_join(expulsado)
    # evento apagado en el TOML
    perfil.config = replace(perfil.config, eventos=replace(
        perfil.config.eventos, anti_multicuentas=False, fundador_automatico=False))
    normal = nuevo(guild, 3)
    await mod.on_member_join(normal)
    assert tabla.filas.get(guild.id, {}) == {}
    assert bot.agregados == expulsado.agregados == normal.agregados == []


async def test_sin_el_rol_o_sin_jerarquia_no_se_guarda_a_nadie(mod, perfil, tabla):
    guild = entrada_pss(mod, perfil, tabla)
    guild.me.top_role = RolJerarquia(1, "bot", 0)                   # el bot queda por debajo del rol
    a = nuevo(guild, 1)
    assert await mod.asignar_fundador_automatico(a) is None
    guild.roles.clear()                                             # el rol ni existe
    assert await mod.asignar_fundador_automatico(nuevo(guild, 2)) is None
    assert tabla.filas.get(guild.id, {}) == {} and a.agregados == []


async def test_un_fallo_al_dar_el_rol_no_rompe_la_entrada(mod, perfil, tabla, capsys):
    guild = entrada_pss(mod, perfil, tabla)
    a = nuevo(guild, 1)

    async def falla(*r, **k):
        raise RuntimeError("sin permisos")

    a.add_roles = falla
    await mod.on_member_join(a)                                     # no lanza
    assert "No pude asignar el Fundador automatico" in capsys.readouterr().out


async def test_el_fundador_que_vuelve_recupera_el_rol_sin_ocupar_otro_puesto(mod, perfil, tabla):
    guild = entrada_pss(mod, perfil, tabla)
    tabla.filas[guild.id] = {"7": 1}
    vuelve = nuevo(guild, 7)
    await mod.on_member_join(vuelve)
    assert [r.id for r in vuelve.agregados] == [91] and tabla.filas[guild.id] == {"7": 1}


async def test_en_eito_nadie_recibe_fundador_automatico(mod, fakes, tabla, monkeypatch):
    guild = fakes.Guild()
    guild.rol(int(mod.ROL_AUTOMATICO), "COMUNIDAD")
    guild.canal(mod.CANAL_BIENVENIDA)
    guild.member_count = 3
    monkeypatch.setattr(mod.bot, "get_cog", lambda n: None)

    class Nuevo:
        id, bot, mention, name = 7, False, "<@7>", "Ana"
        display_avatar = types.SimpleNamespace(url="https://cdn/a.png")

        async def add_roles(self, *r, **k):
            pass

    Nuevo.guild = guild
    await mod.on_member_join(Nuevo())
    assert "registrar" not in tabla.llamadas and tabla.filas == {}


# --- !fundadores convive con lo automatico ------------------------------------------------------------------
def poblar(guild, n, desde=0):
    guild.members = [Miembro(100 + i, BASE + timedelta(days=desde + i), guild=guild) for i in range(n)]
    guild.chunked = True
    return guild.members


def ctx_de(mod, fakes, guild):
    ctx = fakes.Ctx(guild=guild)
    return ctx


async def test_confirmar_en_pss_completa_la_lista_con_los_actuales_y_sigue_los_puestos(mod, fakes, perfil, tabla):
    guild = entrada_pss(mod, perfil, tabla)
    miembros = poblar(guild, 6)
    tabla.filas[guild.id] = {"100": 1, "101": 2}                    # ya entraron dos con el automatico
    ctx = ctx_de(mod, fakes, guild)
    await mod.fundadores.callback(ctx, "confirmar")
    assert tabla.filas[guild.id] == {"100": 1, "101": 2, "102": 3, "103": 4, "104": 5, "105": 6}   # sin duplicar a nadie
    assert [m.id for m in miembros if m.agregados] == [102, 103, 104, 105]                         # solo a los nuevos
    assert "Fundadores guardados: **4**" in ctx.respuestas[-1][0]


async def test_confirmar_en_pss_nunca_pasa_de_100(mod, fakes, perfil, tabla):
    guild = entrada_pss(mod, perfil, tabla)
    poblar(guild, 30)
    tabla.filas[guild.id] = {str(5000 + i): i + 1 for i in range(90)}      # 90 guardados: caben 10 mas
    await mod.fundadores.callback(ctx_de(mod, fakes, guild), "confirmar")
    assert len(tabla.filas[guild.id]) == 100
    assert sorted(v for v in tabla.filas[guild.id].values()) == list(range(1, 101))     # puestos 1..100 sin repetir
    asignados = [m for m in guild.members if m.agregados]
    assert [m.id for m in asignados] == [100 + i for i in range(10)]                    # los 10 mas antiguos


async def test_confirmar_con_100_ya_guardados_avisa_y_no_toca_nada(mod, fakes, perfil, tabla):
    guild = entrada_pss(mod, perfil, tabla)
    poblar(guild, 5)
    tabla.filas[guild.id] = {str(5000 + i): i + 1 for i in range(100)}
    ctx = ctx_de(mod, fakes, guild)
    await mod.fundadores.callback(ctx, "confirmar")
    assert ctx.respuestas[-1][0] == "❌ Ya hay 100 fundadores." and "registrar" not in tabla.llamadas


async def test_la_vista_previa_en_pss_sigue_la_numeracion_y_no_escribe(mod, fakes, perfil, tabla):
    guild = entrada_pss(mod, perfil, tabla)
    poblar(guild, 3)
    tabla.filas[guild.id] = {"1": 1, "2": 2}
    ctx = ctx_de(mod, fakes, guild)
    await mod.fundadores.callback(ctx, None)
    descripcion = ctx.respuestas[-1][1]["embed"].description
    assert "**#3** <@100>" in descripcion and "**#5** <@102>" in descripcion
    assert tabla.filas[guild.id] == {"1": 1, "2": 2} and "registrar" not in tabla.llamadas


async def test_si_alguien_ocupa_el_cupo_a_la_vez_solo_se_da_el_rol_a_quien_se_guardo(mod, fakes, perfil, tabla, monkeypatch):
    guild = entrada_pss(mod, perfil, tabla)
    miembros = poblar(guild, 4)

    async def con_carrera(guild_id, lista, maximo):
        # entre la lectura y el guardado entra otro y ocupa 2 puestos: solo caben los dos primeros
        tabla.filas.setdefault(guild_id, {}).update({"x1": 1, "x2": 2})
        return await tabla.registrar(guild_id, lista, 4)

    monkeypatch.setattr(mod, "registrar_fundadores_con_cupo", con_carrera)
    await mod.fundadores.callback(ctx_de(mod, fakes, guild), "confirmar")
    assert [m.id for m in miembros if m.agregados] == [100, 101] and len(tabla.filas[guild.id]) == 4


# --- EITO: igual que siempre ---------------------------------------------------------------------------------------
def guild_eito(mod, fakes, n):
    guild = fakes.Guild()
    rol = RolJerarquia(mod.ROL_FUNDADOR_ID, "🌱 Fundador", 1)
    guild.roles.append(rol)
    guild.me = types.SimpleNamespace(top_role=RolJerarquia(1, "bot", 100))
    miembros = poblar(guild, n)
    miembros.append(Miembro(999, BASE, bot=True, guild=guild))               # un bot: nunca
    return guild, miembros


async def test_en_eito_confirmar_guarda_los_100_primeros_y_se_cierra(mod, fakes, tabla):
    guild, miembros = guild_eito(mod, fakes, 130)
    ctx = fakes.Ctx(guild=guild)
    await mod.fundadores.callback(ctx, "confirmar")
    assert tabla.llamadas == ["guardar"]                                    # camino de siempre: ni listar ni registrar
    assert len(tabla.filas[guild.id]) == 100 and tabla.filas[guild.id]["100"] == 1 and tabla.filas[guild.id]["199"] == 100
    assert "999" not in tabla.filas[guild.id]
    ctx2 = fakes.Ctx(guild=guild)
    await mod.fundadores.callback(ctx2, "confirmar")
    assert ctx2.respuestas[-1][0] == "❌ Los fundadores ya fueron asignados."
    assert len(tabla.filas[guild.id]) == 100


async def test_en_eito_la_vista_previa_numera_desde_1(mod, fakes, tabla):
    guild, _ = guild_eito(mod, fakes, 3)
    ctx = fakes.Ctx(guild=guild)
    await mod.fundadores.callback(ctx, None)
    descripcion = ctx.respuestas[-1][1]["embed"].description
    assert "**#1** <@100>" in descripcion and "**#3** <@102>" in descripcion and tabla.llamadas == []
