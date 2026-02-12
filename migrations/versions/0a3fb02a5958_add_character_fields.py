"""add character fields for talking-head bots

Revision ID: 0a3fb02a5958
Revises: b0f8d3bce09e
Create Date: 2026-02-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a3fb02a5958'
down_revision: Union[str, Sequence[str], None] = 'b0f8d3bce09e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Bot: character fields for talking-head pipeline
    op.add_column('bots', sa.Column('character_face_url', sa.Text(), nullable=True))
    op.add_column('bots', sa.Column('character_voice_id', sa.String(length=100), nullable=True))
    op.add_column('bots', sa.Column('character_personality', sa.Text(), nullable=True))
    # ContentItem: audio file path for TTS output
    op.add_column('content_items', sa.Column('audio_file_path', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('content_items', 'audio_file_path')
    op.drop_column('bots', 'character_personality')
    op.drop_column('bots', 'character_voice_id')
    op.drop_column('bots', 'character_face_url')
