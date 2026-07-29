from pathlib import Path

from coptertime_docs.storage.database import Database


def test_term_and_memory(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.upsert_term("QYSEA", "Thruster", "Движитель")
    terms = database.search_terms("Thruster", "QYSEA")
    assert terms[0]["target_text"] == "Движитель"

    database.memory_put("Power button", "Кнопка питания")
    assert database.memory_get("Power button") == "Кнопка питания"
