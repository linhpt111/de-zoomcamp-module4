"""
Tải green + yellow taxi 2019-2020 (DataTalksClub) lên GCS, rồi nạp vào BigQuery.

Ví dụ:
    python load_taxi_data.py
    python load_taxi_data.py --colors green --years 2019
    python load_taxi_data.py --skip-upload      # chỉ chạy lại bước nạp BigQuery
"""
import argparse
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from google.cloud import bigquery, storage

BASE_URL = "https://github.com/DataTalksClub/nyc-tlc-data/releases/download"

_local = threading.local()


def get_bucket(project, bucket_name):
    # Mỗi thread dùng một client riêng cho an toàn
    if not hasattr(_local, "bucket"):
        _local.bucket = storage.Client(project=project).bucket(bucket_name)
    return _local.bucket


def list_files(colors, years):
    for color in colors:
        for year in years:
            for month in range(1, 13):
                yield color, f"{color}_tripdata_{year}-{month:02d}.csv.gz"


def upload_one(project, bucket_name, color, file_name, tmp_dir):
    bucket = get_bucket(project, bucket_name)
    blob = bucket.blob(f"{color}/{file_name}")

    # Bỏ qua file đã có -> chạy lại script không phải tải lại từ đầu
    if blob.exists():
        return f"Bỏ qua (đã có): {file_name}"

    local_path = os.path.join(tmp_dir, file_name)
    try:
        url = f"{BASE_URL}/{color}/{file_name}"
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)

        # Upload resumable: nếu lỗi giữa chừng, object không được tạo trên GCS
        blob.chunk_size = 8 * 1024 * 1024
        blob.upload_from_filename(local_path, timeout=600)
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)

    return f"Đã upload: {file_name}"


def upload_all(project, bucket_name, colors, years, workers):
    files = list(list_files(colors, years))
    print(f"== Bước 1: upload {len(files)} file lên gs://{bucket_name}/ ==")

    failed = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(upload_one, project, bucket_name, color, name, tmp_dir): name
                for color, name in files
            }
            for i, fut in enumerate(as_completed(futures), start=1):
                name = futures[fut]
                try:
                    print(f"[{i}/{len(files)}] {fut.result()}")
                except Exception as e:
                    print(f"[{i}/{len(files)}] LỖI {name}: {e}")
                    failed.append(name)

    if failed:
        print(f"\nCó {len(failed)} file lỗi: {failed}")
        print("Chạy lại script để thử lại (file đã xong sẽ được bỏ qua).")
        sys.exit(1)


def load_all(project, bucket_name, dataset, location, colors):
    print(f"\n== Bước 2: nạp vào BigQuery dataset {dataset} ({location}) ==")
    client = bigquery.Client(project=project, location=location)

    ds = bigquery.Dataset(f"{project}.{dataset}")
    ds.location = location
    ds = client.create_dataset(ds, exists_ok=True)
    if ds.location.upper() != location.upper():
        sys.exit(
            f"Dataset {dataset} đang ở {ds.location}, khác --location {location}. "
            "Dataset và bucket phải cùng location."
        )

    for color in colors:
        table_id = f"{project}.{dataset}.{color}_tripdata"
        uri = f"gs://{bucket_name}/{color}/*.csv.gz"
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            autodetect=True,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        print(f"Đang nạp {uri} -> {table_id} ...")
        job = client.load_table_from_uri(uri, table_id, job_config=job_config)
        try:
            job.result()
        except Exception:
            print(f"LỖI khi nạp {table_id}:")
            for err in job.errors or []:
                print("  ", err)
            raise

        table = client.get_table(table_id)
        print(f"  -> {table.num_rows:,} dòng, {table.num_bytes / 1024**3:.2f} GB")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default="de-zoomcamp-510004")
    p.add_argument("--bucket", default="de-zoomcamp-510004-taxi")
    p.add_argument("--dataset", default="nytaxi")
    p.add_argument("--location", default="US", help="Phải trùng location của bucket")
    p.add_argument("--colors", nargs="+", default=["green", "yellow"])
    p.add_argument("--years", nargs="+", default=["2019", "2020"])
    p.add_argument("--workers", type=int, default=4, help="Số file tải song song")
    p.add_argument("--skip-upload", action="store_true")
    p.add_argument("--skip-load", action="store_true")
    args = p.parse_args()

    if not args.skip_upload:
        upload_all(args.project, args.bucket, args.colors, args.years, args.workers)
    if not args.skip_load:
        load_all(args.project, args.bucket, args.dataset, args.location, args.colors)

    print("\nXong.")


if __name__ == "__main__":
    main()
