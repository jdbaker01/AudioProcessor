import streamlit as st
import os
import librosa
import librosa.display
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from io import BytesIO
import boto3
import json
import soundfile as sf
import tempfile
from faster_whisper import WhisperModel
from pydub import AudioSegment

from AudioTranscriptionService import AudioTranscriptionService
from AudioFileService import LocalAudioFileService, S3AudioFileService
from JSONFileService import LocalJSONFileService, S3JSONFileService

import uuid
import os

# Get bucket names from environment variables - raise error if not set
try:
    audio_bucket = os.environ["MY_S3_AUDIO_BUCKET"]
    results_bucket = os.environ["MY_S3_RESULTS_BUCKET"]
except KeyError as e:
    raise RuntimeError(f"Required environment variable {e} is not set") from e

audio_file_service = S3AudioFileService(audio_bucket)
processed_file_service = S3JSONFileService(results_bucket)

# Set page configuration
st.set_page_config(
    page_title="Audio Processor",
    page_icon="🎵",
    layout="wide"
)

hide_menu_style = """<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;}</style>"""
st.markdown(hide_menu_style, unsafe_allow_html=True)

# Initialize session state for persistent settings
if 'selected_file' not in st.session_state:
    st.session_state.selected_file = None

# Initialize AI configuration in session state
if 'whisper_model' not in st.session_state:
    st.session_state.whisper_model = "base"
    
if 'claude_model' not in st.session_state:
    st.session_state.claude_model = "anthropic.claude-3-sonnet-20240229-v1:0"
    
if 'summary_prompt' not in st.session_state:
    st.session_state.summary_prompt = """
    Please provide a concise summary of the following transcript:\n\n{text}\n\nSummary:
    """

if 'action_items_prompt' not in st.session_state:
    st.session_state.action_items_prompt = """
    Please extract a list of action items from the following transcript and format as a json array.
    Each json object should have an assignee and a task. If there is no assignee then use "none". 
    If there are no action items then output an empty json array.
    Format them as a json array:\n\n{text}\n\n Action Items: [
    """

# Create directories if they don't exist
os.makedirs("audio_files", exist_ok=True)
os.makedirs("processed_files", exist_ok=True)

def save_uploaded_file(uploaded_file):
    """Save the uploaded audio file using the audio_file_service"""
    try:
        # Read the file content and convert memoryview to bytes
        file_content = bytes(uploaded_file.getbuffer())
        
        # Save the file using the service
        audio_file_service.save(uploaded_file.name, file_content)
        
        return uploaded_file.name
    except Exception as e:
        st.error(f"Error saving file: {str(e)}")
        return None

def transcribe_audio(file_path):
    """Transcribe audio using faster-whisper model"""
    try:
        # Get the filename without extension
        filename = os.path.basename(file_path)
        name, ext = os.path.splitext(filename)
        
        # Get the model name from session state
        model_name = st.session_state.whisper_model
        
        # Load the Whisper model
        with st.spinner(f"Loading Whisper {model_name} model..."):
            # Use CPU or CUDA if available
            transcription_service = AudioTranscriptionService(model_name=model_name)
        
        # Transcribe the audio
        with st.spinner("Transcribing audio..."):
            transcription, detailed_transcription = transcription_service.transcribe(file_path, "file")
        
        # Save the transcription to a text file
        guid = str(uuid.uuid4())
        transcription_path = os.path.join("processed_files", f"{guid}.json")
        transcription_data = {
            "transcription": transcription,
            "detailed_transcription": detailed_transcription,
            "model_name": f"whisper[{model_name}]",
            "created_ts":  pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "filename": filename,
            "file_path": file_path
        }
        with open(transcription_path, "w") as f:
            json.dump(transcription_data, f, indent=4)

        return transcription_path, transcription
    
    except Exception as e:
        st.error(f"Error transcribing audio: {e}")
        return None, str(e)

