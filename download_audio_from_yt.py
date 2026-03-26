# /// script
# dependencies = [
#   "yt-dlp",
# ]
# ///

import os
import yt_dlp
import sys


def download_audio(url):
    output_dir = "mp3"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    ydl_opts = {
        "format": "bestaudio/best",
        # This line tells yt-dlp to save into the mp3/ folder
        "outtmpl": f"{output_dir}/%(title)s.%(ext)s",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        # Avoid 403 errors by using browser-like headers
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"Downloading to the '{output_dir}' folder...")
            ydl.download([url])
            print(f"\nSuccess! Check your '{output_dir}' directory.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run download_audio_from_yt.py <YOUTUBE_URL>")
    else:
        video_url = sys.argv[1]
        download_audio(video_url)
