# Chỉ tạo hạ tầng (bucket + dataset). Việc nạp dữ liệu do load_taxi_data.py đảm nhận.
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

output "nytaxi_location" {
  value = google_bigquery_dataset.nytaxi.location
}
