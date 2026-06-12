# /// script
# dependencies = [
#   "yt-dlp",
# ]
# ///

"""Download YouTube audio and upload MP3s to the remote audiobook server."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from download_audio_from_yt import download_audio

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_REMOTE_HOST = "10.0.0.181"
DEFAULT_REMOTE_USER = "pdesjardins"
DEFAULT_REMOTE_ENV = f"/home/{DEFAULT_REMOTE_USER}/code/audio-stream-google-home/.env"


@dataclass(frozen=True)
class Track:
    category: str
    title: str
    url: str
    playlist: bool = False


TRACKS: list[Track] = [
    # Anazala family
    Track("Anazala family", "My Daughter's First Sleepover in the New House", "https://www.youtube.com/watch?v=KqquITBkCBE"),
    Track("Anazala family", "I Let My Kids Build their Own Rooms", "https://www.youtube.com/watch?v=_-Ch3AQXuMs"),
    Track("Anazala family", "We Got LOCKED OUT of our House", "https://www.youtube.com/watch?v=FEkHkrwXsNM"),
    Track("Anazala family", "I Let Ages 1-18 Plan My Date Night ALONE", "https://www.youtube.com/watch?v=0oOqFhrlpTw"),
    # Jordan Matter
    Track("Jordan Matter", "Building CRAZY Water Attractions at Home", "https://www.youtube.com/watch?v=PnECVyWkRHY"),
    Track("Jordan Matter", "My Daughter Survives WORLD'S STRICTEST PARENTS", "https://www.youtube.com/watch?v=ilvh7PShS9c"),
    Track("Jordan Matter", "My Daughter Survives WORLD'S TINIEST BEDROOM", "https://www.youtube.com/watch?v=HK2QdT85a7k"),
    Track("Jordan Matter", "My Daughter Survives WORLD'S TINIEST HOUSE", "https://www.youtube.com/watch?v=9F3n_qdhlRU"),
    Track("Jordan Matter", "How Long Can I Secretly Live in a Celebrity Mansion", "https://www.youtube.com/watch?v=-LooUJlcdjU"),
    Track("Jordan Matter", "My Daughter's Phone Was Stolen", "https://www.youtube.com/watch?v=NcG3QyyOhck"),
    Track("Jordan Matter", "MY DAUGHTER AGES 1-50", "https://www.youtube.com/watch?v=RGj1E_HSwEA"),
    Track("Jordan Matter", "Surprising My Daughter with a DREAM VACATION", "https://www.youtube.com/watch?v=QaF1r2qdV_E"),
    # Audiobook
    Track(
        "Audiobook",
        "Diary of a Wimpy Kid #15 - The Deep End",
        "https://www.youtube.com/watch?v=m-GOhkqhge4",
    ),
    Track(
        "Audiobook",
        "Diary of a Wimpy Kid 2 - Rodrick Rules",
        "https://www.youtube.com/watch?v=E9aJhQttZR4",
    ),
    Track("Audiobook", "The BAD SEED Books read aloud", "https://www.youtube.com/watch?v=RzpdVrQ4-Nk"),
    Track("Audiobook", "THE GOOD EGG books read aloud", "https://www.youtube.com/watch?v=spHZSpoyYCs"),
    Track("Audiobook", "The Sour Grape Kids Books Read Aloud", "https://www.youtube.com/watch?v=trhqfW4d3uk"),
    Track("Audiobook", "What Should Danny Do On Vacation", "https://www.youtube.com/watch?v=aWLberjYzfc"),
    Track("Audiobook", "What Should Danny Do", "https://www.youtube.com/watch?v=Cno-61jwbf4"),
    Track("Audiobook", "What Should Danny Do School Day", "https://www.youtube.com/watch?v=8_lpP-u2Zbs"),
    # Songs
    Track("Songs", "Top Christmas Songs of All Time", "https://www.youtube.com/watch?v=lPArG5w-svY"),
    Track("Songs", "1 Hour Upbeat Background Music", "https://www.youtube.com/watch?v=DC7Y6sC7Ae4"),
    Track("Songs", "Cozy Library Coffee Shop Lofi", "https://www.youtube.com/watch?v=Y9mRoCerrpY"),
    # Background noises
    Track("Background noises", "Relaxing Music - Flute, Gentle Birds and Rainforest", "https://www.youtube.com/watch?v=zQtfnPTlFFE"),
    Track("Background noises", "Ocean Waves, Sea Sounds", "https://www.youtube.com/watch?v=hw32XIVdHCU"),
]


def load_local_mp3_folder() -> Path:
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("AB_MP3_FOLDER=") and not line.startswith("#"):
                return Path(line.split("=", 1)[1].strip())
    return REPO_ROOT / "mp3"


def fetch_remote_mp3_folder(host: str, user: str, remote_env: str) -> str:
    cmd = [
        "ssh",
        f"{user}@{host}",
        f"grep '^AB_MP3_FOLDER=' {remote_env} | cut -d= -f2-",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    remote_path = result.stdout.strip()
    if not remote_path:
        raise RuntimeError(f"AB_MP3_FOLDER not found in {user}@{host}:{remote_env}")
    return remote_path


def upload_mp3s(local_dir: Path, host: str, user: str, remote_dir: str) -> None:
    dest = f"{user}@{host}:{remote_dir.rstrip('/')}/"
    cmd = [
        "rsync",
        "-avz",
        "--progress",
        "--include=*.mp3",
        "--include=*.MP3",
        "--exclude=*",
        f"{local_dir}/",
        dest,
    ]
    print(f"\nUploading MP3s to {dest}")
    subprocess.run(cmd, check=True)


def download_all(tracks: list[Track], output_dir: Path) -> list[str]:
    downloaded: list[str] = []
    for i, track in enumerate(tracks, 1):
        print(f"\n[{i}/{len(tracks)}] {track.category} — {track.title}")
        print(f"  {track.url}")
        try:
            files = download_audio(track.url, str(output_dir), playlist=track.playlist)
            downloaded.extend(files)
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
    return downloaded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_REMOTE_HOST)
    parser.add_argument("--user", default=DEFAULT_REMOTE_USER)
    parser.add_argument("--remote-env", default=DEFAULT_REMOTE_ENV)
    parser.add_argument("--output-dir", type=Path, default=None, help="Local MP3 folder (default: AB_MP3_FOLDER from .env)")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--upload-only", action="store_true")
    parser.add_argument("--category", action="append", help="Only process tracks in this category (repeatable)")
    args = parser.parse_args()

    output_dir = args.output_dir or load_local_mp3_folder()
    output_dir.mkdir(parents=True, exist_ok=True)

    tracks = TRACKS
    if args.category:
        categories = {c.lower() for c in args.category}
        tracks = [t for t in tracks if t.category.lower() in categories]
        if not tracks:
            print(f"No tracks matched categories: {args.category}", file=sys.stderr)
            return 1

    if not args.upload_only:
        print(f"Downloading {len(tracks)} track(s) to {output_dir}")
        download_all(tracks, output_dir)

    if not args.download_only:
        remote_dir = fetch_remote_mp3_folder(args.host, args.user, args.remote_env)
        print(f"Remote AB_MP3_FOLDER: {remote_dir}")
        upload_mp3s(output_dir, args.host, args.user, remote_dir)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
