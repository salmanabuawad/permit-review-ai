"""text chunks of committee passages with local embeddings (pgvector on PostgreSQL)"""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == 'postgresql'
    op.create_table('committee_chunks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('passage_id', sa.Integer(), sa.ForeignKey('committee_passages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ord', sa.Integer(), nullable=False), sa.Column('start', sa.Integer(), nullable=False),
        sa.Column('end', sa.Integer(), nullable=False), sa.Column('model', sa.String(80), nullable=True),
        sa.Column('embedding', sa.Text(), nullable=True))
    op.create_index('ix_committee_chunks_passage_id', 'committee_chunks', ['passage_id'])
    op.create_index('ix_committee_chunks_model', 'committee_chunks', ['model'])
    if pg:                       # a real vector column; exact search first, an approximate index only after a benchmark
        op.execute('ALTER TABLE committee_chunks ALTER COLUMN embedding TYPE vector(384) USING embedding::vector')


def downgrade():
    op.drop_table('committee_chunks')
