"""Pruebas contra PostgreSQL real (marker `db`).

Se SALTAN por defecto (y en CI, que no tiene Postgres por ahora). Para correrlas:

    TEST_DATABASE_URL=postgresql://usuario:clave@localhost/eito_test pytest -m db

Usa una base de pruebas, nunca la de produccion: crean las tablas y escriben con
un guild_id aleatorio, sin borrar nada. OJO: estan escritas pero todavia no se han
ejecutado contra una BD real; revisalas la primera vez que las corras.
"""

import asyncio
import uuid

import pytest

import database

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
async def bd_de_pruebas():
    await database.crear_tablas()
    yield
    # Las conexiones del pool pertenecen al event loop de cada prueba
    await database.engine.dispose()


@pytest.fixture
def guild_id():
    return f"test-{uuid.uuid4().hex[:12]}"


async def test_contador_con_tope_es_atomico(guild_id):
    resultados = await asyncio.gather(*[
        database.incrementar_contador_con_tope(guild_id, "1", "voz_dia:2026-10-01", 3)
        for _ in range(10)
    ])
    assert sorted(r for r in resultados if r is not None) == [1, 2, 3]


async def test_cerrar_lfg_post_solo_lo_cierra_una_llamada(guild_id):
    post_id = await database.crear_lfg_post(guild_id, "10", f"msg-{guild_id}", "1")
    resultados = await asyncio.gather(*[database.cerrar_lfg_post(post_id) for _ in range(5)])
    assert len([r for r in resultados if r is not None]) == 1


async def test_top_xp_mensual_ordena_por_xp(guild_id):
    await database.add_xp_mensual(guild_id, "1", "2026-09", 50)
    await database.add_xp_mensual(guild_id, "2", "2026-09", 80)
    await database.add_xp_mensual(guild_id, "3", "2026-08", 999)  # otro mes: no cuenta
    assert await database.top_xp_mensual(guild_id, "2026-09", 10) == [("2", 80), ("1", 50)]
