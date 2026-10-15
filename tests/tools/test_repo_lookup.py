import json

from chronology.tools.repo_lookup import KNOWLEDGE_DIR


def test_knowledge_files_parse():
    for path in KNOWLEDGE_DIR.rglob("*.json"):
        json.loads(path.read_text())
