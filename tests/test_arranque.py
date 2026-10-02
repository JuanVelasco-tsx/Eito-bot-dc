"""Arranque: setup_hook (vistas, tablas, servidor web), on_ready y el engine de la BD."""

import asyncio

import pytest

import database


@pytest.fixture
def arranque(mod, monkeypatch):
    """Parchea todo lo que setup_hook toca fuera del proceso y registra lo que pasa."""
    eventos = []

    async def crear_tablas():
        eventos.append("crear_tablas")

    async def servidor_web():
        eventos.append("servidor_web")

    monkeypatch.setattr(mod, "crear_tablas", crear_tablas)
    monkeypatch.setattr(mod, "start_web_server", servidor_web)
    monkeypatch.setattr(mod.bot, "add_view", lambda vista: eventos.append(type(vista).__name__))
    for nombre in ("premiar_activo_mes", "actualizar_rangos",
                   "cerrar_convocatorias_vencidas", "contar_voz"):
        loop = getattr(mod, nombre)
        monkeypatch.setattr(loop, "start", lambda nombre=nombre: eventos.append(f"loop:{nombre}"))
    return eventos


async def test_setup_hook_registra_todas_las_vistas_despues_de_crear_tablas(mod, arranque):
    await mod.setup_hook()
    await mod.tarea_web

    assert arranque[0] == "crear_tablas"
    vistas = arranque[1:arranque.index("loop:premiar_activo_mes")]
    assert [v for v in vistas if v != "servidor_web"] == [
        "LfgView", "PanelRoles", "PanelTickets", "CerrarTicket",
    ]
    assert {"loop:premiar_activo_mes", "loop:actualizar_rangos",
            "loop:cerrar_convocatorias_vencidas", "loop:contar_voz"} <= set(arranque)


async def test_setup_hook_registra_las_vistas_aunque_falle_crear_tablas(mod, arranque, monkeypatch):
    async def falla():
        raise ConnectionError("BD caída")

    monkeypatch.setattr(mod, "crear_tablas", falla)

    await mod.setup_hook()  # no debe propagar el error
    await mod.tarea_web

    for vista in ("LfgView", "PanelRoles", "PanelTickets", "CerrarTicket"):
        assert vista in arranque


async def test_setup_hook_guarda_la_tarea_del_servidor_web(mod, arranque):
    await mod.setup_hook()
    assert isinstance(mod.tarea_web, asyncio.Task)
    await mod.tarea_web


async def test_si_el_servidor_web_no_arranca_se_imprime(mod, arranque, monkeypatch, capsys):
    async def puerto_ocupado():
        raise OSError("puerto ocupado")

    monkeypatch.setattr(mod, "start_web_server", puerto_ocupado)

    await mod.setup_hook()
    await asyncio.wait({mod.tarea_web})
    await asyncio.sleep(0)  # deja correr el callback de la tarea

    salida = capsys.readouterr().out
    assert "servidor web no pudo arrancar" in salida
    assert "puerto ocupado" in salida


async def test_on_ready_no_propaga_el_fallo_de_crear_tablas(mod, monkeypatch, capsys):
    async def falla():
        raise ConnectionError("BD caída")

    monkeypatch.setattr(mod, "crear_tablas", falla)

    await mod.on_ready()  # no debe lanzar

    salida = capsys.readouterr().out
    assert "crear_tablas() falló en on_ready" in salida
    assert "Conectado como" in salida  # el resto de on_ready se ejecuta


async def test_on_ready_ya_no_registra_vistas(mod, monkeypatch):
    async def crear_tablas():
        return None

    registradas = []
    monkeypatch.setattr(mod, "crear_tablas", crear_tablas)
    monkeypatch.setattr(mod.bot, "add_view", lambda vista: registradas.append(vista))

    await mod.on_ready()

    assert registradas == []


def test_el_engine_comprueba_y_renueva_las_conexiones():
    pool = database.engine.sync_engine.pool
    assert pool._pre_ping is True
    assert pool._recycle == 1800
