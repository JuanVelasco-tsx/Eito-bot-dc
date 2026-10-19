"""Ningun rol del perfil es mencionable por miembros; directrices de los foros en el tema del canal, y el
perfil nunca toca etiquetas, reaccion por defecto ni archivado de los foros."""

import tomllib
from pathlib import Path

import discord

from profiles import pss_exec, pss_plan
from profiles.pss_config import cargar, parsear
from tests.pss_fakes import MINIMO_BOT
from tests.test_pss_real import (  # noqa: F401  (desplegado y real son fixtures)
    RUTA, aplicar_real, desplegado, real, plan_de, acciones, guardado,
)
from tests.test_recursos import FRol, FTexto, GuildPSS, perfil, sin_bd  # noqa: F401


def test_ningun_rol_del_perfil_es_mencionable_por_miembros():
    assert [r.key for r in cargar(RUTA).roles if r.mentionable] == []


def test_el_bot_puede_mencionar_roles_no_mencionables():
    assert discord.Permissions(MINIMO_BOT).mention_everyone is True


async def test_el_webhook_menciona_novedades_aunque_no_sea_mencionable(mod, fakes, perfil, monkeypatch):
    novedades_cfg = perfil.config.rol("novedades")
    assert not novedades_cfg.mentionable                                  # el rol del TOML no es mencionable
    guild = GuildPSS()
    anuncios = guild.canales[32] = FTexto(32, "📣・anuncios")
    novedades = FRol(33, "🔔 Novedades")
    guild.roles.append(novedades)
    perfil.ids = {"anuncios": 32, "novedades": 33}
    monkeypatch.setattr(mod.bot, "get_guild", lambda ident: guild)
    respuesta = await mod.handle_release_webhook(
        fakes.Peticion({"Authorization": "Bearer secreto-de-prueba"}, {"version": "1", "destino": "pss"}))
    assert respuesta.status == 200
    contenido, kwargs = anuncios.enviados[0]
    # la mencion se pide explicitamente (allowed_mentions) y el bot tiene mention_everyone: notifica
    assert contenido == "<@&33>" and [r.id for r in kwargs["allowed_mentions"].roles] == [33]


def test_directrices_de_los_foros():
    c = cargar(RUTA)
    assert c.canal("reportar_bugs").tema == (
        "Un bug por publicación, con un título corto que lo describa. Indica tu plataforma, qué estabas haciendo, "
        "qué esperabas y qué pasó; si puedes, añade captura o vídeo. Busca antes por si ya está reportado. "
        "Los exploits NO se publican aquí: repórtalos por ticket en #🎫・soporte.")
    assert c.canal("ayuda").tema == (
        "Una duda por publicación, con un título claro. Busca antes por si ya está respondida y marca ✅ Resuelto "
        "cuando te ayuden. Para temas privados (cuenta, compras), abre un ticket en #🎫・soporte.")
    assert all(c.canal(k).tipo == "forum" for k in ("reportar_bugs", "ayuda"))


def test_el_perfil_no_menciona_etiquetas_reaccion_ni_archivado_de_los_foros():
    for modulo in (pss_exec, pss_plan):
        codigo = Path(modulo.__file__).read_text(encoding="utf-8")
        for palabra in ("available_tags", "default_reaction", "default_auto_archive", "default_thread_slowmode",
                        "default_sort_order", "default_layout", "require_tag", "flags"):
            assert palabra not in codigo, (modulo.__name__, palabra)


async def test_cambiar_el_tema_de_un_foro_solo_edita_el_tema(desplegado):
    srv, estado = desplegado
    await aplicar_real(srv, cargar(RUTA), estado)                          # el estado actual, ya con los foros
    foros = {c.name for c in srv.canales.values() if c.tipo == "forum"}
    assert foros == {"❓・ayuda", "🐛・reportar-bugs"}
    with RUTA.open("rb") as f:
        datos = tomllib.load(f)
    for canal in datos["canales"]:
        if canal["key"] in ("ayuda", "reportar_bugs"):
            canal["tema"] += " (editado)"
    config = parsear(datos)
    antes = len(srv.llamadas)
    plan, res = await aplicar_real(srv, config, estado)
    assert res.fallos == [] and {k for k, a in acciones(plan).items() if a.op != "omitir"} == {"ayuda", "reportar_bugs"}
    ediciones = [ll for ll in srv.llamadas[antes:] if ll[0] == "edit_channel"]
    assert sorted(ll[2] for ll in ediciones) == [("topic",), ("topic",)]       # NADA mas: ni etiquetas ni reaccion ni archivado
    assert {c.name: c.topic.endswith("(editado)") for c in srv.canales.values() if c.tipo == "forum"} == {
        "❓・ayuda": True, "🐛・reportar-bugs": True}


async def test_al_crear_un_foro_solo_se_envian_nombre_categoria_overwrites_y_tema(real):
    srv, estado = real
    enviados = []
    original = srv.create_forum

    async def espia(nombre, **opciones):
        enviados.append((nombre, set(opciones)))
        return await original(nombre, **opciones)

    srv.create_forum = espia
    await aplicar_real(srv, cargar(RUTA), estado)
    assert {n for n, _ in enviados} == {"❓・ayuda", "🐛・reportar-bugs"}
    for _nombre, claves in enviados:
        assert claves <= {"category", "overwrites", "topic", "slowmode_delay", "reason"}
