from dataclasses import dataclass
from typing import Optional


@dataclass
class MeetingDocument:

    agency: str = ""

    document_type: str = ""

    number: str = ""

    title: str = ""

    downloaded: bool = False

    local_path: str = ""

    # Which AgendaItem (ND) this document was referenced under in the
    # invitation text, matched against AgendaItem.index — None if the
    # document's number never occurs in the invitation text at all (so
    # its ND block couldn't be determined; see
    # MeetingParserAgent._assign_agenda_item_indices).
    agenda_item_index: Optional[int] = None