from pathlib import Path
from typing import cast, LiteralString

import psycopg
from psycopg import sql

import local_config as config
from solala.database.solala_database_connections import make_connection_string


def create_database() -> None:
    admin_connection_str = make_connection_string(
        role=config.DATABASE_ADMIN_ROLE,
        password=config.DATABASE_ADMIN_PASSWORD,
        host=config.DATABASE_HOST,
        port=config.DATABASE_PORT,
        database_name=config.DATABASE_NAME,
    )

    with psycopg.connect(admin_connection_str, autocommit=True) as conn:

        # Create the app role
        exists = conn.execute(
            'SELECT 1 FROM pg_roles WHERE rolname = %s',
            (config.DATABASE_APP_ROLE,),
        ).fetchone()
        if exists:
            print(f'Role {config.DATABASE_APP_ROLE!r} already exists.')
        else:
            conn.execute(
                sql.SQL('CREATE ROLE {} WITH LOGIN PASSWORD {}').format(
                    sql.Identifier(config.DATABASE_APP_ROLE),
                    sql.Literal(config.DATABASE_APP_PASSWORD),
                )
            )
            print(f'Created role {config.DATABASE_APP_ROLE!r}.')

        # create the app database
        exists = conn.execute(
            'SELECT 1 FROM pg_database WHERE datname = %s',
            (config.DATABASE_NAME,),
        ).fetchone()
        if exists:
            print(f'Database {config.DATABASE_NAME!r} already exists.')
        else:
            conn.execute(
                sql.SQL('CREATE DATABASE {} OWNER {}').format(
                    sql.Identifier(config.DATABASE_NAME),
                    sql.Identifier(config.DATABASE_APP_ROLE),
                )
            )
            print(f'Created database {config.DATABASE_NAME!r}.')


def create_schema() -> None:
    schema_path = Path(__file__).parent / 'schema.sql'
    schema = cast(LiteralString, schema_path.read_text(encoding='utf-8'))

    app_connection_str = make_connection_string(
        role=config.DATABASE_APP_ROLE,
        password=config.DATABASE_APP_PASSWORD,
        host=config.DATABASE_HOST,
        port=config.DATABASE_PORT,
        database_name=config.DATABASE_NAME,
    )

    with psycopg.connect(app_connection_str) as conn:
        conn.execute(schema)

    print('Solala tables created or recreated.')


def main() -> None:
    create_database()
    create_schema()


if __name__ == '__main__':
    main()
