"""Tests rapides : python -m pytest tests (ou python tests/test_agenda.py)"""
import sys, tempfile
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import agenda

FIX = Path(__file__).parent / "fixtures"

def test_parse_fr():
    evs = agenda.scrape("fr", FIX)
    assert len(evs) == 30
    expo = next(e for e in evs if "Aurélie" in e.title)
    assert expo.all_day and expo.multi_day and expo.start.startswith("2026-10-05")
    baby = next(e for e in evs if e.title == "Babycafé jeux sensoriels")
    assert baby.start == "2026-10-15T10:00:00" and baby.end == "2026-10-15T12:00:00"

def test_parse_nl_single_hour():
    evs = agenda.scrape("nl", FIX)
    e = next(e for e in evs if e.title.startswith("Herfstfestijn"))
    assert e.start == "2026-11-21T18:00:00" and e.end is None

def test_window_thursday():
    assert agenda.window_for(date(2026, 10, 15)) == (date(2026, 10, 15), date(2026, 10, 24))
    assert agenda.window_for(date(2026, 10, 18)) == (date(2026, 10, 15), date(2026, 10, 24))

def test_full_run_and_history():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        assert agenda.main(["--fixtures", str(FIX), "--today", "2026-10-15", "--out", d]) == 0
        for f in ["agenda-fr.ics", "agenda-nl.ics", "index.html", "nl.html", "whatsapp.html",
                  "whatsapp-fr.txt", "whatsapp-nl.txt"]:
            assert (out / f).exists(), f
        # une seconde exécution plus tard garde les activités passées
        assert agenda.main(["--fixtures", str(FIX), "--today", "2026-12-01", "--out", d]) == 0
        assert (out / "agenda-fr.ics").read_text().count("BEGIN:VEVENT") == 30

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
