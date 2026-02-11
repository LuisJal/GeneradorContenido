from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.models.bot import Bot  # noqa: E402, F401
from app.models.content import ContentItem  # noqa: E402, F401
from app.models.credential import SocialCredential  # noqa: E402, F401
from app.models.log_entry import PipelineLog  # noqa: E402, F401
