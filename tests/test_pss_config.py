"""Loader y validador de profiles/pss.toml (sin Discord ni BD)."""

import copy
from pathlib import Path

import pytest

from profiles.pss_config import ConfigInvalida, cargar, parsear

RUTA_REAL = Path(__file__).resolve().parent.parent / "profiles" / "pss.toml"

BASE = {
    "perfil": {"guild_id": 10, "gestores": []},
    "eventos": {"rol_al_entrar": "miembro", "bienvenida": "general", "canal_logs": "logs"},
    "roles": [{"key": "miembro", "nombre": "Miembro", "color": "#2ECC71",
               "permisos": ["send_messages"]}],
    "categorias": [{"key": "cat_a", "nombre": "A", "orden": 1,
                    "overrides": [{"objetivo": "@everyone", "denegar": ["view_channel"]},
                                  {"objetivo": "miembro", "permitir": ["view_channel"]}]}],
    "canales": [{"key": "general", "nombre": "general", "categoria": "cat_a"},
                {"key": "logs", "nombre": "logs", "categoria": "cat_a"}],
    "mensajes": [{"key": "msg", "canal": "general", "titulo": "Hola {canal:logs}"}],
}


def datos(**cambios):
    d = copy.deepcopy(BASE)
    d.update(cambios)
    return d


def errores_de(d):
    with pytest.raises(ConfigInvalida) as e:
        parsear(d)
    return e.value.errores


def alguno(errores, *trozos):
    return any(all(t in e for t in trozos) for e in errores)


def test_la_base_es_valida():
    c = parsear(BASE)
    assert c.guild_id == 10 and c.rol("miembro").color == 0x2ECC71
    assert c.canal("general").categoria == "cat_a"


def test_el_toml_real_es_valido_y_refleja_lo_acordado():
    c = cargar(RUTA_REAL)
    assert c.guild_id == 1420403964746268684 and c.owner_id == 668148837579227137
    assert c.gestores == ()
    # PSS es publico: XP y voz apagadas, pero el filtro de cuentas nuevas SI se aplica
    assert (c.eventos.xp, c.eventos.voz, c.eventos.anti_multicuentas) == (False, False, True)
    assert c.eventos.rol_al_entrar == "miembro" and c.eventos.canal_logs == "registros"
    assert c.canal("registros").categoria == "cat_staff"
    # Propietario: solo color y hoist, sin permisos (ni administrator)
    assert c.rol("propietario").permisos == () and c.rol("propietario").hoist
    # Developer existente: se reutiliza sin adoptar
    assert c.rol("developer").existing_id == 1561497283315638312 and not c.rol("developer").adoptar
    assert not any("administrator" in r.permisos for r in c.roles)


def test_estructura_publica_solo_equipo_y_staff_son_privadas():
    c = cargar(RUTA_REAL)
    assert c.categoria("cat_proyectos") is None            # sustituida por Equipo
    privadas = {cat.key for cat in c.categorias
                if any(o.objetivo == "@everyone" and "view_channel" in o.denegar for o in cat.overrides)}
    assert privadas == {"cat_equipo", "cat_staff"}
    equipo = c.categoria("cat_equipo")
    assert equipo.nombre == "🔒 Equipo"
    visibles = {o.objetivo for o in equipo.overrides if "view_channel" in o.permitir}
    assert visibles == {"developer", "colaborador", "administrador"}
    staff = c.categoria("cat_staff")
    assert {o.objetivo for o in staff.overrides if "view_channel" in o.permitir} == {"propietario", "administrador"}
    # Anuncios y Estudio: visibles para todos, solo lectura para @everyone; escriben developer y administrador
    for key in ("cat_anuncios", "cat_estudio"):
        cat = c.categoria(key)
        todos = next(o for o in cat.overrides if o.objetivo == "@everyone")
        assert "send_messages" in todos.denegar and "view_channel" not in todos.denegar
        assert {o.objetivo for o in cat.overrides if "send_messages" in o.permitir} == {"developer", "administrador"}
    # Desarrollo, Roblox, Comunidad, Soporte y Voz: sin restricciones
    for key in ("cat_desarrollo", "cat_roblox", "cat_comunidad", "cat_soporte", "cat_voz"):
        assert c.categoria(key).overrides == ()


