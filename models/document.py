from dataclasses import dataclass


@dataclass
class MeetingDocument:

    agency: str = ""

    document_type: str = ""

    number: str = ""

    title: str = ""

    downloaded: bool = False

    local_path: str = ""