def process_with_bedrock(text, task, model_id):
    """Process text with Amazon Bedrock Claude model"""
    try:
        # Create a Bedrock client
        bedrock_runtime = boto3.client(
            service_name='bedrock-runtime',
            region_name='us-east-1'  # Change to your preferred region
        )
        
        # Prepare the prompt based on the task
        if task == "summarize":
            prompt = st.session_state.summary_prompt.format(text=text)
        elif task == "action_items":
            prompt = st.session_state.action_items_prompt.format(text=text)
        else:
            return "Invalid task specified"
        
        # Prepare the request for Claude
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }
        
        # Invoke the model
        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            body=json.dumps(request_body)
        )

        if task == "action_items":
            try:
                # Parse the response
                response_body = json.loads(response['body'].read().decode('utf-8'))

                # Initialize result with the default value
                result = "[{\"Assignee\": \"None\", \"Task\":\"\"}]"

                # Extract the text content if available
                if "content" in response_body:
                    if len(response_body["content"]) > 0 and "text" in response_body["content"][0]:
                        text_content = response_body['content'][0]['text']
                        if "Action Items:" in text_content:
                            result = text_content.replace("Action Items:", "").strip()

                # Convert the string to a Python list
                action_items = json.loads(result)
                return action_items
            except Exception as e:
                # If anything fails, return the default value
                print(f"Error processing action items: {str(e)}")
                return json.loads("[{\"Assignee\": \"None\", \"Task\":\"\"}]")
        else:
            # Parse the response
            response_body = json.loads(response['body'].read().decode('utf-8'))
            result = response_body['content'][0]['text']
        
        return result
    
    except Exception as e:
        st.error(f"Error processing with Bedrock: {e}")
        return str(e)

