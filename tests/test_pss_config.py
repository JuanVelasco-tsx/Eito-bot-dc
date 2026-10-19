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
    # Orden de las categorias y nombres con el formato "emoji » NOMBRE"
    cats = sorted(c.categorias, key=lambda x: x.orden)
    assert [x.nombre for x in cats] == [
        "📌 » IMPORTANTE", "💬 » COMUNIDAD", "💻 » DESARROLLO", "🔊 » VOZ", "🔒 » EQUIPO", "🛡️ » STAFF"]
    assert [x.key for x in cats] == ["cat_estudio", "cat_comunidad", "cat_desarrollo", "cat_voz", "cat_equipo", "cat_staff"]
    for vieja in ("cat_anuncios", "cat_roblox", "cat_soporte", "cat_proyectos"):
        assert c.categoria(vieja) is None                  # fusionadas: sus canales se mueven
    privadas = {cat.key for cat in c.categorias
                if any(o.objetivo == "@everyone" and "view_channel" in o.denegar for o in cat.overrides)}
    assert privadas == {"cat_equipo", "cat_staff"}
    equipo = c.categoria("cat_equipo")
    assert {o.objetivo for o in equipo.overrides if "view_channel" in o.permitir} == {"developer", "colaborador", "administrador"}
    staff = c.categoria("cat_staff")
    assert {o.objetivo for o in staff.overrides if "view_channel" in o.permitir} == {"propietario", "administrador"}
    # IMPORTANTE: visible para todos, solo lectura para @everyone; escriben developer y administrador
    importante = c.categoria("cat_estudio")
    todos = next(o for o in importante.overrides if o.objetivo == "@everyone")
    assert "send_messages" in todos.denegar and "view_channel" not in todos.denegar
    assert {o.objetivo for o in importante.overrides if "send_messages" in o.permitir} == {"developer", "administrador"}
    for key in ("cat_comunidad", "cat_desarrollo", "cat_voz"):
        assert c.categoria(key).overrides == ()


def test_el_formato_de_nombres_es_emoji_y_punto_medio():
    c = cargar(RUTA_REAL)
    for canal in c.canales:
        if canal.tipo == "voice":
            continue
        emoji, sep, resto = canal.nombre.partition("・")
        assert sep == "・" and emoji and resto == resto.lower() and " " not in resto, canal.nombre
    for cat in c.categorias:
        assert " » " in cat.nombre and cat.nombre.split(" » ")[1].isupper(), cat.nombre


def test_canales_existentes_renombrados_con_adoptar_y_nombre_actual():
    c = cargar(RUTA_REAL)
    esperado = {"general": "general", "no_relacionado": "no-relacionado", "info_importante": "info-importante",
                "planificacion_sesiones": "planificación-de-sesiones"}
    for key, actual in esperado.items():
        canal = c.canal(key)
        assert canal.adoptar and canal.nombre_actual == actual and canal.mover, key
        assert canal.tema is None, key                          # solo se renombra: no se cambia el tema
    # los creados por el bot no necesitan adoptar: se renombran por estar mapeados
    for key in ("reglas", "anuncios", "showcase", "scripting_luau", "registros"):
        assert not c.canal(key).adoptar and c.canal(key).nombre_actual is None, key


def test_canales_segun_la_estructura_objetivo():
    c = cargar(RUTA_REAL)
    en = lambda cat: [x.nombre for x in sorted((x for x in c.canales if x.categoria == cat), key=lambda x: x.orden)]
    assert en("cat_estudio") == ["📜・reglas", "📣・anuncios", "ℹ️・info-estudio"]
    assert en("cat_comunidad") == ["💬・general", "📸・showcase", "💡・sugerencias", "🤖・comandos", "🎲・no-relacionado"]
    assert en("cat_desarrollo") == ["🟥・scripting-luau", "❓・ayuda"]
    assert en("cat_voz") == ["🔊 General"]
    assert en("cat_equipo") == ["📌・info-importante", "🗓️・planificación-de-sesiones", "Reuniones"]
    assert en("cat_staff") == ["🛡️・registros"]
    # tipos: anuncios = news (se convierte el existente), ayuda = foro nuevo que reemplaza al canal de texto
    assert c.canal("anuncios").tipo == "news" and c.canal("anuncios").mover
    ayuda = c.canal("ayuda")
    assert ayuda.tipo == "forum" and ayuda.reemplaza == "ayuda" and not ayuda.adoptar and ayuda.nombre_actual is None
    assert c.canal("info_estudio").categoria == "cat_estudio" and not c.canal("info_estudio").mover
    # Equipo: existentes movidos y sincronizados, sin cambiar su tema
    for key in ("info_importante", "planificacion_sesiones", "reuniones"):
        assert c.canal(key).categoria == "cat_equipo" and c.canal(key).sincronizar_permisos, key
    assert c.canal("reuniones").nombre == "Reuniones" and not c.canal("reuniones").adoptar
    # Desarrollo y Comunidad son publicos: nada de sincronizar
    for key in ("general", "no_relacionado"):
        assert not c.canal(key).sincronizar_permisos, key
    # #frontend y #backend los borro el dueño a proposito: el TOML ya no los menciona
    assert c.canal("frontend") is None and c.canal("backend") is None
    assert not any("frontend" in x.nombre or "backend" in x.nombre for x in c.canales)
    assert c.canal("voz_general").tipo == "voice" and c.canal("voz_general").overrides == ()
    # hasta 16 canales de texto (texto + anuncios + foros), mas la voz
    no_voz = [x for x in c.canales if x.tipo != "voice"]
    assert len(no_voz) == 13 <= 16 and len([x for x in c.canales if x.tipo == "voice"]) == 2


