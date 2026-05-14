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
            ensure_sqlite_migrations(connection)
            connection.commit()


def ensure_sqlite_migrations(connection) -> None:
    """Keep old user SQLite databases compatible with newer app builds."""
    migrations = {
        "shop": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("shop_name", "shop_name VARCHAR(255)"),
            ("wangwang", "wangwang VARCHAR(255)"),
            ("shop_type", "shop_type VARCHAR(64)"),
            ("account_id", "account_id VARCHAR(128)"),
            ("profile_id", "profile_id VARCHAR(128)"),
            ("profile_path", "profile_path VARCHAR(500)"),
            ("browser_env_json", "browser_env_json JSON"),
            ("worker_id", "worker_id VARCHAR(128)"),
            ("cookie_status", "cookie_status VARCHAR(32) DEFAULT 'unknown'"),
            ("enabled", "enabled BOOLEAN DEFAULT 1"),
            ("last_cookie_check_at", "last_cookie_check_at DATETIME"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "cookie_snapshot": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("shop_name", "shop_name VARCHAR(255)"),
            ("profile_id", "profile_id VARCHAR(128)"),
            ("profile_path", "profile_path VARCHAR(500)"),
            ("cookie_type", "cookie_type VARCHAR(32) DEFAULT 'main'"),
            ("cookie_count", "cookie_count INTEGER DEFAULT 0"),
            ("cookie_header_text", "cookie_header_text TEXT"),
            ("cookies_json", "cookies_json JSON"),
            ("storage_state_json", "storage_state_json JSON"),
            ("status", "status VARCHAR(32) DEFAULT 'captured'"),
            ("created_at", "created_at DATETIME"),
        ],
        "product": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("product_id", "product_id VARCHAR(128)"),
            ("title", "title VARCHAR(255)"),
            ("main_image_url", "main_image_url VARCHAR(1000)"),
            ("price", "price FLOAT DEFAULT 0"),
            ("stock", "stock INTEGER DEFAULT 0"),
            ("status", "status VARCHAR(32) DEFAULT 'draft'"),
            ("total_sales", "total_sales INTEGER DEFAULT 0"),
            ("sales_30d", "sales_30d INTEGER DEFAULT 0"),
            ("last_platform_updated_at", "last_platform_updated_at DATETIME"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "product_sku": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("product_id", "product_id VARCHAR(128)"),
            ("sku_id", "sku_id VARCHAR(128)"),
            ("sku_code", "sku_code VARCHAR(255)"),
            ("sku_name", "sku_name VARCHAR(500)"),
            ("image_url", "image_url VARCHAR(1000)"),
            ("taobao_price", "taobao_price FLOAT DEFAULT 0"),
            ("stock", "stock INTEGER DEFAULT 0"),
            ("normal_sale_price", "normal_sale_price FLOAT"),
            ("shunshou_signup_price", "shunshou_signup_price FLOAT"),
            ("status", "status VARCHAR(32) DEFAULT 'active'"),
            ("props_json", "props_json JSON"),
            ("raw_json", "raw_json JSON"),
            ("last_platform_updated_at", "last_platform_updated_at DATETIME"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "feishu_sku_price_map": [
            ("shop_id", "shop_id VARCHAR(128)"),
            ("shop_name", "shop_name VARCHAR(255)"),
            ("sku_code", "sku_code VARCHAR(255)"),
            ("normal_sale_price", "normal_sale_price FLOAT"),
            ("shunshou_signup_price", "shunshou_signup_price FLOAT"),
            ("record_status", "record_status VARCHAR(32) DEFAULT 'active'"),
            ("feishu_record_id", "feishu_record_id VARCHAR(128)"),
            ("activity_id", "activity_id VARCHAR(128)"),
            ("activity_name", "activity_name VARCHAR(255)"),
            ("remark", "remark TEXT"),
            ("raw_json", "raw_json JSON"),
            ("last_sync_at", "last_sync_at DATETIME"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "product_pxi": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("product_id", "product_id VARCHAR(128)"),
            ("pxi_score", "pxi_score VARCHAR(64)"),
            ("update_date", "update_date VARCHAR(8)"),
            ("range_day", "range_day VARCHAR(32) DEFAULT '30d'"),
            ("status", "status VARCHAR(32) DEFAULT 'active'"),
            ("raw_json", "raw_json JSON"),
            ("last_platform_updated_at", "last_platform_updated_at DATETIME"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "shunshou_activity": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("activity_id", "activity_id VARCHAR(128)"),
            ("activity_name", "activity_name VARCHAR(255)"),
            ("activity_status", "activity_status INTEGER"),
            ("activity_status_text", "activity_status_text VARCHAR(64)"),
            ("signed_item_count", "signed_item_count INTEGER"),
            ("max_item_limit", "max_item_limit INTEGER"),
            ("start_time", "start_time VARCHAR(64)"),
            ("end_time", "end_time VARCHAR(64)"),
            ("sync_status", "sync_status VARCHAR(32) DEFAULT 'active'"),
            ("raw_json", "raw_json JSON"),
            ("last_platform_updated_at", "last_platform_updated_at DATETIME"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "shunshou_activity_item": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("activity_id", "activity_id VARCHAR(128)"),
            ("product_id", "product_id VARCHAR(128)"),
            ("item_title", "item_title VARCHAR(255)"),
            ("warn_message", "warn_message VARCHAR(1000)"),
            ("warn_status", "warn_status VARCHAR(64)"),
            ("activity_item_status", "activity_item_status VARCHAR(64)"),
            ("is_joined", "is_joined INTEGER DEFAULT 0"),
            ("auction_status", "auction_status INTEGER DEFAULT 0"),
            ("sync_status", "sync_status VARCHAR(32) DEFAULT 'active'"),
            ("raw_json", "raw_json JSON"),
            ("last_platform_updated_at", "last_platform_updated_at DATETIME"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "task": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("shop_name", "shop_name VARCHAR(255)"),
            ("account_id", "account_id VARCHAR(128)"),
            ("profile_id", "profile_id VARCHAR(128)"),
            ("worker_id", "worker_id VARCHAR(128)"),
            ("task_type", "task_type VARCHAR(64)"),
            ("status", "status VARCHAR(32) DEFAULT 'pending'"),
            ("priority", "priority INTEGER DEFAULT 100"),
            ("payload_json", "payload_json JSON"),
            ("result_json", "result_json JSON"),
            ("error_message", "error_message TEXT"),
            ("retry_count", "retry_count INTEGER DEFAULT 0"),
            ("max_retries", "max_retries INTEGER DEFAULT 3"),
            ("next_run_at", "next_run_at DATETIME"),
            ("locked_at", "locked_at DATETIME"),
            ("lock_expired_at", "lock_expired_at DATETIME"),
            ("started_at", "started_at DATETIME"),
            ("finished_at", "finished_at DATETIME"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "request_log": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("shop_name", "shop_name VARCHAR(255)"),
            ("account_id", "account_id VARCHAR(128)"),
            ("profile_id", "profile_id VARCHAR(128)"),
            ("worker_id", "worker_id VARCHAR(128)"),
            ("task_id", "task_id INTEGER"),
            ("method", "method VARCHAR(16)"),
            ("url", "url VARCHAR(1000)"),
            ("status_code", "status_code INTEGER"),
            ("request_headers_json", "request_headers_json JSON"),
            ("request_body_json", "request_body_json JSON"),
            ("response_headers_json", "response_headers_json JSON"),
            ("response_body_json", "response_body_json JSON"),
            ("error_message", "error_message TEXT"),
            ("duration_ms", "duration_ms INTEGER"),
            ("created_at", "created_at DATETIME"),
        ],
        "task_log": [
            ("task_id", "task_id INTEGER"),
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("level", "level VARCHAR(32) DEFAULT 'info'"),
            ("message", "message TEXT"),
            ("context_json", "context_json JSON"),
            ("created_at", "created_at DATETIME"),
        ],
        "captcha_challenge": [
            ("platform", "platform VARCHAR(32)"),
            ("shop_id", "shop_id VARCHAR(128)"),
            ("task_id", "task_id INTEGER"),
            ("scene", "scene VARCHAR(64)"),
            ("captcha_type", "captcha_type VARCHAR(64) DEFAULT 'manual'"),
            ("provider", "provider VARCHAR(64) DEFAULT 'manual'"),
            ("status", "status VARCHAR(32) DEFAULT 'waiting'"),
            ("page_url", "page_url VARCHAR(1000)"),
            ("screenshot_path", "screenshot_path VARCHAR(500)"),
            ("payload_json", "payload_json JSON"),
            ("result_json", "result_json JSON"),
            ("error_message", "error_message TEXT"),
            ("expired_at", "expired_at DATETIME"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "app_config": [
            ("key", "key VARCHAR(128)"),
            ("value", "value TEXT"),
            ("value_type", "value_type VARCHAR(32) DEFAULT 'string'"),
            ("sensitive", "sensitive BOOLEAN DEFAULT 0"),
            ("description", "description TEXT"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "ai_prompt_template": [
            ("name", "name VARCHAR(128)"),
            ("scene", "scene VARCHAR(64)"),
            ("version", "version VARCHAR(32)"),
            ("prompt_text", "prompt_text TEXT"),
            ("enabled", "enabled BOOLEAN DEFAULT 1"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "ai_model_config": [
            ("provider", "provider VARCHAR(64)"),
            ("model_name", "model_name VARCHAR(128)"),
            ("base_url", "base_url VARCHAR(500)"),
            ("api_key_name", "api_key_name VARCHAR(128)"),
            ("enabled", "enabled BOOLEAN DEFAULT 1"),
            ("created_at", "created_at DATETIME"),
            ("updated_at", "updated_at DATETIME"),
        ],
        "ai_task": [
            ("scene", "scene VARCHAR(64)"),
            ("input_json", "input_json JSON"),
            ("status", "status VARCHAR(32) DEFAULT 'pending'"),
            ("model_name", "model_name VARCHAR(128)"),
            ("prompt_version", "prompt_version VARCHAR(32)"),
            ("created_at", "created_at DATETIME"),
            ("finished_at", "finished_at DATETIME"),
        ],
        "ai_result": [
            ("ai_task_id", "ai_task_id INTEGER"),
            ("result_json", "result_json JSON"),
            ("summary", "summary TEXT"),
            ("confidence", "confidence FLOAT"),
            ("created_at", "created_at DATETIME"),
        ],
    }
    for table_name, columns in migrations.items():
        for column_name, ddl in columns:
            ensure_sqlite_column(connection, table_name=table_name, column_name=column_name, ddl=ddl)


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
