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

OLLAMA_MODEL = "gpt-oss:20b"
WHISPER_MODEL = "openai/whisper-large-v2"
WHISPER_LANGUAGE = "en"
MAX_TITLE_LENGTH = 80


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


def find_obsidian_attachments() -> Path | None:
    """Check if we're in an Obsidian vault by looking for Attachments folder."""
    current = Path.cwd()
    # Check current directory and up to 3 parent levels
    for _ in range(4):
        attachments = current / "Attachments"
        if attachments.exists() and attachments.is_dir():
            return attachments
        if current.parent == current:  # Reached root
            break
        current = current.parent
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
    response = ollama.chat(
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
    response = ollama.chat(
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
    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return clean_thinking_chunks(response["message"]["content"])


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

    args = parser.parse_args()

    # Argument validation
    if args.with_prompt and not args.from_transcript:
        parser.error("--with-prompt can only be used with --from-transcript.")
    if args.research and args.with_prompt:
        parser.error("--research cannot be used with --with-prompt.")
    if args.transcript_only and args.from_transcript:
        print("Warning: --transcript-only has no effect when using --from-transcript.")

    # Determine language setting
    language = args.language if args.language else WHISPER_LANGUAGE
    if language and language.lower() == "auto":
        language = None

    # Check for Obsidian vault
    attachments_dir = find_obsidian_attachments()
    if attachments_dir:
        print(f"Obsidian vault detected. Attachments folder: {attachments_dir}")
        data_directory = attachments_dir
    else:
        data_directory = Path("tmp")
        if not data_directory.exists():
            data_directory.mkdir(parents=True)
            print(f"Created directory: {data_directory}")

    transcript = None
    transcript_path = None
    audio_file_path = None
    video_title = None
    llm_result = None

    # Input Processing
    if args.from_youtube:
        print(f"Downloading YouTube video from {args.from_youtube}")
        try:
            # Get title first
            video_title = (
                args.title or get_youtube_title(args.from_youtube) or "Unknown Video"
            )
            audio_file_path = download_from_youtube(
                args.from_youtube, str(data_directory), title=video_title
            )
            print(f"Audio downloaded to: {audio_file_path}")

            # Generate transcript filename
            transcript_filename = generate_filename(
                sanitize_title(video_title), ".txt", is_transcript=True
            )
            transcript_path = data_directory / transcript_filename

            print(f"Transcribing file: {audio_file_path}")
            transcript = transcribe_file(
                str(audio_file_path), str(transcript_path), language
            )
        except Exception as e:
            print(f"Error during YouTube download or transcription: {e}")
            sys.exit(1)

    elif args.from_local:
        file_path = Path(args.from_local)
        if not file_path.is_file():
            print(f"Error: Local file not found at {file_path}")
            sys.exit(1)

        # Use provided title or filename
        video_title = args.title or file_path.stem
        print(f"Transcribing file: {file_path}")

        try:
            # Generate transcript filename
            transcript_filename = generate_filename(
                sanitize_title(video_title), ".txt", is_transcript=True
            )
            transcript_path = data_directory / transcript_filename

            transcript = transcribe_file(str(file_path), str(transcript_path), language)
            audio_file_path = file_path
        except Exception as e:
            print(f"Error during local file transcription: {e}")
            sys.exit(1)

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
                output_filename = generate_filename(sanitize_title(video_title), ".md")
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


if __name__ == "__main__":
    main()
