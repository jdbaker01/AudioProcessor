"""
Audio File Service abstract base class.
This service provides an interface for retrieving audio files and listing available files.
"""
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import os
import datetime
import mimetypes
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
import io


class AudioFileService(ABC):
    """
    Abstract base class for audio file services.
    
    This class defines the interface for retrieving and listing audio files.
    Implementations of this class should provide concrete implementations
    for accessing audio files from specific storage systems (e.g., local filesystem, S3, etc.).
    """
    
    @abstractmethod
    def get_contents(self, id: str) -> bytes:
        """
        Retrieve the contents of an audio file as a byte array.
        
        Args:
            id (str): The identifier for the audio file to retrieve
            
        Returns:
            bytes: The contents of the audio file as a byte array
            
        Raises:
            FileNotFoundError: If the audio file cannot be found
            PermissionError: If the audio file cannot be accessed due to permissions
        """
        pass
    
    @abstractmethod
    def file_count(self) -> int:
        """
        Get the total number of audio files available.
        
        Returns:
            int: The total count of audio files accessible through this service
            
        Raises:
            ConnectionError: If the service cannot connect to the storage system
        """
        pass
    
    @abstractmethod
    def list(self, num_files: int, page: int) -> List[Dict[str, Any]]:
        """
        List available audio files with pagination.
        
        Args:
            num_files (int): The maximum number of files to return per page
            page (int): The page number (0-indexed) of results to return
            
        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing metadata about each audio file.
                Each dictionary should at minimum contain an 'id' key that can be used with get_contents().
                
        Raises:
            ValueError: If num_files or page are invalid (e.g., negative values)
        """
        pass
    
    @abstractmethod
    def save(self, id: str, content: bytes) -> None:
        """
        Save audio content to storage.
        
        Args:
            id (str): The identifier for the audio file to save
            content (bytes): The audio content as bytes
            
        Raises:
            PermissionError: If the audio file cannot be written due to permissions
            IOError: If there is an error writing the file
        """
        passs


