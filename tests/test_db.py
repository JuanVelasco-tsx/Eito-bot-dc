"""Pruebas contra PostgreSQL real (marker `db`).

Se SALTAN si no hay TEST_DATABASE_URL (en CI corren contra el servicio de Postgres). Para correrlas:

    TEST_DATABASE_URL=postgresql://usuario:clave@localhost/eito_test pytest -m db

Usa una base de pruebas, nunca la de produccion: crean las tablas y escriben con
un guild_id aleatorio, sin borrar nada. Ejecutadas contra PostgreSQL 16 real el 2026-11-11.
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


async def test_usuarios_permitidos(guild_id):
    assert await database.es_usuario_permitido(guild_id, "1") is False
    assert await database.permitir_usuario(guild_id, "1", "Mod") is True
    assert await database.permitir_usuario(guild_id, "1", "Otro") is False  # ya estaba, sin error
    assert await database.es_usuario_permitido(guild_id, "1") is True
    assert await database.es_usuario_permitido(f"{guild_id}-otro", "1") is False  # por servidor
    assert await database.quitar_usuario_permitido(guild_id, "1") is True
    assert await database.quitar_usuario_permitido(guild_id, "1") is False
    assert await database.es_usuario_permitido(guild_id, "1") is False


async def test_permitir_usuario_concurrente_solo_lo_anade_una_vez(guild_id):
    resultados = await asyncio.gather(*[
        database.permitir_usuario(guild_id, "2", "Mod") for _ in range(5)
    ])
    assert resultados.count(True) == 1


async def test_sumar_xp_concurrente_que_cruza_un_nivel_avisa_una_vez(guild_id, mod, fakes, monkeypatch):
    """T5 contra PostgreSQL real: dos sumas a la vez de 95 a 125 cruzan el nivel 1 (100) una vez."""
    recompensas = []

    async def otorgar(guild, miembro, previo, nuevo, canal):
        recompensas.append((previo, nuevo))

    monkeypatch.setattr(mod, "otorgar_recompensas", otorgar)
    guild = fakes.Guild(id=guild_id)
    niveles = guild.canal(mod.CANAL_NIVELES)
    miembro = fakes.Usuario(9, "Pepe")
    miembro.guild = guild
    await database.add_user_xp(guild_id, "9", 95)

    totales = await asyncio.gather(mod.sumar_xp(miembro, 15), mod.sumar_xp(miembro, 15))

    assert sorted(totales) == [110, 125]
    assert await database.get_user_xp(guild_id, "9") == 125
    assert len(niveles.enviados) == 1
    assert recompensas == [(0, 1)]
