"""El perfil PSS contra el estado REAL del servidor: el export de tras el primer !pss aplicar
(tests/fixtures/pss_export_real.json) con el mapa de perfil_recursos que dejo esa aplicacion.

Aqui no hay reconstrucciones: roles, categorias, canales, overwrites y posiciones son los del
export. Solo son sinteticos los miembros (el export trae recuentos) y los IDs de los 4 mensajes
de #reglas (ver `_nota` del JSON)."""

import tomllib
import types
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

SOBRANTES = {"🟥 Roblox", "📢 Anuncios", "🛠️ Soporte"}        # las categorias viejas que quedan vacias
DESARROLLO = {"💻 Desarrollo", "💻 » DESARROLLO"}            # y la de DESARROLLO (segun el TOML con el que se creo)


@pytest.fixture
def real(guardado):
    """(servidor falso con el PSS real, estado de la BD ya cargado en `guardado`)."""
    srv = FServidorReal()
    guardado.update(estado_real())
    publicar_mensajes_reales(srv, guardado)
    return srv, guardado


async def aplicar_real(srv, config, estado, admin=True, permisos=8):
    plan = plan_de(srv, config, estado, admin, permisos)
    from profiles.pss import PanelEspecialidades
    cog = types.SimpleNamespace(config=config)                      # lo unico que usa la vista para pintar los botones
    return plan, await ejecutar(srv, plan, config, estado, lambda botones: PanelEspecialidades(cog, botones))


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
        "info_estudio", "sugerencias", "comandos", "ayuda", "bienvenida", "niveles", "pruebas_bot", "helper", "novedades",
        "activo_mes", "og", "fundador", "leyenda", "veterano", "cat_tickets", "soporte", "tickets_log", "voz_activa",
        "cat_juego", "codigos", "reportar_bugs", "eventos", "movil", "pc", "consola"}
    assert [x for x in plan.acciones if x.op == "bloqueado"] == []
    assert {k for k, x in a.items() if x.op == "omitir"} == {
        "propietario", "administrador", "developer", "colaborador", "miembro", "scripter", "builder", "ui",
        "voz_general", "reuniones"}
    actualizar = {k for k, x in a.items() if x.op == "actualizar"}
    assert actualizar == {
        "cat_estudio", "cat_comunidad", "cat_voz", "cat_equipo", "cat_staff",
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
    assert {k for k, x in a.items() if x.op == "bloqueado"} == {"anuncios", "ayuda", "reportar_bugs", "msg_reglas", "msg_guia"}
    assert "activa Comunidad" in a["anuncios"].razon and "activa Comunidad" in a["ayuda"].razon
    assert {k for k, x in a.items() if x.op == "crear"} == {
        "info_estudio", "sugerencias", "comandos", "bienvenida", "niveles", "pruebas_bot", "helper", "novedades",
        "activo_mes", "og", "fundador", "leyenda", "veterano", "cat_tickets", "soporte", "tickets_log", "voz_activa",
        "cat_juego", "codigos", "eventos", "movil", "pc", "consola"}
    texto = "\n".join(lineas_plan(plan))
    assert "reemplazado" not in texto and "Categoría «📢 Anuncios»" not in texto     # anuncios sigue ahi
    assert "Categoría «🟥 Roblox»: queda **vacía**" in texto


# --- aplicar sobre el estado real: el orden --------------------------------------------------------------------
async def comprobar_orden(srv, detras=None):
    """Las categorias del TOML en su orden y, DETRAS, las sobrantes. `detras`: canales que el TOML ya no
    menciona y que se quedan al final de su categoria (el bot no los borra)."""
    cats, hijos = orden_actual(srv)
    n = len(CATEGORIAS_FINAL)
    assert cats[:n] == CATEGORIAS_FINAL
    assert SOBRANTES <= set(cats[n:]) <= SOBRANTES | DESARROLLO and len(set(cats[n:])) == len(cats[n:])
    for categoria, esperados in HIJOS_FINAL.items():
        assert hijos[categoria] == esperados + (detras or {}).get(categoria, []), categoria
    for vacia in (set(cats[n:]) - {"🛠️ Soporte"}):
        assert hijos[vacia] == [], vacia
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
        "👻 Phantom Shadows Studios", "🧭 Guía para jugadores", "🎭 Elige tus roles"]
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
    assert cats[:5] == ["📌 » IMPORTANTE", "🎮 » EL JUEGO", "💬 » COMUNIDAD", "🔊 » VOZ", "🔒 » EQUIPO"]
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
                             "adoptar": True, "mover": True, "categoria": "cat_comunidad", "orden": 9})
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
    # el resto sigue aplicandose: 13 canales y categorias nuevos (JUEGO, TICKETS y sus canales...)
    assert len(srv.canales) == antes + 13
    assert res.fallos == []


