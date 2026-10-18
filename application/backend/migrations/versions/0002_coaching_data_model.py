"""coaching data model

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 18:55:55.023434
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('challenges',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('metric', sa.String(length=48), nullable=False),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('target_value', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('starts_on', sa.Date(), nullable=False),
    sa.Column('ends_on', sa.Date(), nullable=False),
    sa.Column('reward_points', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('accounts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('owner_user_id', sa.UUID(), nullable=True),
    sa.Column('public_ref', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('industry', sa.String(length=64), nullable=True),
    sa.Column('segment', sa.String(length=32), nullable=False),
    sa.Column('tier', sa.String(length=1), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('first_touch_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['app_users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_accounts_org_owner', 'accounts', ['organization_id', 'owner_user_id'], unique=False)
    op.create_index(op.f('ix_accounts_public_ref'), 'accounts', ['public_ref'], unique=True)
    op.create_table('coaching_actions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('title', sa.String(length=256), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('related_metric', sa.String(length=48), nullable=True),
    sa.Column('due_on', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_coaching_org_status', 'coaching_actions', ['organization_id', 'status'], unique=False)
    op.create_table('sales_targets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('metric', sa.String(length=48), nullable=False),
    sa.Column('period', sa.String(length=16), nullable=False),
    sa.Column('target_value', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'user_id', 'metric', 'period', 'valid_from', name='uq_target')
    )
    op.create_table('activities',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=True),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('outcome', sa.String(length=24), nullable=False),
    sa.Column('is_hunting', sa.Boolean(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_seconds', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activities_account_id'), 'activities', ['account_id'], unique=False)
    op.create_index('ix_activities_org_occurred', 'activities', ['organization_id', 'occurred_at'], unique=False)
    op.create_index('ix_activities_user_occurred', 'activities', ['user_id', 'occurred_at'], unique=False)
    op.create_table('opportunities',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('public_ref', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('is_new_logo', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expected_close_date', sa.Date(), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_stage_change_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_step', sa.String(length=256), nullable=True),
    sa.Column('next_step_due', sa.Date(), nullable=True),
    sa.Column('lost_reason', sa.String(length=32), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_opportunities_account_id'), 'opportunities', ['account_id'], unique=False)
    op.create_index('ix_opportunities_org_user_stage', 'opportunities', ['organization_id', 'user_id', 'stage'], unique=False)
    op.create_index(op.f('ix_opportunities_public_ref'), 'opportunities', ['public_ref'], unique=True)
    op.create_table('opportunity_stage_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('opportunity_id', sa.UUID(), nullable=False),
    sa.Column('from_stage', sa.String(length=16), nullable=True),
    sa.Column('to_stage', sa.String(length=16), nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_opportunity_stage_events_opportunity_id'), 'opportunity_stage_events', ['opportunity_id'], unique=False)
    op.add_column('app_users', sa.Column('alias', sa.String(length=64), nullable=True))
    op.add_column('meeting_classifications', sa.Column('account_id', sa.UUID(), nullable=True))
    op.add_column('meeting_classifications', sa.Column('opportunity_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_meeting_classifications_account_id'), 'meeting_classifications', ['account_id'], unique=False)
    op.create_foreign_key('fk_meeting_classifications_opportunity', 'meeting_classifications', 'opportunities', ['opportunity_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_meeting_classifications_account', 'meeting_classifications', 'accounts', ['account_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_meeting_classifications_account', 'meeting_classifications', type_='foreignkey')
    op.drop_constraint('fk_meeting_classifications_opportunity', 'meeting_classifications', type_='foreignkey')
    op.drop_index(op.f('ix_meeting_classifications_account_id'), table_name='meeting_classifications')
    op.drop_column('meeting_classifications', 'opportunity_id')
    op.drop_column('meeting_classifications', 'account_id')
    op.drop_column('app_users', 'alias')
    op.drop_index(op.f('ix_opportunity_stage_events_opportunity_id'), table_name='opportunity_stage_events')
    op.drop_table('opportunity_stage_events')
    op.drop_index(op.f('ix_opportunities_public_ref'), table_name='opportunities')
    op.drop_index('ix_opportunities_org_user_stage', table_name='opportunities')
    op.drop_index(op.f('ix_opportunities_account_id'), table_name='opportunities')
    op.drop_table('opportunities')
    op.drop_index('ix_activities_user_occurred', table_name='activities')
    op.drop_index('ix_activities_org_occurred', table_name='activities')
    op.drop_index(op.f('ix_activities_account_id'), table_name='activities')
    op.drop_table('activities')
    op.drop_table('sales_targets')
    op.drop_index('ix_coaching_org_status', table_name='coaching_actions')
    op.drop_table('coaching_actions')
    op.drop_index(op.f('ix_accounts_public_ref'), table_name='accounts')
    op.drop_index('ix_accounts_org_owner', table_name='accounts')
    op.drop_table('accounts')
    op.drop_table('challenges')
