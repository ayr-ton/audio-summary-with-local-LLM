[![CI](https://github.com/ayr-ton/audio-summary-with-local-LLM/actions/workflows/ci.yml/badge.svg)](https://github.com/ayr-ton/audio-summary-with-local-LLM/actions/workflows/ci.yml)
# Audio Summary with Local LLM

This tool is designed to provide a quick and concise summary of audio and video files. It supports summarizing content either from a local file or directly from YouTube. The tool uses Whisper for transcription and a local LLM (via Ollama) for generating summaries. The default model is `gpt-oss:120b`.

> [!TIP]
> It is possible to change the model you wish to use.
> To do this, change the `OLLAMA_MODEL` variable, and download the associated model via [ollama](https://github.com/ollama/ollama)

## Features

- **YouTube Integration**: Download and summarize content directly from YouTube.
- **Local File Support**: Summarize audio/video files available on your local disk.
- **Transcription**: Converts audio content to text using Whisper.
- **Summarization**: Generates a concise summary using GPT-OSS:120b (via Ollama).
- **Transcript Only Option**: Option to only transcribe the audio content without generating a summary.
- **Question Answering**: Extract answers from the context of a provided transcript.
- **Device Optimization**: Automatically uses the best available hardware (MPS for Mac, CUDA for NVIDIA GPUs, or CPU).

## Prerequisites

Before you start using this tool, you need to install the following dependencies:

- Python 3.12 and lower than 3.13
- [Ollama](https://ollama.com) for LLM model management
- `ffmpeg` (required for audio processing)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for package management

## Installation

### Using uv (Recommended for Development)

Clone the repository and install the required Python packages using [uv](https://github.com/astral-sh/uv):

```bash
git clone https://github.com/damienarnodo/audio-summary-with-local-LLM.git
cd audio-summary-with-local-LLM

# Create and activate a virtual environment with uv
uv sync
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Run with uv
uv run audio-summary [OPTIONS]
```

### Using pipx (Recommended for Global CLI Access)

For a global command-line tool that stays updated with the latest code:

1. Clone the repository:

```bash
git clone https://github.com/damienarnodo/audio-summary-with-local-LLM.git
cd audio-summary-with-local-LLM
```

2. Install with pipx in editable mode:
   ([install pipx](https://pipx.pypa.io/latest/installation/) if needed)

```bash
pipx install -e .
```

3. To update, just run `git pull` inside the repository directory. No pip commands needed again.

### LLM Requirement

[Download and install](https://ollama.com) Ollama to carry out LLM Management. More details about LLM models supported can be found on the Ollama [GitHub](https://github.com/ollama/ollama).

Download and use the default model (gpt-oss:120b):

```bash
ollama pull gpt-oss:20b

# Test the access:
ollama run gpt-oss:20b "which tools do you have available?"
```

### Ollama Cloud Configuration (Optional)

The tool supports both local Ollama and Ollama Cloud. By default, it connects to `http://localhost:11434`. To use Ollama Cloud:

**1. Set environment variables:**

```bash
export OLLAMA_HOST="https://ollama.com"
export OLLAMA_API_KEY="your-api-key-here"
```

**2. Add to your shell profile (e.g., ~/.bashrc or ~/.zshrc):**

```bash
echo 'export OLLAMA_HOST="https://ollama.com"' >> ~/.bashrc
echo 'export OLLAMA_API_KEY="your-api-key-here"' >> ~/.bashrc
source ~/.bashrc
```

**3. Verify configuration:**

```bash
ollama list  # Should show your cloud models
```

**Environment Variables:**
- `OLLAMA_HOST` - Ollama server URL (default: `http://localhost:11434`)
- `OLLAMA_API_KEY` - API key for Ollama Cloud authentication

### Granular Remote Execution (Advanced)

Execute each stage of the pipeline on either local or remote machines, allowing flexible hybrid workflows.

**Remote Flags:**
- `--remote-download` - Download YouTube video on remote machine
- `--remote-transcription` - Run Whisper transcription on remote machine
- `--remote-summarize` - Run Ollama summarization on remote machine
- `--remote-transcribe` - Shorthand for `--remote-download --remote-transcription`

**Remote Configuration:**
- `--remote-host <HOST>` - Specify remote host (required if using remote flags without config)
- `--remote-path <PATH>` - Path to audio-summary installation on remote
- `--remote-user <USER>` - SSH username for remote
- `--dry-run` - Show what would be executed without running

### Setup

**1. Configure SSH Key Authentication:**
```bash
# Generate SSH key if you don't have one
ssh-keygen -t ed25519 -C "audio-summary"

# Copy key to remote host
ssh-copy-id user@remote-host

# Test connection
ssh user@remote-host "echo 'Connected!'"
```

**2. Create Configuration File (Optional but Recommended):**

Create `~/.config/audio-summary/config.yaml`:

```yaml
# Audio Summary Remote Configuration
remotes:
  gpu-server:
    host: gpu-server.local
    user: tom
    path: /home/tom/projects/audio-summary
    ssh_key: ~/.ssh/id_ed25519
    max_retries: 3
```

### Examples

**Example 1: Download on Remote (Local Transcribe + Summarize)**
```bash
# Download remotely, transcribe and summarize locally
audio-summary --from-youtube "<URL>" --remote-download
```

**Example 2: Transcribe on Remote (Local Download, Remote Transcribe)**
```bash
# Download locally, transcribe remotely, summarize locally
audio-summary --from-youtube "<URL>" --remote-transcription
```

**Example 3: Remote Transcribe Only (Upload Local MP3)**
```bash
# Upload local MP3 to remote, transcribe remotely, download transcript
audio-summary --from-local "./file.mp3" --remote-transcription
```

**Example 4: Remote Summarize Only**
```bash
# Upload transcript to remote, summarize remotely, download markdown
audio-summary --from-transcript "./file.txt" --remote-summarize
```

**Example 5: Remote Download + Transcribe (Shorthand)**
```bash
# Same as --remote-download --remote-transcription
audio-summary --from-youtube "<URL>" --remote-transcribe
```

**Example 6: Full Remote Pipeline**
```bash
# Download, transcribe, and summarize all on remote
audio-summary --from-youtube "<URL>" --remote-transcribe --remote-summarize
```

**Example 7: Ad-hoc Remote (No Config File)**
```bash
# Use remote without creating config file
audio-summary --from-youtube "<URL>" \
  --remote-host gpu-server.local \
  --remote-user tom \
  --remote-path /home/tom/audio-summary \
  --remote-transcribe
```

**Example 8: Dry Run (Test Configuration)**
```bash
# Show what would be executed without actually running
audio-summary --from-youtube "<URL>" --remote-transcribe --dry-run
```

### Hardware Security Keys (FIDO2/U2F)

This tool supports hardware security keys (e.g., YubiKey) with SSH:

**Supported keys:**
- `id_ecdsa_sk` (ECDSA-SK keys)
- `id_ed25519_sk` (ED25519-SK keys)

**Configuration:**
Simply specify your hardware key in the config file:
```yaml
remotes:
  dave:
    host: dave.local
    user: tom
    path: /home/tom/audio-summary
    ssh_key: ~/.ssh/id_ecdsa_sk  # Hardware key
    max_retries: 3
```

The tool automatically detects hardware keys and uses subprocess-based SSH/SCP instead of paramiko to avoid compatibility issues.

### File Existence Checks

The tool automatically checks for existing files before processing:

- **MP3 files:** Checked in `Attachments/` before downloading from YouTube
- **Transcripts:** Checked before running Whisper transcription
- **Markdown:** Checked before LLM summarization

**Behavior:**
- If file exists **locally** → Skips the step and notifies you
- If file exists **on remote** → Downloads existing file instead of regenerating
- Remote checks look in `Attachments/` directory only

## Usage

The tool offers multiple input options:

```bash
audio-summary [OPTIONS]
```

### Options

- **Input Sources**:
  - `--from-youtube <URL>`: Process audio from YouTube.
  - `--from-local <PATH>`: Use a local audio/video file.
  - `--from-transcript <PATH>`: Read and process an existing transcript file.

- **Output Options**:
  - `--output <FILE>`: Specify output path (default: ./summary.md).
  - `--append`: Append to existing file instead of overwriting.
  - `--transcript-only`: Only transcribe without summarizing.

- **Language Support**:
  - `--language <CODE>`: Set transcription language (e.g., 'en', 'fr') or use auto-detection.

- **Question Answering**:
  - `--with-prompt <QUESTION>`: Ask a specific question about the transcript.

### Examples

1. **Summarizing a YouTube video:**

   ```bash
   audio-summary --from-youtube <YouTube-Video-URL>
   ```

2. **Summarizing a local audio file:**

   ```bash
   audio-summary --from-local <path-to-audio-file>
   ```

3. **Transcribing a YouTube video without summarizing:**

   ```bash
   audio-summary --from-youtube <YouTube-Video-URL> --transcript-only
   ```

4. **Transcribing a local audio file without summarizing:**

   ```bash
   audio-summary --from-local <path-to-audio-file> --transcript-only
   ```

5. **Process transcript file**:

   ```bash
   audio-summary --from-transcript "transcript.txt"
   ```

6. **Answer a specific question from transcript**:

   ```bash
   audio-summary --from-transcript "transcript.txt" --with-prompt "What is the main topic?"
   ```

6. **Specifying a custom output file:**

   ```bash
   audio-summary --from-youtube <YouTube-Video-URL> --output my_summary.md
   ```

The output summary will be saved in a markdown file in the specified output directory, while the transcript will be saved in the `Attachments/` directory.

## Output

The summarized content is saved as a markdown file (default: `summary.md`) in the current working directory. This file includes a title and a concise summary of the content. The transcript is saved in the `Attachments/` directory.

## Hardware Acceleration

The tool automatically detects and uses the best available hardware:

- MPS (Metal Performance Shaders) for Apple Silicon Macs
- CUDA for NVIDIA GPUs
- Falls back to CPU when neither is available

### Handling Longer Audio Files

This tool can process audio files of any length. For files longer than 30 seconds, the script automatically:

1. Chunks the audio into manageable segments
2. Processes each chunk separately
3. Combines the results into a single transcript

## Sources

- [YouTube Video Summarizer with OpenAI Whisper and GPT](https://github.com/mirabdullahyaser/Summarizing-Youtube-Videos-with-OpenAI-Whisper-and-GPT-3/tree/master)
- [Ollama GitHub Repository](https://github.com/ollama/ollama)
- [Transformers by Hugging Face](https://huggingface.co/docs/transformers/index)
- [yt-dlp Documentation](https://github.com/yt-dlp/yt-dlp)

## Troubleshooting

### ffmpeg not found

If you encounter this error::

```bash
yt_dlp.utils.DownloadError: ERROR: Postprocessing: ffprobe and ffmpeg not found. Please install or provide the path using --ffmpeg-location
```

Please refer to [this post](https://www.reddit.com/r/StacherIO/wiki/ffmpeg/?utm_source=share&utm_medium=web3x&utm_name=web3xcss&utm_term=1&utm_content=share_button)

### Audio Format Issues

If you encounter this error:

```bash
ValueError: Soundfile is either not in the correct format or is malformed. Ensure that the soundfile has a valid audio file extension (e.g. wav, flac or mp3) and is not corrupted.
```

Try converting your file with ffmpeg:

```bash
ffmpeg -i my_file.mp4 -movflags faststart my_file_fixed.mp4
```

### Memory Issues on CPU

If you're running on CPU and encounter memory issues during transcription, consider:

1. Using a smaller Whisper model
2. Processing shorter audio segments
3. Ensuring you have sufficient RAM available

### Slow Transcription

Transcription can be slow on CPU. For best performance:

1. Use a machine with GPU or Apple Silicon (MPS)
2. Keep audio files under 10 minutes when possible
3. Close other resource-intensive applications

### Update the Whisper or LLM Model

You can easily change the models used for transcription and summarization by modifying the variables at the top of the script:

```python
# Default models
OLLAMA_MODEL = "gpt-oss:120b"
WHISPER_MODEL = "openai/whisper-large-v2"
```

#### Changing the Whisper Model

To use a different Whisper model for transcription:

1. Update the `WHISPER_MODEL` variable with one of these options:
   - `"openai/whisper-tiny"` (fastest, least accurate)
   - `"openai/whisper-base"` (faster, less accurate)
   - `"openai/whisper-small"` (balanced)
   - `"openai/whisper-medium"` (slower, more accurate)
   - `"openai/whisper-large-v2"` (slowest, most accurate)

2. Example:

   ```python
   WHISPER_MODEL = "openai/whisper-medium"  # A good balance between speed and accuracy
   ```

For CPU-only systems, using a smaller model like `whisper-base` is recommended for better performance.

#### Changing the LLM Model

To use a different model for summarization:

1. First, pull the desired model with Ollama:

   ```bash
   ollama pull mistral  # or any other supported model
   ```

2. Then update the `OLLAMA_MODEL` variable:

   ```python
   OLLAMA_MODEL = "mistral"  # or any other model you've pulled
   ```

3. Popular alternatives include:
   - `"gpt-oss:120b"` (default)
   - `"llama3"`
   - `"mistral"`
   - `"llama2"`
   - `"gemma:7b"`
   - `"phi"`

For a complete list of available models, visit the [Ollama model library](https://ollama.com/library).
