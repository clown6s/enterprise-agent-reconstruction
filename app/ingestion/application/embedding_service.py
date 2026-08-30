"""嵌入编排与响应验证."""


def build_search_text(chunk) -> str:
    context = " > ".join(chunk.section_path)
    metadata = chunk.metadata
    if metadata.get("category"):
        context = f"{context} > {metadata['category']}" if context else metadata["category"]
    if metadata.get("question_number") is not None:
        context = (f"{context} > 问题 {metadata['question_number']}"
                   if context else f"问题 {metadata['question_number']}")
    return f"上下文：{context}\n{chunk.text}" if context else chunk.text


class EmbeddingService:
    def __init__(self, embedder, embedding_dim=None):
        self.embedder = embedder
        self.embedding_dim = embedding_dim

    def embed(self, chunks):
        texts = [build_search_text(chunk) for chunk in chunks]
        dense = self.embedder.embed_batch(texts)
        if not isinstance(dense, list) or len(dense) != len(chunks):
            raise ValueError("dense embedding 数量必须与 chunk 数量一致")
        if any(not isinstance(vector, (list, tuple)) or not vector for vector in dense):
            raise ValueError("dense embedding 向量格式无效")
        if self.embedding_dim is not None and any(
            len(vector) != self.embedding_dim for vector in dense
        ):
            raise ValueError(f"dense embedding 维度必须为 {self.embedding_dim}")
        return texts, dense
