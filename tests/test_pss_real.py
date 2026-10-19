"""El perfil PSS contra el estado REAL del servidor: el export de tras el primer !pss aplicar
(tests/fixtures/pss_export_real.json) con el mapa de perfil_recursos que dejo esa aplicacion.

Aqui no hay reconstrucciones: roles, categorias, canales, overwrites y posiciones son los del
export. Solo son sinteticos los miembros (el export trae recuentos) y los IDs de los 4 mensajes
de #reglas (ver `_nota` del JSON)."""

import tomllib
from pathlib import Path

import pytest

from profiles.pss_config import cargar, parsear
from profiles.pss_exec import ejecutar
from profiles.pss_plan import calcular_plan, lineas_plan
from tests.pss_fakes import (
    BOT_REAL, DEVELOPER, FServidorReal, cargar_export_real, estado_mensajes, estado_real, foto,
    orden_actual, publicar_mensajes_reales,
)
FASE0 = Path(__file__).resolve().parent / "fixtures" / "pss_fase0.toml"     # los pss.toml ya desplegados
FASE1 = Path(__file__).resolve().parent / "fixtures" / "pss_fase1.toml"
FASE2 = Path(__file__).resolve().parent / "fixtures" / "pss_fase2.toml"

from tests.test_pss_exec import (  # noqa: F401  (guardado es un fixture)
    CATEGORIAS_FINAL, HIJOS_FINAL, MINIMO_BOT, RUTA, acciones, guardado, plan_de, por_nombre,
)

SOBRANTES = ["🟥 Roblox", "📢 Anuncios", "🛠️ Soporte"]       # las categorias viejas que quedan vacias


@pytest.fixture
def real(guardado):
    """(servidor falso con el PSS real, estado de la BD ya cargado en `guardado`)."""
    srv = FServidorReal()
    guardado.update(estado_real())
    publicar_mensajes_reales(srv, guardado)
    return srv, guardado


async def aplicar_real(srv, config, estado, admin=True, permisos=8):
    plan = plan_de(srv, config, estado, admin, permisos)
    return plan, await ejecutar(srv, plan, config, estado, lambda keys: object())


# --- el fixture es el estado que describio el dueño ---------------------------------------------------------
def test_el_fixture_refleja_el_estado_real(real):
    srv, estado = real
    nombres = [c.name for c in srv.canales.values()]
    assert "frontend" not in nombres and "backend" not in nombres        # los borro el dueño
    for vieja in ("Información", "Canales de texto", "Canales de voz"):
        assert vieja not in nombres
    assert sum(1 for m in srv.miembros if DEVELOPER in m.roles) == 5 and len(srv.miembros) == 6
    cats, _ = orden_actual(srv)
    assert cats == ["🛡️ Staff", "🔒 Equipo", "💻 Desarrollo", "📌 Estudio", "🟥 Roblox", "📢 Anuncios",
                    "💬 Comunidad", "🛠️ Soporte", "🔊 Voz"]
    assert srv.me.id == BOT_REAL
    # el mapa de la BD tiene las 35 filas de la primera aplicacion (frontend/backend siguen, huerfanas)
    assert len(estado) == 35 and estado["frontend"].discord_id not in srv.canales
    assert estado["developer"].creado is False and estado["reglas"].creado is True
    assert estado["ayuda"].creado is False and estado["ayuda"].discord_id == 1420403965446721603


def test_el_toml_ya_no_menciona_frontend_ni_backend():
    config = cargar(RUTA)
    assert config.canal("frontend") is None and config.canal("backend") is None
    texto = RUTA.read_text(encoding="utf-8")
    assert "frontend" not in texto and "backend" not in texto and "PENDIENTE" not in texto
    assert "{canal:ayuda}" in texto            # la guia sigue apuntando al foro


