"""Guardas: check global de mensajes privados y tope de !darnivel."""

import pytest
from discord.ext import commands


# --- Check global: nada de comandos por mensaje privado ---------------------------------
def test_el_check_global_esta_registrado(mod):
    assert mod.solo_en_servidor in mod.bot._checks


async def test_en_un_servidor_el_comando_pasa(mod, fakes):
    ctx = fakes.Ctx(guild=fakes.Guild(), comando=mod.top)
    assert await mod.bot.can_run(ctx) is True
    assert ctx.respuestas == []


async def test_en_mensaje_privado_se_rechaza_y_se_avisa_si_el_comando_no_tiene_manejador(mod, fakes):
    # !top no tiene .error propio: nadie mas contestaria al usuario
    assert not mod.top.has_error_handler()
    ctx = fakes.Ctx(guild=None, comando=mod.top)

    with pytest.raises(commands.NoPrivateMessage) as error:
        await mod.bot.can_run(ctx)

    assert str(error.value) == mod.MENSAJE_SOLO_SERVIDOR
    assert len(ctx.respuestas) == 1
    assert ctx.respuestas[0][0] == f"❌ {mod.MENSAJE_SOLO_SERVIDOR}"


async def test_en_mensaje_privado_con_manejador_propio_no_se_duplica_el_aviso(mod, fakes):
    # !warn tiene .error propio: es el quien responde (con str(error))
    assert mod.warn.has_error_handler()
    ctx = fakes.Ctx(guild=None, comando=mod.warn)

    with pytest.raises(commands.NoPrivateMessage):
        await mod.bot.can_run(ctx)

    assert ctx.respuestas == []


async def test_el_manejador_de_un_comando_muestra_el_mensaje_claro(mod, fakes):
    ctx = fakes.Ctx(guild=None, comando=mod.warn)
    await mod.warn_error(ctx, commands.NoPrivateMessage(mod.MENSAJE_SOLO_SERVIDOR))
    assert mod.MENSAJE_SOLO_SERVIDOR in ctx.respuestas[0][0]


# --- !darnivel ----------------------------------------------------------------------------
@pytest.fixture
def darnivel_sin_bd(mod, monkeypatch):
    """Parchea la BD y las recompensas; devuelve las llamadas hechas a la BD."""
    llamadas = []

    async def get_user_xp(*args):
        llamadas.append(("get", args))
        return 0

    async def add_user_xp(*args):
        llamadas.append(("add", args))
        return args[2]

    async def otorgar(*args, **kwargs):
        return None

    monkeypatch.setattr(mod, "get_user_xp", get_user_xp)
    monkeypatch.setattr(mod, "add_user_xp", add_user_xp)
    monkeypatch.setattr(mod, "otorgar_recompensas", otorgar)
    monkeypatch.setattr(mod, "EITO_GUILD_ID", "")
    return llamadas


def test_el_tope_de_darnivel_es_200(mod):
    assert mod.NIVEL_MAX_DARNIVEL == 200


@pytest.mark.parametrize("nivel", [201, 1000, 10**9])
async def test_darnivel_rechaza_niveles_por_encima_del_tope(mod, fakes, darnivel_sin_bd, nivel):
    ctx = fakes.Ctx(guild=fakes.Guild())

    await mod.darnivel.callback(ctx, nivel)

    assert ctx.respuestas[0][0] == "❌ El nivel máximo es 200."
    assert darnivel_sin_bd == []  # no llego a calcular ni a tocar la BD


async def test_darnivel_acepta_el_nivel_maximo(mod, fakes, darnivel_sin_bd):
    ctx = fakes.Ctx(guild=fakes.Guild())

    await mod.darnivel.callback(ctx, 200)

    assert "nivel **200**" in ctx.respuestas[0][0]
    assert [accion for accion, _ in darnivel_sin_bd] == ["get", "add"]


async def test_darnivel_sigue_rechazando_niveles_negativos(mod, fakes, darnivel_sin_bd):
    ctx = fakes.Ctx(guild=fakes.Guild())
    await mod.darnivel.callback(ctx, -1)
    assert ctx.respuestas[0][0] == "❌ El nivel debe ser 0 o mayor."
    assert darnivel_sin_bd == []


async def test_darnivel_sigue_bloqueado_en_el_servidor_principal(mod, fakes, darnivel_sin_bd, monkeypatch):
    guild = fakes.Guild(id=42)
    monkeypatch.setattr(mod, "EITO_GUILD_ID", "42")
    ctx = fakes.Ctx(guild=guild)

    await mod.darnivel.callback(ctx, 10)

    assert "deshabilitado" in ctx.respuestas[0][0]
    assert darnivel_sin_bd == []
