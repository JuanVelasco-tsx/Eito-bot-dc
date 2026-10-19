"""Fundadores con cupo contra PostgreSQL real (marker db): puestos sin repetir y nunca mas del maximo,
incluso con entradas simultaneas y mezclando altas sueltas con una carga de golpe."""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

import database

pytestmark = pytest.mark.db
AHORA = datetime(2026, 10, 19, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
async def bd_de_pruebas():
    await database.crear_tablas()
    yield
    await database.engine.dispose()


@pytest.fixture
def guild_id():
    return f"test-{uuid.uuid4().hex[:12]}"


async def test_las_altas_sueltas_toman_puestos_consecutivos(guild_id):
    for n in range(1, 4):
        assert await database.registrar_fundadores_con_cupo(guild_id, [(n, AHORA)], 100) == {str(n): n}
    assert await database.listar_fundadores(guild_id) == {"1": 1, "2": 2, "3": 3}


async def test_quien_ya_esta_guardado_no_se_duplica_ni_cambia_de_puesto(guild_id):
    await database.registrar_fundadores_con_cupo(guild_id, [(1, AHORA), (2, AHORA)], 100)
    assert await database.registrar_fundadores_con_cupo(guild_id, [(2, AHORA), (3, AHORA)], 100) == {"3": 3}
    assert await database.listar_fundadores(guild_id) == {"1": 1, "2": 2, "3": 3}


async def test_nunca_pasa_del_maximo(guild_id):
    guardados = await database.registrar_fundadores_con_cupo(guild_id, [(n, AHORA) for n in range(10)], 4)
    assert guardados == {"0": 1, "1": 2, "2": 3, "3": 4}
    assert await database.registrar_fundadores_con_cupo(guild_id, [(99, AHORA)], 4) == {}
    assert len(await database.listar_fundadores(guild_id)) == 4


async def test_entradas_simultaneas_no_repiten_puesto_ni_pasan_del_maximo(guild_id):
    resultados = await asyncio.gather(*[
        database.registrar_fundadores_con_cupo(guild_id, [(n, AHORA)], 5) for n in range(20)
    ])
    puestos = sorted(p for r in resultados for p in r.values())
    assert puestos == [1, 2, 3, 4, 5]                                   # exactamente 5, sin huecos ni repetidos
    assert sorted((await database.listar_fundadores(guild_id)).values()) == [1, 2, 3, 4, 5]


async def test_una_carga_de_golpe_y_entradas_a_la_vez_conviven(guild_id):
    # 3 ya guardados; a la vez: un «confirmar» con 10 miembros y 10 entradas sueltas; tope 8
    await database.registrar_fundadores_con_cupo(guild_id, [(n, AHORA) for n in range(3)], 8)
    tareas = [database.registrar_fundadores_con_cupo(guild_id, [(100 + n, AHORA) for n in range(10)], 8)]
    tareas += [database.registrar_fundadores_con_cupo(guild_id, [(200 + n, AHORA)], 8) for n in range(10)]
    await asyncio.gather(*tareas)
    final = await database.listar_fundadores(guild_id)
    assert sorted(final.values()) == list(range(1, 9))                  # 8 en total, puestos 1..8 unicos
    assert len(final) == 8


async def test_cada_servidor_lleva_su_cuenta(guild_id):
    otro = guild_id + "-b"
    await database.registrar_fundadores_con_cupo(guild_id, [(1, AHORA), (2, AHORA)], 2)
    assert await database.registrar_fundadores_con_cupo(otro, [(1, AHORA)], 2) == {"1": 1}
    assert await database.registrar_fundadores_con_cupo(guild_id, [(3, AHORA)], 2) == {}


async def test_compatible_con_guardar_fundadores_de_eito(guild_id):
    await database.guardar_fundadores(guild_id, [(1, 1, AHORA), (2, 2, AHORA)])
    assert await database.registrar_fundadores_con_cupo(guild_id, [(3, AHORA)], 100) == {"3": 3}
    assert await database.get_fundador(guild_id, 3) == 3
