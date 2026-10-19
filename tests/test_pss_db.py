"""Tabla perfil_recursos y lock por servidor contra PostgreSQL real (marker `db`).

Se saltan salvo que definas TEST_DATABASE_URL (ver tests/test_db.py). Usan un guild_id
aleatorio y no borran nada ajeno."""

import asyncio
import random

import pytest

import database
from profiles import pss_db
from profiles.pss_plan import Registro

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
async def bd_de_pruebas():
    pss_db._tabla_lista = False
    await pss_db.asegurar_tabla()
    yield
    await database.engine.dispose()


@pytest.fixture
def guild_id():
    return random.randint(10**17, 10**18)


async def test_guardar_y_cargar_mapa(guild_id):
    await pss_db.guardar(guild_id, "general", "canal", 111, creado=True)
    await pss_db.guardar(guild_id, "msg", "mensaje", 222, canal_id=111, hash_contenido="abc", creado=True)
    mapa = await pss_db.cargar_mapa(guild_id)
    assert mapa["general"] == Registro("canal", 111, None, None, True)
    assert mapa["msg"] == Registro("mensaje", 222, 111, "abc", True)
    assert await pss_db.cargar_mapa(guild_id + 1) == {}          # por servidor


async def test_guardar_es_un_upsert_y_creado_no_baja_mientras_el_id_no_cambie(guild_id):
    await pss_db.guardar(guild_id, "r", "rol", 5, creado=True)
    await pss_db.guardar(guild_id, "r", "rol", 5, creado=False)       # vincular otra vez
    assert (await pss_db.cargar_mapa(guild_id))["r"].creado is True
    await pss_db.guardar(guild_id, "r", "rol", 6, creado=False)       # otro recurso distinto
    reg = (await pss_db.cargar_mapa(guild_id))["r"]
    assert (reg.discord_id, reg.creado) == (6, False)
    assert len(await pss_db.cargar_mapa(guild_id)) == 1               # una fila por (guild, key)


async def test_borrar_solo_olvida_ese_mapeo(guild_id):
    await pss_db.guardar(guild_id, "a", "rol", 1)
    await pss_db.guardar(guild_id, "b", "rol", 2)
    assert await pss_db.borrar(guild_id, "a") is True
    assert await pss_db.borrar(guild_id, "a") is False
    assert list(await pss_db.cargar_mapa(guild_id)) == ["b"]


async def test_lock_por_servidor_es_exclusivo(guild_id):
    async with pss_db.lock_aplicar(guild_id) as primero:
        assert primero is True
        async with pss_db.lock_aplicar(guild_id) as segundo:
            assert segundo is False                                   # ya hay una aplicacion en curso
        async with pss_db.lock_aplicar(guild_id + 1) as otro_servidor:
            assert otro_servidor is True                              # cada servidor tiene el suyo
    async with pss_db.lock_aplicar(guild_id) as de_nuevo:
        assert de_nuevo is True                                       # se libero al salir


async def test_el_lock_se_libera_aunque_la_aplicacion_falle(guild_id):
    with pytest.raises(RuntimeError):
        async with pss_db.lock_aplicar(guild_id) as obtenido:
            assert obtenido
            raise RuntimeError("fallo a mitad")
    async with pss_db.lock_aplicar(guild_id) as de_nuevo:
        assert de_nuevo is True


async def test_solo_una_de_varias_aplicaciones_simultaneas_obtiene_el_lock(guild_id):
    obtenidos = []
    listos = asyncio.Event()

    async def intentar():
        async with pss_db.lock_aplicar(guild_id) as ok:
            obtenidos.append(ok)
            await listos.wait()

    tareas = [asyncio.create_task(intentar()) for _ in range(4)]
    while len(obtenidos) < 4:
        await asyncio.sleep(0.05)
    listos.set()
    await asyncio.gather(*tareas)
    assert obtenidos.count(True) == 1


def test_clave_de_lock_cabe_en_bigint_y_no_choca_entre_servidores():
    a, b = pss_db.clave_lock(1420403964746268684), pss_db.clave_lock(1420403964746268685)
    assert 0 <= a < 2**63 and 0 <= b < 2**63 and a != b


async def test_aplicar_de_punta_a_punta_con_la_bd_real_y_plan_posterior_en_omitir():
    """El flujo completo (plan -> ejecutar -> guardar en perfil_recursos -> plan) con la tabla real."""
    from pathlib import Path

    from profiles.pss_config import cargar
    from profiles.pss_exec import ejecutar
    from profiles.pss_plan import calcular_plan
    from tests.pss_fakes import G, MINIMO_BOT, FServidor, estado_mensajes, foto

    config = cargar(Path(__file__).resolve().parent.parent / "profiles" / "pss.toml")
    claves = [e.key for e in (*config.roles, *config.categorias, *config.canales, *config.mensajes)]
    for k in claves:
        await pss_db.borrar(G, k)
    srv = FServidor()
    try:
        plan = calcular_plan(config, foto(srv), {}, {})
        resultado = await ejecutar(srv, plan, config, {}, lambda keys: object())
        assert resultado.fallos == []
        guardado = await pss_db.cargar_mapa(G)
        assert guardado["propietario"].creado and guardado["general"].tipo == "canal"
        assert guardado["msg_reglas"].hash and guardado["msg_reglas"].canal_id
        plan2 = calcular_plan(config, foto(srv, admin=False, permisos=MINIMO_BOT), guardado,
                              estado_mensajes(srv, config, guardado))
        assert [a for a in plan2.acciones if a.op != "omitir"] == []
    finally:
        for k in claves:
            await pss_db.borrar(G, k)
