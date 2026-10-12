"""Apply CORS to the S3 bucket now, then read it back."""
import boto3
from app.config import get_settings

s = get_settings()
c = boto3.client(
    "s3",
    region_name=s.aws_region,
    endpoint_url=s.s3_endpoint_url,
    aws_access_key_id=s.aws_access_key_id or "test",
    aws_secret_access_key=s.aws_secret_access_key or "test",
)
c.put_bucket_cors(
    Bucket=s.s3_bucket_name,
    CORSConfiguration={
        "CORSRules": [
            {
                "AllowedOrigins": ["*"],
                "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
                "AllowedHeaders": ["*"],
                "ExposeHeaders": ["ETag"],
                "MaxAgeSeconds": 3600,
            }
        ]
    },
)
print("CORS applied to", s.s3_bucket_name)
got = c.get_bucket_cors(Bucket=s.s3_bucket_name)
print("CORS now:", got["CORSRules"])