def test_canales_existentes_y_nuevos_segun_lo_acordado():
    c = cargar(RUTA_REAL)
    for key in ("info_importante", "planificacion_sesiones"):
        canal = c.canal(key)
        assert canal.categoria == "cat_equipo" and canal.mover and canal.sincronizar_permisos
        assert not canal.adoptar and canal.tema is None        # no se cambia su tema
    # #deberes-ayuda se renombra a #ayuda (adoptar) y se busca por su nombre actual
    ayuda = c.canal("ayuda")
    assert (ayuda.nombre, ayuda.nombre_actual, ayuda.adoptar) == ("ayuda", "deberes-ayuda", True)
    assert ayuda.categoria == "cat_soporte" and ayuda.tema is None       # solo cambia el nombre
    # Reuniones pasa a Equipo (privado, sincronizado); la voz publica nueva es "🔊 General"
    reuniones = c.canal("reuniones")
    assert reuniones.categoria == "cat_equipo" and reuniones.mover and reuniones.sincronizar_permisos
    assert reuniones.tipo == "voice" and not reuniones.adoptar
    voz = c.canal("voz_general")
    assert (voz.nombre, voz.tipo, voz.categoria, voz.overrides) == ("🔊 General", "voice", "cat_voz", ())
    assert [x.key for x in c.canales if x.categoria == "cat_voz"] == ["voz_general"]
    for key in ("frontend", "backend"):                         # publicos: se mueven, sin sincronizar
        assert c.canal(key).categoria == "cat_desarrollo" and c.canal(key).mover
        assert not c.canal(key).sincronizar_permisos
    assert c.canal("showcase").categoria == "cat_comunidad" and not c.canal("showcase").overrides
    assert c.canal("scripting_luau").categoria == "cat_roblox"
    texto = [x for x in c.canales if x.tipo == "text"]
    assert len(texto) <= 12 and len([x for x in c.canales if x.tipo == "voice"]) == 2


def test_las_reglas_son_de_comunidad_publica():
    c = cargar(RUTA_REAL)
    reglas = c.mensaje("msg_reglas").descripcion.lower()
    for tema in ("respeto", "spam", "publicidad", "código ni assets ajenos", "cada canal", "staff"):
        assert tema in reglas
    assert {m.canal for m in c.mensajes} == {"reglas"}
    assert "{canal:ayuda}" in reglas
    assert "msg_proyectos_activos" not in {m.key for m in c.mensajes}
    assert "setup" in c.comandos_bloqueados and "pss" not in c.comandos_bloqueados


def test_permiso_invalido_con_sugerencia():
    d = datos()
    d["roles"][0]["permisos"] = ["manage_server"]
    errores = errores_de(d)
    assert alguno(errores, "roles[0] 'miembro'", "manage_server", "manage_guild")


def test_administrator_exige_permitir_admin():
    d = datos()
    d["roles"][0]["permisos"] = ["administrator"]
    assert alguno(errores_de(d), "administrator", "permitir_admin")
    d["roles"][0]["permitir_admin"] = True
    assert parsear(d).rol("miembro").permitir_admin


def test_claves_duplicadas_entre_tipos():
    d = datos()
    d["canales"].append({"key": "miembro", "nombre": "x", "categoria": "cat_a"})
    assert alguno(errores_de(d), "key duplicada", "miembro")


def test_referencias_inexistentes():
    d = datos()
    d["categorias"][0]["overrides"][1]["objetivo"] = "fantasma"
    d["canales"][0]["categoria"] = "no_existe"
    d["mensajes"][0]["canal"] = "nada"
    d["eventos"]["rol_al_entrar"] = "otro"
    d["perfil"]["gestores"] = ["jefe"]
    errores = errores_de(d)
    assert alguno(errores, "fantasma")
    assert alguno(errores, "no_existe")
    assert alguno(errores, "mensaje 'msg'.canal", "nada")
    assert alguno(errores, "eventos.rol_al_entrar", "otro")
    assert alguno(errores, "perfil.gestores", "jefe")


def test_placeholder_a_recurso_inexistente():
    d = datos()
    d["mensajes"][0]["descripcion"] = "mira {rol:nadie} y {canal:tampoco}"
    errores = errores_de(d)
    assert alguno(errores, "{rol:nadie}") and alguno(errores, "{canal:tampoco}")


def test_se_reportan_todos_los_errores_juntos():
    d = datos()
    d["roles"][0]["permisos"] = ["nope"]
    d["roles"][0]["color"] = "rojo"
    d["canales"][0]["slowmode"] = 99999
    assert len(errores_de(d)) >= 3


