
import os
from pathlib import Path

import boto3
from dotenv import load_dotenv
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_BASE = PROJECT_ROOT / "knowledge_base"

load_dotenv(PROJECT_ROOT / ".env", override=True)

required = [
    "B2_ENDPOINT_URL",
    "B2_BUCKET_NAME",
    "B2_KEY_ID",
    "B2_APPLICATION_KEY",
]
missing = [key for key in required if not os.getenv(key)]
if missing:
    raise SystemExit("Missing settings: " + ", ".join(missing))

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["B2_ENDPOINT_URL"],
    aws_access_key_id=os.environ["B2_KEY_ID"],
    aws_secret_access_key=os.environ["B2_APPLICATION_KEY"],
    region_name="us-east-005",
)

bucket = os.environ["B2_BUCKET_NAME"]

config = TransferConfig(
    multipart_threshold=64 * 1024 * 1024,
    multipart_chunksize=16 * 1024 * 1024,
    max_concurrency=4,
    use_threads=True,
)

pdfs = sorted(KNOWLEDGE_BASE.rglob("*.pdf"))

if not pdfs:
    raise SystemExit("No PDF files found.")

print(f"Found {len(pdfs)} PDFs.")
print(f"Destination bucket: {bucket}")
print("Starting upload...\n")

uploaded = 0
skipped = 0
failed = 0

for index, path in enumerate(pdfs, start=1):
    key = path.relative_to(PROJECT_ROOT).as_posix()
    size = path.stat().st_size

    try:
        # Skip files already present with the same size.
        try:
            existing = s3.head_object(Bucket=bucket, Key=key)
            if existing.get("ContentLength") == size:
                skipped += 1
                print(f"[{index}/{len(pdfs)}] SKIPPED: {key}")
                continue
            print(f"[{index}/{len(pdfs)}] Updating different-sized file: {key}")
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code not in ("404", "NoSuchKey", "NotFound") and status != 404:
                raise

        s3.upload_file(
            str(path),
            bucket,
            key,
            Config=config,
            ExtraArgs={"ContentType": "application/pdf"},
        )

        uploaded += 1
        print(f"[{index}/{len(pdfs)}] UPLOADED: {key}")

    except Exception as error:
        failed += 1
        print(f"[{index}/{len(pdfs)}] FAILED: {key}")
        print("Error:", type(error).__name__, str(error))

print("\n========== UPLOAD SUMMARY ==========")
print("Total PDFs:", len(pdfs))
print("Uploaded:", uploaded)
print("Skipped:", skipped)
print("Failed:", failed)
print("===================================")
