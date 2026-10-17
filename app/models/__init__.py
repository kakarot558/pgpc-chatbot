"""Import every model so Base.metadata (used by Alembic) knows all tables."""
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.employee import Employee
from app.models.facility import Facility
from app.models.faq import FAQ
from app.models.handbook import HandbookSection
from app.models.history import SchoolHistory
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.library import LibraryBook
from app.models.office import Office
from app.models.position import Position
from app.models.quick_link import QuickLink
from app.models.room import Room
from app.models.user import User

__all__ = [
    "ChatMessage", "ChatSession", "Document", "Employee", "Facility", "FAQ",
    "HandbookSection", "SchoolHistory", "KnowledgeChunk", "LibraryBook",
    "Office", "Position", "QuickLink", "Room", "User",
]
