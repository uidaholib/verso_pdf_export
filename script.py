import pandas as pd
import time
import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv
from tqdm import tqdm
import logging

# CONFIGURATION
load_dotenv()
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
CSV_FILENAME = "assetsWithPDFs_just_ETDs.csv"
DEBUG_MODE = False
DF_SUBSET_SIZE = 5  # Number of records to process in debug mode
df = None
errors = []

# Create C folder for logs and metadata
os.makedirs(f'./C/{timestamp}/', exist_ok=True)

# File logging (all messages) - now in C folder
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'C/{timestamp}/logs.log'), 
    ]
)

# Console logging (only warnings and above)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING) 
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(console_handler)

logger = logging.getLogger(__name__)


def load_data():
    """
    Load a list of asset IDs from a CSV file and use them to construct Esploro API URLs
    """
    df = pd.read_csv(CSV_FILENAME)
    print(f"Loaded {len(df)} records.")

    # Construct the API URL
    api_base_url = "https://api-na.hosted.exlibrisgroup.com/esploro/v1/assets/"
    df['api_url'] = df['Asset Id'].apply(lambda x: f"{api_base_url}{int(x)}" if pd.notna(x) else None)

    return df


def make_api_calls(df):
    """
    Request each asset's metadata as JSON from the Esploro API and compile into a single JSON file.
    """

    API_KEY = os.getenv("VERSO_API_KEY")
    all_records = [] 
    if DEBUG_MODE:
        df_subset = df.head(DF_SUBSET_SIZE)
    else:
        df_subset = df

    print(f"\nStarting API extraction for {len(df_subset)} records...")
    logger.info(f"Starting API extraction for {len(df_subset)} records.")

    # Fetch records
    for index, row in tqdm(df_subset.iterrows(), total=len(df_subset), desc="Fetching Records", unit="rec"):
        target_url = row['api_url']

        try:
            headers = {
                'Accept': 'application/json'
            }

            response = requests.get(target_url, params={'apikey': API_KEY}, headers=headers)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    if 'records' in data and isinstance(data['records'], list):
                        all_records.extend(data['records'])
                    
                except Exception as e:
                    tqdm.write(f"Error [Row {index}]: Response was not valid JSON. URL: {target_url}")
                    logger.error(f"Error for URL {target_url}: {e}")
                    errors.append({'url': target_url, 'error': f"{e}"})
            else:
                error_msg = f"Failed: {response.status_code} - {response.text}"
                tqdm.write(f"Error [Row {index}]: {error_msg} URL: {target_url}")
                logger.error(f"Error for URL {target_url}: {error_msg}")
                errors.append({'url': target_url, 'error': error_msg})

        except Exception as e:
            tqdm.write(f"Error [Row {index}]: {e} URL: {target_url}")
            logger.error(f"Exception for URL {target_url}: {e}")
            errors.append({'url': target_url, 'error': str(e)})

        time.sleep(0.2) 

    # Construct the final dictionary
    final_output = {
        "totalRecordCount": len(all_records),
        "records": all_records
    }

    # Save the JSON data to a file in C folder
    output_file = f"C/{timestamp}/asset_metadata.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4)

    print(f"\nExtraction complete.\n\n")

    # check expected number of records were retrieved based on CSV input
    if len(all_records) == len(df_subset):
        logger.info(f"All records successfully retrieved: {len(all_records)} records.")
        logger.info(f"Saved {len(all_records)} records to {output_file}")
    else:
        logger.warning(f"Discrepancy in record count: Retrieved {len(all_records)} out of {len(df_subset)} records.")
        logger.info(f"Saved {len(all_records)} records to {output_file}")

    if errors:
        print(f"Encountered {len(errors)} errors (check log).")

    return final_output


def download_asset_files(final_output):
    """
    Download asset files by making GET requests to urls listed in the fileDownloadUrl field. Skip all non-PDF files.
    Save all PDFs into folder named 'A'.
    """
    logger.info("Starting download_asset_files")

    assets_with_files = 0
    total_files = 0
    file_tasks = []
    
    # Create folder A if it doesn't exist
    output_dir = "A"
    os.makedirs(output_dir, exist_ok=True)
    
    # create list of file download tasks so tqdm can track progress with a pretty bar
    for record in final_output["records"]:

        if "files" in record:
            id_wrapper_dict = record['originalRepository']
            id = id_wrapper_dict['assetId']
            
            if len(record['files']) > 1: # for assets with multiple files, number them
                pdf_idx = 0
                for asset_files in record['files']:

                    if asset_files['file.extension'].lower() != 'pdf':
                        continue
                    
                    file_tasks.append({
                        'url': asset_files['fileDownloadUrl'],
                        'original_name': asset_files['file.name'],
                        'asset_id': id,
                        'file_number': pdf_idx,
                        'file_creation_date': asset_files.get('file.creationDate', ''),
                        'file_size_bytes': asset_files.get('file.size', ''),
                        'file_order': asset_files.get('file.order', '')
                    })
                    pdf_idx += 1

                assets_with_files += 1
            else:
                for asset_files in record['files']:

                    if asset_files['file.extension'].lower() != 'pdf':
                        continue

                    file_tasks.append({
                        'url': asset_files['fileDownloadUrl'],
                        'original_name': asset_files['file.name'],
                        'asset_id': id,
                        'file_number': None,
                        'file_creation_date': asset_files.get('file.creationDate', ''),
                        'file_size_bytes': asset_files.get('file.size', ''),
                        'file_order': asset_files.get('file.order', '')
                    })

                    assets_with_files += 1

    # Now download with progress bar directly into folder A
    logger.info(f"Downloading {len(file_tasks)} files into folder 'A'")
    
    for task in tqdm(file_tasks, desc="Downloading PDFs"):
        try:
            response = requests.get(task['url'])
            response.raise_for_status()
            file = response.content
            
            file_name, file_extension = os.path.splitext(task['original_name'])
            
            # Determine filename
            if task['file_number'] is not None:
                filename = f"{task['asset_id']}_{task['file_number']}{file_extension}"
            else:
                filename = f"{task['asset_id']}{file_extension}"
            
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as f:
                f.write(file)
            
            total_files += 1
            time.sleep(0.2)
            
        except requests.exceptions.RequestException as e:
            error_msg = f'Error downloading {task["original_name"]} from {task["asset_id"]}: {e}'
            print(f'\n{error_msg}')
            logger.error(error_msg)
            errors.append(error_msg)
            time.sleep(0.2)

    print(f"\nAssets with files: {assets_with_files}")
    print(f"Total PDFs saved to folder 'A': {total_files}")
    print(f'Errors encountered (if any): {errors}')
    logger.info(f"File download complete: {total_files} files downloaded to 'A', {len(errors)} errors")
    
    return file_tasks


