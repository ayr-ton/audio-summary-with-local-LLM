import ollama
import argparse
from pathlib import Path
from transformers import pipeline
import yt_dlp
import torch
import sys # Added for exiting on argument error

OLLAMA_MODEL = "llama3"
WHISPER_MODEL = "openai/whisper-large-v2"
WHISPER_LANGUAGE = "en"  # Set to desired language or None for auto-detection

# Function to download a video from YouTube using yt-dlp
def download_from_youtube(url: str, path: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(Path(path) / 'to_transcribe.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    # Return the path to the downloaded file
    # Find the downloaded mp3 file (yt-dlp might add metadata)
    downloaded_files = list(Path(path).glob('to_transcribe.*.mp3'))
    if not downloaded_files:
        downloaded_files = list(Path(path).glob('to_transcribe.mp3')) # Fallback if no metadata added
    if downloaded_files:
        return downloaded_files[0]
    else:
        raise FileNotFoundError(f"Could not find downloaded audio file in {path}")


# Function to get the best available device
def get_device():
    if torch.backends.mps.is_available():
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    else:
        return "cpu"

# Function to transcribe an audio file using the transformers pipeline
def transcribe_file(file_path: str, output_file: str, language: str = None) -> str:
    # Get the best available device
    device = get_device()
    print(f"Using device: {device} for transcription")

    # Load the pipeline model for automatic speech recognition
    transcriber = pipeline(
        "automatic-speech-recognition",
        model=WHISPER_MODEL,
        device=device,
        chunk_length_s=30,  # Process in 30-second chunks
        return_timestamps=True  # Enable timestamp generation for longer audio
    )

    # Transcribe the audio file
    # For CPU, we might want to use a smaller model or chunk the audio if memory is an issue
    if device == "cpu":
        print("Warning: Using CPU for transcription. This may be slow.")

    # Set up generation keyword arguments including language
    generate_kwargs = {}
    if language and language.lower() != "auto":
        generate_kwargs["language"] = language
        print(f"Transcribing in language: {language}")
    else:
        print("Using automatic language detection")

    # Transcribe the audio file
    print(f"Starting transcription for {file_path} (this may take a while for longer files)...")
    transcribe = transcriber(file_path, generate_kwargs=generate_kwargs)

    # Extract the full text from the chunked transcription
    if isinstance(transcribe, dict) and "text" in transcribe and "chunks" not in transcribe:
         # Simple case - just one chunk/result
         full_text = transcribe["text"]
    elif isinstance(transcribe, dict) and "chunks" in transcribe:
         # Multiple chunks with timestamps
         full_text = " ".join([chunk["text"].strip() for chunk in transcribe["chunks"]])
    elif isinstance(transcribe, str):
         # Some pipeline versions might just return a string
         full_text = transcribe
    else:
         # Fallback for other potential return formats
         full_text = transcribe["text"] if isinstance(transcribe, dict) and "text" in transcribe else str(transcribe)


    # Save the transcribed text to the specified temporary file
    with open(output_file, 'w') as tmp_file:
        tmp_file.write(full_text)
        print(f"Transcription saved to file: {output_file}")

    # Return the transcribed text
    return full_text

# Function to summarize a text using the Ollama model
def summarize_text(text: str) -> str:
    # Define the system prompt for the Ollama model
    system_prompt = "You are a helpful assistant designed to summarize text accurately and concisely."
    # Define the user prompt for the Ollama model
    user_prompt = f"""Generate a concise summary of the text below.
    Text : {text}
    Add a title to the summary using markdown H1 (# Title).
    Make sure your summary has useful and true information about the main points of the topic.
    Begin with a short introduction explaining the topic. If you can, use bullet points to list important details,
    and finish your summary with a concluding sentence."""

    print(f"Sending request to Ollama ({OLLAMA_MODEL}) for summarization...")
    # Use the Ollama model to generate a summary
    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    )
    # Return the generated summary
    return response["message"]["content"]

# Function to ask a specific question about a text using the Ollama model
def ask_question_from_text(text: str, question: str) -> str:
    # Define the system prompt for the Ollama model
    system_prompt = "You are a helpful assistant. Answer the user's question based *only* on the provided text context."
    # Define the user prompt for the Ollama model
    user_prompt = f"""Based on the text below, please answer the following question.
    Text:
    ---
    {text}
    ---

    Question: {question}
    """

    print(f"Sending request to Ollama ({OLLAMA_MODEL}) to answer question...")
    # Use the Ollama model to generate an answer
    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    )
    # Return the generated answer
    return response["message"]["content"]


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Download, transcribe, summarize, or query audio/video/text files.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-youtube", type=str, help="YouTube URL to download and process.")
    group.add_argument("--from-local", type=str, help="Path to the local audio/video file to process.")
    group.add_argument("--from-transcript", type=str, help="Path to a local .txt transcript file to process.")

    parser.add_argument("--output", type=str, default="./summary.md", help="Output markdown file path.")
    parser.add_argument("--transcript-only", action='store_true', help="Only transcribe the file (if applicable), do not summarize or query.")
    parser.add_argument("--language", type=str, help=f"Language code for transcription (e.g., 'en', 'fr', 'es', or 'auto' for detection). Default: {WHISPER_LANGUAGE}")
    parser.add_argument("--with-prompt", type=str, help="Ask a specific question about the transcript (only valid with --from-transcript).")

    args = parser.parse_args()

    # --- Argument Validation ---
    if args.with_prompt and not args.from_transcript:
        parser.error("--with-prompt can only be used with --from-transcript.")
    if args.transcript_only and args.from_transcript:
         print("Warning: --transcript-only has no effect when using --from-transcript.")
         # Allow execution to continue, as the user might just want the transcript copied or validated.
         # Or you could choose to exit:
         # parser.error("--transcript-only cannot be used with --from-transcript.")

    # --- Setup ---
    # Determine language setting
    language = args.language if args.language else WHISPER_LANGUAGE
    if language and language.lower() == "auto":
        language = None  # None triggers automatic language detection in Whisper

    # Set up temporary data directory
    data_directory = Path("tmp")
    # Check if the directory exists, if not, create it
    if not data_directory.exists():
        data_directory.mkdir(parents=True)
        print(f"Created directory: {data_directory}")

    transcript = None
    transcript_source_path = data_directory / "transcript.txt" # Default temp transcript path
    output_title = "# Summary" # Default title for the output file
    llm_result = None # To store the result from Ollama (summary or answer)

    # --- Input Processing ---
    if args.from_youtube:
        # Download from YouTube
        print(f"Downloading YouTube video from {args.from_youtube}")
        try:
            audio_file_path = download_from_youtube(args.from_youtube, str(data_directory))
            print(f"Audio downloaded to: {audio_file_path}")
            print(f"Transcribing file: {audio_file_path}")
            transcript = transcribe_file(str(audio_file_path), str(transcript_source_path), language)
        except Exception as e:
             print(f"Error during YouTube download or transcription: {e}")
             sys.exit(1)

    elif args.from_local:
        # Use local file
        file_path = Path(args.from_local)
        if not file_path.is_file():
            print(f"Error: Local file not found at {file_path}")
            sys.exit(1)
        print(f"Transcribing file: {file_path}")
        try:
            transcript = transcribe_file(str(file_path), str(transcript_source_path), language)
        except Exception as e:
            print(f"Error during local file transcription: {e}")
            sys.exit(1)

    elif args.from_transcript:
        # Use existing transcript file
        transcript_file_path = Path(args.from_transcript)
        if not transcript_file_path.is_file():
            print(f"Error: Transcript file not found at {transcript_file_path}")
            sys.exit(1)
        try:
            print(f"Reading transcript from: {transcript_file_path}")
            with open(transcript_file_path, 'r') as f:
                transcript = f.read()
            transcript_source_path = transcript_file_path # Update source path for reference
        except Exception as e:
            print(f"Error reading transcript file {transcript_file_path}: {e}")
            sys.exit(1)

    # --- LLM Processing (Summarization or Question Answering) ---
    if transcript and not args.transcript_only:
        if args.with_prompt:
            print("Asking specific question...")
            try:
                llm_result = ask_question_from_text(transcript, args.with_prompt)
                output_title = f"# Answer to: {args.with_prompt}"
            except Exception as e:
                print(f"Error getting answer from Ollama: {e}")
                sys.exit(1)
        else:
            print("Generating summary...")
            try:
                llm_result = summarize_text(transcript)
                # Keep default title "# Summary", or let summarize_text handle title if preferred
            except Exception as e:
                print(f"Error generating summary from Ollama: {e}")
                sys.exit(1)

    # --- Output ---
    if args.transcript_only:
        if transcript:
            print(f"Transcription complete. Transcript saved to {transcript_source_path}")
        else:
            print("No transcript was generated (check for errors above).")
        return # Exit after transcription if requested

    if llm_result:
        # Write summary or answer to the output markdown file
        try:
            output_path = Path(args.output)
            # Ensure parent directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as md_file:
                # md_file.write(f"{output_title}\n\n") # Add title if not included by LLM
                md_file.write(llm_result)
            print(f"Output written to {output_path}")
        except Exception as e:
            print(f"Error writing output file {args.output}: {e}")
            sys.exit(1)
    elif transcript:
         print("Transcript generated, but no summary or answer was requested or generated (check for errors).")
    else:
         print("Processing failed. No transcript or summary/answer generated.")


if __name__ == "__main__":
    main()
