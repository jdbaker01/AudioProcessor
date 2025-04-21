"""
JSON File Service for managing JSON files.
This service provides an interface for retrieving and listing JSON files.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import os
import json
import datetime
import mimetypes
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
import io


class JSONFileService(ABC):
    """
    Abstract base class for JSON file services.
    
    This class defines the interface for retrieving and listing JSON files.
    Implementations of this class should provide concrete implementations
    for accessing JSON files from specific storage systems (e.g., local filesystem, S3, etc.).
    """
    
    @abstractmethod
    def get_contents(self, id: str) -> Dict[str, Any]:
        """
        Retrieve the contents of a JSON file as a dictionary.
        
        Args:
            id (str): The identifier for the JSON file to retrieve
            
        Returns:
            Dict[str, Any]: The parsed JSON content as a dictionary
            
        Raises:
            FileNotFoundError: If the JSON file cannot be found
            PermissionError: If the JSON file cannot be accessed due to permissions
            json.JSONDecodeError: If the file contains invalid JSON
        """
        pass
    
    @abstractmethod
    def file_count(self) -> int:
        """
        Get the total number of JSON files available.
        
        Returns:
            int: The total count of JSON files accessible through this service
            
        Raises:
            ConnectionError: If the service cannot connect to the storage system
        """
        pass
    
    @abstractmethod
    def list(self, num_files: int, page: int) -> List[Dict[str, Any]]:
        """
        List available JSON files with pagination.
        
        Args:
            num_files (int): The maximum number of files to return per page
            page (int): The page number (0-indexed) of results to return
            
        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing metadata about each JSON file.
                Each dictionary should at minimum contain an 'id' key that can be used with get_contents().
                
        Raises:
            ValueError: If num_files or page are invalid (e.g., negative values)
        """
        pass
    
    @abstractmethod
    def save(self, id: str, data: Dict[str, Any]) -> None:
        """
        Save a dictionary as a JSON file.
        
        Args:
            id (str): The identifier for the JSON file to save
            data (Dict[str, Any]): The dictionary to save as JSON
            
        Raises:
            PermissionError: If the JSON file cannot be written due to permissions
            TypeError: If the data cannot be serialized to JSON
        """
        pass


class LocalJSONFileService(JSONFileService):
    """
    Implementation of JSONFileService that uses the local filesystem.
    
    This class provides access to JSON files stored in a local directory and its subdirectories.
    """
    
    def __init__(self, base_folder: str):
        """
        Initialize the LocalJSONFileService with a base folder.
        
        Args:
            base_folder (str): The path to the folder containing JSON files
        """
        self.base_folder = os.path.abspath(base_folder)
        
        if not os.path.exists(self.base_folder):
            os.makedirs(self.base_folder, exist_ok=True)
        
        if not os.path.isdir(self.base_folder):
            raise NotADirectoryError(f"Base path is not a directory: {self.base_folder}")
        
        # Initialize file cache
        self._file_cache = None
        self._last_cache_update = None
    
    def _is_json_file(self, file_path: str) -> bool:
        """
        Check if a file is a JSON file based on its extension.
        
        Args:
            file_path (str): Path to the file
            
        Returns:
            bool: True if the file has a .json extension, False otherwise
        """
        return file_path.lower().endswith('.json')
    
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
        Scan the base folder and its subdirectories for JSON files.
        
        Returns:
            List[Dict[str, Any]]: List of dictionaries containing metadata about each JSON file
        """
        files = []
        
        for root, _, filenames in os.walk(self.base_folder):
            for filename in filenames:
                full_path = os.path.join(root, filename)
                
                if self._is_json_file(full_path):
                    relative_path = self._get_relative_path(full_path)
                    
                    # Get file stats
                    stats = os.stat(full_path)
                    
                    # Try to read the first few keys from the JSON file
                    preview = {}
                    try:
                        with open(full_path, 'r') as f:
                            data = json.load(f)
                            # Get up to 3 top-level keys for preview
                            preview = {k: data[k] for k in list(data.keys())[:3] if not isinstance(data[k], (dict, list))}
                    except (json.JSONDecodeError, IOError):
                        # If we can't read the file or it's not valid JSON, just skip the preview
                        pass
                    
                    files.append({
                        'id': relative_path,
                        'name': filename,
                        'filename': data["filename"],
                        'path': relative_path,
                        'size': stats.st_size,
                        'created': datetime.datetime.fromtimestamp(stats.st_ctime).isoformat(),
                        'modified': datetime.datetime.fromtimestamp(stats.st_mtime).isoformat(),
                        'preview': preview
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
            List[Dict[str, Any]]: List of dictionaries containing metadata about each JSON file
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
    
    def get_contents(self, id: str) -> Dict[str, Any]:
        """
        Retrieve the contents of a JSON file as a dictionary.
        
        Args:
            id (str): The relative path to the JSON file from the base folder
            
        Returns:
            Dict[str, Any]: The parsed JSON content as a dictionary
            
        Raises:
            FileNotFoundError: If the JSON file cannot be found
            PermissionError: If the JSON file cannot be accessed due to permissions
            json.JSONDecodeError: If the file contains invalid JSON
        """
        full_path = os.path.join(self.base_folder, id)
        
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {id}")
        
        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"Path is not a file: {id}")
        
        if not self._is_json_file(full_path):
            raise ValueError(f"File is not a JSON file: {id}")
        
        try:
            with open(full_path, 'r') as f:
                return json.load(f)
        except PermissionError:
            raise PermissionError(f"Permission denied when accessing file: {id}")
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Invalid JSON in file {id}: {str(e)}", e.doc, e.pos)
    
    def file_count(self) -> int:
        """
        Get the total number of JSON files available.
        
        Returns:
            int: The total count of JSON files in the base folder and its subdirectories
        """
        files = self._get_cached_files()
        return len(files)
    
    def list(self, num_files: int, page: int) -> List[Dict[str, Any]]:
        """
        List available JSON files with pagination.
        
        Args:
            num_files (int): The maximum number of files to return per page
            page (int): The page number (0-indexed) of results to return
            
        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing metadata about each JSON file
            
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
    
    def save(self, id: str, data: Dict[str, Any]) -> None:
        """
        Save a dictionary as a JSON file.
        
        Args:
            id (str): The relative path to the JSON file from the base folder
            data (Dict[str, Any]): The dictionary to save as JSON
            
        Raises:
            PermissionError: If the JSON file cannot be written due to permissions
            TypeError: If the data cannot be serialized to JSON
        """
        full_path = os.path.join(self.base_folder, id)
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(full_path)), exist_ok=True)
        
        try:
            with open(full_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Invalidate cache
            self._file_cache = None
        except PermissionError:
            raise PermissionError(f"Permission denied when writing file: {id}")
        except TypeError as e:
            raise TypeError(f"Cannot serialize data to JSON: {str(e)}")
class S3JSONFileService(JSONFileService):
    """
    Implementation of JSONFileService that uses Amazon S3.
    
    This class provides access to JSON files stored in an S3 bucket.
    """
    
    def __init__(self, bucket_name: str, prefix: str = "", region_name: str = None, profile_name: str = None):
        """
        Initialize the S3JSONFileService with a bucket and optional prefix.
        
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
    
    def _is_json_file(self, key: str) -> bool:
        """
        Check if an S3 object key represents a JSON file.
        
        Args:
            key (str): S3 object key
            
        Returns:
            bool: True if the key ends with .json, False otherwise
        """
        return key.lower().endswith('.json')
    
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
        Scan the S3 bucket for JSON files.
        
        Returns:
            List[Dict[str, Any]]: List of dictionaries containing metadata about each JSON file
        """
        files = []
        paginator = self.s3_client.get_paginator('list_objects_v2')
        
        # List all objects with the given prefix
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=self.prefix):
            if 'Contents' not in page:
                continue
                
            for obj in page['Contents']:
                key = obj['Key']
                
                if self._is_json_file(key):
                    relative_path = self._get_relative_path(key)
                    name = os.path.basename(key)

                    # Try to get a preview of the JSON content
                    preview = {}
                    try:
                        # Get just the first few KB to extract preview
                        response = self.s3_client.get_object(
                            Bucket=self.bucket_name,
                            Key=key
                        )
                        
                        # Read the partial content
                        content = response['Body'].read().decode('utf-8')
                        
                        # Try to parse it as JSON (this might fail if we cut in the middle of the JSON)
                        try:
                            data = json.loads(content)
                            # Get up to 3 top-level keys for preview
                            preview = {k: data[k] for k in list(data.keys())[:3] if not isinstance(data[k], (dict, list))}
                        except json.JSONDecodeError:
                            # If we can't parse the partial content, just skip the preview
                            pass
                    except ClientError:
                        # If we can't read the file, just skip the preview
                        pass
                    
                    # Create full S3 URI for the name
                    s3_uri = f"s3://{self.bucket_name}/{key}"
                    
                    files.append({
                        'id': relative_path,
                        'name': s3_uri,
                        'path': relative_path,
                        'size': obj['Size'],
                        'created': obj.get('LastModified', datetime.datetime.now()).isoformat(),
                        'modified': obj.get('LastModified', datetime.datetime.now()).isoformat(),
                        'preview': preview,
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
            List[Dict[str, Any]]: List of dictionaries containing metadata about each JSON file
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
    
    def get_contents(self, id: str) -> Dict[str, Any]:
        """
        Retrieve the contents of a JSON file from S3 as a dictionary.
        
        Args:
            id (str): The relative path to the JSON file from the prefix
            
        Returns:
            Dict[str, Any]: The parsed JSON content as a dictionary
            
        Raises:
            FileNotFoundError: If the JSON file cannot be found
            PermissionError: If the JSON file cannot be accessed due to permissions
            json.JSONDecodeError: If the file contains invalid JSON
        """
        # Construct the full S3 key
        key = self.prefix + id if self.prefix else id
        
        try:
            # Get the object from S3
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            
            # Read and parse the JSON content
            content = response['Body'].read().decode('utf-8')
            return json.loads(content)
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'NoSuchKey':
                raise FileNotFoundError(f"File not found in S3: {id}")
            elif error_code == 'AccessDenied':
                raise PermissionError(f"Permission denied when accessing S3 file: {id}")
            else:
                raise e
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Invalid JSON in S3 file {id}: {str(e)}", e.doc, e.pos)
    
    def file_count(self) -> int:
        """
        Get the total number of JSON files available in the S3 bucket.
        
        Returns:
            int: The total count of JSON files in the bucket with the given prefix
        """
        files = self._get_cached_files()
        return len(files)
    
    def list(self, num_files: int, page: int) -> List[Dict[str, Any]]:
        """
        List available JSON files in the S3 bucket with pagination.
        
        Args:
            num_files (int): The maximum number of files to return per page
            page (int): The page number (0-indexed) of results to return
            
        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing metadata about each JSON file
            
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
    
    def save(self, id: str, data: Dict[str, Any]) -> None:
        """
        Save a dictionary as a JSON file in S3.
        
        Args:
            id (str): The relative path to the JSON file from the prefix
            data (Dict[str, Any]): The dictionary to save as JSON
            
        Raises:
            PermissionError: If the JSON file cannot be written due to permissions
            TypeError: If the data cannot be serialized to JSON
        """
        # Construct the full S3 key
        key = self.prefix + id if self.prefix else id
        
        try:
            # Convert the dictionary to a JSON string
            json_data = json.dumps(data, indent=2)
            
            # Upload the JSON string to S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json_data,
                ContentType='application/json'
            )
            
            # Invalidate cache
            self._file_cache = None
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'AccessDenied':
                raise PermissionError(f"Permission denied when writing to S3: {id}")
            else:
                raise e
        except TypeError as e:
            raise TypeError(f"Cannot serialize data to JSON: {str(e)}")