def generate_metadata_csv(file_tasks, final_output):
    """
    Generate a CSV in folder B containing metadata for each downloaded PDF.
    """
    logger.info("Generating metadata CSV in folder B")
    
    # Create folder B
    os.makedirs("B", exist_ok=True)
    
    # Build lookup dictionary for records by assetId
    record_lookup = {}
    for record in final_output["records"]:
        if "originalRepository" in record and "assetId" in record["originalRepository"]:
            asset_id = record["originalRepository"]["assetId"]
            record_lookup[asset_id] = record
    
    # Prepare metadata rows
    metadata_rows = []
    for task in file_tasks:
        asset_id = task['asset_id']
        record = record_lookup.get(asset_id, {})
        
        # Extract creators as list of 'creatorname'
        creators_list = []
        if "creators" in record and isinstance(record["creators"], list):
            for creator in record["creators"]:
                if isinstance(creator, dict) and "creatorname" in creator:
                    creators_list.append(creator["creatorname"])
        creators_str = "; ".join(creators_list)

        # Extract additional identifiers
        additional_ids = record.get("creators", [{}])[0].get("additionalIdentifiers", {}) if record.get("creators") else {}
        external_id = additional_ids.get("EXTERNAL", "")
        barcode = additional_ids.get("BARCODE", "")
        pivot_id = additional_ids.get("Pivot", "")
        inst_id = additional_ids.get("INST_ID", "")
        other_id = additional_ids.get("Other", "")

        # Get almaUserId and user.primaryId from first creator
        first_creator = record.get("creators", [{}])[0] if record.get("creators") else {}
        alma_user_id = first_creator.get("almaUserId", "")
        user_primary_id = first_creator.get("user.primaryId", "")

        # Extract filename
        if task['file_number'] is not None:
            filename = f"{task['asset_id']}_{task['file_number']}.pdf"
        else:
            filename = f"{task['asset_id']}.pdf"

        # Build row
        row = {
            "filename": filename,
            "asset_id": asset_id,
            "original_filename": task['original_name'],
            "file_name_in_record": task['original_name'],  # e.g., chapter title
            "file_number": task['file_number'] if task['file_number'] is not None else "",
            "file_order": task.get('file_order', ""),
            "file_creation_date": task.get('file_creation_date', ""),
            "file_size_bytes": task.get('file_size_bytes', ""),
            "title": record.get("title", ""),
            "description": record.get("description.abstract", [{}])[0].get("value", "") if record.get("description.abstract") else "",
            "creators": creators_str,
            "publisher": record.get("publisher", ""),
            "publication_date": record.get("date.published", ""),
            "displayed_date": record.get("displayedDateByPriorityEsploroCP", ""),
            "language": "; ".join(record.get("language", [])) if isinstance(record.get("language"), list) else record.get("language", ""),
            # Additional identifiers from first creator
            "external_id": external_id,
            "barcode": barcode,
            "pivot_id": pivot_id,
            "inst_id": inst_id,
            "other_id": other_id,
            "alma_user_id": alma_user_id,
            "user_primary_id": user_primary_id,
            # Top-level identifiers
            "doi": record.get("identifier.doi", ""),
            "uri": record.get("identifier.uri", ""),
            "wos_id": record.get("identifier.wos", ""),
            "download_url": task['url']
        }
        metadata_rows.append(row)
    
    # Create DataFrame and save to CSV
    metadata_df = pd.DataFrame(metadata_rows)
    metadata_csv_path = "B/pdf_metadata.csv"
    metadata_df.to_csv(metadata_csv_path, index=False, encoding="utf-8")
    
    logger.info(f"Metadata CSV saved to {metadata_csv_path} ({len(metadata_rows)} records)")
    print(f"\nMetadata CSV generated: {metadata_csv_path}")


# Main execution
df = load_data()
final_output = make_api_calls(df)
file_tasks = download_asset_files(final_output)
generate_metadata_csv(file_tasks, final_output)