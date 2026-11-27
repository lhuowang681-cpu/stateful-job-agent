"""Optional legacy FAISS lane: Unicode paths and unchanged binary format."""
from io import BytesIO
import pytest
faiss=pytest.importorskip('faiss',reason='requires explicitly installed career-knowledge optional dependency')
from job_agent.knowledge.faiss_vector_index import FAISSVectorIndex
from test_knowledge_faiss_vector_index import _chunks,_vectors


def test_unicode_directory_roundtrip_preserves_rankings_and_dimension_guards(tmp_path):
    index=FAISSVectorIndex();index.add(chunks=_chunks(),vectors=_vectors())
    path=tmp_path/'学习索引'/'真实格式.faiss';path.parent.mkdir()
    index.save(path)
    loaded=FAISSVectorIndex.load(path,chunks=_chunks(),expected_dimension=2)
    assert [h.chunk.chunk_id for h in loaded.search(query_vector=[1.,0.],limit=3)]==['A','B','C']
    with pytest.raises(ValueError,match='dimension'):FAISSVectorIndex.load(path,chunks=_chunks(),expected_dimension=3)
    with pytest.raises(ValueError,match='count'):FAISSVectorIndex.load(path,chunks=_chunks()[:1])


def test_native_faiss_stream_format_remains_readable_in_unicode_location(tmp_path):
    index=FAISSVectorIndex();index.add(chunks=_chunks(),vectors=_vectors())
    buffer=BytesIO();faiss.write_index(index._index,faiss.PyCallbackIOWriter(buffer.write))
    path=tmp_path/'旧版索引.faiss';path.write_bytes(buffer.getvalue())
    loaded=FAISSVectorIndex.load(path,chunks=_chunks(),expected_dimension=2)
    new=tmp_path/'新版索引.faiss';loaded.save(new)
    assert new.read_bytes()==buffer.getvalue()
