"""Capa de persistencia con PostgreSQL (SQLAlchemy async + asyncpg).

Reemplaza el guardado en archivos JSON (niveles.json, avisos.json) por
tablas en una base de datos PostgreSQL, para que los datos persistan
entre despliegues y escalen mejor que un archivo plano.
"""

import os

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Cargar variables desde un archivo .env local (si existe).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- CONEXION ---
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://usuario:contraseña@localhost/eito_db"
)
# SQLAlchemy async necesita el driver asyncpg explicito en la URL.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


# =====================================================================
#  MODELOS
# =====================================================================
class UserXP(Base):
    """XP acumulada por un usuario en un servidor."""

    __tablename__ = "user_xp"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_user_xp_guild_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    xp: Mapped[int] = mapped_column(BigInteger, default=0)


class UserWarn(Base):
    """Aviso (warn) de moderacion aplicado a un usuario en un servidor."""

    __tablename__ = "user_warns"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    moderator: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped["object"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConfigServidor(Base):
    """Configuracion propia de cada servidor (un registro por guild_id)."""

    __tablename__ = "config_servidor"

    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    mensaje_cochipuerco_id: Mapped[str] = mapped_column(String(32), nullable=True)


async def crear_tablas():
    """Crea las tablas en la base de datos si todavia no existen."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# =====================================================================
#  HELPERS: XP / NIVELES
# =====================================================================
async def get_user_xp(guild_id, user_id) -> int:
    """Devuelve la XP total de un usuario en un servidor (0 si no tiene)."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(UserXP.xp).where(
                UserXP.guild_id == str(guild_id), UserXP.user_id == str(user_id)
            )
        )
        xp = resultado.scalar_one_or_none()
        return xp or 0


async def add_user_xp(guild_id, user_id, cantidad) -> int:
    """Suma `cantidad` de XP a un usuario (crea el registro si no existe).

    Devuelve la XP total resultante. `cantidad` puede ser negativa para
    restar (por ejemplo, para fijar un total exacto).
    """
    async with SessionLocal() as session:
        stmt = pg_insert(UserXP).values(
            guild_id=str(guild_id), user_id=str(user_id), xp=cantidad
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id", "user_id"],
            set_={"xp": UserXP.__table__.c.xp + cantidad},
        ).returning(UserXP.xp)
        resultado = await session.execute(stmt)
        nueva_xp = resultado.scalar_one()
        await session.commit()
        return nueva_xp


async def get_all_xp(guild_id) -> dict:
    """Devuelve un diccionario {user_id: xp} con toda la XP de un servidor."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(UserXP.user_id, UserXP.xp).where(UserXP.guild_id == str(guild_id))
        )
        return {user_id: xp for user_id, xp in resultado.all()}


# =====================================================================
#  HELPERS: AVISOS (WARNS)
# =====================================================================
async def get_warns(guild_id, user_id) -> list:
    """Devuelve la lista de avisos de un usuario en un servidor."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(UserWarn)
            .where(UserWarn.guild_id == str(guild_id), UserWarn.user_id == str(user_id))
            .order_by(UserWarn.timestamp)
        )
        return [
            {"reason": w.reason, "moderator": w.moderator, "timestamp": w.timestamp}
            for w in resultado.scalars().all()
        ]


async def add_warn(guild_id, user_id, reason, moderator) -> int:
    """Registra un aviso nuevo y devuelve el total de avisos del usuario."""
    async with SessionLocal() as session:
        session.add(
            UserWarn(
                guild_id=str(guild_id),
                user_id=str(user_id),
                reason=reason,
                moderator=moderator,
            )
        )
        await session.commit()

        total = await session.scalar(
            select(func.count())
            .select_from(UserWarn)
            .where(UserWarn.guild_id == str(guild_id), UserWarn.user_id == str(user_id))
        )
        return total


# =====================================================================
#  HELPERS: CONFIGURACION DEL SERVIDOR
# =====================================================================
async def set_mensaje_cochipuerco(guild_id: str, message_id: str):
    """Guarda el ID del mensaje-panel del rol +18 para este servidor (upsert)."""
    async with SessionLocal() as session:
        stmt = pg_insert(ConfigServidor).values(
            guild_id=str(guild_id), mensaje_cochipuerco_id=str(message_id)
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id"],
            set_={"mensaje_cochipuerco_id": str(message_id)},
        )
        await session.execute(stmt)
        await session.commit()


async def get_mensaje_cochipuerco(guild_id: str) -> str | None:
    """Devuelve el ID del mensaje-panel del rol +18 de este servidor, o None."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(ConfigServidor.mensaje_cochipuerco_id).where(
                ConfigServidor.guild_id == str(guild_id)
            )
        )
        return resultado.scalar_one_or_none()
