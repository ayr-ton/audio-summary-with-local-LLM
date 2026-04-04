import ollama
import argparse
from pathlib import Path
from typing import Any
from transformers import pipeline
import yt_dlp
import torch
import sys
import re
from datetime import datetime

import os
from .config import load_config, create_remote_config, RemoteConfig
from .progress import create_file_progress_bar
from .lock_manager import LockManager, get_queue_status
from .remote_lock import check_and_wait_for_remote

OLLAMA_MODEL = "gpt-oss:20b"
WHISPER_MODEL = "openai/whisper-large-v2"
WHISPER_LANGUAGE = "en"
MAX_TITLE_LENGTH = 80


def get_ollama_client() -> ollama.Client:
    """Get Ollama client with proper authentication configuration."""
    host = os.environ.get("OLLAMA_HOST", "localhost:11434")
    api_key = os.environ.get("OLLAMA_API_KEY")

    # Determine protocol based on API key presence
    if api_key:
        protocol = "https"
    else:
        protocol = "http"

    # Ensure host has protocol prefix
    if not host.startswith(("http://", "https://")):
        host = f"{protocol}://{host}"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    return ollama.Client(host=host, headers=headers if headers else None)


def resolve_remote_config(args, remote_name: str | None = None) -> RemoteConfig:
    """Resolve remote configuration from args or config file."""
    config = load_config()

    # If ad-hoc parameters are provided, use them
    if args.remote_host:
        return create_remote_config(
            host=args.remote_host,
            user=args.remote_user or "tom",  # Default user
            path=args.remote_path
            or "/home/tom/github.com/ayr-ton/audio-summary-with-local-LLM",
            max_retries=3,
        )

    # Otherwise use config file
    return config.get_remote(remote_name)


def sanitize_title(title: str) -> str:
    """Sanitize title for use in filenames."""
    # Remove special characters but keep spaces
    sanitized = re.sub(r'[<>:"/\\|?*]', "", title)
    # Replace multiple spaces with single space
    sanitized = re.sub(r"\s+", " ", sanitized)
    # Strip leading/trailing whitespace
    sanitized = sanitized.strip()
    # Limit length
    if len(sanitized) > MAX_TITLE_LENGTH:
        sanitized = sanitized[:MAX_TITLE_LENGTH].rstrip()
    return sanitized


def get_youtube_title(url: str) -> str | None:
    """Extract video title from YouTube URL using yt-dlp."""
    try:
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=False)
            return info.get("title") if info else None
    except Exception:
        return None


def clean_thinking_chunks(text: str) -> str:
    """Remove thinking blocks from model output."""
    # Remove thinking blocks (support both formats)
    cleaned = re.sub(r"<\|thinking\|>.*?<\|/thinking\|>", "", text, flags=re.DOTALL)
    # Also handle nested or alternative formats
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL)
    # Clean up excessive whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def generate_filename(title: str, extension: str, is_transcript: bool = False) -> str:
    """Generate filename with date prefix."""
    today = datetime.now().strftime("%Y-%m-%d")
    sanitized = sanitize_title(title)

    if is_transcript:
        return f"{today} {sanitized}_transcript{extension}"
    else:
        return f"{today} {sanitized}{extension}"


