"""Proteccion de menciones: el allowed_mentions EFECTIVO de cada envio.

El bot nace con everyone=False y roles=False (solo usuarios); los envios que deben
pinguear un rol o @everyone lo piden con su propio allowed_mentions.
"""

import json

import pytest


def test_configuracion_global(mod):
    permitidas = mod.bot.allowed_mentions
    assert permitidas.everyone is False
    assert permitidas.roles is False
    assert permitidas.users is True
    assert permitidas.replied_user is True


async def test_warn_con_everyone_en_la_razon_no_menciona(mod, fakes, efectivo, monkeypatch):
    async def add_warn(*args):
        return 1

    monkeypatch.setattr(mod, "add_warn", add_warn)
    guild = fakes.Guild()
    logs = guild.canal(mod.CANAL_LOGS)
    ctx = fakes.Ctx(guild=guild, canal=guild.canal("general"))
    miembro = fakes.Usuario(9, "Pepe")

    await mod.warn.callback(ctx, miembro, razon="@everyone @here <@&123> mira")

    envios = [kw for _contenido, kw in ctx.respuestas] + [kw for _c, kw in logs.enviados]
    assert len(envios) == 2  # la respuesta del comando y el log de moderacion
    for kwargs in envios:
        permitido = efectivo(kwargs)
        assert permitido.get("parse") == ["users"], permitido
        assert "roles" not in permitido


async def test_jugar_sigue_mencionando_al_rol_leftsito(mod, fakes, efectivo, monkeypatch):
    async def crear_lfg_post(*args):
        return 1

    monkeypatch.setattr(mod, "crear_lfg_post", crear_lfg_post)
    monkeypatch.setattr(mod, "ultimo_jugar", {})
    guild = fakes.Guild()
    rol = guild.rol(777, mod.ROL_LEFTSITO)
    canal = guild.canal(mod.CANAL_BUSCAR_PARTIDA)
    ctx = fakes.Ctx(guild=guild, canal=canal, autor=fakes.Usuario(1, "Ana"))

    await mod.jugar.callback(ctx, mensaje="hola")

    contenido, kwargs = canal.enviados[0]
    permitido = efectivo(kwargs)
    assert contenido == rol.mention
    assert permitido["roles"] == [777]
    assert "everyone" not in permitido.get("parse", [])


async def test_webhook_sigue_mencionando_al_rol_mod_loader(mod, fakes, efectivo, monkeypatch):
    guild = fakes.Guild()
    rol = guild.rol(888, mod.ROL_MODLOADER)
    canal = guild.canal(mod.CANAL_MODLOADER)
    monkeypatch.setattr(mod, "RELEASE_CHANNEL_ID", "123")
    monkeypatch.setattr(mod.bot, "get_channel", lambda _id: canal)
    peticion = fakes.Peticion(
        {"Authorization": "Bearer secreto-de-prueba"}, {"version": "1.0", "changelog": "x"}
    )

    respuesta = await mod.handle_release_webhook(peticion)

    assert respuesta.status == 200, json.loads(respuesta.text)
    contenido, kwargs = canal.enviados[0]
    permitido = efectivo(kwargs)
    assert contenido == rol.mention
    assert permitido["roles"] == [888]
    assert "everyone" not in permitido.get("parse", [])


async def test_anuncio_everyone_sigue_funcionando(mod, fakes, efectivo):
    guild = fakes.Guild()
    canal = guild.canal(mod.CANAL_ANUNCIOS)
    ctx = fakes.Ctx(guild=guild, canal=canal)

    await mod.anuncio.callback(ctx, texto="everyone hola")

    contenido, kwargs = canal.enviados[0]
    permitido = efectivo(kwargs)
    assert contenido == "@everyone"
    assert "everyone" in permitido["parse"]
    assert "roles" not in permitido and "users" not in permitido.get("parse", [])
    # La confirmacion al autor lleva el texto "@everyone" pero no puede pinguear
    assert efectivo(ctx.respuestas[0][1]).get("parse", []) == []


