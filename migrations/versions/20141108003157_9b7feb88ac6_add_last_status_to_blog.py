"""Add last status to blog

Revision ID: 9b7feb88ac6
Revises: 1c915a042c5f
Create Date: 2014-11-08 00:31:57.191657

"""

# revision identifiers, used by Alembic.
revision = '9b7feb88ac6'
down_revision = '1c915a042c5f'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('blog', sa.Column('last_status', sa.Boolean(), nullable=True))
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('blog', 'last_status')
    ### end Alembic commands ###