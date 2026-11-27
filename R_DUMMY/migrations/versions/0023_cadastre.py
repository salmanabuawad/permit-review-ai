"""National cadastre (Survey of Israel open data): registered parcels and blocks, EPSG:2039"""
from alembic import op
import sqlalchemy as sa

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == 'postgresql'
    for name, keys in (('cadastre_parcels', ('gush', 'helka')), ('cadastre_blocks', ('gush',))):
        cols = [sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
                sa.Column('gush', sa.Integer(), nullable=False), sa.Column('gush_suffix', sa.Integer())]
        if name == 'cadastre_parcels':
            cols.append(sa.Column('helka', sa.Integer(), nullable=False))
        cols += [sa.Column('legal_area', sa.Float()), sa.Column('status', sa.String(60)), sa.Column('locality', sa.String(120)),
                 sa.Column('attrs', sa.JSON()), sa.Column('source', sa.String(120), nullable=False),
                 sa.Column('geojson', sa.Text())]                       # SQLite / tests; PostgreSQL uses geom
        op.create_table(name, *cols)
        op.create_index(f'ix_{name}_key', name, list(keys))
        if pg:
            op.execute(f'ALTER TABLE {name} ADD COLUMN geom geometry(MultiPolygon, 2039)')
            op.execute(f'CREATE INDEX ix_{name}_geom ON {name} USING gist (geom)')


def downgrade():
    op.drop_table('cadastre_blocks')
    op.drop_table('cadastre_parcels')