# --- El juego sobre lo DESPLEGADO: el estado real + los pss.toml de las Fases 0 a 3 aplicados ---------------------------
FASE3 = Path(__file__).resolve().parent / "fixtures" / "pss_fase3.toml"


@pytest.fixture
async def desplegado(real):
    """PSS tal como esta hoy: el export real al que se le aplicaron los pss.toml de las Fases 0, 1, 2 y 3
    (en cada paso el plan, con el bot en permisos minimos, da «coincide»)."""
    srv, estado = real
    for ruta in (FASE0, FASE1, FASE2, FASE3):
        config = cargar(ruta)
        plan, res = await aplicar_real(srv, config, estado)
        assert res.fallos == [] and res.bloqueadas == []
        assert plan_de(srv, config, estado, admin=False, permisos=MINIMO_BOT).coincide(), ruta.name
    return srv, estado


async def test_plan_del_juego_sobre_lo_desplegado(desplegado):
    srv, estado = desplegado
    plan = plan_de(srv, cargar(RUTA), estado)
    a = acciones(plan)
    assert {k for k, x in a.items() if x.op == "crear"} == {
        "cat_juego", "codigos", "reportar_bugs", "eventos", "movil", "pc", "consola"}
    assert {k for k, x in a.items() if x.op == "actualizar"} == {
        "sugerencias", "ayuda", "soporte", "showcase", "scripting_luau", "info_estudio",
        "msg_reglas", "msg_info_estudio", "msg_guia", "msg_especialidades", "@orden"}
    assert [x for x in plan.acciones if x.op == "bloqueado"] == []
    assert a["scripting_luau"].cambios == {"mover": "cat_equipo", "sincronizar": True}      # pasa a ser privado
    for key in ("sugerencias", "ayuda", "soporte"):
        assert a[key].cambios["mover"] == "cat_juego", key
    assert a["showcase"].cambios["nombre"] == "📸・capturas"
    assert a["cat_comunidad"].op == "omitir"
    # «A mano»: lo que el TOML ya no tiene (el bot no borra)
    texto = "\n".join(lineas_plan(plan))
    assert "Canal «🙋・presentaciones» ya no está en el TOML: bórralo a mano" in texto
    assert "`!pss olvidar presentaciones`" in texto
    assert "Categoría «💻 » DESARROLLO»: queda **vacía**; bórrala a mano" in texto
    assert "«ayuda» queda **reemplazado**" in texto
    # el nombre del juego esta vacio: la categoria se llama «EL JUEGO»
    assert "🎮 » EL JUEGO" in texto