def format_timestamp(seconds):
    """Format seconds into HH:MM:SS.mmm format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

def display_audio_waveform(file_path):
    """Display the waveform of an audio file"""
    y, sr = librosa.load(file_path)
    
    fig, ax = plt.subplots(figsize=(10, 4))
    librosa.display.waveshow(y, sr=sr, ax=ax)
    ax.set_title('Waveform')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Amplitude')
    
    return fig

def display_spectrogram(file_path):
    """Display the spectrogram of an audio file"""
    y, sr = librosa.load(file_path)
    
    # Compute spectrogram
    D = librosa.amplitude_to_db(np.abs(librosa.stft(y)), ref=np.max)
    
    fig, ax = plt.subplots(figsize=(10, 4))
    img = librosa.display.specshow(D, x_axis='time', y_axis='log', ax=ax)
    ax.set_title('Spectrogram')
    fig.colorbar(img, ax=ax, format="%+2.0f dB")
    
    return fig

def main():
    st.title("Audio Processor")
    
    # Create tabs
    uploadAudioTab, processAudioTab, viewAudioTab, aiConfigTab = st.tabs(["Upload Audio", "Process Audio", "View Processed Audio", "AI Configuration"])
    
    # Tab 1: Upload Audio
    with uploadAudioTab:
        st.header("Upload Audio Files")
        
        uploaded_file = st.file_uploader("Choose an audio file", type=["wav", "mp3", "ogg"])
        
        if uploaded_file is not None:
            st.success(f"File {uploaded_file.name} uploaded successfully!")
            
            # Save the uploaded file
            file_path = save_uploaded_file(uploaded_file)
            
            # Display audio player
            st.audio(uploaded_file)
    
    # Tab 2: Process Audio
    with processAudioTab:
        st.header("Process Audio Files")
        
        # Get list of uploaded audio files using the audio_file_service
        files_data = audio_file_service.list(num_files=100, page=0)  # Get first 100 files
        audio_files = [file_data['name'] for file_data in files_data]
        
        if not audio_files:
            st.info("No audio files uploaded yet. Please upload files in the 'Upload Audio' tab.")
        else:
            # Select file to process
            selected_file = st.selectbox("Select audio file to process", audio_files)
            
            # Get the file ID from the name
            selected_file_data = next((file_data for file_data in files_data if file_data['name'] == selected_file), None)
            
            if selected_file_data:
                # Get the file contents using the service
                file_content = audio_file_service.get_contents(selected_file_data['id'])
                
                # Create a temporary file for displaying in the audio player
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(selected_file)[1]) as tmp_file:
                    tmp_file.write(file_content)
                    tmp_path = tmp_file.name
                
                # Display audio player for selected file
                st.audio(tmp_path)

                # Store the file ID in session state for later use
                st.session_state.selected_file_id = selected_file_data['id']
            
            # Post-processing options
            st.markdown("### Post-processing Options")
            
            # Create a styled container for the checkboxes
            with st.container():
                # Create a box around the checkboxes
                with st.expander("AI Analysis Options", expanded=True):
                    summarize = st.checkbox("Summarize Audio", value=True)
                    action_items = st.checkbox("List Action Items", value=True)
            
            # Transcribe button
            if st.button("Transcribe Audio"):
                # Get the file ID from session state
                file_id = st.session_state.selected_file_id
                
                # Create a temporary file for processing
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(selected_file)[1]) as tmp_file:
                    tmp_file.write(audio_file_service.get_contents(file_id))
                    temp_file_path = tmp_file.name
                
                # Transcribe the temporary file
                transcription_path, transcription = transcribe_audio(temp_file_path)
                
                if transcription_path:
                    st.success(f"Audio transcribed successfully! Saved as {os.path.basename(transcription_path)}")
                    
                    # Display transcription
                    st.subheader("Transcription Result")
                    st.text_area("Transcription", transcription, height=200)

                    # Process with Bedrock if requested
                    if summarize:
                        with st.spinner("Generating summary with Claude..."):
                            summary = process_with_bedrock(transcription, "summarize", st.session_state.claude_model)
                            # Save summary
                            with open(transcription_path, "r") as f:
                                data = json.load(f)
                            data["summary"] = summary
                            with open(transcription_path, "w") as f:
                                json.dump(data, f, indent=4)

                            # Display summary
                            st.subheader("Summary")
                            st.text_area("Summary of Audio", summary, height=200)

                    if action_items:
                        with st.spinner("Extracting action items with Claude..."):
                            actions = process_with_bedrock(transcription, "action_items", st.session_state.claude_model)
                            
                            # Save action items
                            with open(transcription_path, "r") as f:
                                data = json.load(f)
                            data["action_items"] = actions
                            with open(transcription_path, "w") as f:
                                json.dump(data, f, indent=4)

                            # Display action items
                            st.subheader("Action Items")
                            st.text_area("Action Items from Audio", actions, height=200)

    
    # Tab 3: View Processed Audio
    with viewAudioTab:
        st.header("View Processed Audio Files")
        
        # Get list of all processed audio files using the processed_file_service
        processed_files_data = processed_file_service.list(num_files=100, page=0)
        
        # Filter for JSON files only
        json_files = [file_data for file_data in processed_files_data if file_data['path'].endswith('.json')]
        
        for file_data in json_files:
            try:
                # Use the service to get the file contents instead of opening directly
                data = processed_file_service.get_contents(file_data['id'])
                
                with st.container(border=True):
                    # Display a simplified name (without the s3:// prefix if it exists)
                    display_name = file_data['name']
                    if display_name.startswith('s3://'):
                        # Extract just the filename from the S3 path
                        display_name = os.path.basename(display_name.split('/')[-1])
                    
                    st.header(display_name)
                    st.write(data["filename"])
                    st.subheader("Summary")
                    st.write(data["summary"])
                    st.subheader(f"Action Items")
                    st.json(data["action_items"])
            except Exception as e:
                st.error(f"Error loading file {file_data['name']}: {str(e)}")


        if not processed_files_data:
            st.info("No audio files found. Please upload files in the 'Upload Audio' tab.")
        else:
            # Create two columns layout
            col1, col2 = st.columns([1, 2])
            

    # Tab 4: AI Configuration
    with aiConfigTab:
        st.header("AI Configuration")
        
        # Create two columns for the configuration
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("Whisper Configuration")
            
            # Whisper model selection
            st.session_state.whisper_model = st.selectbox(
                "Select Whisper model",
                ["tiny", "base", "small", "medium", "large-v3"],
                index=["tiny", "base", "small", "medium", "large-v3"].index(st.session_state.whisper_model),
                key="whisper_model_select"
            )
        
        with col2:
            st.subheader("Claude Configuration")
            
            # Claude model selection
            st.session_state.claude_model = st.selectbox(
                "Select Claude model",
                [
                    "anthropic.claude-3-sonnet-20240229-v1:0",
                    "anthropic.claude-3-haiku-20240307-v1:0",
                    "anthropic.claude-3-opus-20240229-v1:0"
                ],
                index=["anthropic.claude-3-sonnet-20240229-v1:0", "anthropic.claude-3-haiku-20240307-v1:0", "anthropic.claude-3-opus-20240229-v1:0"].index(st.session_state.claude_model)
            )
        
        # Prompt configuration
        st.subheader("Prompt Templates")
        
        # Summary prompt
        st.markdown("#### Summary Prompt")
        st.session_state.summary_prompt = st.text_area(
            "Template for generating summaries",
            value=st.session_state.summary_prompt,
            height=150,
            help="Use {text} as a placeholder for the transcript"
        )
        
        # Action items prompt
        st.markdown("#### Action Items Prompt")
        st.session_state.action_items_prompt = st.text_area(
            "Template for extracting action items",
            value=st.session_state.action_items_prompt,
            height=150,
            help="Use {text} as a placeholder for the transcript"
        )
        
        # Save configuration button
        if st.button("Save Configuration"):
            st.success("AI configuration saved successfully!")
            st.balloons()

if __name__ == "__main__":
    main()
