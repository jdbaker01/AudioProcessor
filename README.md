# AudioProcessor

A Streamlit application for uploading, transcribing, and analyzing audio files.

## Features

- **Upload Audio**: Upload audio files (WAV, MP3, OGG) and visualize their waveforms and spectrograms
- **Process Audio**: 
  - Transcribe audio using faster-whisper model
  - Generate summaries using Amazon Bedrock Claude
  - Extract action items using Amazon Bedrock Claude
- **View Processed Audio**: Browse and download processed audio files, transcriptions, summaries, and action items

## Setup and Installation

1. Clone this repository
2. Create and activate the virtual environment:

```bash
# On macOS/Linux
python3 -m venv venv
source venv/bin/activate

# On Windows
python -m venv venv
venv\Scripts\activate
```

3. Install the required packages:

```bash
pip install -r requirements.txt
```

4. Configure AWS credentials for Amazon Bedrock:
   - Ensure you have AWS credentials configured with access to Amazon Bedrock
   - You can configure credentials using `aws configure` or environment variables

5. Run the application:

```bash
streamlit run app.py
```

## Transcription and Analysis

The application provides two main processing capabilities:

### 1. Audio Transcription
Uses faster-whisper for audio transcription with multiple model options:
- **tiny**: Fastest, lowest accuracy
- **base**: Good balance of speed and accuracy for most use cases
- **small**: Better accuracy, slower than base
- **medium**: High accuracy, slower processing
- **large-v3**: Highest accuracy, slowest processing

### 2. AI Analysis with Claude
Uses Amazon Bedrock Claude models to:
- **Summarize Audio**: Generate concise summaries of the transcribed content
- **List Action Items**: Extract actionable items from the transcribed content

Available Claude models:
- Claude 3 Sonnet
- Claude 3 Haiku
- Claude 3 Opus

## Project Structure

```
AudioProcessor/
├── app.py                 # Main Streamlit application
├── requirements.txt       # Project dependencies
├── audio_files/           # Directory for uploaded audio files
└── processed_files/       # Directory for processed files (transcriptions, summaries, etc.)
```

## Dependencies

- streamlit: Web application framework
- librosa: Audio processing library
- numpy: Numerical computing
- pandas: Data manipulation
- matplotlib: Data visualization
- faster-whisper: Audio transcription
- boto3: AWS SDK for Python (for Amazon Bedrock integration)
