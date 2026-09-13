import logging

from sqlalchemy import Engine, inspect, text
from sqlmodel import SQLModel

from src.persistence.models import get_engine

logger = logging.getLogger(__name__)


def _apply_additive_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    for table_name, table in SQLModel.metadata.tables.items():
        if table_name not in inspector.get_table_names():
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            column_type = column.type.compile(engine.dialect)
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {column_type}"))
            logger.info(f"Additive migration column successfully added. Table: {table_name}. Column: {column.name}.")


def create_schema() -> None:
    logger.info("Starting relational schema creation.")
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _apply_additive_migrations(engine)
    logger.info(f"Relational schema successfully created. Tables: {len(SQLModel.metadata.tables)}.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    create_schema()
