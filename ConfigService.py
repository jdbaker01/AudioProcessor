import streamlit as st
import yaml
from yaml.loader import SafeLoader
import boto3
import io
from datetime import datetime


def emit_auth_metric(metric_name, username):
    """
    Emit authentication metrics to CloudWatch
    """
    try:
        # Create CloudWatch client with region specified
        cloudwatch = boto3.client('cloudwatch', region_name='us-east-1')  # Replace with your preferred region
        cloudwatch.put_metric_data(
            Namespace='StreamlitAuth',
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [
                        {
                            'Name': 'Username',
                            'Value': username
                        }
                    ],
                    'Timestamp': datetime.utcnow()
                }
            ]
        )
    except Exception as e:
        st.warning(f"Failed to emit metric: {e}")


def get_config_from_s3(bucket_name):
    """
    Retrieve configuration from S3 bucket
    """
    try:
        # Initialize S3 client
        s3 = boto3.client('s3')

        # Define bucket and key
        key = 'config.yaml'

        # Get the object from S3
        response = s3.get_object(Bucket=bucket_name, Key=key)

        # Read the content
        config_content = response['Body'].read().decode('utf-8')

        # Parse YAML
        config = yaml.load(io.StringIO(config_content), Loader=SafeLoader)
        return config
    except Exception as e:
        st.error(f"Error loading config from S3: {e}")
