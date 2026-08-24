# Migration Plan: Backblaze B2 to Local RustFS (S3)

This document outlines the standard operating procedure for migrating your Frappe external storage from Backblaze B2 to your newly hosted local Rust-based S3 filesystem (RustFS) using the `dfp_external_storage` app.

## Phase 1: Migrate the Physical Files

Before switching the Frappe configuration, you must copy all existing files from the Backblaze bucket to your new RustFS bucket. The safest and most efficient tool for this is **Rclone**.

1. **Install Rclone** on your server:
   ```bash
   sudo -v ; curl https://rclone.org/install.sh | sudo bash
   ```
2. **Configure Rclone** (`rclone config`):
   - Set up a remote named `backblaze` pointing to your B2 bucket (using B2 S3 credentials).
   - Set up a remote named `rustfs` pointing to your local RustFS S3 endpoint (using your local RustFS credentials).
3. **Run the Sync**:
   ```bash
   rclone sync -P backblaze:your-b2-bucket-name rustfs:your-rustfs-bucket-name
   ```
   *Note: Using `sync` ensures that the new bucket perfectly mirrors the old bucket.*

## Phase 2: Update Frappe Configuration

Once the files are mirrored, you need to point the `dfp_external_storage` app to the new RustFS endpoint.

1. Log into your Frappe/ERPNext instance as an Administrator.
2. Search for **S3 Settings** (or the specific configuration doctype provided by `dfp_external_storage`).
3. Update the following fields:
   - **Endpoint URL**: Change this from the Backblaze URL to your local RustFS URL (e.g., `http://127.0.0.1:9000` or your custom domain).
   - **Access Key**: Your RustFS Access Key.
   - **Secret Key**: Your RustFS Secret Key.
   - **Bucket Name**: The name of the bucket in RustFS.
4. Save the settings. 

## Phase 3: Database URL Correction (Not Required!)

I have reviewed the source code of `dfp_external_storage` on your machine, specifically `dfp_external_storage.py`. 

When the app uploads a file to S3, it **never** hardcodes the Backblaze domain into the database. Instead, it saves the `file_url` using a virtual route:
`self.file_url = f"/{DFP_EXTERNAL_STORAGE_URL_SEGMENT_FOR_FILE_LOAD}/{self.name}/{self.file_name}"`

Because of this architectural design, **you do not need to run any SQL updates**. When a user requests an old file, Frappe dynamically routes it through the app, which will instantly use your *new* RustFS endpoint to fetch the file!

## Phase 4: Verification

1. **Test Old Files**: Go to any old document (e.g., a Sales Invoice) that had an attachment uploaded when you were using Backblaze. Click the attachment to ensure it downloads correctly from the new RustFS server.
2. **Test New Uploads**: Upload a brand new file to a document. Verify that the file successfully appears inside your RustFS storage and can be downloaded again.
3. **Decommission Backblaze**: Once everything is confirmed working for a few days, you can safely delete the Backblaze B2 bucket to stop paying for its storage.