class LocalAudioFileService(AudioFileService):
    """
    Implementation of AudioFileService that uses the local filesystem.
    
    This class provides access to audio files stored in a local directory and its subdirectories.
    """
    
    def __init__(self, base_folder: str, supported_extensions: List[str] = None):
        """
        Initialize the LocalAudioFileService with a base folder.
        
        Args:
            base_folder (str): The path to the folder containing audio files
            supported_extensions (List[str], optional): List of supported file extensions (e.g., ['.mp3', '.wav'])
                If None, common audio extensions will be used.
        """
        self.base_folder = os.path.abspath(base_folder)
        
        if not os.path.exists(self.base_folder):
            raise FileNotFoundError(f"Base folder does not exist: {self.base_folder}")
        
        if not os.path.isdir(self.base_folder):
            raise NotADirectoryError(f"Base path is not a directory: {self.base_folder}")
        
        self.supported_extensions = supported_extensions or ['.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac']
        
        # Initialize file cache
        self._file_cache = None
        self._last_cache_update = None
    
    def _is_audio_file(self, file_path: str) -> bool:
        """
        Check if a file is an audio file based on its extension.
        
        Args:
            file_path (str): Path to the file
            
        Returns:
            bool: True if the file has a supported audio extension, False otherwise
        """
        _, ext = os.path.splitext(file_path)
        return ext.lower() in self.supported_extensions
    
    def _get_relative_path(self, full_path: str) -> str:
        """
        Get the path relative to the base folder.
        
        Args:
            full_path (str): Full path to a file
            
        Returns:
            str: Path relative to the base folder
        """
        return os.path.relpath(full_path, self.base_folder)
    
    def _scan_files(self) -> List[Dict[str, Any]]:
        """
        Scan the base folder and its subdirectories for audio files.
        
        Returns:
            List[Dict[str, Any]]: List of dictionaries containing metadata about each audio file
        """
        files = []
        
        for root, _, filenames in os.walk(self.base_folder):
            for filename in filenames:
                full_path = os.path.join(root, filename)
                
                if self._is_audio_file(full_path):
                    relative_path = self._get_relative_path(full_path)
                    
                    # Get file stats
                    stats = os.stat(full_path)
                    
                    # Get file MIME type
                    mime_type, _ = mimetypes.guess_type(full_path)
                    
                    files.append({
                        'id': relative_path,
                        'name': filename,
                        'path': relative_path,
                        'size': stats.st_size,
                        'created': datetime.datetime.fromtimestamp(stats.st_ctime).isoformat(),
                        'modified': datetime.datetime.fromtimestamp(stats.st_mtime).isoformat(),
                        'mime_type': mime_type or 'application/octet-stream'
                    })
        
        # Sort files by name
        files.sort(key=lambda x: x['name'])
        
        return files
    
    def _get_cached_files(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get the cached list of files, refreshing if necessary.
        
        Args:
            force_refresh (bool): Whether to force a refresh of the cache
            
        Returns:
            List[Dict[str, Any]]: List of dictionaries containing metadata about each audio file
        """
        current_time = datetime.datetime.now()
        cache_age = None
        
        if self._last_cache_update:
            cache_age = (current_time - self._last_cache_update).total_seconds()
        
        # Refresh cache if it's None, force_refresh is True, or cache is older than 5 minutes
        if self._file_cache is None or force_refresh or (cache_age and cache_age > 300):
            self._file_cache = self._scan_files()
            self._last_cache_update = current_time
        
        return self._file_cache
    
    def get_contents(self, id: str) -> bytes:
        """
        Retrieve the contents of an audio file as a byte array.
        
        Args:
            id (str): The relative path to the audio file from the base folder
            
        Returns:
            bytes: The contents of the audio file as a byte array
            
        Raises:
            FileNotFoundError: If the audio file cannot be found
            PermissionError: If the audio file cannot be accessed due to permissions
        """
        full_path = os.path.join(self.base_folder, id)
        
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {id}")
        
        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"Path is not a file: {id}")
        
        if not self._is_audio_file(full_path):
            raise ValueError(f"File is not a supported audio file: {id}")
        
        try:
            with open(full_path, 'rb') as f:
                return f.read()
        except PermissionError:
            raise PermissionError(f"Permission denied when accessing file: {id}")
    
    def file_count(self) -> int:
        """
        Get the total number of audio files available.
        
        Returns:
            int: The total count of audio files in the base folder and its subdirectories
        """
        files = self._get_cached_files()
        return len(files)
    
    def list(self, num_files: int, page: int) -> List[Dict[str, Any]]:
        """
        List available audio files with pagination.
        
        Args:
            num_files (int): The maximum number of files to return per page
            page (int): The page number (0-indexed) of results to return
            
        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing metadata about each audio file
            
        Raises:
            ValueError: If num_files or page are invalid (e.g., negative values)
        """
        if num_files <= 0:
            raise ValueError("num_files must be a positive integer")
        
        if page < 0:
            raise ValueError("page must be a non-negative integer")
        
        files = self._get_cached_files()
        
        # Calculate start and end indices for pagination
        start_idx = page * num_files
        end_idx = start_idx + num_files
        
        # Return empty list if start index is beyond the available files
        if start_idx >= len(files):
            return []
        
        # Return the requested page of files
        return files[start_idx:end_idx]

class S3AudioFileService(AudioFileService):
    """
    Implementation of AudioFileService that uses Amazon S3.
    
    This class provides access to audio files stored in an S3 bucket.
    """
    
    def __init__(self, bucket_name: str, prefix: str = "", region_name: str = None, profile_name: str = None):
        """
        Initialize the S3AudioFileService with a bucket and optional prefix.
        
        Args:
            bucket_name (str): The name of the S3 bucket
            prefix (str, optional): The prefix (folder path) within the bucket. Defaults to "".
            region_name (str, optional): AWS region name. Defaults to None (uses default from AWS config).
            profile_name (str, optional): AWS profile name. Defaults to None (uses default profile).
        """
        self.bucket_name = bucket_name
        self.prefix = prefix.rstrip('/') + '/' if prefix else ""
        
        # Initialize S3 client
        session = boto3.Session(profile_name=profile_name, region_name=region_name)
        self.s3_client = session.client('s3')
        
        # Test connection to bucket
        try:
            self.s3_client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404':
                raise FileNotFoundError(f"S3 bucket not found: {bucket_name}")
            elif error_code == '403':
                raise PermissionError(f"Permission denied for S3 bucket: {bucket_name}")
            else:
                raise ConnectionError(f"Error connecting to S3 bucket: {str(e)}")
        
        # Initialize file cache
        self._file_cache = None
        self._last_cache_update = None
    
    def _is_audio_file(self, key: str) -> bool:
        """
        Check if an S3 object key represents an audio file.
        
        Args:
            key (str): S3 object key
            
        Returns:
            bool: True if the key ends with a common audio extension, False otherwise
        """
        audio_extensions = ('.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma')
        return key.lower().endswith(audio_extensions)
    
    def _get_relative_path(self, key: str) -> str:
        """
        Get the path relative to the prefix.
        
        Args:
            key (str): S3 object key
            
        Returns:
            str: Path relative to the prefix
        """
        if self.prefix and key.startswith(self.prefix):
            return key[len(self.prefix):]
        return key
    
    def _scan_files(self) -> List[Dict[str, Any]]:
        """
        Scan the S3 bucket for audio files.
        
        Returns:
            List[Dict[str, Any]]: List of dictionaries containing metadata about each audio file
        """
        files = []
        paginator = self.s3_client.get_paginator('list_objects_v2')
        
        # List all objects with the given prefix
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=self.prefix):
            if 'Contents' not in page:
                continue
                
            for obj in page['Contents']:
                key = obj['Key']
                
                if self._is_audio_file(key):
                    relative_path = self._get_relative_path(key)
                    name = os.path.basename(key)
                    
                    # Create full S3 URI for the name
                    s3_uri = f"s3://{self.bucket_name}/{key}"
                    
                    # Get MIME type
                    mime_type, _ = mimetypes.guess_type(key)
                    
                    files.append({
                        'id': relative_path,
                        'name': s3_uri,
                        'path': relative_path,
                        'size': obj['Size'],
                        'created': obj.get('LastModified', datetime.datetime.now()).isoformat(),
                        'modified': obj.get('LastModified', datetime.datetime.now()).isoformat(),
                        'mime_type': mime_type or 'audio/mpeg',
                        's3_key': key
                    })
        
        # Sort files by modification time (newest first)
        files.sort(key=lambda x: x['modified'], reverse=True)
        
        return files
    
    def _get_cached_files(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get the cached list of files, refreshing if necessary.
        
        Args:
            force_refresh (bool): Whether to force a refresh of the cache
            
        Returns:
            List[Dict[str, Any]]: List of dictionaries containing metadata about each audio file
        """
        current_time = datetime.datetime.now()
        cache_age = None
        
        if self._last_cache_update:
            cache_age = (current_time - self._last_cache_update).total_seconds()
        
        # Refresh cache if it's None, force_refresh is True, or cache is older than 5 minutes
        if self._file_cache is None or force_refresh or (cache_age and cache_age > 300):
            self._file_cache = self._scan_files()
            self._last_cache_update = current_time
        
        return self._file_cache
    
    def get_contents(self, id: str) -> bytes:
        """
        Retrieve the contents of an audio file from S3 as a byte array.
        
        Args:
            id (str): The relative path to the audio file from the prefix
            
        Returns:
            bytes: The contents of the audio file as a byte array
            
        Raises:
            FileNotFoundError: If the audio file cannot be found
            PermissionError: If the audio file cannot be accessed due to permissions
        """
        # Construct the full S3 key
        key = self.prefix + id if self.prefix else id
        
        try:
            # Get the object from S3
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            
            # Read the content as bytes
            return response['Body'].read()
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'NoSuchKey':
                raise FileNotFoundError(f"File not found in S3: {id}")
            elif error_code == 'AccessDenied':
                raise PermissionError(f"Permission denied when accessing S3 file: {id}")
            else:
                raise e
    
    def file_count(self) -> int:
        """
        Get the total number of audio files available in the S3 bucket.
        
        Returns:
            int: The total count of audio files in the bucket with the given prefix
        """
        files = self._get_cached_files()
        return len(files)
    
    def list(self, num_files: int, page: int) -> List[Dict[str, Any]]:
        """
        List available audio files in the S3 bucket with pagination.
        
        Args:
            num_files (int): The maximum number of files to return per page
            page (int): The page number (0-indexed) of results to return
            
        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing metadata about each audio file
            
        Raises:
            ValueError: If num_files or page are invalid (e.g., negative values)
        """
        if num_files <= 0:
            raise ValueError("num_files must be a positive integer")
        
        if page < 0:
            raise ValueError("page must be a non-negative integer")
        
        files = self._get_cached_files()
        
        # Calculate start and end indices for pagination
        start_idx = page * num_files
        end_idx = start_idx + num_files
        
        # Return empty list if start index is beyond the available files
        if start_idx >= len(files):
            return []
        
        # Return the requested page of files
        return files[start_idx:end_idx]
    
    def save(self, id: str, content: bytes) -> None:
        """
        Save audio content to S3.
        
        Args:
            id (str): The relative path to the audio file from the prefix
            content (bytes): The audio content as bytes
            
        Raises:
            PermissionError: If the audio file cannot be written due to permissions
        """
        # Construct the full S3 key
        key = self.prefix + id if self.prefix else id
        
        # Determine content type based on file extension
        content_type, _ = mimetypes.guess_type(id)
        if not content_type:
            content_type = 'audio/mpeg'  # Default to audio/mpeg if we can't determine the type
        
        try:
            # Upload the audio content to S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=content,
                ContentType=content_type
            )
            
            # Invalidate cache
            self._file_cache = None
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'AccessDenied':
                raise PermissionError(f"Permission denied when writing to S3: {id}")
            else:
                raise e
