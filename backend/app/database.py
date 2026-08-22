from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

if settings.require_postgres and not settings.database_url.startswith("postgresql"):
    raise RuntimeError("REQUIRE_POSTGRES=true，但 DATABASE_URL 不是 PostgreSQL，拒绝启动")

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
if not settings.database_url.startswith("sqlite"):
    engine_options.update(
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_recycle=settings.database_pool_recycle_seconds,
    )
engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        existing = {column["name"] for column in inspect(engine).get_columns("products")}
        additions = {
            "brand_name": "VARCHAR(256) NOT NULL DEFAULT ''",
            "ingredients": "TEXT NOT NULL DEFAULT ''",
            "usage_method": "TEXT NOT NULL DEFAULT ''",
            "specifications": "TEXT NOT NULL DEFAULT ''",
            "learned_profile_enabled": "BOOLEAN NOT NULL DEFAULT 1",
        }
        with engine.begin() as connection:
            for column, definition in additions.items():
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE products ADD COLUMN {column} {definition}"))
        generation_existing = {
            column["name"] for column in inspect(engine).get_columns("generations")
        }
        generation_additions = {
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "max_attempts": "INTEGER NOT NULL DEFAULT 3",
        }
        with engine.begin() as connection:
            for column, definition in generation_additions.items():
                if column not in generation_existing:
                    connection.execute(
                        text(f"ALTER TABLE generations ADD COLUMN {column} {definition}")
                    )
        tenant_tables = ("products", "generations", "knowledge_documents", "product_assets")
        with engine.begin() as connection:
            for table in tenant_tables:
                columns = {column["name"] for column in inspect(engine).get_columns(table)}
                if "tenant_id" not in columns:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'"))
        knowledge_columns = {
            column["name"] for column in inspect(engine).get_columns("knowledge_documents")
        }
        if "brand_name" not in knowledge_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE knowledge_documents ADD COLUMN brand_name VARCHAR(256) NOT NULL DEFAULT ''"))
        if "creative_generations" in inspect(engine).get_table_names():
            creative_columns = {column["name"] for column in inspect(engine).get_columns("creative_generations")}
            if "context_snapshot" not in creative_columns:
                with engine.begin() as connection:
                    connection.execute(text("ALTER TABLE creative_generations ADD COLUMN context_snapshot JSON"))
            if "duration_ms" not in creative_columns:
                with engine.begin() as connection:
                    connection.execute(text("ALTER TABLE creative_generations ADD COLUMN duration_ms INTEGER"))
        if "product_assets" in inspect(engine).get_table_names():
            asset_columns = {column["name"] for column in inspect(engine).get_columns("product_assets")}
            asset_additions = {
                "material_role": "VARCHAR(64) NOT NULL DEFAULT 'auto'", "priority": "INTEGER NOT NULL DEFAULT 0",
                "locked": "BOOLEAN NOT NULL DEFAULT 0", "excluded": "BOOLEAN NOT NULL DEFAULT 0",
                "benchmark_role": "VARCHAR(64) NOT NULL DEFAULT 'none'",
                "protection": "JSON NOT NULL DEFAULT '{}'",
            }
            with engine.begin() as connection:
                for column, definition in asset_additions.items():
                    if column not in asset_columns:
                        connection.execute(text(f"ALTER TABLE product_assets ADD COLUMN {column} {definition}"))
        legacy_additions = {
            "creative_projects": {"review_status": "VARCHAR(32) NOT NULL DEFAULT 'draft'", "review_round": "INTEGER NOT NULL DEFAULT 0"},
            "design_skills": {"version": "INTEGER NOT NULL DEFAULT 1"},
            "detail_page_templates": {"completed_count": "INTEGER NOT NULL DEFAULT 0", "approved_count": "INTEGER NOT NULL DEFAULT 0", "total_revision_rounds": "INTEGER NOT NULL DEFAULT 0", "variables": "JSON NOT NULL DEFAULT '[]'", "conditions": "JSON NOT NULL DEFAULT '{}'"},
        }
        for table, additions in legacy_additions.items():
            if table not in inspect(engine).get_table_names(): continue
            columns = {column["name"] for column in inspect(engine).get_columns(table)}
            with engine.begin() as connection:
                for column, definition in additions.items():
                    if column not in columns:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        if "approval_issues" in inspect(engine).get_table_names():
            issue_columns = {column["name"] for column in inspect(engine).get_columns("approval_issues")}
            issue_additions={"region":"JSON NOT NULL DEFAULT '{}'","assignee_id":"VARCHAR(64) NOT NULL DEFAULT ''","due_at":"DATETIME","blocks_finalize":"BOOLEAN NOT NULL DEFAULT 1"}
            with engine.begin() as connection:
                for column,definition in issue_additions.items():
                    if column not in issue_columns:connection.execute(text(f"ALTER TABLE approval_issues ADD COLUMN {column} {definition}"))
