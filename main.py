"""
YouTube Playlist Downloader - CLI Application
Downloads playlists and provides metadata using YouTube Data API v3
"""

from typing import List, Dict, Optional
import re
import os
import sys
import argparse
import requests
import yt_dlp
from creds import CredsManager


def parse_iso8601_duration(duration: str) -> str:
    """
    Convert ISO 8601 duration to human-readable format.

    Args:
        duration: ISO 8601 duration string (e.g., 'PT2M50S')

    Returns:
        Human-readable duration (e.g., '2:50' or '1:23:45')
    """
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return duration

    hours, minutes, seconds = match.groups()
    hours = int(hours) if hours else 0
    minutes = int(minutes) if minutes else 0
    seconds = int(seconds) if seconds else 0

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"


def get_available_audios(video_id: str) -> List[Dict]:
    """
    Get available audio formats for a video using yt-dlp.

    Args:
        video_id: YouTube video ID

    Returns:
        List of dictionaries with audio format information
    """
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )

            # Filter for audio-only formats
            audio_formats = []
            for fmt in info.get("formats", []):
                # Only include audio-only formats (no video)
                if fmt.get("vcodec") == "none" and fmt.get("acodec") != "none":
                    abr = fmt.get("abr", 0) or 0  # Audio bitrate, default to 0 if None
                    ext = fmt.get("ext", "unknown")
                    audio_formats.append(
                        {
                            "bitrate": abr,
                            "ext": ext,
                            "format_note": fmt.get("format_note", ""),
                            "format_id": fmt.get("format_id", ""),
                        }
                    )

            # Sort by bitrate (highest first)
            audio_formats.sort(
                key=lambda x: x["bitrate"] if x["bitrate"] is not None else 0,
                reverse=True,
            )

            return audio_formats

    except Exception as e:
        raise Exception(f"Error getting audio formats: {str(e)}")


class YouTubeAPI:
    """Handles YouTube Data API v3 interactions."""

    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: str):
        """Initialize with API key."""
        self.api_key = api_key

    def get_playlist_videos(
        self, playlist_id: str, max_results: int = 100
    ) -> List[Dict]:
        """
        Get videos from a playlist.

        Args:
            playlist_id: YouTube playlist ID
            max_results: Maximum number of videos to fetch (default: 100)

        Returns:
            List of video dictionaries with video IDs and basic info
        """
        videos = []
        next_page_token = None

        while len(videos) < max_results:
            params = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": min(50, max_results - len(videos)),  # API max is 50
                "key": self.api_key,
            }

            if next_page_token:
                params["pageToken"] = next_page_token

            response = requests.get(f"{self.BASE_URL}/playlistItems", params=params)
            response.raise_for_status()
            data = response.json()

            for item in data.get("items", []):
                videos.append(
                    {
                        "video_id": item["contentDetails"]["videoId"],
                        "title": item["snippet"]["title"],
                        "position": item["snippet"]["position"],
                    }
                )

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

        return videos[:max_results]

    def get_video_details(self, video_id: str) -> Dict:
        """
        Get detailed information about a video including available formats.

        Args:
            video_id: YouTube video ID

        Returns:
            Dictionary with video metadata and content details
        """
        params = {
            "part": "snippet,contentDetails,statistics,status",
            "id": video_id,
            "key": self.api_key,
        }

        response = requests.get(f"{self.BASE_URL}/videos", params=params)
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            return {}

        item = data["items"][0]
        snippet = item["snippet"]
        content = item["contentDetails"]
        stats = item.get("statistics", {})

        return {
            "video_id": video_id,
            "title": snippet["title"],
            "description": snippet["description"],
            "channel": snippet["channelTitle"],
            "published_at": snippet["publishedAt"],
            "duration": content["duration"],
            "duration_formatted": parse_iso8601_duration(content["duration"]),
            "definition": content["definition"],  # 'hd' or 'sd'
            "caption": content.get("caption", "false"),
            "view_count": stats.get("viewCount", "N/A"),
            "like_count": stats.get("likeCount", "N/A"),
            "comment_count": stats.get("commentCount", "N/A"),
            "tags": snippet.get("tags", []),
            "category_id": snippet["categoryId"],
        }

    def extract_playlist_id(self, url: str) -> Optional[str]:
        """
        Extract playlist ID from a YouTube URL.

        Args:
            url: YouTube playlist URL

        Returns:
            Playlist ID or None if not found
        """
        # Handle different URL formats
        if "list=" in url:
            return url.split("list=")[1].split("&")[0]
        return url if len(url) == 34 and url.startswith("PL") else None