# --- el plan simulado sobre el estado real -------------------------------------------------------------------
def test_plan_real_con_comunidad(real):
    srv, estado = real
    plan = plan_de(srv, cargar(RUTA), estado)
    a = acciones(plan)
    assert {k for k, x in a.items() if x.op == "crear"} == {
        "info_estudio", "sugerencias", "comandos", "ayuda", "bienvenida", "presentaciones", "niveles", "pruebas_bot", "helper", "novedades", "msg_presentaciones",
        "activo_mes", "og", "fundador", "leyenda", "veterano", "cat_tickets", "soporte", "tickets_log", "voz_activa"}
    assert [x for x in plan.acciones if x.op == "bloqueado"] == []
    assert {k for k, x in a.items() if x.op == "omitir"} == {
        "propietario", "administrador", "developer", "colaborador", "miembro", "scripter", "builder", "ui",
        "voz_general", "reuniones"}
    actualizar = {k for k, x in a.items() if x.op == "actualizar"}
    assert actualizar == {
        "cat_estudio", "cat_comunidad", "cat_desarrollo", "cat_voz", "cat_equipo", "cat_staff",
        "reglas", "anuncios", "general", "showcase", "no_relacionado", "scripting_luau", "info_importante",
        "planificacion_sesiones", "registros",
        "msg_reglas", "msg_info_estudio", "msg_guia", "msg_especialidades", "@orden"}
    assert "convertir a canal de anuncios" in a["anuncios"].detalle and a["anuncios"].cambios["tipo"] == "news"
    # Equipo ya estaba sincronizado en el servidor real: solo se renombran
    assert set(a["info_importante"].cambios) == {"nombre"} and set(a["planificacion_sesiones"].cambios) == {"nombre"}
    texto = "\n".join(lineas_plan(plan))
    assert "«ayuda» queda **reemplazado** por el foro «❓・ayuda»" in texto
    for vieja in ("📢 Anuncios", "🟥 Roblox"):
        assert f"Categoría «{vieja}»: queda **vacía**; bórrala a mano" in texto
    assert "Categoría «🛠️ Soporte»: queda **vacía** (solo queda el canal reemplazado" in texto
    assert "frontend" not in texto and "backend" not in texto


def test_plan_real_sin_comunidad(real):
    srv, estado = real
    srv.features.clear()
    plan = plan_de(srv, cargar(RUTA), estado)
    a = acciones(plan)
    assert {k for k, x in a.items() if x.op == "bloqueado"} == {"anuncios", "ayuda", "msg_reglas", "msg_guia"}
    assert "activa Comunidad" in a["anuncios"].razon and "activa Comunidad" in a["ayuda"].razon
    assert {k for k, x in a.items() if x.op == "crear"} == {
        "info_estudio", "sugerencias", "comandos", "bienvenida", "presentaciones", "niveles", "pruebas_bot", "helper",
        "novedades", "msg_presentaciones", "activo_mes", "og", "fundador", "leyenda", "veterano", "cat_tickets", "soporte", "tickets_log", "voz_activa"}
    texto = "\n".join(lineas_plan(plan))
    assert "reemplazado" not in texto and "Categoría «📢 Anuncios»" not in texto     # anuncios sigue ahi
    assert "Categoría «🟥 Roblox»: queda **vacía**" in texto


# --- aplicar sobre el estado real: el orden --------------------------------------------------------------------
async def comprobar_orden(srv):
    cats, hijos = orden_actual(srv)
    assert cats == CATEGORIAS_FINAL + SOBRANTES          # primero las del TOML, luego las sobrantes
    for categoria, esperados in HIJOS_FINAL.items():
        assert hijos[categoria] == esperados, categoria
    assert hijos["🟥 Roblox"] == [] and hijos["📢 Anuncios"] == []
    assert hijos["🛠️ Soporte"] == ["ayuda"]               # el #ayuda de texto, sin tocar


async def test_aplicar_deja_el_orden_importante_comunidad_desarrollo_voz_equipo_staff(real):
    srv, estado = real
    config = cargar(RUTA)
    _, res = await aplicar_real(srv, config, estado)
    assert res.fallos == [] and res.bloqueadas == []
    await comprobar_orden(srv)
    # lo ya existente conserva su ID; el #ayuda de texto sigue siendo texto y el foro es otro canal
    c = por_nombre(srv)
    assert c["💬・general"].id == 1420403965446721602 and c["📣・anuncios"].tipo == "news"
    assert c["ayuda"].tipo == "text" and c["❓・ayuda"].tipo == "forum" and c["❓・ayuda"].id != c["ayuda"].id
    # nada de frontend/backend: ni se recrean ni aparecen
    assert not any("frontend" in n or "backend" in n for n in c)
    # los mensajes: #reglas conserva el suyo (editado) y los otros 3 pasan a #info-estudio
    assert [m.embed.title for m in c["📜・reglas"].mensajes.values()] == ["📜 Reglas"]
    assert [m.embed.title for m in c["ℹ️・info-estudio"].mensajes.values()] == [
        "👻 Phantom Shadows Studios", "🧭 Guía para nuevos integrantes", "🎭 Especialidades y avisos"]
    # el bot en el mínimo de permisos: ya no hay nada que hacer
    plan = plan_de(srv, config, estado, admin=False, permisos=MINIMO_BOT)
    assert [x for x in plan.acciones if x.op != "omitir"] == []


