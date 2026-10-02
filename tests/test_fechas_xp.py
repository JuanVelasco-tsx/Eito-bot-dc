"""Fechas (mes, dia contable en UTC-5) y matematicas de XP/niveles."""

from datetime import datetime, timezone

import pytest


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# --- XP y niveles -----------------------------------------------------------------
def test_xp_necesaria_valores_conocidos(mod):
    assert mod.xp_necesaria(0) == 100
    assert mod.xp_necesaria(1) == 155
    assert mod.xp_necesaria(10) == 1100


@pytest.mark.parametrize("nivel", range(0, 61))
def test_xp_acumulada_es_la_inversa_de_nivel_desde_xp(mod, nivel):
    xp = mod.xp_acumulada(nivel)
    assert mod.nivel_desde_xp(xp) == nivel
    if nivel >= 1:
        # Un punto de XP menos y todavia no se alcanza el nivel
        assert mod.nivel_desde_xp(xp - 1) == nivel - 1


def test_xp_acumulada_ignora_niveles_negativos(mod):
    assert mod.xp_acumulada(0) == 0
    assert mod.xp_acumulada(-5) == 0


def test_xp_acumulada_suma_los_niveles_anteriores(mod):
    assert mod.xp_acumulada(3) == mod.xp_necesaria(0) + mod.xp_necesaria(1) + mod.xp_necesaria(2)


# --- Meses (Activo del mes) -------------------------------------------------------
def test_mes_utc(mod):
    assert mod.mes_utc(utc(2026, 10, 1, 0, 0)) == "2026-10"
    assert mod.mes_utc(utc(2026, 1, 31, 23, 59)) == "2026-01"


@pytest.mark.parametrize(
    "fecha, esperado",
    [
        (utc(2026, 10, 1), "2026-09"),
        (utc(2026, 1, 15), "2025-12"),   # enero: el anterior es diciembre del año pasado
        (utc(2026, 3, 31), "2026-02"),   # fin de mes largo tras un mes corto
        (utc(2026, 12, 31, 23, 59), "2026-11"),
    ],
)
def test_mes_anterior_utc(mod, fecha, esperado):
    assert mod.mes_anterior_utc(fecha) == esperado


def test_limites_mes_utc(mod):
    assert mod.limites_mes_utc("2026-10") == (utc(2026, 10, 1), utc(2026, 11, 1))
    assert mod.limites_mes_utc("2026-12") == (utc(2026, 12, 1), utc(2027, 1, 1))
    assert mod.limites_mes_utc("2026-02") == (utc(2026, 2, 1), utc(2026, 3, 1))


# --- Dia contable (UTC-5 fijo) ----------------------------------------------------
@pytest.mark.parametrize(
    "fecha, esperado",
    [
        (utc(2026, 10, 1, 4, 59, 59), "2026-09-30"),  # justo antes de la medianoche en UTC-5
        (utc(2026, 10, 1, 5, 0, 0), "2026-10-01"),    # medianoche en UTC-5
        (utc(2026, 10, 1, 23, 59, 59), "2026-10-01"),
        (utc(2026, 1, 1, 0, 0, 0), "2025-12-31"),     # cruza el año
    ],
)
def test_dia_contable(mod, fecha, esperado):
    assert mod.dia_contable(fecha) == esperado