def download_playlist_to_folder(
    playlist_url: str,
    folder_path: str,
    api_key: Optional[str] = None,
    audio_format: str = "mp3",
    audio_quality: str = "192",
    verbose: bool = True,
) -> Dict:
    """
    Download all audio from a YouTube playlist to a local folder.

    IMPORTANT: Only downloads audio-only formats. Videos without viable audio formats
    will be skipped automatically. Never downloads MP4 or other video containers.

    Args:
        playlist_url: YouTube playlist URL or playlist ID
        folder_path: Local folder path to save audio files
        api_key: YouTube Data API key (optional, will use CredsManager if not provided)
        audio_format: Desired audio format (default: 'mp3')
        audio_quality: Audio quality/bitrate (default: '192')
        verbose: Print progress messages (default: True)

    Returns:
        Dictionary with download results:
        {
            'success_count': int,
            'failed_count': int,
            'skipped_count': int,
            'total': int,
            'downloaded_files': List[str],
            'failed_videos': List[Dict],
            'skipped_videos': List[Dict]
        }
    """
    # Initialize API
    if api_key is None:
        creds_manager = CredsManager()
        api_key = creds_manager.get_api_key()

    youtube_api = YouTubeAPI(api_key)

    # Create folder if it doesn't exist
    os.makedirs(folder_path, exist_ok=True)

    # Extract playlist ID
    playlist_id = youtube_api.extract_playlist_id(playlist_url)
    if not playlist_id:
        raise ValueError("Invalid playlist URL")

    if verbose:
        print(f"Fetching playlist: {playlist_id}")

    # Get all videos from playlist
    videos = youtube_api.get_playlist_videos(playlist_id)
    if not videos:
        raise ValueError("No videos found in playlist")

    if verbose:
        print(f"Found {len(videos)} videos in playlist")

    # Download each video
    success_count = 0
    failed_count = 0
    skipped_count = 0
    downloaded_files = []
    failed_videos = []
    skipped_videos = []

    for i, video in enumerate(videos, 1):
        video_id = video["video_id"]
        try:
            if verbose:
                print(f"[{i}/{len(videos)}] Checking: {video['title'][:50]}...")

            # First, check if audio-only formats are available
            try:
                audio_formats = get_available_audios(video_id)
                if not audio_formats:
                    skipped_count += 1
                    skipped_videos.append(
                        {"video_id": video_id, "title": video["title"], "reason": "No audio-only formats available"}
                    )
                    if verbose:
                        print(f"  ⊗ Skipped: No audio-only formats available")
                    continue
            except Exception as e:
                skipped_count += 1
                skipped_videos.append(
                    {"video_id": video_id, "title": video["title"], "reason": f"Could not check formats: {str(e)}"}
                )
                if verbose:
                    print(f"  ⊗ Skipped: Could not check formats")
                continue

            # Use format selector that ONLY downloads audio streams (no video)
            # Prioritize progressive download formats (m4a, webm, opus) over HLS/DASH fragments
            # These formats are typically available via direct HTTP and avoid fragmented streams
            ydl_opts = {
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio[ext=opus]/bestaudio",
                "outtmpl": os.path.join(folder_path, "%(title)s.%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": audio_format,
                        "preferredquality": audio_quality,
                    }
                ],
                "quiet": True,  # Always quiet to reduce spam
                "no_warnings": True,
                "noprogress": True,  # Disable progress bar
                "prefer_free_formats": True,
                # Abort if no audio-only format is available
                "noplaylist": True,
                "extract_audio": True,
                # Retry options for stability
                "retries": 10,
                "fragment_retries": 10,
                "http_chunk_size": 10485760,  # 10MB chunks
                "extractor_retries": 3,
            }

            if verbose:
                print(f"  → Downloading audio...")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=True
                )

                # Verify we downloaded an audio-only format
                if info:
                    vcodec = info.get("vcodec", "")

                    # Double-check we didn't download video
                    if vcodec and vcodec not in ["none", None]:
                        # If we somehow got video, delete the file and skip
                        if verbose:
                            print(f"  ⊗ Skipped: Downloaded format contained video stream, removed")
                        skipped_count += 1
                        skipped_videos.append(
                            {"video_id": video_id, "title": video["title"], "reason": "Format contained video stream"}
                        )
                        continue

                title = info.get("title", "Unknown")
                filename = ydl.prepare_filename(info)
                # Change extension to audio format
                filename = os.path.splitext(filename)[0] + f".{audio_format}"
                downloaded_files.append(filename)
                success_count += 1

                if verbose:
                    print(f"  ✓ Downloaded: {title}")

        except Exception as e:
            error_msg = str(e)
            # Check if error is about no suitable formats
            if "No suitable formats" in error_msg or "requested format not available" in error_msg.lower():
                skipped_count += 1
                skipped_videos.append(
                    {"video_id": video_id, "title": video["title"], "reason": "No viable audio format"}
                )
                if verbose:
                    print(f"  ⊗ Skipped: No viable audio format")
            else:
                failed_count += 1
                failed_videos.append(
                    {"video_id": video_id, "title": video["title"], "error": error_msg}
                )
                if verbose:
                    print(f"  ✗ Failed: {error_msg}")

    if verbose:
        print(f"\nDownload complete: {success_count} successful, {skipped_count} skipped, {failed_count} failed")

    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "total": len(videos),
        "downloaded_files": downloaded_files,
        "failed_videos": failed_videos,
        "skipped_videos": skipped_videos,
    }


