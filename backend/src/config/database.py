from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .settings import DATABASE_URL

class Base(DeclarativeBase):
    pass

connect_args = {}
if DATABASE_URL.startswith('sqlite'):
    connect_args['timeout'] = 30

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800,
                       connect_args=connect_args)

if DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA busy_timeout=30000')
        cur.execute('PRAGMA foreign_keys=ON')
        cur.close()

Session = sessionmaker(engine, expire_on_commit=False)

def get_db():
    with Session() as db:
        yield db
