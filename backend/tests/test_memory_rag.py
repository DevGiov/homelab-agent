"""Test unitari per vector store e knowledge base (Fase 2). Usa DB temporaneo isolato."""
import os
import tempfile
import unittest


# Isola il DB in un file temporaneo PRIMA di importare i moduli che lo usano
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_checkpoints.db")
os.environ["CHECKPOINT_DB_PATH"] = _tmp_db

import vector_store
from knowledge_base import _chunk_text, delete_document, ingest_document, list_documents, search_knowledge


class TestVectorStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        vector_store.init_vector_db()

    def test_add_and_search(self):
        rid = vector_store.add_memory(
            "L'utente preferisce Debian 12 per i container LXC", kind="fact", thread_id="vs_test"
        )
        self.assertIsNotNone(rid)
        results = vector_store.search_memory("che distribuzione linux usa?", k=1)
        self.assertGreater(len(results), 0)
        self.assertIn("Debian", results[0]["content"])

    def test_search_with_kind_filter(self):
        vector_store.add_memory("fatto generico di test", kind="fact", thread_id="vs_test")
        res = vector_store.search_memory("fatto generico", k=5, kind="kb")
        for r in res:
            self.assertEqual(r["kind"], "kb")

    def test_delete_thread_memory(self):
        vector_store.add_memory("memo da cancellare xyz", kind="fact", thread_id="vs_del")
        deleted = vector_store.delete_thread_memory("vs_del")
        self.assertGreaterEqual(deleted, 1)
        res = vector_store.search_memory("memo da cancellare", k=10, thread_id="vs_del")
        self.assertEqual(len(res), 0)


class TestChunking(unittest.TestCase):
    def test_short_text_single_chunk(self):
        chunks = _chunk_text("Testo breve di prova.")
        self.assertEqual(len(chunks), 1)

    def test_long_text_multiple_chunks(self):
        text = "\n\n".join([f"Paragrafo {i} " + "x" * 200 for i in range(10)])
        chunks = _chunk_text(text)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 1000)  # margine overlap

    def test_empty_chunks_filtered(self):
        chunks = _chunk_text("Paragrafo valido.\n\n   \n\nAltro paragrafo.")
        self.assertTrue(all(len(c) > 30 for c in chunks))


class TestKnowledgeBase(unittest.TestCase):
    """Ogni test crea il proprio documento con nome univoco (unittest ordina alfabeticamente)."""

    DOC_CONTENT = (
        "# Guida Test\n\n"
        "## Backup\n"
        "Per fare il backup usare vzdump con compressione zstd sullo storage nas-backup.\n\n"
        "## Rete\n"
        "La VLAN management è la 10 con subnet 192.168.10.0/24.\n"
        "Il gateway è 192.168.10.1."
    )

    def test_ingest_stats(self):
        stats = ingest_document("test_kb_ingest.md", text_content=self.DOC_CONTENT)
        self.assertEqual(stats["filename"], "test_kb_ingest.md")
        self.assertGreaterEqual(stats["chunks_indexed"], 1)

    def test_search_finds_relevant(self):
        ingest_document("test_kb_search.md", text_content=self.DOC_CONTENT)
        res = search_knowledge("come si fa il backup con vzdump?", k=3)
        self.assertGreater(len(res), 0)
        self.assertEqual(res[0]["filename"], "test_kb_search.md")

    def test_list_documents(self):
        ingest_document("test_kb_list.md", text_content=self.DOC_CONTENT)
        docs = list_documents()
        names = [d["filename"] for d in docs]
        self.assertIn("test_kb_list.md", names)

    def test_delete_document(self):
        ingest_document("test_kb_delete.md", text_content=self.DOC_CONTENT)
        deleted = delete_document("test_kb_delete.md")
        self.assertGreaterEqual(deleted, 1)
        docs = list_documents()
        self.assertNotIn("test_kb_delete.md", [d["filename"] for d in docs])


if __name__ == "__main__":
    unittest.main()


def test_dockerfile_bundles_the_configured_embedding_model():
    """Il modello pre-scaricato nell'immagine deve essere quello usato da vector_store."""
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text(encoding="utf-8")
    assert f"TextEmbedding('{vector_store.EMBEDDING_MODEL}')" in dockerfile
