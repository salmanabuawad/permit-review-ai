"""permit dependency graph nodes (v1: rule evaluations per run)"""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('pdg_nodes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('run_id', sa.String(32), sa.ForeignKey('check_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False), sa.Column('key', sa.String(120), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('inputs', sa.JSON(), nullable=False), sa.Column('output', sa.JSON(), nullable=False))
    op.create_index('ix_pdg_nodes_tenant_id', 'pdg_nodes', ['tenant_id'])
    op.create_index('ix_pdg_nodes_run_id', 'pdg_nodes', ['run_id'])
    op.create_index('ix_pdg_nodes_fingerprint', 'pdg_nodes', ['fingerprint'])


def downgrade():
    op.drop_table('pdg_nodes')
