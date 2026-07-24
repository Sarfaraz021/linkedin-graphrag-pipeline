"""Record-count text splitter for neo4j-graphrag."""

from __future__ import annotations

from neo4j_graphrag.experimental.components.text_splitters.base import TextSplitter
from neo4j_graphrag.experimental.components.types import TextChunk, TextChunks

from src.backbone import RECORD_SEPARATOR


class RecordCountSplitter(TextSplitter):
    """Group fixed-size record blocks into chunks with record overlap."""

    def __init__(
        self,
        chunk_records: int = 30,
        chunk_overlap: int = 5,
        record_separator: str = RECORD_SEPARATOR,
    ) -> None:
        if chunk_overlap >= chunk_records:
            raise ValueError("chunk_overlap must be smaller than chunk_records")
        self.chunk_records = chunk_records
        self.chunk_overlap = chunk_overlap
        self.record_separator = record_separator

    def split_records(self, records: list[str], post_id: str = "") -> TextChunks:
        if not records:
            return TextChunks(chunks=[])

        chunks: list[TextChunk] = []
        step = self.chunk_records - self.chunk_overlap
        index = 0
        chunk_index = 0

        while index < len(records):
            window = records[index : index + self.chunk_records]
            prefix = f"[postId={post_id}] Extract entities from the following records.\n"
            chunk_text = prefix + self.record_separator.join(window)
            chunks.append(
                TextChunk(
                    text=chunk_text,
                    index=chunk_index,
                    metadata={
                        "postId": post_id,
                        "recordStart": index,
                        "recordCount": len(window),
                    },
                )
            )
            chunk_index += 1
            if index + self.chunk_records >= len(records):
                break
            index += step

        return TextChunks(chunks=chunks)

    async def run(self, text: str) -> TextChunks:
        post_id = ""
        if text.startswith("[postId="):
            first_line, _, remainder = text.partition("\n")
            if first_line.endswith("]"):
                post_id = first_line[len("[postId=") : -1]
            text = remainder
        records = [r.strip() for r in text.split(self.record_separator) if r.strip()]
        return self.split_records(records, post_id=post_id)
