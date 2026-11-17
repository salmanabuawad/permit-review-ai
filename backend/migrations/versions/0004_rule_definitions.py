"""rule definitions (rules created/edited in the rules screen)

Revision ID: 0004
Revises: 0002
Create Date: 2026-11-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision: str = '0004'
down_revision: Union[str, None] = '0002'   # TODO on merge with the source-monitor work: '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('rule_definitions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=40), nullable=False),
    sa.Column('rule_id', sa.String(length=80), nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('deleted', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', models.UTCDateTime(timezone=True), nullable=False),
    sa.Column('updated_by', sa.String(length=40), nullable=False),
    sa.Column('updated_at', models.UTCDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['municipalities.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'rule_id', name='uq_rule_definitions_tenant_rule')
    )
    with op.batch_alter_table('rule_definitions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rule_definitions_tenant_id'), ['tenant_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('rule_definitions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rule_definitions_tenant_id'))
    op.drop_table('rule_definitions')
