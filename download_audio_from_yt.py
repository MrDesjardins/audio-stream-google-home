# /// script
# dependencies = [
#   "yt-dlp",
# ]
# ///

import os
import sys
import yt_dlp


def _ydl_opts(output_dir: str, playlist: bool) -> dict:
    return {
        "format": "bestaudio/best",
        "outtmpl": f"{output_dir}/%(title)s.%(ext)s",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "noplaylist": not playlist,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }


def download_audio(url: str, output_dir: str = "mp3", *, playlist: bool = False) -> list[str]:
    """Download audio from a YouTube URL as MP3. Returns paths to new files."""
    os.makedirs(output_dir, exist_ok=True)
    before = {f for f in os.listdir(output_dir) if f.lower().endswith(".mp3")}

    ydl_opts = _ydl_opts(output_dir, playlist)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        print(f"Downloading to '{output_dir}'...")
        ydl.download([url])

    after = {f for f in os.listdir(output_dir) if f.lower().endswith(".mp3")}
    new_files = sorted(after - before)
    if new_files:
        print(f"Downloaded {len(new_files)} file(s).")
    else:
        print("No new MP3 files were created.")
    return [os.path.join(output_dir, f) for f in new_files]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run download_audio_from_yt.py <YOUTUBE_URL> [output_dir]")
        sys.exit(1)

    video_url = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "mp3"
    try:
        download_audio(video_url, out_dir)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
