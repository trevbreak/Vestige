"""phase9_traits_relationships_elevenlabs

Adds:
  - character_traits table (trait evolution with strength/decay/manifestation)
  - relationship_states table (structured trust/affection/respect axes)
  - elevenlabs_voice_id, elevenlabs_voice_params, elevenlabs_model_preference to avatars

Revision ID: a2f1c9e4b857
Revises: 1e3da4b47230
Create Date: 2026-05-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2f1c9e4b857'
down_revision: Union[str, None] = '1e3da4b47230'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── character_traits ─────────────────────────────────────────────────
    op.create_table(
        'character_traits',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('avatar_id', sa.Integer(), sa.ForeignKey('avatars.id'), nullable=False, index=True),
        sa.Column('trait_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('current_strength', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('last_reinforced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('manifestation_probability', sa.Float(), nullable=False, server_default='0.3'),
        sa.Column('trigger_keywords', sa.Text(), nullable=True),
        sa.Column('emotional_signature', sa.String(length=50), nullable=True),
        sa.Column('onset_session_id', sa.Integer(), sa.ForeignKey('sessions.id'), nullable=True),
        sa.Column('is_resolved', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('is_positive', sa.Boolean(), nullable=False, server_default='0'),
    )

    # ── relationship_states ──────────────────────────────────────────────
    op.create_table(
        'relationship_states',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('avatar_a_id', sa.Integer(), sa.ForeignKey('avatars.id'), nullable=False, index=True),
        sa.Column('avatar_b_id', sa.Integer(), sa.ForeignKey('avatars.id'), nullable=True, index=True),
        sa.Column('target_name', sa.String(length=100), nullable=True),
        sa.Column('trust', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('affection', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('respect', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('key_moments', sa.Text(), nullable=True),
        sa.Column('last_updated_session_id', sa.Integer(), sa.ForeignKey('sessions.id'), nullable=True),
    )

    # ── avatars ElevenLabs fields ────────────────────────────────────────
    import sqlite3, os
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'campaign.db')
    conn = sqlite3.connect(db_path)
    existing_cols = {r[1] for r in conn.execute('PRAGMA table_info(avatars)').fetchall()}
    conn.close()

    if 'elevenlabs_voice_id' not in existing_cols:
        op.add_column('avatars', sa.Column('elevenlabs_voice_id', sa.String(length=100), nullable=True))
    if 'elevenlabs_voice_params' not in existing_cols:
        op.add_column('avatars', sa.Column('elevenlabs_voice_params', sa.JSON(), nullable=True))
    if 'elevenlabs_model_preference' not in existing_cols:
        op.add_column('avatars', sa.Column(
            'elevenlabs_model_preference', sa.String(length=30),
            nullable=False, server_default='eleven_v3',
        ))


def downgrade() -> None:
    op.drop_table('relationship_states')
    op.drop_table('character_traits')
    op.drop_column('avatars', 'elevenlabs_model_preference')
    op.drop_column('avatars', 'elevenlabs_voice_params')
    op.drop_column('avatars', 'elevenlabs_voice_id')
