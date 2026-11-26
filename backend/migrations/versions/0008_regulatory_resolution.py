"""regulatory registry, parcel plan discovery and resumable crawls"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('source_crawls', sa.Column('checkpoint', sa.JSON(), nullable=True))
    op.create_table('regulatory_entries',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('municipalities.id'),nullable=False),
        sa.Column('snapshot_id',sa.Integer(),sa.ForeignKey('source_snapshots.id'),nullable=False),
        sa.Column('data',sa.JSON(),nullable=False),
        sa.Column('approved_by',sa.String(40),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('approved_at',models.UTCDateTime(),nullable=False))
    op.create_index('ix_regulatory_entries_tenant_id','regulatory_entries',['tenant_id'])
    op.create_table('parcel_plan_discovery',
        sa.Column('case_id',sa.String(32),sa.ForeignKey('permit_cases.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('municipalities.id'),nullable=False),
        sa.Column('parcel_hash',sa.String(64),nullable=False),sa.Column('result',sa.JSON(),nullable=False),
        sa.Column('checked_at',models.UTCDateTime(),nullable=False))
    op.create_index('ix_parcel_plan_discovery_tenant_id','parcel_plan_discovery',['tenant_id'])

def downgrade():
    op.drop_table('parcel_plan_discovery');op.drop_table('regulatory_entries')
    with op.batch_alter_table('source_crawls') as b: b.drop_column('checkpoint')
