from qnuchat.core.config import CorpusConfig, EmbeddingConfig, SourceConfig
from qnuchat.core.snapshot import build_snapshot
from qnuchat.documents import Passage

EMBEDDING = EmbeddingConfig(
    model="BAAI/bge-m3", revision="5617a9f61b028005a4858fdac845db406aefb181"
)
PASSAGES = [
    Passage("a:p004", "a", 4, "văn bản một", 2025),
    Passage("a:p005", "a", 5, "văn bản hai", 2025),
]


def corpus(path, excluded=(3, 1), source_id="a"):
    source = SourceConfig(
        source_id=source_id, path=str(path), excluded_pages=list(excluded), source_year=2025
    )
    return CorpusConfig(sources=[source], max_chunk_chars=1500)


def snapshot(tmp_path, pdf=b"%PDF-1", passages=PASSAGES, excluded=(3, 1), embedding=EMBEDDING):
    path = tmp_path / "corpus.pdf"
    path.write_bytes(pdf)
    return build_snapshot(corpus=corpus(path, excluded), embedding=embedding, passages=passages)


def test_snapshot_is_deterministic(tmp_path):
    assert snapshot(tmp_path) == snapshot(tmp_path)


def test_snapshot_id_is_a_prefix_of_the_content_hash(tmp_path):
    snap = snapshot(tmp_path)
    assert snap.content_hash.startswith(snap.id) and len(snap.content_hash) == 64


def test_snapshot_changes_when_chunk_text_changes(tmp_path):
    changed = [PASSAGES[0], Passage("a:p005", "a", 5, "văn bản KHÁC", 2025)]
    assert snapshot(tmp_path).content_hash != snapshot(tmp_path, passages=changed).content_hash


def test_snapshot_changes_when_the_source_file_changes(tmp_path):
    assert snapshot(tmp_path).content_hash != snapshot(tmp_path, pdf=b"%PDF-2").content_hash


def test_snapshot_ignores_excluded_page_order(tmp_path):
    other = snapshot(tmp_path, excluded=(1, 3))
    assert snapshot(tmp_path).content_hash == other.content_hash


def test_snapshot_covers_every_source(tmp_path):
    first, second = tmp_path / "a.pdf", tmp_path / "b.pdf"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    one = corpus(first)
    two = one.model_copy(
        update={"sources": [*one.sources, corpus(second, source_id="b").sources[0]]}
    )
    build = lambda c: build_snapshot(corpus=c, embedding=EMBEDDING, passages=PASSAGES)
    assert build(one).content_hash != build(two).content_hash


def test_vector_hash_tracks_the_embedding_only(tmp_path):
    a = snapshot(tmp_path)
    b = snapshot(tmp_path, embedding=EmbeddingConfig(model="BAAI/bge-m3", revision="a" * 40))
    assert a.content_hash == b.content_hash
    assert a.vector_hash != b.vector_hash