def download_from_youtube(url: str, path: str, title: str | None = None) -> Path:
    """Download a video from YouTube and return the audio file path."""
    # Get title if not provided
    if not title:
        title = get_youtube_title(url) or "Unknown Video"

    # Pass unsanitized title - generate_filename will sanitize it
    filename_base = generate_filename(title, "", is_transcript=False)
    # Remove extension from base for yt-dlp template
    filename_base = Path(filename_base).stem

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(Path(path) / f"{filename_base}.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Find the downloaded mp3 file
    downloaded_files = list(Path(path).glob(f"{filename_base}.*.mp3"))
    if not downloaded_files:
        downloaded_files = list(Path(path).glob(f"{filename_base}.mp3"))

    if downloaded_files:
        return downloaded_files[0]
    else:
        raise FileNotFoundError(f"Could not find downloaded audio file in {path}")


def get_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    else:
        return "cpu"


def transcribe_file(
    file_path: str, output_file: str, language: str | None = None
) -> str:
    device = get_device()
    print(f"Using device: {device} for transcription")

    transcriber = pipeline(
        "automatic-speech-recognition",
        model=WHISPER_MODEL,
        device=device,
        chunk_length_s=30,
        return_timestamps=True,
    )

    if device == "cpu":
        print("Warning: Using CPU for transcription. This may be slow.")

    generate_kwargs = {}
    if language and language.lower() != "auto":
        generate_kwargs["language"] = language
        print(f"Transcribing in language: {language}")
    else:
        print("Using automatic language detection")

    print(
        f"Starting transcription for {file_path} (this may take a while for longer files)..."
    )
    transcribe = transcriber(file_path, generate_kwargs=generate_kwargs)

    if (
        isinstance(transcribe, dict)
        and "text" in transcribe
        and "chunks" not in transcribe
    ):
        full_text = transcribe["text"]
    elif isinstance(transcribe, dict) and "chunks" in transcribe:
        full_text = " ".join([chunk["text"].strip() for chunk in transcribe["chunks"]])
    elif isinstance(transcribe, str):
        full_text = transcribe
    else:
        full_text = (
            transcribe["text"]
            if isinstance(transcribe, dict) and "text" in transcribe
            else str(transcribe)
        )

    with open(output_file, "w") as tmp_file:
        tmp_file.write(full_text)
        print(f"Transcription saved to file: {output_file}")

    return full_text


def summarize_text(text: str) -> str:
    system_prompt = "You are a helpful assistant designed to summarize text accurately and concisely."
    user_prompt = f"""Generate a concise summary of the text below.
    Text : {text}
    Add a title to the summary using markdown H1 (# Title).
    Make sure your summary has useful and true information about the main points of the topic.
    Begin with a short introduction explaining the topic. If you can, use bullet points to list important details,
    and finish your summary with a concluding sentence."""

    print(f"Sending request to Ollama ({OLLAMA_MODEL}) for summarization...")
    client = get_ollama_client()
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return clean_thinking_chunks(response["message"]["content"])


def research_text(text: str) -> str:
    """Generate a comprehensive research-style analysis of the text."""
    system_prompt = """You are a research analyst designed to provide comprehensive, detailed analysis of content.
    Your analysis should be thorough, well-structured, and insightful."""

    user_prompt = f"""Provide a comprehensive research-style analysis of the text below. Structure your analysis with the following sections:

    # [Create an appropriate title based on the content]
    
    ## Overview
    Provide a brief but informative overview of what this content is about and its significance.
    
    ## Key Concepts
    Identify and explain the main concepts, ideas, and themes discussed. Use bullet points for clarity.
    
    ## Detailed Analysis
    Dive deep into the content. Explain the arguments, methodologies, findings, or narrative in detail. 
    Break this into subsections if there are multiple distinct topics or themes.
    
    ## Connections and Implications
    Discuss how this content relates to broader contexts, field of study, or real-world applications. 
    What are the implications of what's discussed?
    
    ## Key Takeaways
    Summarize the most important points that someone should remember from this content.
    
    ---
    
    Text to analyze:
    {text}
    
    Make your analysis insightful, accurate, and comprehensive."""

    print(f"Sending request to Ollama ({OLLAMA_MODEL}) for research analysis...")
    client = get_ollama_client()
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return clean_thinking_chunks(response["message"]["content"])


def ask_question_from_text(text: str, question: str) -> str:
    system_prompt = "You are a helpful assistant. Answer the user's question based *only* on the provided text context."
    user_prompt = f"""Based on the text below, please answer the following question.
    Text:
    ---
    {text}
    ---

    Question: {question}
    """

    print(f"Sending request to Ollama ({OLLAMA_MODEL}) to answer question...")
    client = get_ollama_client()
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return clean_thinking_chunks(response["message"]["content"])


def execute_remote_download(args, remote_config, video_title, data_directory):
    """Execute download on remote host and download MP3 back."""
    print(f"Connecting to remote host: {remote_config.host}")

    # Determine which executor to use
    use_subprocess = (
        remote_config.ssh_key_path and "_sk" in remote_config.ssh_key_path.name.lower()
    )
    if use_subprocess:
        from .remote_ssh import RemoteExecutorSSH as RemoteExecutorClass
    else:
        from .remote import RemoteExecutor as RemoteExecutorClass

    with RemoteExecutorClass(remote_config) as executor:
        # Check if MP3 already exists on remote
        mp3_filename = generate_filename(video_title, ".mp3")
        remote_mp3_path = f"{remote_config.path}/Attachments/{mp3_filename}"

        if args.dry_run:
            print("[DRY-RUN] Would check if MP3 exists on remote")
        elif not executor.check_file_exists(remote_mp3_path):
            # MP3 doesn't exist on remote, execute download
            print("MP3 does not exist on remote, downloading...")
            cmd = f"uv run audio-summary --from-youtube '{args.from_youtube}' --transcript-only --output /dev/null"
            if args.dry_run:
                print(f"[DRY-RUN] Would execute: {cmd}")
            else:
                print("Executing download on remote...")
                # First ensure Attachments directory exists on remote
                executor.execute(
                    "mkdir -p Attachments", cwd=remote_config.path, dry_run=args.dry_run
                )

                success, stdout, stderr = executor.execute_with_retry(
                    cmd, cwd=remote_config.path, dry_run=args.dry_run
                )
                if not success:
                    print(f"Remote download failed: {stderr}")
                    sys.exit(1)
                print("Download complete on remote")

                # Verify file was created (check both stdout message and file existence)
                if not executor.check_file_exists(remote_mp3_path):
                    # File may have been skipped if it already existed - check for that in output
                    if "MP3 already exists" in stdout or "Skipping download" in stdout:
                        print("Remote indicated file already exists, checking again...")
                        # Wait a moment and check again
                        import time

                        time.sleep(1)

                    if not executor.check_file_exists(remote_mp3_path):
                        print(
                            f"Error: Remote MP3 file was not created at {remote_mp3_path}"
                        )
                        print(f"stdout: {stdout}")
                        print(f"stderr: {stderr}")
                        sys.exit(1)
        else:
            print(f"MP3 already exists on remote: {remote_mp3_path}")

        # Download MP3 from remote
        print("Downloading MP3 from remote...")

        if args.dry_run:
            print(f"[DRY-RUN] Would download {remote_mp3_path} to {data_directory}/")
        else:
            # Ensure local directory exists
            data_directory.mkdir(parents=True, exist_ok=True)

            # Get file size for progress bar
            mp3_size = executor.get_file_size(remote_mp3_path)

            # Download MP3 with progress
            if mp3_size > 0:
                progress = create_file_progress_bar(mp3_filename, mp3_size)
                executor.download_file(
                    remote_mp3_path,
                    data_directory / mp3_filename,
                    progress_bar=progress,
                    dry_run=args.dry_run,
                )
                print(f"MP3 downloaded to: {data_directory / mp3_filename}")
            else:
                print(f"Warning: Remote MP3 file has size 0: {remote_mp3_path}")

        # Verify file exists locally before returning
        local_mp3_path = data_directory / mp3_filename
        if not args.dry_run and not local_mp3_path.is_file():
            print(f"Error: MP3 file was not downloaded successfully: {local_mp3_path}")
            sys.exit(1)

        return local_mp3_path


def execute_remote_transcription(
    args, remote_config, audio_file_path, transcript_path, video_title
):
    """Execute transcription on remote host and download transcript back."""
    print(f"Connecting to remote host: {remote_config.host}")

    # Determine which executor to use
    use_subprocess = (
        remote_config.ssh_key_path and "_sk" in remote_config.ssh_key_path.name.lower()
    )
    if use_subprocess:
        from .remote_ssh import RemoteExecutorSSH as RemoteExecutorClass
    else:
        from .remote import RemoteExecutor as RemoteExecutorClass

    with RemoteExecutorClass(remote_config) as executor:
        transcript_filename = generate_filename(video_title, ".txt", is_transcript=True)
        remote_transcript_path = (
            f"{remote_config.path}/Attachments/{transcript_filename}"
        )

        # Check if transcript already exists on remote
        if args.dry_run:
            print(f"[DRY-RUN] Would check if {remote_transcript_path} exists")
        elif executor.check_file_exists(remote_transcript_path):
            print(f"Transcript already exists on remote: {remote_transcript_path}")
        else:
            # Determine if we need to upload the audio file
            mp3_filename = audio_file_path.name
            remote_mp3_path = f"{remote_config.path}/Attachments/{mp3_filename}"

            # Check if MP3 exists on remote
            if executor.check_file_exists(remote_mp3_path):
                print(f"MP3 already exists on remote: {remote_mp3_path}")
            else:
                # Need to upload the audio file
                if args.dry_run:
                    print(
                        f"[DRY-RUN] Would upload {audio_file_path} to {remote_mp3_path}"
                    )
                else:
                    # Ensure audio_file_path is absolute Path
                    audio_path = Path(audio_file_path)
                    if not audio_path.is_absolute():
                        audio_path = audio_path.resolve()

                    if not audio_path.is_file():
                        print(f"Error: Audio file not found at {audio_path}")
                        sys.exit(1)

                    print(f"Uploading audio file to remote: {audio_path}")
                    file_size = audio_path.stat().st_size
                    progress = create_file_progress_bar(mp3_filename, file_size)
                    executor.upload_file(
                        audio_path,
                        remote_mp3_path,
                        progress_bar=progress,
                        dry_run=args.dry_run,
                    )
                    print(f"Audio uploaded to remote: {remote_mp3_path}")

            # Execute transcription on remote
            cmd = f"uv run audio-summary --from-local 'Attachments/{mp3_filename}' --transcript-only"
            if args.dry_run:
                print(f"[DRY-RUN] Would execute: {cmd}")
            else:
                print("Executing transcription on remote...")
                success, stdout, stderr = executor.execute_with_retry(
                    cmd, cwd=remote_config.path, dry_run=args.dry_run
                )
                if not success:
                    print(f"Remote transcription failed: {stderr}")
                    sys.exit(1)
                print("Transcription complete on remote")

        # Download transcript from remote
        print("Downloading transcript from remote...")

        local_transcript_path = Path(transcript_path)

        if args.dry_run:
            print(
                f"[DRY-RUN] Would download {remote_transcript_path} to {local_transcript_path}"
            )
        else:
            # Ensure local directory exists
            local_transcript_path.parent.mkdir(parents=True, exist_ok=True)

            # Get file size for progress bar
            transcript_size = executor.get_file_size(remote_transcript_path)

            # Download transcript with progress
            if transcript_size > 0:
                progress = create_file_progress_bar(
                    transcript_filename, transcript_size
                )
                executor.download_file(
                    remote_transcript_path,
                    local_transcript_path,
                    progress_bar=progress,
                    dry_run=args.dry_run,
                )
                print(f"Transcript downloaded to: {local_transcript_path}")

        # Cleanup remote MP3 if requested
        if args.cleanup_audio and not args.dry_run:
            try:
                if executor.check_file_exists(remote_mp3_path):
                    executor.remove_file(remote_mp3_path)
                    print(f"Cleaned up remote MP3: {mp3_filename}")
            except Exception as e:
                print(f"Warning: Failed to cleanup remote MP3: {e}")

        # Cleanup local MP3 if it was downloaded
        if args.cleanup_audio and not args.dry_run and audio_file_path:
            try:
                local_mp3 = Path(audio_file_path)
                if local_mp3.exists():
                    local_mp3.unlink()
                    print(f"Cleaned up local MP3: {audio_file_path}")
            except Exception as e:
                print(f"Warning: Failed to cleanup local MP3: {e}")

        # Read and return transcript content
        if args.dry_run:
            return ""
        with open(local_transcript_path, "r") as f:
            return f.read()


def execute_remote_summarize(args, remote_config, transcript_path, video_title):
    """Execute summarization on remote host and download result."""
    print(f"Connecting to remote host: {remote_config.host}")

    # Determine which executor to use
    use_subprocess = (
        remote_config.ssh_key_path and "_sk" in remote_config.ssh_key_path.name.lower()
    )
    if use_subprocess:
        from .remote_ssh import RemoteExecutorSSH as RemoteExecutorClass
    else:
        from .remote import RemoteExecutor as RemoteExecutorClass

    with RemoteExecutorClass(remote_config) as executor:
        # Upload transcript to remote
        remote_transcript_path = (
            f"{remote_config.path}/Attachments/{transcript_path.name}"
        )

        if args.dry_run:
            print(
                f"[DRY-RUN] Would upload {transcript_path} to {remote_transcript_path}"
            )
        else:
            # Upload with progress
            file_size = transcript_path.stat().st_size
            progress = create_file_progress_bar(transcript_path.name, file_size)
            executor.upload_file(
                transcript_path,
                remote_transcript_path,
                progress_bar=progress,
                dry_run=args.dry_run,
            )
            print(f"Transcript uploaded to remote: {remote_transcript_path}")

        # Execute summarization on remote
        cmd = f"uv run audio-summary --from-transcript 'Attachments/{transcript_path.name}'"
        if args.research:
            cmd += " --research"

        if args.dry_run:
            print(f"[DRY-RUN] Would execute: {cmd}")
        else:
            print("Executing summarization on remote...")
            success, stdout, stderr = executor.execute_with_retry(
                cmd, cwd=remote_config.path, dry_run=args.dry_run
            )
            if not success:
                print(f"Remote summarization failed: {stderr}")
                sys.exit(1)
            print("Summarization complete on remote")

        # Download markdown from remote
        md_filename = generate_filename(video_title, ".md")
        remote_md_path = f"{remote_config.path}/{md_filename}"
        local_md_path = Path(md_filename)

        if args.dry_run:
            print(f"[DRY-RUN] Would download {remote_md_path} to {local_md_path}")
            return local_md_path
        else:
            # Download with progress
            md_size = executor.get_file_size(remote_md_path)
            if md_size > 0:
                progress = create_file_progress_bar(md_filename, md_size)
                executor.download_file(
                    remote_md_path,
                    local_md_path,
                    progress_bar=progress,
                    dry_run=args.dry_run,
                )
                print(f"Markdown downloaded to: {local_md_path}")
                return local_md_path
            else:
                print("Warning: Markdown file not found on remote or is empty")
                return None


def main():
    parser = argparse.ArgumentParser(
        description="Download, transcribe, summarize, or query audio/video/text files."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--from-youtube", type=str, help="YouTube URL to download and process."
    )
    group.add_argument(
        "--from-local", type=str, help="Path to the local audio/video file to process."
    )
    group.add_argument(
        "--from-transcript",
        type=str,
        help="Path to a local .txt transcript file to process.",
    )

    parser.add_argument(
        "--output", type=str, default="./summary.md", help="Output markdown file path."
    )
    parser.add_argument(
        "--title",
        type=str,
        help="Custom title to use for file naming (for local files or override YouTube title).",
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help="Generate a detailed research analysis instead of a concise summary.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to the output file instead of overwriting it.",
    )
    parser.add_argument(
        "--transcript-only",
        action="store_true",
        help="Only transcribe the file (if applicable), do not summarize or query.",
    )
    parser.add_argument(
        "--language",
        type=str,
        help=f"Language code for transcription (e.g., 'en', 'fr', 'es', or 'auto' for detection). Default: {WHISPER_LANGUAGE}",
    )
    parser.add_argument(
        "--with-prompt",
        type=str,
        help="Ask a specific question about the transcript (only valid with --from-transcript).",
    )

    # Remote execution arguments
    parser.add_argument(
        "--remote-transcribe",
        action="store_true",
        help="Shorthand for --remote-download --remote-transcription",
    )
    parser.add_argument(
        "--remote-download",
        action="store_true",
        help="Download YouTube video on remote machine",
    )
    parser.add_argument(
        "--remote-transcription",
        action="store_true",
        help="Run Whisper transcription on remote machine",
    )
    parser.add_argument(
        "--remote-summarize",
        action="store_true",
        help="Execute summarization on remote Ollama, sync markdown back",
    )
    parser.add_argument(
        "--remote-host",
        type=str,
        help="Ad-hoc: specify remote host (overrides config)",
    )
    parser.add_argument(
        "--remote-path",
        type=str,
        help="Ad-hoc: specify remote path (overrides config)",
    )
    parser.add_argument(
        "--remote-user",
        type=str,
        help="Ad-hoc: specify remote user (overrides config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running",
    )

    # Lock and queue arguments
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Fail immediately if another instance is running instead of waiting",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=7200,
        help="Maximum seconds to wait for lock (default: 7200 = 2 hours)",
    )
    parser.add_argument(
        "--queue-status",
        action="store_true",
        help="Show current queue status and exit",
    )

    # Audio cleanup argument
    parser.add_argument(
        "--cleanup-audio",
        action="store_true",
        help="Remove MP3 file after transcription to save storage space",
    )

    args = parser.parse_args()

    # Handle --queue-status early
    if args.queue_status:
        print(get_queue_status())
        sys.exit(0)

    # Argument validation
    if args.with_prompt and not args.from_transcript:
        parser.error("--with-prompt can only be used with --from-transcript.")
    if args.research and args.with_prompt:
        parser.error("--research cannot be used with --with-prompt.")
    if args.transcript_only and args.from_transcript:
        print("Warning: --transcript-only has no effect when using --from-transcript.")

    # Cleanup validation: never cleanup when using --from-local (preserve user's original file)
    if args.cleanup_audio and args.from_local:
        print(
            "Warning: --cleanup-audio is ignored when using --from-local (source file preserved)"
        )
        args.cleanup_audio = False

    # Handle --remote-transcribe shorthand (sets both download and transcription)
    if args.remote_transcribe:
        args.remote_download = True
        args.remote_transcription = True

    # Remote execution validation
    remote_flags = [
        args.remote_download,
        args.remote_transcription,
        args.remote_summarize,
    ]
    if any(remote_flags):
        # Check if remote is configured (either ad-hoc args or config file)
        has_remote_config = args.remote_host or args.remote_path or args.remote_user
        if not has_remote_config:
            # Try to load from config file
            try:
                config = load_config()
                config.get_remote(None)  # This will raise if no default
                has_remote_config = True
            except ValueError:
                has_remote_config = False

        if not has_remote_config:
            parser.error(
                "Remote execution requires --remote-host, --remote-path, --remote-user, "
                "or a default remote configured in ~/.config/audio-summary/config.yaml"
            )
        if args.remote_download and not args.from_youtube:
            parser.error("--remote-download requires --from-youtube")
        if args.remote_transcription and args.from_transcript:
            parser.error("--remote-transcription cannot be used with --from-transcript")

    # Determine language setting
    language = args.language if args.language else WHISPER_LANGUAGE
    if language and language.lower() == "auto":
        language = None

    # Use Attachments/ as default directory
    data_directory = Path("Attachments")
    if not data_directory.exists():
        data_directory.mkdir(parents=True)
        print(f"Created directory: {data_directory}")

    transcript = None
    transcript_path = None
    audio_file_path = None
    video_title = None
    llm_result = None

    # Setup remote config if any remote flags are used
    remote_config = None
    if args.remote_download or args.remote_transcription or args.remote_summarize:
        remote_config = resolve_remote_config(args, None)

    # Determine which remote executor to use based on key type
    use_subprocess_ssh = False
    if remote_config and remote_config.ssh_key_path:
        key_name = remote_config.ssh_key_path.name.lower()
        if "_sk" in key_name:
            use_subprocess_ssh = True
            print(
                f"Using subprocess SSH for hardware key: {remote_config.ssh_key_path}"
            )

    # Import the appropriate executor
    if use_subprocess_ssh:
        from .remote_ssh import RemoteExecutorSSH as RemoteExecutorClass
    else:
        from .remote import RemoteExecutor as RemoteExecutorClass

    # Acquire lock before processing
    lock_manager = LockManager()
    command = " ".join(sys.argv[1:])
    remote_host = remote_config.host if remote_config else None
    lock = lock_manager.acquire_lock(
        command=command,
        remote_host=remote_host,
        timeout=args.timeout,
        no_wait=args.no_wait,
    )
    if not lock:
        sys.exit(1)

    # Enter lock context - ALL processing must be inside this block
    with lock:
        # Check remote lock if using remote execution
        if remote_config:
            with RemoteExecutorClass(remote_config) as executor:
                if not check_and_wait_for_remote(
                    executor, remote_config, args.timeout, args.no_wait
                ):
                    sys.exit(1)

        # Phase 1: Download
        if args.from_youtube:
            # Get title first
            video_title = (
                args.title or get_youtube_title(args.from_youtube) or "Unknown Video"
            )

            if args.remote_download:
                # Check if MP3 already exists locally before connecting to remote
                mp3_filename = generate_filename(video_title, ".mp3")
                local_mp3_path = data_directory / mp3_filename

                if local_mp3_path.is_file():
                    print(f"MP3 already exists locally: {local_mp3_path}")
                    print("Skipping remote download.")
                    audio_file_path = local_mp3_path
                else:
                    # Check if MP3 already exists on remote before downloading
                    remote_mp3_path = f"{remote_config.path}/Attachments/{mp3_filename}"

                    # Determine which executor to use for checking
                    if use_subprocess_ssh:
                        from .remote_ssh import RemoteExecutorSSH as RemoteExecutorClass
                    else:
                        from .remote import RemoteExecutor as RemoteExecutorClass

                    with RemoteExecutorClass(remote_config) as executor:
                        if executor.check_file_exists(remote_mp3_path):
                            print(f"MP3 already exists on remote: {remote_mp3_path}")
                            print("Skipping download on remote.")
                            # Download existing file from remote
                            print("Downloading existing MP3 from remote...")
                            data_directory.mkdir(parents=True, exist_ok=True)
                            local_mp3_path = data_directory / mp3_filename
                            mp3_size = executor.get_file_size(remote_mp3_path)
                            if mp3_size > 0 and not args.dry_run:
                                progress = create_file_progress_bar(
                                    mp3_filename, mp3_size
                                )
                                executor.download_file(
                                    remote_mp3_path,
                                    local_mp3_path,
                                    progress_bar=progress,
                                    dry_run=args.dry_run,
                                )
                                print(f"MP3 downloaded to: {local_mp3_path}")
                            audio_file_path = local_mp3_path
                        else:
                            # Download on remote
                            print(f"Downloading YouTube video from {args.from_youtube}")
                            audio_file_path = execute_remote_download(
                                args, remote_config, video_title, data_directory
                            )
            else:
                # Check if MP3 already exists locally before downloading
                mp3_filename = generate_filename(video_title, ".mp3")
                local_mp3_path = data_directory / mp3_filename

                if local_mp3_path.is_file():
                    print(f"MP3 already exists locally: {local_mp3_path}")
                    print("Skipping download.")
                    audio_file_path = local_mp3_path
                else:
                    print(f"Downloading YouTube video from {args.from_youtube}")
                    try:
                        audio_file_path = download_from_youtube(
                            args.from_youtube, str(data_directory), title=video_title
                        )
                        print(f"Audio downloaded to: {audio_file_path}")
                    except Exception as e:
                        print(f"Error during YouTube download: {e}")
                        sys.exit(1)

        elif args.from_local:
            file_path = Path(args.from_local)
            if not file_path.is_file():
                print(f"Error: Local file not found at {file_path}")
                sys.exit(1)

            # Use provided title or filename
            video_title = args.title or file_path.stem
            audio_file_path = file_path

            # Generate transcript filename
            transcript_filename = generate_filename(
                sanitize_title(video_title), ".txt", is_transcript=True
            )
            transcript_path = data_directory / transcript_filename

        elif args.from_transcript:
            transcript_file_path = Path(args.from_transcript)
            if not transcript_file_path.is_file():
                print(f"Error: Transcript file not found at {transcript_file_path}")
                sys.exit(1)
            try:
                print(f"Reading transcript from: {transcript_file_path}")
                with open(transcript_file_path, "r") as f:
                    transcript = f.read()
                transcript_path = transcript_file_path

                # Try to extract title from filename or use --title
                if args.title:
                    video_title = args.title
                else:
                    # Extract from filename pattern: "YYYY-MM-DD Title_transcript.txt"
                    stem = transcript_file_path.stem
                    if "_transcript" in stem:
                        video_title = (
                            stem.replace("_transcript", "").split(" ", 2)[-1]
                            if " " in stem
                            else stem
                        )
                    else:
                        video_title = stem
            except Exception as e:
                print(f"Error reading transcript file {transcript_file_path}: {e}")
                sys.exit(1)

        # Phase 2: Transcription (if not already have transcript)
        if not transcript and audio_file_path:
            try:
                # Generate transcript filename first
                transcript_filename = generate_filename(
                    video_title, ".txt", is_transcript=True
                )
                transcript_path = data_directory / transcript_filename

                if args.remote_transcription:
                    # Check if transcript already exists locally before connecting to remote
                    if transcript_path.is_file():
                        print(f"Transcript already exists locally: {transcript_path}")
                        print("Skipping remote transcription.")
                        with open(transcript_path, "r") as f:
                            transcript = f.read()
                    else:
                        # Check if transcript already exists on remote
                        remote_transcript_path = (
                            f"{remote_config.path}/Attachments/{transcript_filename}"
                        )

                        # Determine which executor to use
                        if use_subprocess_ssh:
                            from .remote_ssh import (
                                RemoteExecutorSSH as RemoteExecutorClass,
                            )
                        else:
                            from .remote import RemoteExecutor as RemoteExecutorClass

                        with RemoteExecutorClass(remote_config) as executor:
                            if executor.check_file_exists(remote_transcript_path):
                                print(
                                    f"Transcript already exists on remote: {remote_transcript_path}"
                                )
                                print("Skipping transcription on remote.")
                                # Download existing transcript
                                transcript_size = executor.get_file_size(
                                    remote_transcript_path
                                )
                                if transcript_size > 0 and not args.dry_run:
                                    progress = create_file_progress_bar(
                                        transcript_filename, transcript_size
                                    )
                                    executor.download_file(
                                        remote_transcript_path,
                                        transcript_path,
                                        progress_bar=progress,
                                        dry_run=args.dry_run,
                                    )
                                    print(
                                        f"Transcript downloaded to: {transcript_path}"
                                    )
                                # Read transcript locally
                                with open(transcript_path, "r") as f:
                                    transcript = f.read()
                            else:
                                # Transcribe on remote
                                transcript = execute_remote_transcription(
                                    args,
                                    remote_config,
                                    audio_file_path,
                                    transcript_path,
                                    video_title,
                                )
                else:
                    # Check if transcript already exists locally
                    if transcript_path.is_file():
                        print(f"Transcript already exists locally: {transcript_path}")
                        print("Skipping transcription.")
                        with open(transcript_path, "r") as f:
                            transcript = f.read()
                    else:
                        # Transcribe locally
                        print(f"Transcribing file: {audio_file_path}")
                        transcript = transcribe_file(
                            str(audio_file_path), str(transcript_path), language
                        )

                        # Cleanup audio file if requested and not from-local
                        if (
                            args.cleanup_audio
                            and audio_file_path
                            and not args.from_local
                        ):
                            try:
                                audio_path = Path(audio_file_path)
                                if audio_path.exists():
                                    audio_path.unlink()
                                    print(f"Cleaned up audio file: {audio_file_path}")
                            except Exception as e:
                                print(f"Warning: Failed to cleanup audio file: {e}")
            except Exception as e:
                print(f"Error during transcription: {e}")
                sys.exit(1)

        # Phase 3: Summarization
        if args.remote_summarize and transcript:
            try:
                # Summarize on remote
                md_path = execute_remote_summarize(
                    args, remote_config, Path(transcript_path), video_title
                )
                if md_path:
                    print(f"Summary saved to: {md_path}")
                return
            except Exception as e:
                print(f"Error during remote summarization: {e}")
                sys.exit(1)

        # LLM Processing
        if transcript and not args.transcript_only:
            if args.with_prompt:
                print("Asking specific question...")
                try:
                    llm_result = ask_question_from_text(transcript, args.with_prompt)
                except Exception as e:
                    print(f"Error getting answer from Ollama: {e}")
                    sys.exit(1)
            elif args.research:
                print("Generating research analysis...")
                try:
                    llm_result = research_text(transcript)
                except Exception as e:
                    print(f"Error generating research analysis from Ollama: {e}")
                    sys.exit(1)
            else:
                print("Generating summary...")
                try:
                    llm_result = summarize_text(transcript)
                except Exception as e:
                    print(f"Error generating summary from Ollama: {e}")
                    sys.exit(1)

        # Output
        if args.transcript_only:
            if transcript:
                print(f"Transcription complete. Transcript saved to {transcript_path}")
            else:
                print("No transcript was generated (check for errors above).")
            return

        if llm_result:
            try:
                # Determine output path
                if args.output == "./summary.md" and video_title:
                    # Generate default output filename with date prefix
                    output_filename = generate_filename(
                        sanitize_title(video_title), ".md"
                    )
                    output_path = Path(output_filename)
                else:
                    output_path = Path(args.output)

                output_path.parent.mkdir(parents=True, exist_ok=True)

                file_mode = "a" if args.append else "w"
                print(
                    f"Writing result to {output_path} (mode: {'append' if args.append else 'overwrite'})"
                )
                with open(output_path, file_mode, encoding="utf-8") as md_file:
                    if (
                        args.append
                        and output_path.exists()
                        and output_path.stat().st_size > 0
                    ):
                        md_file.write("\n\n---\n\n")

                    md_file.write(llm_result)

                print(f"Output successfully written to {output_path}")

            except Exception as e:
                print(f"Error writing output file: {e}")
                sys.exit(1)
        elif transcript:
            print(
                "Transcript generated, but no summary or answer was requested or generated (check for errors)."
            )
        else:
            print("Processing failed. No transcript or summary/answer generated.")

    # Lock is automatically released when exiting the 'with lock:' block


if __name__ == "__main__":
    main()