def test_sugerencias_usa_el_nombre_exacto_que_busca_el_comando_de_eito(mod):
    c = cargar(RUTA_REAL)
    assert c.canal("sugerencias").nombre == mod.CANAL_SUGERENCIAS == "💡・sugerencias"
    assert c.canal("sugerencias").tipo == "text" and c.canal("sugerencias").categoria == "cat_comunidad"
    assert c.canal("comandos").nombre == "🤖・comandos"


def test_las_reglas_son_de_comunidad_publica():
    c = cargar(RUTA_REAL)
    reglas = c.mensaje("msg_reglas").descripcion.lower()
    for tema in ("respeto", "spam", "publicidad", "código ni assets ajenos", "cada canal", "staff"):
        assert tema in reglas
    # #reglas solo tiene las reglas; info, guia y botones van en #info-estudio
    assert [m.key for m in c.mensajes if m.canal == "reglas"] == ["msg_reglas"]
    assert {m.key for m in c.mensajes if m.canal == "info_estudio"} == {"msg_info_estudio", "msg_guia", "msg_especialidades"}
    assert c.mensaje("msg_especialidades").botones_roles == ("scripter", "builder", "ui")
    assert "{canal:ayuda}" in reglas
    assert "msg_proyectos_activos" not in {m.key for m in c.mensajes}
    assert "setup" in c.comandos_bloqueados and "pss" not in c.comandos_bloqueados


def test_plantillas_comentadas_de_juego_y_archivo():
    """Las plantillas estan en el TOML pero comentadas; descomentandolas el archivo sigue siendo valido."""
    texto = RUTA_REAL.read_text(encoding="utf-8")
    assert "# nombre = \"🎮 » [JUEGO]\"" in texto and "# nombre = \"🗄️ » ARCHIVO\"" in texto
    for trozo in ('tipo = "news"', 'tipo = "forum"', "noticias", "códigos", "sugerencias-juego", "bug-report"):
        assert trozo in texto
    # descomentar solo los bloques de plantilla (los que llevan cat_juego1 / cat_archivo / juego1_*)
    lineas, salida, activo = texto.split("\n"), [], False
    for i, linea in enumerate(lineas):
        if linea.startswith("# [[") and any(k in " ".join(lineas[i:i + 4]) for k in ("cat_juego1", "cat_archivo", "juego1_")):
            activo = True
        elif not linea.startswith("#") or linea.strip() == "#":
            activo = False
        salida.append(linea[2:] if activo and linea.startswith("# ") else linea)
    import tomllib
    c = parsear(tomllib.loads("\n".join(salida)))
    assert c.categoria("cat_juego1").nombre == "🎮 » [JUEGO]"
    assert c.categoria("cat_archivo").nombre == "🗄️ » ARCHIVO"
    archivo = c.categoria("cat_archivo")
    assert "send_messages" in archivo.overrides[0].denegar and archivo.overrides[0].permitir == ()
    assert {x.tipo for x in c.canales if x.categoria == "cat_juego1"} == {"news", "text", "forum"}


def con_canal_extra(**campos):
    """datos() mas un canal 'otro' (los demas estan referenciados por eventos y mensajes)."""
    d = datos()
    d["canales"].append({"key": "otro", "nombre": "otro", "categoria": "cat_a", **campos})
    return d


def test_tipos_de_canal_news_y_forum():
    assert parsear(con_canal_extra(tipo="news")).canal("otro").tipo == "news"
    assert parsear(con_canal_extra(tipo="forum")).canal("otro").tipo == "forum"
    assert alguno(errores_de(con_canal_extra(tipo="stage")), "tipo", "news", "forum")
    # un anuncio no tiene slowmode; un foro no tiene limite de voz
    assert alguno(errores_de(con_canal_extra(tipo="news", slowmode=5)), "slowmode")
    assert alguno(errores_de(con_canal_extra(tipo="forum", limite_usuarios=5)), "limite_usuarios")
    assert parsear(con_canal_extra(tipo="forum", slowmode=5)).canal("otro").slowmode == 5


def test_los_mensajes_solo_pueden_ir_a_canales_de_texto_o_anuncios_no_a_foros():
    d = con_canal_extra(tipo="forum")
    d["mensajes"][0]["canal"] = "otro"
    assert alguno(errores_de(d), "mensaje 'msg'.canal", "otro")            # los foros no reciben mensajes del bot
    d = con_canal_extra(tipo="news")
    d["mensajes"][0]["canal"] = "otro"
    assert parsear(d).mensaje("msg").canal == "otro"                          # un canal de anuncios si


def test_reemplaza_solo_en_foros_y_nombre_actual_no_vale_para_foros():
    assert alguno(errores_de(con_canal_extra(reemplaza="viejo")), "reemplaza", "foros")
    assert parsear(con_canal_extra(tipo="forum", reemplaza="viejo")).canal("otro").reemplaza == "viejo"
    assert alguno(errores_de(con_canal_extra(tipo="forum", adoptar=True, nombre_actual="viejo")), "nombre_actual", "foro")


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


def test_por_encima_del_bot_es_opcional_booleano_y_solo_lo_usa_propietario():
    d = datos()
    assert parsear(d).rol("miembro").por_encima_del_bot is False
    d["roles"][0]["por_encima_del_bot"] = True
    assert parsear(d).rol("miembro").por_encima_del_bot is True
    d["roles"][0]["por_encima_del_bot"] = "si"
    assert errores_de(d)
    c = cargar(RUTA_REAL)
    assert [r.key for r in c.roles if r.por_encima_del_bot] == ["propietario"]


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
