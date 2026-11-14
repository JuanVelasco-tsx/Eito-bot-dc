"""🎧 Voz activa en PSS (`voz = true`): mismo umbral (50 h) y mismo tope diario (6 h) que en EITO, y que activar
la voz solo enciende lo previsto (contadores de voz, XP por voz y el rol)."""

import types
from dataclasses import replace

import pytest

from tests.test_fase2 import Miembro, RolJerarquia, guild_con_roles
from tests.test_recursos import FTexto, perfil, sin_bd  # noqa: F401


class Voz:
    def __init__(self, sordo=False):
        self.self_deaf, self.deaf = sordo, False


def miembro_en_voz(guild, ident, sordo=False, bot=False):
    m = Miembro(ident, guild=guild, bot=bot)
    m.voice = Voz(sordo)
    return m


class Canal:
    def __init__(self, ident, miembros):
        self.id, self.members = ident, miembros

    def __repr__(self):
        return f"Canal({self.id})"


@pytest.fixture
def servidor(mod, perfil):
    guild = guild_con_roles(perfil, {"voz_activa": 71})
    guild.afk_channel = None
    guild.voice_channels = []
    guild.canales = {31: FTexto(31, "📈・niveles")}
    perfil.ids["niveles"] = 31
    guild.get_member = lambda ident: next((m for m in guild.members if m.id == ident), None)
    return guild


@pytest.fixture
def contadores(mod, monkeypatch):
    """Contadores en memoria con la MISMA semantica atomica que database.incrementar_contador_con_tope."""
    estado = {"valores": {}, "topes": []}

    async def con_tope(guild_id, user_id, tipo, tope, n):
        estado["topes"].append((tipo.split(":")[0], tope, n))
        actual = estado["valores"].get((str(user_id), tipo), 0)
        if actual + n > tope:
            return None
        estado["valores"][(str(user_id), tipo)] = actual + n
        return actual + n

    async def incrementar(guild_id, user_id, tipo, n=1):
        clave = (str(user_id), tipo)
        estado["valores"][clave] = estado["valores"].get(clave, 0) + n
        return estado["valores"][clave]

    xp = []

    async def sumar_xp(miembro, cantidad, canal_fallback=None):
        xp.append((miembro.id, cantidad))
        return cantidad

    monkeypatch.setattr(mod, "incrementar_contador_con_tope", con_tope)
    monkeypatch.setattr(mod, "incrementar_contador", incrementar)
    monkeypatch.setattr(mod, "sumar_xp", sumar_xp)
    estado["xp"] = xp
    return estado


def test_el_umbral_y_el_tope_son_los_mismos_en_eito_y_en_pss(mod):
    assert ("voz_minutos", 3000, mod.ROL_VOZ_ACTIVA_ID) in mod.RANGOS_POR_CONTADOR      # 50 h
    assert mod.motivo_umbral("voz_minutos", 3000) == "50 horas en voz"
    assert mod.TOPE_VOZ_DIARIO == 360 and mod.VOZ_MINUTOS_TICK == 5                      # 6 h/dia; ticks de 5 min
    assert mod.CLAVE_ROL_CONTADOR["voz_minutos"] == "voz_activa"


async def test_en_pss_la_voz_cuenta_con_el_tope_diario_de_eito(mod, perfil, servidor, contadores):
    a, b = miembro_en_voz(servidor, 1), miembro_en_voz(servidor, 2)
    servidor.members = [a, b]
    servidor.voice_channels = [Canal(500, [a, b])]
    assert perfil.permite(servidor, "voz") is True
    for _ in range(80):                                  # 80 ticks de 5 min = 400 min, pero solo 360 cuentan
        await mod.contar_voz_guild(servidor)
    assert contadores["valores"][("1", "voz_minutos")] == 360 == contadores["valores"][("2", "voz_minutos")]
    assert {t for t in contadores["topes"]} == {("voz_dia", 360, 5)}                    # tope = TOPE_VOZ_DIARIO, tick = 5
    assert len([x for x in contadores["xp"] if x[0] == 1]) == 72                         # y la XP, solo de los ticks contados
    assert all(cantidad == 5 for _m, cantidad in contadores["xp"])                     # 1 XP por minuto


async def test_con_voz_apagada_no_se_cuenta_nada(mod, perfil, servidor, contadores):
    perfil.config = replace(perfil.config, eventos=replace(perfil.config.eventos, voz=False))
    a, b = miembro_en_voz(servidor, 1), miembro_en_voz(servidor, 2)
    servidor.voice_channels = [Canal(500, [a, b])]
    await mod.contar_voz_guild(servidor)
    assert contadores["valores"] == {} and contadores["xp"] == []