async def test_aplicar_el_juego_sobre_lo_desplegado_deja_el_servidor_coincidiendo(desplegado):
    srv, estado = desplegado
    config = cargar(RUTA)
    _, res = await aplicar_real(srv, config, estado)
    assert res.fallos == [] and res.bloqueadas == []
    await comprobar_orden(srv, detras={"💬 » COMUNIDAD": ["🙋・presentaciones"]})
    c = por_nombre(srv)
    assert c["🙋・presentaciones"].tipo == "text"                          # NO se borra
    # lo que se mueve conserva su ID; scripting-luau queda privado (sincronizado con EQUIPO)
    assert c["🟥・scripting-luau"].overwrites == c["🔒 » EQUIPO"].overwrites
    assert c["💡・sugerencias"].category_id == c["🎮 » EL JUEGO"].id and c["❓・ayuda"].tipo == "forum"
    # los mensajes de info-estudio se editan EN SU SITIO (mismos IDs)
    info = list(c["ℹ️・info-estudio"].mensajes.values())
    assert [m.embed.title for m in info] == ["👻 Phantom Shadows Studios", "🧭 Guía para jugadores", "🎭 Elige tus roles"]
    assert not any("mensaje antiguo del bot borrado" in h for h in res.hechos)
    # info: sin nombre del juego ni grupo, solo el campo del equipo
    assert [f.name for f in info[0].embed.fields] == ["🤝 ¿Quieres unirte al equipo?"]
    assert f"<#{c['🎫・soporte'].id}>" in info[0].embed.fields[0].value
    # guia: 5 campos, ninguno en linea
    guia = info[1].embed
    assert [f.name for f in guia.fields] == ["1️⃣ Empieza aquí", "🎮 El juego", "🐛 ¿Algo falla?", "🆘 Ayuda", "💬 Comunidad"]
    assert not any(f.inline for f in guia.fields)
    assert f"<#{c['🎁・códigos'].id}>" in guia.fields[1].value and f"<#{c['🐛・reportar-bugs'].id}>" in guia.fields[2].value
    assert f"<#{c['📸・capturas'].id}>" in guia.fields[4].value
    # panel de roles: filas, estilos, emojis y el custom_id de Novedades intacto
    panel = info[2]
    assert panel.embed.description == "Pulsa un botón para darte el rol; púlsalo otra vez para quitártelo."
    botones = panel.view.children
    assert [b.custom_id for b in botones] == [f"pss::rol::{k}" for k in ("novedades", "eventos", "movil", "pc", "consola")]
    assert [b.row for b in botones] == [0, 0, 1, 1, 1]
    assert [b.style.name for b in botones] == ["success", "success", "secondary", "secondary", "secondary"]
    assert [str(b.emoji) for b in botones] == ["🔔", "🎉", "📱", "💻", "🎮"]
    assert [b.label for b in botones] == ["Novedades", "Eventos", "Móvil", "PC", "Consola"]
    # las reglas: la del juego
    reglas = list(c["📜・reglas"].mensajes.values())[0].embed.description
    assert "6️⃣ **No uses ni compartas exploits o hacks.**" in reglas and f"<#{c['🐛・reportar-bugs'].id}>" in reglas
    plan = plan_de(srv, config, estado, admin=False, permisos=MINIMO_BOT)
    assert plan.coincide(), "\n".join(lineas_plan(plan))
    llamadas = list(srv.llamadas)
    await aplicar_real(srv, config, estado)
    assert srv.llamadas == llamadas


async def test_al_rellenar_el_juego_se_renombra_la_categoria_y_se_actualizan_los_mensajes(desplegado):
    srv, estado = desplegado
    await aplicar_real(srv, cargar(RUTA), estado)
    with RUTA.open("rb") as f:
        datos = tomllib.load(f)
    datos["juego"] = {"nombre": "Mi Juego", "enlace_juego": "https://www.roblox.com/games/123/Mi-Juego",
                      "enlace_grupo": "https://www.roblox.com/communities/456/PSS"}
    config = parsear(datos)
    assert config.categoria("cat_juego").nombre == "🎮 » MI JUEGO"
    plan = plan_de(srv, config, estado)
    a = acciones(plan)
    assert {k for k, x in a.items() if x.op != "omitir"} == {"cat_juego", "msg_info_estudio"}      # solo eso cambia
    assert a["cat_juego"].cambios["nombre"] == "🎮 » MI JUEGO"
    _, res = await aplicar_real(srv, config, estado)
    assert res.fallos == []
    c = por_nombre(srv)
    assert "🎮 » MI JUEGO" in c and "🎮 » EL JUEGO" not in c
    info = list(c["ℹ️・info-estudio"].mensajes.values())[0].embed
    assert [f.name for f in info.fields] == ["🎮 El juego", "👥 Grupo de Roblox", "🤝 ¿Quieres unirte al equipo?"]
    assert info.fields[0].value == "[Mi Juego](https://www.roblox.com/games/123/Mi-Juego)"
    assert info.fields[1].value == "https://www.roblox.com/communities/456/PSS"
    assert plan_de(srv, config, estado, admin=False, permisos=MINIMO_BOT).coincide()