async def test_subida_de_nivel_menciona_al_usuario(mod, fakes, efectivo, monkeypatch):
    async def get_user_xp(*args):
        return 0

    async def add_user_xp(*args):
        return 200  # nivel 1

    async def sin_efecto(*args, **kwargs):
        return None

    monkeypatch.setattr(mod, "get_user_xp", get_user_xp)
    monkeypatch.setattr(mod, "add_user_xp", add_user_xp)
    monkeypatch.setattr(mod, "add_xp_mensual", sin_efecto)
    monkeypatch.setattr(mod, "otorgar_recompensas", sin_efecto)
    guild = fakes.Guild()
    niveles = guild.canal(mod.CANAL_NIVELES)
    miembro = fakes.Usuario(9, "Pepe")
    miembro.guild = guild

    await mod.sumar_xp(miembro, 200)

    contenido, kwargs = niveles.enviados[0]
    assert miembro.mention in contenido
    assert efectivo(kwargs).get("parse") == ["users"]


@pytest.mark.parametrize(
    "texto, ping, cuerpo",
    [
        ("hola a todos", None, "hola a todos"),
        ("everyone hola", "everyone", "hola"),
        ("Everyone hola", "everyone", "hola"),
        ("HERE   buenas tardes", "here", "buenas tardes"),
        ("hola everyone", None, "hola everyone"),  # no es la primera palabra
        ("everyone", "everyone", ""),
        ("everyoneelse hola", None, "everyoneelse hola"),
    ],
)
def test_parsear_anuncio(mod, texto, ping, cuerpo):
    assert mod.parsear_anuncio(texto) == (ping, cuerpo)


async def test_anuncio_sin_palabra_clave_no_permite_everyone(mod, fakes, efectivo):
    guild = fakes.Guild()
    canal = guild.canal(mod.CANAL_ANUNCIOS)
    ctx = fakes.Ctx(guild=guild, canal=canal)

    await mod.anuncio.callback(ctx, texto="hola everyone")

    contenido, kwargs = canal.enviados[0]
    assert contenido is None
    assert "allowed_mentions" not in kwargs
    assert "everyone" not in efectivo(kwargs).get("parse", [])
    assert kwargs["embed"].description == "hola everyone"
    assert ctx.respuestas[0][0] == f"✅ Anuncio publicado en {canal.mention}"


async def test_anuncio_sin_permiso_mention_everyone_no_publica(mod, fakes):
    guild = fakes.Guild()
    canal = guild.canal(mod.CANAL_ANUNCIOS)
    canal.mention_everyone_permitido = False
    ctx = fakes.Ctx(guild=guild, canal=canal)

    await mod.anuncio.callback(ctx, texto="everyone hola")

    assert canal.enviados == []
    assert ctx.respuestas[0][0] == (
        "❌ Necesitas el permiso Mencionar @everyone para anunciar con ping."
    )


@pytest.mark.parametrize("texto", ["everyone", "here   "])
async def test_anuncio_con_palabra_clave_sin_texto_responde_el_uso(mod, fakes, texto):
    guild = fakes.Guild()
    canal = guild.canal(mod.CANAL_ANUNCIOS)
    ctx = fakes.Ctx(guild=guild, canal=canal)

    await mod.anuncio.callback(ctx, texto=texto)

    assert canal.enviados == []
    assert ctx.respuestas[0][0] == mod.USO_ANUNCIO


async def test_anuncio_here_confirma_con_sufijo(mod, fakes):
    guild = fakes.Guild()
    canal = guild.canal(mod.CANAL_ANUNCIOS)
    ctx = fakes.Ctx(guild=guild, canal=canal)

    await mod.anuncio.callback(ctx, texto="here buenas")

    assert canal.enviados[0][0] == "@here"
    assert canal.enviados[0][1]["embed"].description == "buenas"
    assert ctx.respuestas[0][0].endswith("(con @here)")
