from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {}
engine = create_engine(settings.resolved_database_url, connect_args=connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)

    if settings.resolved_database_url.startswith("sqlite"):
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            ensure_sqlite_column(
                connection,
                table_name="cookie_snapshot",
                column_name="cookie_type",
                ddl="cookie_type VARCHAR(32) DEFAULT 'main'",
            )
            ensure_sqlite_column(
                connection,
                table_name="cookie_snapshot",
                column_name="cookie_header_text",
                ddl="cookie_header_text TEXT",
            )
            ensure_sqlite_column(
                connection,
                table_name="shop",
                column_name="browser_env_json",
                ddl="browser_env_json JSON",
            )
            ensure_sqlite_column(
                connection,
                table_name="shop",
                column_name="wangwang",
                ddl="wangwang VARCHAR(255)",
            )
            ensure_sqlite_column(
                connection,
                table_name="shop",
                column_name="shop_type",
                ddl="shop_type VARCHAR(64)",
            )
            ensure_sqlite_column(
                connection,
                table_name="product",
                column_name="main_image_url",
                ddl="main_image_url VARCHAR(1000)",
            )
            ensure_sqlite_column(
                connection,
                table_name="product",
                column_name="total_sales",
                ddl="total_sales INTEGER DEFAULT 0",
            )
            ensure_sqlite_column(
                connection,
                table_name="product",
                column_name="sales_30d",
                ddl="sales_30d INTEGER DEFAULT 0",
            )
            ensure_sqlite_column(
                connection,
                table_name="product",
                column_name="last_platform_updated_at",
                ddl="last_platform_updated_at DATETIME",
            )
            ensure_sqlite_column(
                connection,
                table_name="product_sku",
                column_name="normal_sale_price",
                ddl="normal_sale_price FLOAT",
            )
            ensure_sqlite_column(
                connection,
                table_name="product_sku",
                column_name="shunshou_signup_price",
                ddl="shunshou_signup_price FLOAT",
            )
            ensure_sqlite_column(
                connection,
                table_name="feishu_sku_price_map",
                column_name="normal_sale_price",
                ddl="normal_sale_price FLOAT",
            )
            ensure_sqlite_column(
                connection,
                table_name="feishu_sku_price_map",
                column_name="shunshou_signup_price",
                ddl="shunshou_signup_price FLOAT",
            )
            ensure_sqlite_column(
                connection,
                table_name="product_pxi",
                column_name="raw_json",
                ddl="raw_json JSON",
            )


def ensure_sqlite_column(connection, table_name: str, column_name: str, ddl: str) -> None:
    rows = connection.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    if not rows:
        return
    existing = {row[1] for row in rows}
    if column_name not in existing:
        connection.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
