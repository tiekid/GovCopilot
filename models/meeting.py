from dataclasses import dataclass, field
from typing import List


@dataclass
class AgendaItem:
    """Một nội dung họp."""

    index: int
    agency: str
    title: str


@dataclass
class Meeting:

    # Thông tin chung
    meeting_name: str = ""
    meeting_date: str = ""
    meeting_time: str = ""
    chairman: str = ""
    location: str = ""
    participants: str = ""

    # Nội dung
    agenda: List[AgendaItem] = field(default_factory=list)