from pathlib import Path
from typing import cast, LiteralString

import psycopg
from psycopg import sql

from local_config import DATABASE_ADMIN_URL, DATABASE_APP_URL, DATABASE_NAME, DATABASE_APP_ROLE, DATABASE_APP_PASSWORD


def create_database() -> None:
    with psycopg.connect(DATABASE_ADMIN_URL, autocommit=True) as conn:

        # Create the app role
        exists = conn.execute(
            'SELECT 1 FROM pg_roles WHERE rolname = %s',
            (DATABASE_APP_ROLE,),
        ).fetchone()
        if exists:
            print(f'Role {DATABASE_APP_ROLE!r} already exists.')
        else:
            conn.execute(
                sql.SQL('CREATE ROLE {} WITH LOGIN PASSWORD {}').format(
                    sql.Identifier(DATABASE_APP_ROLE),
                    sql.Literal(DATABASE_APP_PASSWORD),
                )
            )
            print(f'Created role {DATABASE_APP_ROLE!r}.')

        # create the app database
        exists = conn.execute(
            'SELECT 1 FROM pg_database WHERE datname = %s',
            (DATABASE_NAME,),
        ).fetchone()
        if exists:
            print(f'Database {DATABASE_NAME!r} already exists.')
        else:
            conn.execute(
                sql.SQL('CREATE DATABASE {} OWNER {}').format(
                    sql.Identifier(DATABASE_NAME),
                    sql.Identifier(DATABASE_APP_ROLE),
                )
            )
            print(f'Created database {DATABASE_NAME!r}.')


def create_schema() -> None:
    schema_path = Path(__file__).parent / 'schema.sql'
    schema = cast(LiteralString, schema_path.read_text(encoding='utf-8'))

    with psycopg.connect(DATABASE_APP_URL) as conn:
        conn.execute(schema)

    print('Solala tables created or recreated.')


def main() -> None:
    create_database()
    create_schema()


if __name__ == '__main__':
    main()
