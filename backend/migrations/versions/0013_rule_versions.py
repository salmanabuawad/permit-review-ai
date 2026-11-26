"""immutable history of rules edited in the rules screen (backfilled from current definitions)"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('rule_versions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('rule_id', sa.String(80), nullable=False), sa.Column('version', sa.String(20), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False), sa.Column('deleted', sa.Boolean(), nullable=False),
        sa.Column('saved_by', sa.String(40), nullable=False), sa.Column('saved_at', models.UTCDateTime(), nullable=False))
    op.create_index('ix_rule_versions_tenant_id', 'rule_versions', ['tenant_id'])
    op.create_index('ix_rule_versions_rule_id', 'rule_versions', ['rule_id'])
    # the current definition of each edited rule becomes its first recorded version
    op.execute("INSERT INTO rule_versions (tenant_id, rule_id, version, data, deleted, saved_by, saved_at) "
               "SELECT tenant_id, rule_id, version, data, deleted, updated_by, updated_at FROM rule_definitions")


def downgrade():
    op.drop_table('rule_versions')
