"""根据预处理后的分块构建向量存储行。"""
from ..domain.policies import document_title


def build_vector_rows(chunks, search_texts, dense_vectors, sparse_vectors,
                      document_id: str, source):
    title = document_title(source.title, source.filename or "未命名")
    rows = []
    for index, chunk in enumerate(chunks):
        row = {
            "chunk_id": f"{document_id}:{index}",
            "text": chunk.text, "search_text": search_texts[index],
            "dense": dense_vectors[index], "document_id": document_id,
            "title": title, "source": title, "page": chunk.page,
            "page_end": chunk.page_end, "kind": chunk.kind,
            "section_path": list(chunk.section_path),
            "chunk_role": chunk.metadata.get("chunk_role", chunk.kind),
            "continuation": chunk.continuation,
            "continuation_of": chunk.continuation_of,
            "continuation_index": chunk.continuation_index,
        }
        if sparse_vectors is not None:
            row["sparse"] = sparse_vectors[index]
        row.update(chunk.metadata)
        rows.append(row)
    return rows
