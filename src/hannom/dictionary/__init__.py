"""Optional dictionary adapters and per-book lexicon."""

from .book_lexicon import BookLexicon, qn_syllables, strip_diacritics
from .index import DictionaryIndex, LookupResult, Sense, build_dictionary_index

__all__ = [
    "BookLexicon",
    "DictionaryIndex",
    "LookupResult",
    "Sense",
    "build_dictionary_index",
    "qn_syllables",
    "strip_diacritics",
]
