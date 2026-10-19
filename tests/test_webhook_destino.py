"""POST /release-webhook con destino: {"destino": "pss"} publica en el canal y con el rol del [webhook.pss] del
TOML; sin destino nada cambia (eso lo cubre test_webhook.py); un destino desconocido, o sin perfil cargado, es un
400 y NUNCA cae al canal de EITO."""

import json

import pytest

from tests.test_recursos import FRol, FTexto, GuildPSS, perfil, sin_bd  # noqa: F401

AUTH = {"Authorization": "Bearer secreto-de-prueba"}


def cuerpo(respuesta):
    return json.loads(respuesta.text)


@pytest.fixture
def canal_eito(mod, fakes, monkeypatch):
    """El canal de releases de EITO (RELEASE_CHANNEL_ID) con su rol Mod Loader: NO debe usarse con destino."""
    guild = fakes.Guild()
    guild.rol(888, mod.ROL_MODLOADER)
    canal = guild.canal(mod.CANAL_MODLOADER)
    monkeypatch.setattr(mod, "RELEASE_CHANNEL_ID", "123")
    monkeypatch.setattr(mod.bot, "get_channel", lambda _id: canal)
    return canal


@pytest.fixture
def pss(mod, perfil, monkeypatch):
    """El servidor de PSS con #anuncios y el rol Novedades ya creados y mapeados."""
    guild = GuildPSS()
    anuncios = guild.canales[32] = FTexto(32, "📣・anuncios")
    novedades = FRol(33, "🔔 Novedades")
    guild.roles.append(novedades)
    perfil.ids = {"anuncios": 32, "novedades": 33}
    monkeypatch.setattr(mod.bot, "get_guild", lambda ident: guild if ident == guild.id else None)
    return guild, anuncios, novedades


def pedido(fakes, **datos):
    return fakes.Peticion(AUTH, {"version": "1.2.0", "changelog": "Cambios", **datos})


async def test_con_destino_pss_publica_en_el_canal_de_pss_y_menciona_novedades(mod, fakes, canal_eito, pss):
    guild, anuncios, novedades = pss
    respuesta = await mod.handle_release_webhook(pedido(fakes, destino="pss"))
    assert respuesta.status == 200 and cuerpo(respuesta) == {"ok": True, "version": "1.2.0"}
    contenido, kwargs = anuncios.enviados[0]
    assert contenido == "<@&33>"
    assert kwargs["embed"].title == "🚀 Nueva version: 1.2.0" and kwargs["embed"].description == "Cambios"
    assert [r.id for r in kwargs["allowed_mentions"].roles] == [33]
    assert canal_eito.enviados == []                     # el canal de EITO, ni tocado


async def test_el_destino_no_distingue_mayusculas_ni_espacios(mod, fakes, canal_eito, pss):
    _guild, anuncios, _rol = pss
    assert (await mod.handle_release_webhook(pedido(fakes, destino=" PSS "))).status == 200
    assert len(anuncios.enviados) == 1


async def test_destino_desconocido_con_perfil_cargado_es_400_y_no_publica_en_ningun_sitio(mod, fakes, canal_eito, pss):
    _guild, anuncios, _rol = pss
    respuesta = await mod.handle_release_webhook(pedido(fakes, destino="otro"))
    assert respuesta.status == 400 and "Destino desconocido: otro" in cuerpo(respuesta)["error"]
    assert anuncios.enviados == [] and canal_eito.enviados == []


@pytest.mark.parametrize("destino", ["", "   "])
async def test_destino_vacio_es_desconocido(mod, fakes, canal_eito, pss, destino):
    assert (await mod.handle_release_webhook(pedido(fakes, destino=destino))).status == 400
    assert canal_eito.enviados == []


@pytest.mark.parametrize("destino", [5, ["pss"], {"a": 1}, True])
async def test_destino_que_no_es_texto_es_400(mod, fakes, canal_eito, pss, destino):
    respuesta = await mod.handle_release_webhook(pedido(fakes, destino=destino))
    assert respuesta.status == 400 and "destino debe ser un texto" in cuerpo(respuesta)["error"]
    assert canal_eito.enviados == []


async def test_con_destino_pero_sin_perfil_cargado_es_400_y_no_cae_al_canal_de_eito(mod, fakes, canal_eito):
    assert mod.bot.get_cog("PerfilPSS") is None
    respuesta = await mod.handle_release_webhook(pedido(fakes, destino="pss"))
    assert respuesta.status == 400 and "Destino desconocido: pss" in cuerpo(respuesta)["error"]
    assert canal_eito.enviados == []


async def test_destino_conocido_pero_sin_canal_creado_es_500_y_no_cae_al_de_eito(mod, fakes, canal_eito, pss, perfil):
    perfil.ids = {}                                       # el perfil aun no se ha aplicado
    respuesta = await mod.handle_release_webhook(pedido(fakes, destino="pss"))
    assert respuesta.status == 500 and "No se encontro el canal del destino pss" in cuerpo(respuesta)["error"]
    assert canal_eito.enviados == []


async def test_destino_conocido_con_el_servidor_fuera_de_cache_es_500(mod, fakes, canal_eito, pss, monkeypatch):
    monkeypatch.setattr(mod.bot, "get_guild", lambda ident: None)
    assert (await mod.handle_release_webhook(pedido(fakes, destino="pss"))).status == 500
    assert canal_eito.enviados == []


async def test_destino_sin_el_rol_creado_publica_sin_mencionar(mod, fakes, canal_eito, pss, perfil):
    _guild, anuncios, _rol = pss
    perfil.ids = {"anuncios": 32}
    assert (await mod.handle_release_webhook(pedido(fakes, destino="pss"))).status == 200
    contenido, kwargs = anuncios.enviados[0]
    assert contenido is None and "allowed_mentions" not in kwargs


async def test_sin_destino_y_con_perfil_cargado_el_flujo_de_eito_no_cambia(mod, fakes, canal_eito, pss):
    _guild, anuncios, _rol = pss
    respuesta = await mod.handle_release_webhook(pedido(fakes))
    assert respuesta.status == 200
    assert len(canal_eito.enviados) == 1 and anuncios.enviados == []
    contenido, _kw = canal_eito.enviados[0]
    assert contenido == "<@&888>"                          # el rol Mod Loader de EITO, como siempre


async def test_destino_null_es_como_no_ponerlo(mod, fakes, canal_eito, pss):
    respuesta = await mod.handle_release_webhook(pedido(fakes, destino=None))
    assert respuesta.status == 200 and len(canal_eito.enviados) == 1


async def test_con_destino_las_validaciones_de_siempre_siguen_primero(mod, fakes, canal_eito, pss):
    assert (await mod.handle_release_webhook(fakes.Peticion(AUTH, {"destino": "pss"}))).status == 400   # sin version
    sin_auth = fakes.Peticion({}, {"version": "1", "destino": "pss"})
    assert (await mod.handle_release_webhook(sin_auth)).status == 401