def test_limites_de_discord():
    d = datos()
    d["roles"][0]["nombre"] = "x" * 101
    d["canales"][0]["tema"] = "t" * 1025
    d["canales"][0]["slowmode"] = 21601
    d["mensajes"][0]["titulo"] = "t" * 257
    d["mensajes"][0]["descripcion"] = "d" * 4097
    errores = errores_de(d)
    assert alguno(errores, "roles[0]", "nombre", "101")
    assert alguno(errores, "tema", "1025")
    assert alguno(errores, "slowmode", "21601")
    assert alguno(errores, "titulo", "257")
    assert alguno(errores, "descripcion", "4097")


def test_limite_de_50_canales_por_categoria():
    d = datos()
    d["canales"] = [{"key": f"c{i}", "nombre": f"c{i}", "categoria": "cat_a"} for i in range(51)]
    d["eventos"] = {}
    d["mensajes"] = []
    assert alguno(errores_de(d), "cat_a", "51", "50")


def test_limite_de_250_roles_y_500_canales():
    d = datos()
    d["roles"] = [{"key": f"r{i}", "nombre": f"r{i}"} for i in range(251)]
    d["categorias"][0]["overrides"] = []
    d["eventos"] = {}
    assert alguno(errores_de(d), "251", "250")
    d = datos()
    d["categorias"] = [{"key": f"cat{i}", "nombre": f"c{i}"} for i in range(11)]
    d["canales"] = [{"key": f"ch{i}", "nombre": f"c{i}", "categoria": f"cat{i % 11}"} for i in range(490)]
    d["eventos"] = {}
    d["mensajes"] = []
    assert alguno(errores_de(d), "501", "500")


def test_embed_demasiado_grande():
    d = datos()
    d["mensajes"][0] = {"key": "msg", "canal": "general", "descripcion": "a" * 4000,
                        "campos": [{"nombre": "n", "valor": "v" * 1000} for _ in range(3)]}
    assert alguno(errores_de(d), "embed", "6000")


def test_clave_desconocida_y_key_mal_formada():
    d = datos()
    d["roles"][0]["colorr"] = "#fff"
    d["canales"][0]["key"] = "Mala Key"
    errores = errores_de(d)
    assert alguno(errores, "colorr", "desconocida")
    assert alguno(errores, "key", "[a-z0-9_]")


def test_rol_autoasignable_no_puede_ser_elevado_ni_existente():
    d = datos()
    d["roles"].append({"key": "esp", "nombre": "Esp", "autoasignable": True, "permisos": ["manage_roles"]})
    assert alguno(errores_de(d), "autoasignable", "elevados", "manage_roles")
    d["roles"][1] = {"key": "esp", "nombre": "Esp", "autoasignable": True, "existing_id": 5}
    assert alguno(errores_de(d), "autoasignable", "existing_id")


def test_botones_solo_de_roles_autoasignables():
    d = datos()
    d["mensajes"][0]["botones_roles"] = ["miembro"]
    assert alguno(errores_de(d), "botones_roles", "no es autoasignable")


def test_no_se_puede_bloquear_pss_y_existing_id_no_se_repite():
    d = datos()
    d["comandos"] = {"bloquear": ["pss"]}
    assert alguno(errores_de(d), "pss")
    d = datos()
    d["roles"].append({"key": "otro", "nombre": "Otro", "existing_id": 7})
    d["roles"][0]["existing_id"] = 7
    assert alguno(errores_de(d), "existing_id 7")


def test_overrides_contradictorios():
    d = datos()
    d["categorias"][0]["overrides"] = [{"objetivo": "@everyone", "permitir": ["view_channel"], "denegar": ["view_channel"]}]
    assert alguno(errores_de(d), "a la vez")
    d = datos()
    d["canales"][0]["sincronizar_permisos"] = True
    d["canales"][0]["overrides"] = [{"objetivo": "@everyone", "denegar": ["send_messages"]}]
    assert alguno(errores_de(d), "sincronizar_permisos", "overrides")


def test_nombre_actual_solo_con_adoptar():
    d = datos()
    d["canales"][0]["nombre_actual"] = "viejo"
    assert alguno(errores_de(d), "nombre_actual", "adoptar")
    d["canales"][0]["adoptar"] = True
    assert parsear(d).canal("general").nombre_actual == "viejo"


def test_toml_roto_o_inexistente(tmp_path):
    malo = tmp_path / "malo.toml"
    malo.write_text("[perfil\nguild_id = 1", encoding="utf-8")
    with pytest.raises(ConfigInvalida) as e:
        cargar(malo)
    assert "no es un TOML valido" in str(e.value)
    with pytest.raises(ConfigInvalida) as e:
        cargar(tmp_path / "no_existe.toml")
    assert "no existe" in str(e.value)