async def test_solo_cuenta_quien_esta_acompanado_y_sin_ensordecer_y_no_el_canal_afk(mod, perfil, servidor, contadores):
    solo = miembro_en_voz(servidor, 1)
    sordo, compa = miembro_en_voz(servidor, 2, sordo=True), miembro_en_voz(servidor, 3)
    bot, uno = miembro_en_voz(servidor, 4, bot=True), miembro_en_voz(servidor, 5)
    afk1, afk2 = miembro_en_voz(servidor, 6), miembro_en_voz(servidor, 7)
    servidor.afk_channel = types.SimpleNamespace(id=999)
    servidor.voice_channels = [Canal(500, [solo]), Canal(501, [sordo, compa]), Canal(502, [bot, uno]),
                               Canal(999, [afk1, afk2])]
    await mod.contar_voz_guild(servidor)
    assert contadores["valores"] == {}                      # nadie esta acompanado de verdad ni fuera del AFK


async def test_a_las_50_horas_se_da_voz_activa_y_se_anuncia_en_niveles(mod, perfil, servidor, contadores):
    m = miembro_en_voz(servidor, 1)
    servidor.members = [m]
    contadores["valores"][("1", "voz_minutos")] = 2995
    assert await mod.contar(servidor, 1, "voz_minutos", 5) == 3000
    assert [r.id for r in m.agregados] == [71]
    contenido, kw = servidor.canales[31].enviados[0]
    assert "Felicidades" in contenido and kw["embed"].title == "🎧 Nueva Voz activa"
    assert "!antiguedad" in kw["embed"].footer.text
    # un minuto menos y no hay rol; y no se da dos veces
    otro = miembro_en_voz(servidor, 2)
    servidor.members.append(otro)
    contadores["valores"][("2", "voz_minutos")] = 2990
    await mod.contar(servidor, 2, "voz_minutos", 5)
    assert otro.agregados == []
    n = len(servidor.canales[31].enviados)
    await mod.contar(servidor, 1, "voz_minutos", 5)
    assert len(m.agregados) == 1 and len(servidor.canales[31].enviados) == n


async def test_activar_la_voz_no_enciende_los_otros_contadores_de_eito(mod, perfil, servidor, contadores):
    """Superviviente y Convocador (L4D2) no estan mapeados: aunque su contador llegue al umbral, no hay rol."""
    m = miembro_en_voz(servidor, 1)
    servidor.members = [m]
    assert await mod.contar(servidor, 1, "partidas", 10) == 10
    assert await mod.contar(servidor, 1, "convocatorias_exitosas", 10) == 10
    assert m.agregados == [] and servidor.canales[31].enviados == []


async def test_el_respaldo_de_cada_6_horas_da_el_rol_a_quien_ya_llego_al_umbral(mod, perfil, servidor, monkeypatch):
    m = miembro_en_voz(servidor, 1)
    servidor.members = [m]

    async def con_contador(guild_id, tipo, umbral):
        return ["1"] if tipo == "voz_minutos" else []

    monkeypatch.setattr(mod, "usuarios_con_contador", con_contador)
    await mod.revisar_umbrales_guild(servidor)
    assert [r.id for r in m.agregados] == [71]


async def test_en_eito_la_voz_sigue_igual(mod, fakes, contadores):
    guild = fakes.Guild()
    rol = RolJerarquia(mod.ROL_VOZ_ACTIVA_ID, "🎧 Voz activa", 1)
    guild.roles.append(rol)
    guild.me = types.SimpleNamespace(top_role=RolJerarquia(1, "bot", 100))
    m = miembro_en_voz(guild, 1)
    guild.get_member = lambda ident: m
    guild.canal(mod.CANAL_NIVELES)
    contadores["valores"][("1", "voz_minutos")] = 2995
    await mod.contar(guild, 1, "voz_minutos", 5)
    assert m.agregados == [rol]


# --- Sin tick de voz inmediato al reiniciar (T6) -------------------------------------------------
async def test_al_arrancar_el_primer_tick_de_voz_espera_un_tick_entero(mod, monkeypatch):
    llamadas = []

    async def wait_until_ready():
        llamadas.append("listo")

    async def sleep(segundos):
        llamadas.append(("sleep", segundos))

    monkeypatch.setattr(mod.bot, "wait_until_ready", wait_until_ready)
    monkeypatch.setattr(mod.asyncio, "sleep", sleep)
    await mod.antes_de_contar_voz()
    assert llamadas == ["listo", ("sleep", mod.VOZ_MINUTOS_TICK * 60)]


def test_el_tick_de_voz_coincide_con_el_intervalo_del_loop(mod):
    assert mod.contar_voz.minutes == mod.VOZ_MINUTOS_TICK
