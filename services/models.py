from dataclasses import dataclass


@dataclass
class Track:
    title: str
    url: str
    duration: int = 0
    thumbnail: str = ""
    requested_by: int = 0
    requested_name: str = ""
    # "youtube" (anything yt-dlp can open) | "saavn" | "file" (Telegram file) | "query" (resolved when played)
    source: str = "youtube"
    stream_url: str = ""  # direct audio URL (JioSaavn) or local path (Telegram file)
    video: bool = False  # play as video in the video chat

    @staticmethod
    def source_for(url: str) -> str:
        if url.startswith("saavn:"):
            return "saavn"
        if url.startswith("search:"):
            return "query"
        return "youtube"
