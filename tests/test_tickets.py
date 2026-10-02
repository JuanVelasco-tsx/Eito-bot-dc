"""Tickets: roles, nombre/dueño del canal, transcripcion y privacidad al cerrar."""

import types

import pytest

ID_ADMINS = 1545581826654076979
ID_MODERADOR = 1546381843132317736
ID_GOAT = 1544889052011040828


# --- Helpers puros -----------------------------------------------------------------
@pytest.mark.parametrize(
    "topic, esperado",
    [
        ("ticket:123456789", 123456789),
        ("ticket:1", 1),
        (None, None),
        ("", None),
        ("ticket:abc", None),
        ("ticket:12 extra", None),
        ("otro ticket:12", None),
        ("Canal de soporte", None),
    ],
)
def test_dueno_ticket(mod, fakes, topic, esperado):
    assert mod.dueno_ticket(fakes.Canal(topic=topic)) == esperado


@pytest.mark.parametrize(
    "nombre, esperado",
    [
        ("Juan", "ticket-juan"),
        ("Juan Pérez!", "ticket-juanprez"),
        ("ana_maria-2", "ticket-ana_maria-2"),
    ],
)
def test_nombre_canal_ticket(mod, fakes, nombre, esperado):
    assert mod.nombre_canal_ticket(fakes.Usuario(7, nombre)) == esperado


def test_nombre_canal_ticket_sin_caracteres_validos_usa_el_id(mod, fakes):
    assert mod.nombre_canal_ticket(fakes.Usuario(7, "😀😀")) == "ticket-7"


def test_roles_de_ping_son_solo_admins_y_moderador(mod):
    assert mod.ROLES_PING_TICKETS == [ID_ADMINS, ID_MODERADOR]
    assert set(mod.ROLES_PING_TICKETS) <= set(mod.ROLES_STAFF_TICKETS)


def test_roles_de_staff_ven_los_tickets(mod):
    assert set(mod.ROLES_STAFF_TICKETS) == {
        ID_GOAT, mod.ROL_DEVELOPER_ID, ID_ADMINS, ID_MODERADOR,
    }


def test_roles_ping_tickets_solo_devuelve_los_que_existen(mod, fakes):
    guild = fakes.Guild()
    admins = guild.rol(ID_ADMINS, "Admins")
    guild.rol(ID_GOAT, "GOAT")  # staff, pero no se pingea
    assert mod.roles_ping_tickets(guild) == [admins]
    assert [r.id for r in mod.roles_staff_tickets(guild)] == [ID_GOAT, ID_ADMINS]


# --- Transcripcion -----------------------------------------------------------------
async def test_generar_transcripcion(mod, fakes):
    canal = fakes.Canal("ticket-ana")
    canal.mensajes = [
        fakes.Mensaje(1, "Hola, necesito ayuda", fakes.Usuario(9, "Ana")),
        fakes.Mensaje(2, "Mira esto", fakes.Usuario(10, "Staff"),
                      adjuntos=["https://cdn.test/captura.png"]),
    ]
    texto = await mod.generar_transcripcion(canal)
    assert texto.startswith("Transcripción de #ticket-ana")
    assert "[2026-10-01 12:30:05 UTC] Ana (9): Hola, necesito ayuda" in texto
    assert "[2026-10-01 12:30:05 UTC] Staff (10): Mira esto" in texto
    assert "    [adjunto] https://cdn.test/captura.png" in texto


# --- Cierre y privacidad --------------------------------------------------------------
@pytest.fixture
def escenario(mod, fakes, monkeypatch):
    """Servidor con un ticket de Ana (id 9), canal de transcripciones y de registros."""
    async def sin_espera(segundos, *args, **kwargs):
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", sin_espera)
    guild = fakes.Guild()
    ticket = guild.canal("ticket-ana", topic="ticket:9")
    ticket.mensajes = [fakes.Mensaje(1, "Hola", fakes.Usuario(9, "Ana"))]
    transcripciones = guild.canal(mod.CANAL_TRANSCRIPCIONES)
    registros = guild.canal(mod.CANAL_LOGS)
    dueno = fakes.Usuario(9, "Ana")
    staff = fakes.Usuario(20, "Mod", roles=[fakes.Rol(ID_MODERADOR)])
    ajeno = fakes.Usuario(30, "Otro")
    return types.SimpleNamespace(
        guild=guild, ticket=ticket, transcripciones=transcripciones, registros=registros,
        dueno=dueno, staff=staff, ajeno=ajeno,
    )


