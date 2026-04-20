
from dataclasses import dataclass, field
from typing import List


@dataclass
class QuestionItem:
    subject: str
    qtype: str = "single"
    question: str = ""
    options: List[str] = field(default_factory=list)      # single: len=4
    correct: List[str] = field(default_factory=list)      # single: e.g. ["2"]
    explanation: str = ""
    needs_review: bool = False
    source: str = ""  # generate / import / local