def download_single_video(
    video_url: str,
    folder_path: str,
    audio_format: str = "mp3",
    audio_quality: str = "192",
    verbose: bool = True,
) -> Dict:
    """
    Download audio from a single YouTube video.

    Args:
        video_url: YouTube video URL or video ID
        folder_path: Local folder path to save audio file
        audio_format: Desired audio format (default: 'mp3')
        audio_quality: Audio quality/bitrate (default: '192')
        verbose: Print progress messages (default: True)

    Returns:
        Dictionary with download result:
        {
            'success': bool,
            'video_id': str,
            'title': str,
            'filename': str,
            'error': str (if failed)
        }
    """
    # Create folder if it doesn't exist
    os.makedirs(folder_path, exist_ok=True)

    # Extract video ID from URL if needed
    video_id = video_url
    if "youtube.com" in video_url or "youtu.be" in video_url:
        if "v=" in video_url:
            video_id = video_url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]

    try:
        if verbose:
            print(f"Downloading video: {video_id}")

        # Check if audio-only formats are available
        try:
            audio_formats = get_available_audios(video_id)
            if not audio_formats:
                return {
                    "success": False,
                    "video_id": video_id,
                    "title": "",
                    "error": "No audio-only formats available"
                }
        except Exception as e:
            return {
                "success": False,
                "video_id": video_id,
                "title": "",
                "error": f"Could not check formats: {str(e)}"
            }

        # Download options (same as playlist download)
        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio[ext=opus]/bestaudio",
            "outtmpl": os.path.join(folder_path, "%(title)s.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": audio_quality,
                }
            ],
            "quiet": True,  # Always quiet to reduce spam
            "no_warnings": True,
            "noprogress": True,  # Disable progress bar
            "prefer_free_formats": True,
            "noplaylist": True,
            "extract_audio": True,
            # Retry options for stability
            "retries": 10,
            "fragment_retries": 10,
            "http_chunk_size": 10485760,  # 10MB chunks
            "extractor_retries": 3,
        }

        if verbose:
            print(f"  → Downloading audio...")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=True
            )

            title = info.get("title", "Unknown")
            filename = ydl.prepare_filename(info)
            # Change extension to audio format
            filename = os.path.splitext(filename)[0] + f".{audio_format}"

            if verbose:
                print(f"  ✓ Downloaded: {title}")

            return {
                "success": True,
                "video_id": video_id,
                "title": title,
                "filename": filename,
            }

    except Exception as e:
        error_msg = str(e)
        if verbose:
            print(f"  ✗ Failed: {error_msg}")

        return {
            "success": False,
            "video_id": video_id,
            "title": "",
            "error": error_msg
        }