async def test_cerrar_con_canal_de_transcripciones_privado(mod, fakes, escenario):
    e = escenario
    inter = fakes.Interaccion(e.dueno, e.guild, e.ticket)

    await mod.ticket_cerrar(inter)

    assert inter.defers == 1
    # Transcripcion enviada al canal privado, con indicacion de quien abrio y cerro
    contenido, kwargs = e.transcripciones.enviados[0]
    assert "<@9>" in contenido and e.dueno.mention in contenido
    assert kwargs["file"].filename == "ticket-ana.txt"
    assert "Hola" in kwargs["file"].fp.read().decode("utf-8")
    # El ticket se avisa y se borra
    assert any("se borrará en 5 segundos" in (c or "") for c, _kw in e.ticket.enviados)
    assert e.ticket.borrado is True
    assert e.ticket.id not in mod.tickets_cerrando


async def test_staff_puede_cerrar(mod, fakes, escenario):
    e = escenario
    await mod.ticket_cerrar(fakes.Interaccion(e.staff, e.guild, e.ticket))
    assert e.ticket.borrado is True
    assert len(e.transcripciones.enviados) == 1


async def test_cerrar_con_canal_de_transcripciones_publico_no_cierra(mod, fakes, escenario):
    e = escenario
    e.transcripciones.everyone_ve = True
    inter = fakes.Interaccion(e.dueno, e.guild, e.ticket)

    await mod.ticket_cerrar(inter)

    assert e.transcripciones.enviados == []        # no se envia la transcripcion
    assert e.ticket.borrado is False               # no se cierra el ticket
    assert e.ticket.enviados[0][0] == (
        "⚠️ El canal de transcripciones es público; un admin debe corregirlo"
    )
    assert "público" in inter.respuestas[0][0]     # respuesta efimera a quien pulso
    # Queda registrado en el canal de registros
    assert len(e.registros.enviados) == 1
    assert "visible para @everyone" in e.registros.enviados[0][0]
    assert e.ticket.id not in mod.tickets_cerrando  # se podra reintentar al corregirlo


async def test_cerrar_sin_canal_de_transcripciones_no_cierra(mod, fakes, escenario):
    e = escenario
    e.guild.text_channels.remove(e.transcripciones)
    inter = fakes.Interaccion(e.dueno, e.guild, e.ticket)

    await mod.ticket_cerrar(inter)

    assert e.ticket.borrado is False
    assert "Avisa a un admin" in inter.respuestas[0][0]


async def test_un_usuario_ajeno_no_puede_cerrar(mod, fakes, escenario):
    e = escenario
    inter = fakes.Interaccion(e.ajeno, e.guild, e.ticket)

    await mod.ticket_cerrar(inter)

    assert e.ticket.borrado is False
    assert e.transcripciones.enviados == []
    assert "Solo quien abrió el ticket o el staff" in inter.respuestas[0][0]


async def test_un_canal_que_no_es_ticket_no_se_cierra(mod, fakes, escenario):
    e = escenario
    otro = e.guild.canal("general")
    inter = fakes.Interaccion(e.dueno, e.guild, otro)

    await mod.ticket_cerrar(inter)

    assert otro.borrado is False
    assert inter.respuestas[0][0] == "❌ Este canal no es un ticket."


async def test_no_se_cierra_dos_veces_a_la_vez(mod, fakes, escenario):
    e = escenario
    mod.tickets_cerrando.add(e.ticket.id)
    try:
        inter = fakes.Interaccion(e.dueno, e.guild, e.ticket)
        await mod.ticket_cerrar(inter)
        assert "ya se está cerrando" in inter.respuestas[0][0]
        assert e.transcripciones.enviados == []
    finally:
        mod.tickets_cerrando.discard(e.ticket.id)


# --- !paneltickets -------------------------------------------------------------------
async def test_paneltickets_reconfigura_soporte_y_transcripciones(mod, fakes, monkeypatch):
    orden = []

    async def soporte(ctx):
        orden.append("soporte")

    async def transcripciones(ctx):
        orden.append("transcripciones")

    guild = fakes.Guild()
    canal = guild.canal(mod.CANAL_SOPORTE)

    async def publicar(guild, canal, clave, embed, view=None):
        orden.append(f"publicar:{clave}")
        return types.SimpleNamespace(channel=canal), False

    monkeypatch.setattr(mod, "configurar_canal_soporte", soporte)
    monkeypatch.setattr(mod, "configurar_canal_transcripciones", transcripciones)
    monkeypatch.setattr(mod, "publicar_o_editar_fijo", publicar)
    ctx = fakes.Ctx(guild=guild, canal=canal)

    await mod.paneltickets.callback(ctx)

    assert orden == ["soporte", "transcripciones", "publicar:panel_tickets"]
    assert "Panel de tickets publicado" in ctx.respuestas[0][0]
