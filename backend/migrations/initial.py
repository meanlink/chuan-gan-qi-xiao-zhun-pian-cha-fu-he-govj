from sqlalchemy import inspect, text
from src.config.database import engine, Base
from src import models

# 旧 reports/deliveries 表需要补的列（新库由 create_all 直接建出）
REPORT_COLUMNS = {
    'schedule_kind': "VARCHAR(10) NOT NULL DEFAULT 'weekly'",
    'interval_seconds': 'INTEGER',
    'next_run': 'DOUBLE PRECISION',
    'current_version_id': 'INTEGER',
}
DELIVERY_COLUMNS = {
    'occurrence_id': 'INTEGER',
    'scheduled_local': 'VARCHAR(160)',
    'scheduled_at': 'DOUBLE PRECISION',
    'schedule_version': 'INTEGER',
}

def _add_missing_columns(engine):
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        if 'reports' in tables:
            existing = {c['name'] for c in insp.get_columns('reports')}
            for name, ddl in REPORT_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE reports ADD COLUMN {name} {ddl}'))
        if 'deliveries' in tables:
            existing = {c['name'] for c in insp.get_columns('deliveries')}
            for name, ddl in DELIVERY_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE deliveries ADD COLUMN {name} {ddl}'))

def migrate():
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)

if __name__=='__main__':migrate()
