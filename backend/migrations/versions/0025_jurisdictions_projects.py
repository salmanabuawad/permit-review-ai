"""Planning jurisdictions (official boundaries, versioned datasets), geo query cache, project initialization on cases"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == 'postgresql'
    op.create_table('geo_datasets',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(60), nullable=False), sa.Column('source_url', sa.String(400), nullable=False),
        sa.Column('version', sa.String(32), nullable=False), sa.Column('features', sa.Integer(), nullable=False),
        sa.Column('fetched_at', models.UTCDateTime(), nullable=False), sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('superseded_at', models.UTCDateTime()), sa.Column('meta', sa.JSON()))
    op.create_index('ix_geo_datasets_name', 'geo_datasets', ['name', 'active'])
    op.create_table('jurisdiction_areas',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('dataset_id', sa.Integer(), sa.ForeignKey('geo_datasets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False), sa.Column('code', sa.String(20)),
        sa.Column('name_he', sa.String(200)), sa.Column('area_type', sa.String(40)), sa.Column('district', sa.String(40)),
        sa.Column('parent_name', sa.String(200)), sa.Column('sign_date', sa.Date()),
        sa.Column('committee_id', sa.String(32), sa.ForeignKey('planning_committees.id')),
        sa.Column('link_method', sa.String(40)), sa.Column('attrs', sa.JSON()), sa.Column('geojson', sa.Text()))
    op.create_index('ix_jurisdiction_areas_kind', 'jurisdiction_areas', ['kind', 'dataset_id'])
    if pg:
        op.execute('ALTER TABLE jurisdiction_areas ADD COLUMN geom geometry(MultiPolygon, 2039)')
        op.execute('CREATE INDEX ix_jurisdiction_areas_geom ON jurisdiction_areas USING gist (geom)')
    op.create_table('geo_query_cache',
        sa.Column('key', sa.String(200), primary_key=True), sa.Column('versions', sa.String(200), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False), sa.Column('created_at', models.UTCDateTime(), nullable=False))
    with op.batch_alter_table('planning_committees') as b:
        b.add_column(sa.Column('planning_area_codes', sa.JSON()))
    with op.batch_alter_table('permit_cases') as b:
        b.add_column(sa.Column('committee_id', sa.String(32), sa.ForeignKey('planning_committees.id', name='fk_case_committee')))
        b.add_column(sa.Column('jurisdiction', sa.JSON()))
        b.add_column(sa.Column('workflow', sa.JSON()))


def downgrade():
    with op.batch_alter_table('permit_cases') as b:
        for c in ('workflow', 'jurisdiction', 'committee_id'):
            b.drop_column(c)
    with op.batch_alter_table('planning_committees') as b:
        b.drop_column('planning_area_codes')
    op.drop_table('geo_query_cache')
    op.drop_table('jurisdiction_areas')
    op.drop_table('geo_datasets')
