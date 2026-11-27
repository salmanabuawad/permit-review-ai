"""regulatory hierarchy, Hebrew terminology and clauses"""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('jurisdictions',
        sa.Column('id', sa.String(80), primary_key=True), sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('name_he', sa.String(200), nullable=False),
        sa.Column('parent_id', sa.String(80), sa.ForeignKey('jurisdictions.id'), nullable=True),
        sa.Column('committee_id', sa.String(40), sa.ForeignKey('planning_committees.id'), nullable=True),
        sa.Column('municipality_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=True))
    op.create_index('ix_jurisdictions_kind', 'jurisdictions', ['kind'])
    op.create_index('ix_jurisdictions_parent_id', 'jurisdictions', ['parent_id'])
    op.create_table('terminology',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('concept', sa.String(60), nullable=False), sa.Column('term', sa.String(120), nullable=False),
        sa.Column('label_he', sa.String(120)), sa.Column('note_he', sa.String(300)),
        sa.Column('created_by', sa.String(40), nullable=False), sa.UniqueConstraint('concept', 'term'))
    op.create_index('ix_terminology_concept', 'terminology', ['concept'])
    op.create_table('regulatory_clauses',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('jurisdiction_id', sa.String(80), sa.ForeignKey('jurisdictions.id'), nullable=False),
        sa.Column('passage_id', sa.Integer(), sa.ForeignKey('committee_passages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('number', sa.String(40)), sa.Column('parent_id', sa.Integer(), sa.ForeignKey('regulatory_clauses.id', ondelete='CASCADE')),
        sa.Column('depth', sa.Integer(), nullable=False), sa.Column('start', sa.Integer(), nullable=False),
        sa.Column('end', sa.Integer(), nullable=False), sa.Column('text_he', sa.Text(), nullable=False),
        sa.Column('topics', sa.JSON(), nullable=False), sa.Column('verification', sa.String(20), nullable=False))
    op.create_index('ix_regulatory_clauses_jurisdiction_id', 'regulatory_clauses', ['jurisdiction_id'])
    op.create_index('ix_regulatory_clauses_passage_id', 'regulatory_clauses', ['passage_id'])
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('CREATE INDEX ix_regulatory_clauses_trgm ON regulatory_clauses USING gin (text_he gin_trgm_ops)')


def downgrade():
    op.drop_table('regulatory_clauses')
    op.drop_table('terminology')
    op.drop_table('jurisdictions')
