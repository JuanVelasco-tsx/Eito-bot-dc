"""POST /release-webhook: autenticacion, validacion del body y limites del embed."""

import json

import pytest

AUTH = {"Authorization": "Bearer secreto-de-prueba"}


@pytest.fixture
def canal_releases(mod, fakes, monkeypatch):
    """Canal de releases con el rol Mod Loader, enlazado como RELEASE_CHANNEL_ID."""
    guild = fakes.Guild()
    guild.rol(888, mod.ROL_MODLOADER)
    canal = guild.canal(mod.CANAL_MODLOADER)
    monkeypatch.setattr(mod, "RELEASE_CHANNEL_ID", "123")
    monkeypatch.setattr(mod.bot, "get_channel", lambda _id: canal)
    return canal


def cuerpo(respuesta):
    return json.loads(respuesta.text)


async def test_sin_secreto_configurado_responde_503(mod, fakes, monkeypatch):
    monkeypatch.setattr(mod, "RELEASE_WEBHOOK_SECRET", None)
    respuesta = await mod.handle_release_webhook(fakes.Peticion(AUTH, {"version": "1"}))
    assert respuesta.status == 503


@pytest.mark.parametrize(
    "cabeceras",
    [
        {},
        {"Authorization": "Bearer otro-secreto"},
        {"Authorization": "secreto-de-prueba"},          # sin el prefijo Bearer
        {"Authorization": "Bearer secreto-de-prueba "},  # espacio de mas
        {"Authorization": "Bearer sécreto-de-prueba"},   # no ASCII: no debe romper
    ],
)
async def test_autenticacion_incorrecta_responde_401(mod, fakes, canal_releases, cabeceras):
    respuesta = await mod.handle_release_webhook(fakes.Peticion(cabeceras, {"version": "1"}))
    assert respuesta.status == 401
    assert canal_releases.enviados == []


async def test_el_secreto_se_compara_con_compare_digest(mod, fakes, canal_releases, monkeypatch):
    llamadas = []
    original = mod.hmac.compare_digest

    def espia(a, b):
        llamadas.append((a, b))
        return original(a, b)

    monkeypatch.setattr(mod.hmac, "compare_digest", espia)
    await mod.handle_release_webhook(fakes.Peticion(AUTH, {"version": "1"}))
    assert llamadas == [(b"Bearer secreto-de-prueba", b"Bearer secreto-de-prueba")]


async def test_json_invalido_responde_400(mod, fakes, canal_releases):
    respuesta = await mod.handle_release_webhook(fakes.Peticion(AUTH, json_invalido=True))
    assert respuesta.status == 400


@pytest.mark.parametrize(
    "body",
    [
        ["version", "1.0"],                                # lista, no objeto
        "1.0",                                             # texto suelto
        None,                                              # null
        {},                                                # falta version
        {"version": ""},
        {"version": "   "},
        {"version": 123},                                  # version no es texto
        {"version": ["1.0"]},
        {"version": "1.0", "changelog": 42},               # changelog no es texto
        {"version": "1.0", "changelog": {"a": 1}},
    ],
)
async def test_body_invalido_responde_400_y_no_publica(mod, fakes, canal_releases, body):
    respuesta = await mod.handle_release_webhook(fakes.Peticion(AUTH, body))
    assert respuesta.status == 400, cuerpo(respuesta)
    assert canal_releases.enviados == []


async def test_publica_el_aviso_con_los_datos_recibidos(mod, fakes, canal_releases):
    respuesta = await mod.handle_release_webhook(
        fakes.Peticion(AUTH, {"version": "1.2.0", "changelog": "Arreglos varios"})
    )
    assert respuesta.status == 200
    assert cuerpo(respuesta) == {"ok": True, "version": "1.2.0"}
    embed = canal_releases.enviados[0][1]["embed"]
    assert embed.title.endswith("1.2.0")
    assert embed.description == "Arreglos varios"


async def test_sin_changelog_usa_el_texto_por_defecto(mod, fakes, canal_releases):
    respuesta = await mod.handle_release_webhook(fakes.Peticion(AUTH, {"version": "1.0"}))
    assert respuesta.status == 200
    assert canal_releases.enviados[0][1]["embed"].description == "Sin changelog."


async def test_recorta_titulo_a_256_y_descripcion_a_4096(mod, fakes, canal_releases):
    respuesta = await mod.handle_release_webhook(
        fakes.Peticion(AUTH, {"version": "v" * 500, "changelog": "c" * 5000})
    )
    assert respuesta.status == 200
    embed = canal_releases.enviados[0][1]["embed"]
    assert len(embed.title) == 256 and embed.title.endswith("…")
    assert len(embed.description) == 4096 and embed.description.endswith("…")


async def test_no_recorta_lo_que_ya_cabe(mod, fakes, canal_releases):
    justo = "c" * 4096
    await mod.handle_release_webhook(fakes.Peticion(AUTH, {"version": "1.0", "changelog": justo}))
    assert canal_releases.enviados[0][1]["embed"].description == justo


def test_recortar(mod):
    assert mod.recortar("hola", 10) == "hola"
    assert mod.recortar("hola", 4) == "hola"
    assert mod.recortar("holaa", 4) == "hol…"


async def test_sin_canal_de_releases_responde_500(mod, fakes, monkeypatch):
    monkeypatch.setattr(mod, "RELEASE_CHANNEL_ID", None)
    monkeypatch.setattr(type(mod.bot), "guilds", property(lambda self: []))
    respuesta = await mod.handle_release_webhook(fakes.Peticion(AUTH, {"version": "1.0"}))
    assert respuesta.status == 500
    assert "Avisa a un admin" in cuerpo(respuesta)["error"]
