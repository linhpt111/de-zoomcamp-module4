terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

variable "project" {}
variable "bucket_name" {}                 # phải là tên duy nhất toàn cầu
variable "location" { default = "US" }    # location chung cho bucket và dataset
variable "region" { default = "us-central1" }
variable "load_run" { default = "1" }     # tăng lên khi cần chạy lại job load

resource "google_storage_bucket" "taxi" {
  name                        = var.bucket_name
  location                    = var.location
  force_destroy               = true
  uniform_bucket_level_access = true
}

resource "google_bigquery_dataset" "nytaxi" {
  dataset_id                 = "nytaxi"
  location                   = var.location
  delete_contents_on_destroy = true
}

locals {
  # Thứ tự cột phải khớp đúng với header của file CSV.
  # Các cột kiểu mã (VendorID, passenger_count, ...) để FLOAT vì có tháng ghi dạng "1.0"; dbt staging sẽ cast lại.
  yellow_cols = [
    ["VendorID", "FLOAT"], ["tpep_pickup_datetime", "TIMESTAMP"], ["tpep_dropoff_datetime", "TIMESTAMP"],
    ["passenger_count", "FLOAT"], ["trip_distance", "FLOAT"], ["RatecodeID", "FLOAT"],
    ["store_and_fwd_flag", "STRING"], ["PULocationID", "INTEGER"], ["DOLocationID", "INTEGER"],
    ["payment_type", "FLOAT"], ["fare_amount", "FLOAT"], ["extra", "FLOAT"], ["mta_tax", "FLOAT"],
    ["tip_amount", "FLOAT"], ["tolls_amount", "FLOAT"], ["improvement_surcharge", "FLOAT"],
    ["total_amount", "FLOAT"], ["congestion_surcharge", "FLOAT"],
  ]
  green_cols = [
    ["VendorID", "FLOAT"], ["lpep_pickup_datetime", "TIMESTAMP"], ["lpep_dropoff_datetime", "TIMESTAMP"],
    ["store_and_fwd_flag", "STRING"], ["RatecodeID", "FLOAT"], ["PULocationID", "INTEGER"],
    ["DOLocationID", "INTEGER"], ["passenger_count", "FLOAT"], ["trip_distance", "FLOAT"],
    ["fare_amount", "FLOAT"], ["extra", "FLOAT"], ["mta_tax", "FLOAT"], ["tip_amount", "FLOAT"],
    ["tolls_amount", "FLOAT"], ["ehail_fee", "FLOAT"], ["improvement_surcharge", "FLOAT"],
    ["total_amount", "FLOAT"], ["payment_type", "FLOAT"], ["trip_type", "FLOAT"],
    ["congestion_surcharge", "FLOAT"],
  ]
  tables = {
    yellow = local.yellow_cols
    green  = local.green_cols
  }
}

resource "google_bigquery_table" "trips" {
  for_each            = local.tables
  dataset_id          = google_bigquery_dataset.nytaxi.dataset_id
  table_id            = "${each.key}_tripdata"
  deletion_protection = false
  schema = jsonencode([for c in each.value : { name = c[0], type = c[1], mode = "NULLABLE" }])
}

resource "google_bigquery_job" "load" {
  for_each = local.tables
  job_id   = "load_${each.key}_tripdata_run${var.load_run}"
  location = var.location

  load {
    source_uris        = ["gs://${google_storage_bucket.taxi.name}/${each.key}/*.csv.gz"]
    source_format      = "CSV"
    skip_leading_rows  = 1
    write_disposition  = "WRITE_TRUNCATE"
    create_disposition = "CREATE_NEVER"
    destination_table {
      project_id = var.project
      dataset_id = google_bigquery_dataset.nytaxi.dataset_id
      table_id   = google_bigquery_table.trips[each.key].table_id
    }
  }

  timeouts {
    create = "60m"
  }
}

output "nytaxi_location" {
  value = google_bigquery_dataset.nytaxi.location
}
