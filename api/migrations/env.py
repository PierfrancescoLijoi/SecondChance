import os
from logging.config import fileConfig

from alembic import context
from secondchance.dbconn import make_engine

if context.config.config_file_name:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

engine = make_engine(os.environ["SECONDCHANCE_MIGRATOR_URL"])
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
