"""Textos y constantes: avisos al usuario y enlaces."""

import re
from pathlib import Path

CODIGO = (Path(__file__).resolve().parent.parent / "eito_setup_bot.py").read_text(encoding="utf-8")


def test_ningun_mensaje_manda_a_correr_setup():
    assert not re.search(r"[Cc]orre !setup|debe correr", CODIGO)


async def test_los_canales_que_faltan_piden_avisar_a_un_admin(mod, fakes):
    guild = fakes.Guild()  # sin ningun canal
    ctx = fakes.Ctx(guild=guild, canal=fakes.Canal("general"))

    await mod.reglas.callback(ctx)
    await mod.panelroles.callback(ctx)
    await mod.presentaciones.callback(ctx)
    await mod.anuncio.callback(ctx, texto="hola")

    assert len(ctx.respuestas) == 4
    for contenido, _kwargs in ctx.respuestas:
        assert contenido.endswith("Avisa a un admin.")


async def test_jugar_sin_rol_pide_avisar_a_un_admin(mod, fakes, monkeypatch):
    monkeypatch.setattr(mod, "ultimo_jugar", {})
    ctx = fakes.Ctx(guild=fakes.Guild(), canal=fakes.Canal("general"))

    await mod.jugar.callback(ctx, mensaje="")

    assert ctx.respuestas[0][0].endswith("Avisa a un admin.")


def test_el_enlace_del_mod_loader_es_una_constante(mod):
    assert mod.MODLOADER_URL.startswith("https://www.mediafire.com/")
    assert CODIGO.count("mediafire.com") == 1  # solo en la constante


async def test_el_mensaje_del_mod_loader_usa_la_constante(mod, fakes):
    guild = fakes.Guild()
    canal = guild.canal(mod.CANAL_MODLOADER)  # sin mensajes: se publica la presentacion
    ctx = fakes.Ctx(guild=guild, canal=canal)

    await mod.configurar_canal_modloader(ctx)

    embed = canal.enviados[0][1]["embed"]
    assert mod.MODLOADER_URL in embed.description
