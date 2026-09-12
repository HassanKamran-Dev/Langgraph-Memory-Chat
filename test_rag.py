import os
import io
import json
import asyncio
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject

def create_sample_pdf() -> bytes:
    writer = PdfWriter()
    
    # Page 1: Overview and Specs
    page1 = writer.add_blank_page(width=400, height=500)
    stream1 = DecodedStreamObject()
    content1 = (
        b"BT /F1 12 Tf 50 450 Td (QuantumFlux Engine Specifications) Tj "
        b"0 -25 Td (The QuantumFlux Mk IV delivers 4,200 Terawatts of clean plasma energy.) Tj "
        b"0 -25 Td (Operational temperature must be maintained between 120 Kelvin and 340 Kelvin.) Tj ET"
    )
    stream1.set_data(content1)
    page1[NameObject("/Contents")] = stream1

    # Page 2: Troubleshooting and Error Codes
    page2 = writer.add_blank_page(width=400, height=500)
    stream2 = DecodedStreamObject()
    content2 = (
        b"BT /F1 12 Tf 50 450 Td (Section 4: Diagnostic Error Codes) Tj "
        b"0 -25 Td (Error Code ERR-8819 indicates Critical Coolant Depletion in Sector 4.) Tj "
        b"0 -25 Td (To resolve ERR-8819, immediately initiate the manual helium bypass valve.) Tj ET"
    )
    stream2.set_data(content2)
    page2[NameObject("/Contents")] = stream2

    # Add standard font dictionary to both pages
    for p in [page1, page2]:
        resources = DictionaryObject()
        fonts = DictionaryObject()
        f1 = DictionaryObject()
        f1[NameObject("/Type")] = NameObject("/Font")
        f1[NameObject("/Subtype")] = NameObject("/Type1")
        f1[NameObject("/BaseFont")] = NameObject("/Helvetica")
        fonts[NameObject("/F1")] = f1
        resources[NameObject("/Font")] = fonts
        p[NameObject("/Resources")] = resources

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def run_tests():
    from server import app
    client = TestClient(app)

    print("=== Step 1: Health & Status Check ===")
    status_res = client.get("/api/status")
    print("Status response:", status_res.status_code, status_res.json())
    assert status_res.status_code == 200
    assert status_res.json()["backend_ready"] is True
    print("[OK] Backend status OK\n")

    print("=== Step 2: Upload Sample PDF ===")
    thread_id = "test_verification_thread"
    pdf_bytes = create_sample_pdf()

    files = {"file": ("quantumflux_manual.pdf", pdf_bytes, "application/pdf")}
    data = {"thread_id": thread_id}
    upload_res = client.post("/api/upload", files=files, data=data)
    print("Upload response:", upload_res.status_code, upload_res.json())
    assert upload_res.status_code == 200
    upload_json = upload_res.json()
    assert upload_json["filename"] == "quantumflux_manual.pdf"
    assert upload_json["pages"] == 2
    assert upload_json["chunks"] >= 2
    print("[OK] PDF upload and indexing OK\n")

    print("=== Step 3: Verify Documents Endpoint ===")
    docs_res = client.get(f"/api/documents?thread_id={thread_id}")
    print("Documents list:", docs_res.json())
    assert docs_res.status_code == 200
    docs_list = docs_res.json()["documents"]
    assert any(d["filename"] == "quantumflux_manual.pdf" for d in docs_list)
    print("[OK] Document listing endpoint OK\n")

    print("=== Step 4: Ask Question via Chat Stream Endpoint ===")
    question = "What does error code ERR-8819 indicate, and how should it be resolved? Cite the page."
    chat_payload = {"message": question, "thread_id": thread_id}

    with client.stream("POST", "/api/chat/stream", json=chat_payload) as stream_res:
        assert stream_res.status_code == 200
        tokens = []
        statuses = []
        for line in stream_res.iter_lines():
            if line.startswith("data: "):
                event_data = json.loads(line[6:])
                if event_data.get("type") == "token":
                    tokens.append(event_data.get("content", ""))
                elif event_data.get("type") == "status":
                    statuses.append(event_data.get("content", ""))
                elif event_data.get("type") == "error":
                    print("Stream error:", event_data)

        full_answer = "".join(tokens)
        print("Emitted Status events:", statuses)
        # Use ascii safe representation for printing
        safe_answer = full_answer.encode("ascii", errors="backslashreplace").decode("ascii")
        print("Full Answer:\n", safe_answer)

        assert len(full_answer) > 0, "No answer returned!"
        assert "ERR-8819" in full_answer or "8819" in full_answer or "Coolant" in full_answer or "bypass" in full_answer
        print("[OK] Model successfully retrieved and answered from PDF content!\n")

    print("=== Step 5: Clean Up & Delete Document ===")
    del_res = client.delete(f"/api/documents/quantumflux_manual.pdf?thread_id={thread_id}")
    print("Delete response:", del_res.json())
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    verify_empty = client.get(f"/api/documents?thread_id={thread_id}").json()
    assert len(verify_empty["documents"]) == 0
    print("[OK] Document deletion verified OK\n")

    print("ALL TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    run_tests()
