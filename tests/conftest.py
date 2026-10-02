"""Configuracion comun de las pruebas: entorno, objetos falsos y guardas.

Las pruebas NO se conectan a Discord ni a ninguna base de datos: el bot se
importa como modulo y se prueba con objetos falsos (los de este archivo).
"""

import os
import types
from datetime import datetime, timezone

import pytest

# --- Entorno, ANTES de importar el bot -----------------------------------------
# load_dotenv() no pisa las variables que ya existen: asi un .env local con el
# token y la BD reales nunca se usa en las pruebas.
os.environ["DISCORD_TOKEN"] = "token-de-prueba"
os.environ["DATABASE_URL"] = (
    os.environ.get("TEST_DATABASE_URL") or "postgresql://test:test@localhost:5432/test"
)
os.environ["EITO_GUILD_ID"] = ""
os.environ["RELEASE_CHANNEL_ID"] = ""
os.environ["RELEASE_WEBHOOK_SECRET"] = "secreto-de-prueba"
os.environ["PORT"] = "8080"


# --- Marker "db": se salta salvo que haya una BD de pruebas --------------------
def pytest_collection_modifyitems(config, items):
    if os.environ.get("TEST_DATABASE_URL"):
        return
    saltar = pytest.mark.skip(reason="requiere PostgreSQL (define TEST_DATABASE_URL)")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(saltar)


@pytest.fixture(autouse=True)
def sin_bd_real(request, monkeypatch):
    """Si una prueba (sin marker db) llega a tocar la BD, falla en vez de conectarse."""
    if request.node.get_closest_marker("db") is not None:
        return
    import database

    def prohibido(*args, **kwargs):
        raise AssertionError("Esta prueba intento acceder a la BD: parchea la funcion de database.")

    monkeypatch.setattr(database, "SessionLocal", prohibido)


# --- Objetos falsos -------------------------------------------------------------
class FakeRol:
    def __init__(self, id, nombre="rol"):
        self.id, self.name = id, nombre
        self.mention = f"<@&{id}>"
        self.colour = types.SimpleNamespace(value=0)


class FakeUsuario:
    def __init__(self, id=1, nombre="Usuario", roles=(), bot=False):
        self.id, self.name, self.display_name = id, nombre, nombre
        self.mention = f"<@{id}>"
        self.roles = list(roles)
        self.bot = bot
        self.display_avatar = types.SimpleNamespace(url="https://cdn.test/avatar.png")

    def __str__(self):
        return self.name


class FakeMensaje:
    def __init__(self, id=1, contenido="", autor=None, adjuntos=(), embeds=(), fecha=None):
        self.id = id
        self.clean_content = contenido
        self.author = autor or FakeUsuario(99, "Alguien")
        self.attachments = [types.SimpleNamespace(url=u) for u in adjuntos]
        self.embeds = list(embeds)
        self.created_at = fecha or datetime(2026, 10, 1, 12, 30, 5, tzinfo=timezone.utc)


class FakeCanal:
    """Canal de texto: guarda lo que se envia en `enviados` = [(content, kwargs)]."""

    def __init__(self, nombre="canal", id=1, guild=None, topic=None):
        self.name, self.id, self.guild, self.topic = nombre, id, guild, topic
        self.mention = f"#{nombre}"
        self.enviados = []
        self.mensajes = []  # lo que devuelve history()
        self.borrado = False
        self.everyone_ve = False                # permissions_for(@everyone).view_channel
        self.mention_everyone_permitido = True  # permissions_for(autor).mention_everyone

    async def send(self, content=None, **kwargs):
        self.enviados.append((content, kwargs))
        return types.SimpleNamespace(id=len(self.enviados), channel=self)

    def permissions_for(self, objetivo):
        return types.SimpleNamespace(
            view_channel=self.everyone_ve, mention_everyone=self.mention_everyone_permitido
        )

    async def history(self, limit=None, oldest_first=False):
        for mensaje in self.mensajes:
            yield mensaje

    async def delete(self, reason=None):
        self.borrado = True


class FakeGuild:
    def __init__(self, id=5, nombre="EITO"):
        self.id, self.name = id, nombre
        self.text_channels = []
        self.roles = []
        self.default_role = FakeRol(id, "@everyone")
        self.owner_id = 0

    def canal(self, nombre, **kwargs):
        """Crea un canal de texto con ese nombre dentro del servidor."""
        canal = FakeCanal(nombre, id=len(self.text_channels) + 100, guild=self, **kwargs)
        self.text_channels.append(canal)
        return canal

    def rol(self, id, nombre="rol"):
        rol = FakeRol(id, nombre)
        self.roles.append(rol)
        return rol

    def get_role(self, id):
        return next((r for r in self.roles if r.id == id), None)


class FakeCtx:
    """Contexto de un comando: guarda las respuestas en `respuestas` = [(content, kwargs)]."""

    def __init__(self, guild=None, canal=None, autor=None, comando=None):
        self.guild, self.channel = guild, canal
        self.author = autor or FakeUsuario(1, "Mod")
        self.command = comando
        self.respuestas = []

        async def borrar():
            return None

        self.message = types.SimpleNamespace(delete=borrar)

    async def send(self, content=None, **kwargs):
        self.respuestas.append((content, kwargs))


class FakeInteraccion:
    """Interaccion de un boton: `respuestas` guarda los followup.send."""

    def __init__(self, usuario, guild, canal):
        self.user, self.guild, self.channel = usuario, guild, canal
        self.defers = 0
        self.respuestas = []

        async def defer(ephemeral=False):
            self.defers += 1

        async def enviar(content=None, **kwargs):
            self.respuestas.append((content, kwargs))

        self.response = types.SimpleNamespace(defer=defer)
        self.followup = types.SimpleNamespace(send=enviar)


class FakePeticion:
    """Peticion HTTP del webhook."""

    def __init__(self, cabeceras=None, cuerpo=None, json_invalido=False):
        self.headers = cabeceras or {}
        self._cuerpo, self._invalido = cuerpo, json_invalido

    async def json(self):
        if self._invalido:
            raise ValueError("JSON invalido")
        return self._cuerpo


# --- Fixtures --------------------------------------------------------------------
@pytest.fixture
def mod():
    """El modulo del bot (importado con el entorno de pruebas)."""
    import eito_setup_bot

    return eito_setup_bot


@pytest.fixture
def fakes():
    """Fabricas de los objetos falsos: fakes.Guild(), fakes.Ctx(...), etc."""
    return types.SimpleNamespace(
        Rol=FakeRol, Usuario=FakeUsuario, Mensaje=FakeMensaje, Canal=FakeCanal,
        Guild=FakeGuild, Ctx=FakeCtx, Interaccion=FakeInteraccion, Peticion=FakePeticion,
    )


@pytest.fixture
def efectivo(mod):
    """allowed_mentions EFECTIVO de un envio: el global del bot fusionado con el del
    envio (lo que discord.py manda de verdad). Recibe los kwargs del envio."""

    def calcular(kwargs):
        propio = kwargs.get("allowed_mentions")
        global_ = mod.bot.allowed_mentions
        return (global_.merge(propio) if propio is not None else global_).to_dict()

    return calcular