def interactive_mode():
    """Run the application in interactive mode."""
    print("=" * 60)
    print("YouTube Playlist Downloader - Interactive Mode")
    print("=" * 60)

    try:
        # Initialize API
        creds_manager = CredsManager()
        api_key = creds_manager.get_api_key()
        youtube_api = YouTubeAPI(api_key)
        print("✓ API initialized successfully\n")
    except Exception as e:
        print(f"✗ Error initializing API: {e}")
        return

    while True:
        print("\nOptions:")
        print("1. Download playlist")
        print("2. Download single video")
        print("3. View playlist videos")
        print("4. Get video audio formats")
        print("5. Exit")

        choice = input("\nEnter your choice (1-5): ").strip()

        if choice == "1":
            # Download playlist
            playlist_url = input("\nEnter playlist URL: ").strip()
            folder_path = input("Enter download folder path (default: ./downloads): ").strip() or "./downloads"
            audio_format = input("Enter audio format (default: mp3): ").strip() or "mp3"
            audio_quality = input("Enter audio quality/bitrate (default: 192): ").strip() or "192"

            print("\n" + "-" * 60)
            try:
                results = download_playlist_to_folder(
                    playlist_url,
                    folder_path,
                    api_key=api_key,
                    audio_format=audio_format,
                    audio_quality=audio_quality,
                    verbose=True
                )
                print("-" * 60)
                print(f"\n✓ Download Summary:")
                print(f"  Total videos: {results['total']}")
                print(f"  Successful: {results['success_count']}")
                print(f"  Skipped: {results['skipped_count']}")
                print(f"  Failed: {results['failed_count']}")

                if results['skipped_videos']:
                    print(f"\nSkipped videos (no viable audio):")
                    for skipped in results['skipped_videos']:
                        print(f"  - {skipped['title']}: {skipped['reason']}")

                if results['failed_videos']:
                    print(f"\nFailed videos:")
                    for failed in results['failed_videos']:
                        print(f"  - {failed['title']}: {failed['error']}")

            except Exception as e:
                print(f"\n✗ Error: {e}")

        elif choice == "2":
            # Download single video
            video_url = input("\nEnter video URL or ID: ").strip()
            folder_path = input("Enter download folder path (default: ./downloads): ").strip() or "./downloads"
            audio_format = input("Enter audio format (default: mp3): ").strip() or "mp3"
            audio_quality = input("Enter audio quality/bitrate (default: 192): ").strip() or "192"

            print("\n" + "-" * 60)
            try:
                result = download_single_video(
                    video_url,
                    folder_path,
                    audio_format=audio_format,
                    audio_quality=audio_quality,
                    verbose=True
                )
                print("-" * 60)

                if result['success']:
                    print(f"\n✓ Download successful!")
                    print(f"  Title: {result['title']}")
                    print(f"  File: {result['filename']}")
                else:
                    print(f"\n✗ Download failed: {result['error']}")

            except Exception as e:
                print(f"\n✗ Error: {e}")

        elif choice == "3":
            # View playlist videos
            playlist_url = input("\nEnter playlist URL: ").strip()
            try:
                playlist_id = youtube_api.extract_playlist_id(playlist_url)
                if not playlist_id:
                    print("✗ Invalid playlist URL")
                    continue

                print(f"\nFetching playlist videos...")
                videos = youtube_api.get_playlist_videos(playlist_id)

                print(f"\n✓ Found {len(videos)} videos:\n")
                print(f"{'#':<5} {'Video ID':<15} {'Title':<50}")
                print("-" * 70)

                for video in videos:
                    pos = video['position'] + 1
                    vid_id = video['video_id']
                    title = video['title'][:47] + "..." if len(video['title']) > 50 else video['title']
                    print(f"{pos:<5} {vid_id:<15} {title:<50}")

            except Exception as e:
                print(f"\n✗ Error: {e}")

        elif choice == "4":
            # Get video audio formats
            video_id = input("\nEnter video ID or URL: ").strip()

            # Extract video ID from URL if needed
            if "youtube.com" in video_id or "youtu.be" in video_id:
                if "v=" in video_id:
                    video_id = video_id.split("v=")[1].split("&")[0]
                elif "youtu.be/" in video_id:
                    video_id = video_id.split("youtu.be/")[1].split("?")[0]

            try:
                print(f"\nFetching audio formats for video: {video_id}...")
                formats = get_available_audios(video_id)

                print(f"\n✓ Available audio formats:\n")
                print(f"{'#':<4} {'Extension':<12} {'Bitrate':<12} {'Format Note':<30} {'Format ID':<15}")
                print("-" * 80)

                for i, fmt in enumerate(formats, 1):
                    ext = fmt['ext']
                    bitrate = f"{int(fmt['bitrate'])}k" if fmt['bitrate'] > 0 else "N/A"
                    note = fmt['format_note'][:27] + "..." if len(fmt['format_note']) > 30 else fmt['format_note']
                    fmt_id = fmt['format_id']
                    print(f"{i:<4} {ext:<12} {bitrate:<12} {note:<30} {fmt_id:<15}")

            except Exception as e:
                print(f"\n✗ Error: {e}")

        elif choice == "5":
            print("\nGoodbye!")
            break

        else:
            print("\n✗ Invalid choice. Please enter 1-5.")


