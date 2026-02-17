# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Knowledge graph — document indexing, entity extraction, contradiction detection."""
from .store import KnowledgeStore, get_store
from .extract import extract_from_markdown
from .validate import validate_corpus
