"""
JAI puts a workspace's images and videos on Richard's screen as themselves (not their bytes as text): one file as a
picture or a player, a folder as a gallery of its images and videos (subfolders too, newest first), each through a
short-lived link served with its real media type and only from inside the workspaces.
"""
import asyncio
import os
import time

from app.core.voice import live
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12c_agent_tools import _seed, project  # noqa: F401 - project is a fixture

PNG = b"\x89PNG\r\n\x1a\n" + b"plexecute" * 40
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 400


def _run(coro):
    return asyncio.run(coro)


def test_an_image_a_video_and_a_folder_go_on_screen_as_media(project, client):
    root_host, root, _ = project
    (root / "images").mkdir()
    (root / "images" / "jai-test-image.png").write_bytes(PNG)
    (root / "videos").mkdir()
    (root / "videos" / "launch.mp4").write_bytes(MP4)
    later = time.time() + 5
    os.utime(root / "videos" / "launch.mp4", (later, later))

    async def show(path):
        async with AsyncTestingSessionLocal() as db:
            user_id, _ = await _seed(db, root_host)
            return await live.run_tool(db, user_id, "show_on_screen", {"what": "file", "workspace": "R12c",
                                                                        "path": path})

    image = _run(show("images/jai-test-image.png"))["card"]
    assert image["kind"] == "image" and image["sections"][0]["image"].startswith("/api/backend/api/voice/image/")
    assert "code" not in image["sections"][0]                       # never its bytes as text
    served = client.get(image["sections"][0]["image"].replace("/api/backend", ""))
    assert served.status_code == 200 and served.headers["content-type"] == "image/png" and served.content == PNG

    video = _run(show("videos/launch.mp4"))["card"]
    assert video["kind"] == "video"
    played = client.get(video["sections"][0]["video"].replace("/api/backend", ""))
    assert played.status_code == 200 and played.headers["content-type"] == "video/mp4"

    gallery = _run(show(""))["card"]
    assert gallery["kind"] == "gallery"
    assert [s["heading"] for s in gallery["sections"]] == ["videos/launch.mp4", "images/jai-test-image.png"]
    assert "video" in gallery["sections"][0] and "image" in gallery["sections"][1]

    text = _run(show("src/app.py"))["card"]                         # a text file is still shown as text
    assert text["kind"] == "file" and "def add" in text["sections"][0]["code"]
    assert "error" in _run(show("../outside.png"))


PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n" + b"\x00" * 200 + b"\n%%EOF\n"


def test_a_pdf_goes_on_screen_as_the_document_and_stays_out_of_galleries(project, client):
    """9 November: the pitch deck PDF came up on screen as its source bytes."""
    root_host, root, _ = project
    (root / "pitch-deck").mkdir()
    (root / "pitch-deck" / "deck.pdf").write_bytes(PDF)
    (root / "pitch-deck" / "cover.png").write_bytes(PNG)

    async def show(path):
        async with AsyncTestingSessionLocal() as db:
            user_id, _ = await _seed(db, root_host)
            return await live.run_tool(db, user_id, "show_on_screen", {"what": "file", "workspace": "R12c",
                                                                        "path": path})

    deck = _run(show("pitch-deck/deck.pdf"))["card"]
    assert deck["kind"] == "pdf" and deck["sections"][0]["pdf"].startswith("/api/backend/api/voice/image/")
    assert "code" not in deck["sections"][0]
    served = client.get(deck["sections"][0]["pdf"].replace("/api/backend", ""))
    assert served.status_code == 200 and served.headers["content-type"] == "application/pdf" and served.content == PDF
    gallery = _run(show("pitch-deck"))["card"]
    assert [s["heading"] for s in gallery["sections"]] == ["cover.png"]


def _xlsx(path):
    import zipfile

    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("xl/workbook.xml", f'<workbook xmlns="{main}" xmlns:r="http://schemas.openxmlformats.org/'
                                         'officeDocument/2006/relationships"><sheets><sheet name="Investors" '
                                         'sheetId="1" r:id="rId1"/></sheets></workbook>')
        book.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                                                    '2006/relationships"><Relationship Id="rId1" Type="x" '
                                                    'Target="worksheets/sheet1.xml"/></Relationships>')
        book.writestr("xl/sharedStrings.xml", f'<sst xmlns="{main}"><si><t>Firm</t></si><si><t>Source</t></si>'
                                              '<si><t>Seedcamp</t></si></sst>')
        book.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{main}"><sheetData><row r="1"><c r="A1" t="s">'
                                                  '<v>0</v></c><c r="B1" t="s"><v>1</v></c></row><row r="2"><c r="A2" '
                                                  't="s"><v>2</v></c><c r="B2" t="inlineStr"><is><t>seedcamp.com</t>'
                                                  '</is></c></row></sheetData></worksheet>')


def test_a_spreadsheet_goes_on_screen_as_a_table_and_a_word_file_as_a_note(project):
    """9 November: the prospects spreadsheet came up on screen as the bytes of its zip."""
    root_host, root, _ = project
    (root / "outreach").mkdir()
    _xlsx(root / "outreach" / "prospects.xlsx")
    (root / "outreach" / "list.csv").write_text("Firm,Source\nAtomico,atomico.com\n")
    (root / "outreach" / "letter.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 100)

    async def show(path):
        async with AsyncTestingSessionLocal() as db:
            user_id, _ = await _seed(db, root_host)
            return await live.run_tool(db, user_id, "show_on_screen", {"what": "file", "workspace": "R12c",
                                                                        "path": path})

    table = _run(show("outreach/prospects.xlsx"))["card"]
    assert table["kind"] == "table" and table["sections"][0]["columns"] == ["Firm", "Source"]
    assert table["sections"][0]["rows"] == [["Seedcamp", "seedcamp.com"]]
    csv_table = _run(show("outreach/list.csv"))["card"]
    assert csv_table["sections"][0]["rows"] == [["Atomico", "atomico.com"]]
    note = _run(show("outreach/letter.docx"))["card"]
    assert note["kind"] == "file" and "Word document" in note["sections"][0]["items"][0]
    assert "code" not in note["sections"][0]