def cli_mode():
    """Run the application in CLI mode with arguments."""
    parser = argparse.ArgumentParser(
        description="YouTube Playlist Downloader - Download audio from YouTube playlists",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download a playlist to default folder (./downloads)
  python main.py download "https://youtube.com/playlist?list=PLxxx..."

  # Download with custom output folder and format
  python main.py download "PLxxx..." -o ./music -f m4a -q 256

  # Download a single video
  python main.py single "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

  # Download single video with custom format
  python main.py single dQw4w9WgXcQ -o ./music -f m4a -q 256

  # List videos in a playlist
  python main.py list "https://youtube.com/playlist?list=PLxxx..."

  # Get audio formats for a video
  python main.py formats dQw4w9WgXcQ

  # Run in interactive mode
  python main.py
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Download command
    download_parser = subparsers.add_parser("download", help="Download playlist audio")
    download_parser.add_argument("playlist_url", help="YouTube playlist URL or ID")
    download_parser.add_argument("-o", "--output", default="./downloads",
                                help="Output folder path (default: ./downloads)")
    download_parser.add_argument("-f", "--format", default="mp3",
                                help="Audio format (default: mp3)")
    download_parser.add_argument("-q", "--quality", default="192",
                                help="Audio quality/bitrate (default: 192)")
    download_parser.add_argument("--quiet", action="store_true",
                                help="Suppress progress output")

    # Single video download command
    single_parser = subparsers.add_parser("single", help="Download single video audio")
    single_parser.add_argument("video_url", help="YouTube video URL or ID")
    single_parser.add_argument("-o", "--output", default="./downloads",
                              help="Output folder path (default: ./downloads)")
    single_parser.add_argument("-f", "--format", default="mp3",
                              help="Audio format (default: mp3)")
    single_parser.add_argument("-q", "--quality", default="192",
                              help="Audio quality/bitrate (default: 192)")
    single_parser.add_argument("--quiet", action="store_true",
                              help="Suppress progress output")

    # List command
    list_parser = subparsers.add_parser("list", help="List videos in a playlist")
    list_parser.add_argument("playlist_url", help="YouTube playlist URL or ID")
    list_parser.add_argument("-m", "--max", type=int, default=100,
                            help="Maximum number of videos to fetch (default: 100)")
    list_parser.add_argument("-d", "--details", action="store_true",
                            help="Show detailed video information")

    # Formats command
    formats_parser = subparsers.add_parser("formats", help="Get available audio formats for a video")
    formats_parser.add_argument("video_id", help="YouTube video ID or URL")

    args = parser.parse_args()

    # If no command, run interactive mode
    if not args.command:
        interactive_mode()
        return

    try:
        # Initialize API
        creds_manager = CredsManager()
        api_key = creds_manager.get_api_key()
        youtube_api = YouTubeAPI(api_key)

        if args.command == "download":
            print(f"Downloading playlist to: {args.output}")
            results = download_playlist_to_folder(
                args.playlist_url,
                args.output,
                api_key=api_key,
                audio_format=args.format,
                audio_quality=args.quality,
                verbose=not args.quiet
            )

            if not args.quiet:
                print(f"\n{'='*60}")
                print(f"Download Summary:")
                print(f"  Total: {results['total']}")
                print(f"  Successful: {results['success_count']}")
                print(f"  Skipped: {results['skipped_count']}")
                print(f"  Failed: {results['failed_count']}")
                print(f"{'='*60}")

                if results['skipped_videos']:
                    print("\nSkipped videos (no viable audio):")
                    for skipped in results['skipped_videos']:
                        print(f"  - {skipped['title']}: {skipped['reason']}")

                if results['failed_videos']:
                    print("\nFailed videos:")
                    for failed in results['failed_videos']:
                        print(f"  - {failed['title']}: {failed['error']}")

        elif args.command == "single":
            if not args.quiet:
                print(f"Downloading video to: {args.output}")

            result = download_single_video(
                args.video_url,
                args.output,
                audio_format=args.format,
                audio_quality=args.quality,
                verbose=not args.quiet
            )

            if not args.quiet:
                print(f"\n{'='*60}")
                if result['success']:
                    print(f"Download successful!")
                    print(f"  Title: {result['title']}")
                    print(f"  File: {result['filename']}")
                else:
                    print(f"Download failed!")
                    print(f"  Error: {result['error']}")
                print(f"{'='*60}")

            if not result['success']:
                sys.exit(1)

        elif args.command == "list":
            playlist_id = youtube_api.extract_playlist_id(args.playlist_url)
            if not playlist_id:
                print("Error: Invalid playlist URL")
                sys.exit(1)

            print(f"Fetching playlist videos (max: {args.max})...")
            videos = youtube_api.get_playlist_videos(playlist_id, args.max)

            print(f"\nFound {len(videos)} videos:\n")

            if args.details:
                for video in videos:
                    details = youtube_api.get_video_details(video['video_id'])
                    if details:
                        print(f"#{video['position'] + 1}")
                        print(f"  Video ID: {details['video_id']}")
                        print(f"  Title: {details['title']}")
                        print(f"  Channel: {details['channel']}")
                        print(f"  Duration: {details['duration_formatted']}")
                        print(f"  Views: {details['view_count']}")
                        print(f"  Published: {details['published_at']}")
                        print()
            else:
                print(f"{'#':<5} {'Video ID':<15} {'Title':<50}")
                print("-" * 70)
                for video in videos:
                    pos = video['position'] + 1
                    vid_id = video['video_id']
                    title = video['title'][:47] + "..." if len(video['title']) > 50 else video['title']
                    print(f"{pos:<5} {vid_id:<15} {title:<50}")

        elif args.command == "formats":
            video_id = args.video_id

            # Extract video ID from URL if needed
            if "youtube.com" in video_id or "youtu.be" in video_id:
                if "v=" in video_id:
                    video_id = video_id.split("v=")[1].split("&")[0]
                elif "youtu.be/" in video_id:
                    video_id = video_id.split("youtu.be/")[1].split("?")[0]

            print(f"Fetching audio formats for: {video_id}...")
            formats = get_available_audios(video_id)

            print(f"\nAvailable audio formats:\n")
            print(f"{'#':<4} {'Extension':<12} {'Bitrate':<12} {'Format Note':<30} {'Format ID':<15}")
            print("-" * 80)

            for i, fmt in enumerate(formats, 1):
                ext = fmt['ext']
                bitrate = f"{int(fmt['bitrate'])}k" if fmt['bitrate'] > 0 else "N/A"
                note = fmt['format_note'][:27] + "..." if len(fmt['format_note']) > 30 else fmt['format_note']
                fmt_id = fmt['format_id']
                print(f"{i:<4} {ext:<12} {bitrate:<12} {note:<30} {fmt_id:<15}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli_mode()