async def test_aplicar_sin_comunidad_y_luego_con_ella_llega_al_mismo_orden(real):
    srv, estado = real
    srv.features.clear()
    config = cargar(RUTA)
    _, res = await aplicar_real(srv, config, estado)
    assert res.fallos == []
    cats, _ = orden_actual(srv)
    assert cats[:5] == ["📌 » IMPORTANTE", "💬 » COMUNIDAD", "💻 » DESARROLLO", "🔊 » VOZ", "🔒 » EQUIPO"]
    assert "🛡️ » STAFF" in cats[:7]
    srv.features.add("COMMUNITY")
    _, res = await aplicar_real(srv, config, estado)
    assert res.fallos == []
    await comprobar_orden(srv)


async def test_reaplicar_sobre_el_estado_real_no_repite_nada(real):
    srv, estado = real
    config = cargar(RUTA)
    await aplicar_real(srv, config, estado)
    llamadas, canales = list(srv.llamadas), len(srv.canales)
    plan, res = await aplicar_real(srv, config, estado)
    assert [x for x in plan.acciones if x.op not in ("omitir",)] == []
    assert srv.llamadas == llamadas and len(srv.canales) == canales


# --- adoptar + nombre_actual que no existe: bloqueado, y no se crea nada ----------------------------------------
async def test_adoptar_de_un_canal_que_el_dueno_borro_no_lo_recrea(real):
    srv, estado = real
    # la config anterior (con #frontend adoptado) sobre el estado real, donde ese canal ya no existe
    with RUTA.open("rb") as f:
        datos = tomllib.load(f)
    datos["canales"].append({"key": "frontend", "nombre": "🎨・frontend", "nombre_actual": "frontend",
                             "adoptar": True, "mover": True, "categoria": "cat_desarrollo", "orden": 5})
    config = parsear(datos)
    estado.pop("frontend", None)                              # sin siquiera la fila huerfana de la BD
    plan = plan_de(srv, config, estado)
    a = acciones(plan)["frontend"]
    assert a.op == "bloqueado" and a.razon.startswith("no encontrado (adoptar)")
    assert "bloqueado: no encontrado (adoptar)" in "\n".join(lineas_plan(plan))
    antes = len(srv.canales)
    res = await ejecutar(srv, plan, config, estado, lambda k: object())
    assert not any("frontend" in c.name for c in srv.canales.values()) and "frontend" not in estado
    assert not any(l[0].startswith("create") and "frontend" in str(l) for l in srv.llamadas)
    # el resto sigue aplicandose: info-estudio, sugerencias, comandos, el foro, 4 canales de la Fase 1 y
    # soporte, tickets-log y la categoria de tickets de la Fase 2
    assert len(srv.canales) == antes + 11
    assert res.fallos == []


# --- Fase 3 sobre lo DESPLEGADO: el estado real + los pss.toml de las Fases 0, 1 y 2 aplicados -----------------------
@pytest.fixture
async def desplegado(real):
    """PSS tal como esta hoy: el export real al que se le aplicaron los pss.toml de las Fases 0, 1 y 2
    (en cada paso el plan, con el bot en permisos minimos, da «coincide»)."""
    srv, estado = real
    for ruta in (FASE0, FASE1, FASE2):
        config = cargar(ruta)
        plan, res = await aplicar_real(srv, config, estado)
        assert res.fallos == [] and res.bloqueadas == []
        assert plan_de(srv, config, estado, admin=False, permisos=MINIMO_BOT).coincide(), ruta.name
    return srv, estado


async def test_plan_de_la_fase_3_sobre_lo_desplegado(desplegado):
    srv, estado = desplegado
    plan = plan_de(srv, cargar(RUTA), estado)
    a = acciones(plan)
    assert {k for k, x in a.items() if x.op == "crear"} == {"voz_activa"}        # solo el rol: nada de Nivel 10
    assert [k for k, x in a.items() if x.op in ("actualizar", "vincular", "bloqueado")] == []
    assert not plan.coincide() and "voz_activa" in {x.key for x in plan.acciones if x.op == "crear"}


async def test_aplicar_la_fase_3_sobre_lo_desplegado_deja_el_servidor_coincidiendo(desplegado):
    srv, estado = desplegado
    config = cargar(RUTA)
    _, res = await aplicar_real(srv, config, estado)
    assert res.fallos == [] and res.bloqueadas == []
    await comprobar_orden(srv)
    rol = next(r for r in srv.roles if r.name == "🎧 Voz activa")
    assert rol.permissions.value == 0 and not rol.mentionable and rol.id == estado["voz_activa"].discord_id
    assert not any("Nivel 10" in r.name for r in srv.roles) and not any("nivel-10" in c.name for c in srv.canales.values())
    plan = plan_de(srv, config, estado, admin=False, permisos=MINIMO_BOT)
    assert plan.coincide(), "\n".join(lineas_plan(plan))
    llamadas = list(srv.llamadas)
    await aplicar_real(srv, config, estado)
    assert srv.llamadas == llamadas
