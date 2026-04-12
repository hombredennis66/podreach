import hashlib
import json
from typing import Optional
from pathlib import Path
import shutil
import sqlite3
import time  # For retry delays
import logging

# Assuming deezspot is in a location findable by Python's import system
# from deezspot.spotloader import SpoLogin # Used in validation
# from deezspot.deezloader import DeeLogin # Used in validation
# For now, as per original, validation calls these directly.

logger = logging.getLogger(__name__)  # Assuming logger is configured elsewhere

# --- New Database and Path Definitions ---
CREDS_BASE_DIR = Path("./data/creds")
ACCOUNTS_DB_PATH = CREDS_BASE_DIR / "accounts.db"
BLOBS_DIR = CREDS_BASE_DIR / "blobs"
GLOBAL_SEARCH_JSON_PATH = CREDS_BASE_DIR / "search.json"  # Global Spotify API creds
DEVICE_INFO_FILENAME = "device.json"
DEVICE_INFO_KEYS = {
    "device_name",
    "device_id",
    "device_type",
    "device_software_version",
    "system_info_string",
    "preferred_locale",
}
DEVICE_INFO_DEFAULTS = {
    "device_type": 4,
    "device_software_version": "Spotify Connect 3.2.6",
    "system_info_string": "Spotify Connect 3.2.6; Linux; Speaker",
}

EXPECTED_SPOTIFY_TABLE_COLUMNS = {
    "name": "TEXT PRIMARY KEY",
    # client_id and client_secret are now global
    "region": "TEXT",  # ISO 3166-1 alpha-2
    "created_at": "REAL",
    "updated_at": "REAL",
}

EXPECTED_DEEZER_TABLE_COLUMNS = {
    "name": "TEXT PRIMARY KEY",
    "arl": "TEXT",
    "region": "TEXT",  # ISO 3166-1 alpha-2
    "created_at": "REAL",
    "updated_at": "REAL",
}


def _get_db_connection():
    ACCOUNTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    BLOBS_DIR.mkdir(parents=True, exist_ok=True)  # Ensure blobs directory also exists
    conn = sqlite3.connect(ACCOUNTS_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _get_device_info_path(account_name: str) -> Path:
    return BLOBS_DIR / account_name / DEVICE_INFO_FILENAME


def _normalize_device_info(device_info):
    if device_info is None:
        return None
    if not isinstance(device_info, dict):
        raise ValueError("device_info must be an object if provided.")

    cleaned = {key: device_info.get(key) for key in DEVICE_INFO_KEYS if key in device_info}
    cleaned = {key: value for key, value in cleaned.items() if value is not None}

    device_id = cleaned.get("device_id")
    if device_id is not None:
        if not isinstance(device_id, str) or len(device_id) != 40:
            raise ValueError("device_info.device_id must be a 40-character hex string.")
        try:
            int(device_id, 16)
        except ValueError:
            raise ValueError("device_info.device_id must be a 40-character hex string.")
        cleaned["device_id"] = device_id.lower()

    preferred_locale = cleaned.get("preferred_locale")
    if preferred_locale is not None:
        if not isinstance(preferred_locale, str) or len(preferred_locale) != 2:
            raise ValueError("device_info.preferred_locale must be a 2-letter code.")
        cleaned["preferred_locale"] = preferred_locale.lower()

    device_type = cleaned.get("device_type")
    if device_type is not None:
        if isinstance(device_type, str) and device_type.isdigit():
            cleaned["device_type"] = int(device_type)
        elif isinstance(device_type, int):
            cleaned["device_type"] = device_type
        else:
            raise ValueError("device_info.device_type must be an integer enum value.")

    return cleaned or None


def _write_device_info(account_name: str, device_info: dict) -> None:
    if not device_info:
        return
    device_path = _get_device_info_path(account_name)
    device_path.parent.mkdir(parents=True, exist_ok=True)
    with open(device_path, "w") as device_file:
        json.dump(device_info, device_file, indent=4)


def _read_device_info(account_name: str):
    device_path = _get_device_info_path(account_name)
    if not device_path.exists():
        return None
    try:
        with open(device_path, "r") as device_file:
            data = json.load(device_file)
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning(
            f"Failed reading device info for spotify account '{account_name}': {e}"
        )
    return None


def _device_info_summary(device_info: dict) -> str:
    if not device_info:
        return "device_info: <none>"
    return (
        "device_info: "
        f"name={device_info.get('device_name')}, "
        f"type={device_info.get('device_type')}, "
        f"id={device_info.get('device_id')}, "
        f"locale={device_info.get('preferred_locale')}"
    )


def device_info_summary(device_info) -> str:
    return _device_info_summary(device_info or {})


def build_default_device_info(
    account_name: str,
    region: Optional[str],
    blob_content,
):
    username = ""
    if isinstance(blob_content, dict):
        username = blob_content.get("username") or ""

    seed_region = region or "US"
    seed = f"{account_name}:{seed_region}:{username}"
    device_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    preferred_locale = seed_region.lower()

    device_info = {
        "device_name": f"{account_name} Speaker",
        "device_id": device_id,
        "preferred_locale": preferred_locale,
        **DEVICE_INFO_DEFAULTS,
    }
    return _normalize_device_info(device_info) or device_info


def merge_device_info(existing, defaults):
    merged = dict(existing or {})
    for key, value in defaults.items():
        if key not in merged or merged.get(key) in (None, ""):
            merged[key] = value
    return merged


def backfill_spotify_device_info(force: bool = False):
    created = 0
    updated = 0
    skipped = 0

    accounts = list_credentials("spotify")
    for name in accounts:
        try:
            cred = get_credential("spotify", name)
            if not cred:
                logger.warning("Skipping '%s': credentials not found.", name)
                skipped += 1
                continue

            defaults = build_default_device_info(
                name,
                cred.get("region"),
                cred.get("blob_content"),
            )

            existing = cred.get("device_info")
            normalized_existing = None
            if existing:
                try:
                    normalized_existing = _normalize_device_info(existing)
                except ValueError as e:
                    logger.warning(
                        "Invalid device_info for '%s'; rebuilding defaults (%s)",
                        name,
                        e,
                    )
                    normalized_existing = None

            if force or not normalized_existing:
                merged = defaults
            else:
                merged = merge_device_info(normalized_existing, defaults)

            normalized_merged = _normalize_device_info(merged) or merged

            if not normalized_existing:
                _write_device_info(name, normalized_merged)
                created += 1
                logger.info(
                    "Backfilled Spotify device info for '%s' (%s)",
                    name,
                    _device_info_summary(normalized_merged),
                )
            elif normalized_merged != normalized_existing:
                _write_device_info(name, normalized_merged)
                updated += 1
                logger.info(
                    "Updated Spotify device info for '%s' (%s)",
                    name,
                    _device_info_summary(normalized_merged),
                )
            else:
                skipped += 1
        except Exception as e:
            logger.warning("Device info backfill failed for '%s': %s", name, e)
            skipped += 1

    logger.info(
        "Spotify device info backfill complete: created=%s updated=%s skipped=%s",
        created,
        updated,
        skipped,
    )
    return {"created": created, "updated": updated, "skipped": skipped}


def _ensure_table_schema(
    cursor: sqlite3.Cursor, table_name: str, expected_columns: dict
):
    """Ensures the given table has all expected columns, adding them if necessary."""
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns_info = cursor.fetchall()
        existing_column_names = {col[1] for col in existing_columns_info}

        added_columns = False
        for col_name, col_type in expected_columns.items():
            if col_name not in existing_column_names:
                # Basic protection against altering PK after creation if table is not empty
                if "PRIMARY KEY" in col_type.upper() and existing_columns_info:
                    logger.warning(
                        f"Column '{col_name}' is part of PRIMARY KEY for table '{table_name}' "
                        f"and was expected to be created by CREATE TABLE. Skipping explicit ADD COLUMN."
                    )
                    continue

                col_type_for_add = col_type.replace(" PRIMARY KEY", "").strip()
                try:
                    cursor.execute(
                        f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type_for_add}"
                    )
                    logger.info(
                        f"Added missing column '{col_name} {col_type_for_add}' to table '{table_name}'."
                    )
                    added_columns = True
                except sqlite3.OperationalError as alter_e:
                    logger.warning(
                        f"Could not add column '{col_name}' to table '{table_name}': {alter_e}. "
                        f"It might already exist with a different definition or there's another schema mismatch."
                    )
        return added_columns
    except sqlite3.Error as e:
        logger.error(
            f"Error ensuring schema for table '{table_name}': {e}", exc_info=True
        )
        return False


def init_credentials_db():
    """Initializes the accounts.db and its tables if they don't exist."""
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            # Spotify Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS spotify (
                    name TEXT PRIMARY KEY,
                    region TEXT,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            _ensure_table_schema(cursor, "spotify", EXPECTED_SPOTIFY_TABLE_COLUMNS)

            # Deezer Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deezer (
                    name TEXT PRIMARY KEY,
                    arl TEXT,
                    region TEXT,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            _ensure_table_schema(cursor, "deezer", EXPECTED_DEEZER_TABLE_COLUMNS)

            # Ensure global search.json exists, create if not
            if not GLOBAL_SEARCH_JSON_PATH.exists():
                logger.info(
                    f"Global Spotify search credential file not found at {GLOBAL_SEARCH_JSON_PATH}. Creating empty file."
                )
                with open(GLOBAL_SEARCH_JSON_PATH, "w") as f_search:
                    json.dump(
                        {"client_id": "", "client_secret": ""}, f_search, indent=4
                    )

            conn.commit()
            logger.info(
                f"Credentials database initialized/schema checked at {ACCOUNTS_DB_PATH}"
            )
    except sqlite3.Error as e:
        logger.error(f"Error initializing credentials database: {e}", exc_info=True)
        raise


def _get_global_spotify_api_creds():
    """Loads client_id and client_secret from the global search.json."""
    if GLOBAL_SEARCH_JSON_PATH.exists():
        try:
            with open(GLOBAL_SEARCH_JSON_PATH, "r") as f:
                search_data = json.load(f)
            client_id = search_data.get("client_id")
            client_secret = search_data.get("client_secret")
            if client_id and client_secret:
                return client_id, client_secret
            else:
                logger.warning(
                    f"Global Spotify API credentials in {GLOBAL_SEARCH_JSON_PATH} are incomplete."
                )
        except Exception as e:
            logger.error(
                f"Error reading global Spotify API credentials from {GLOBAL_SEARCH_JSON_PATH}: {e}",
                exc_info=True,
            )
    else:
        logger.warning(
            f"Global Spotify API credential file {GLOBAL_SEARCH_JSON_PATH} not found."
        )
    return (
        None,
        None,
    )  # Return None if file doesn't exist or creds are incomplete/invalid


def save_global_spotify_api_creds(client_id: str, client_secret: str):
    """Saves client_id and client_secret to the global search.json."""
    try:
        GLOBAL_SEARCH_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(GLOBAL_SEARCH_JSON_PATH, "w") as f:
            json.dump(
                {"client_id": client_id, "client_secret": client_secret}, f, indent=4
            )
        logger.info(
            f"Global Spotify API credentials saved to {GLOBAL_SEARCH_JSON_PATH}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Error saving global Spotify API credentials to {GLOBAL_SEARCH_JSON_PATH}: {e}",
            exc_info=True,
        )
        return False


def _validate_with_retry(service_name, account_name, validation_data):
    """
    Attempts to validate credentials with retries for connection errors.
    validation_data (dict): For Spotify, expects {'blob_file_path': ..., 'device_info': ...}
                            For Deezer, expects {'arl': ...}
    Returns True if validated, raises ValueError if not.
    """
    # Deezspot imports need to be available. Assuming they are.
    from deezspot.spotloader import SpoLogin
    from deezspot.deezloader import DeeLogin

    max_retries = 3  # Reduced for brevity, was 5
    last_exception = None

    for attempt in range(max_retries):
        try:
            if service_name == "spotify":
                # For Spotify, validation uses the account's blob and GLOBAL API creds
                global_client_id, global_client_secret = _get_global_spotify_api_creds()
                if not global_client_id or not global_client_secret:
                    raise ValueError(
                        "Global Spotify API client_id or client_secret not configured for validation."
                    )

                blob_file_path = validation_data.get("blob_file_path")
                if not blob_file_path or not Path(blob_file_path).exists():
                    raise ValueError(
                        f"Spotify blob file missing for validation of account {account_name}"
                    )
                SpoLogin(
                    credentials_path=str(blob_file_path),
                    spotify_client_id=global_client_id,
                    spotify_client_secret=global_client_secret,
                    device_info=validation_data.get("device_info"),
                )
            else:  # Deezer
                arl = validation_data.get("arl")
                if not arl:
                    raise ValueError("Missing 'arl' for Deezer validation.")
                DeeLogin(arl=arl)

            logger.info(
                f"{service_name.capitalize()} credentials for {account_name} validated successfully (attempt {attempt + 1})."
            )
            return True
        except Exception as e:
            last_exception = e
            error_str = str(e).lower()
            is_connection_error = (
                "connection refused" in error_str
                or "connection error" in error_str
                or "timeout" in error_str
                or "temporary failure in name resolution" in error_str
                or "dns lookup failed" in error_str
                or "network is unreachable" in error_str
                or "ssl handshake failed" in error_str
                or "connection reset by peer" in error_str
            )

            if is_connection_error and attempt < max_retries - 1:
                retry_delay = 2 + attempt
                logger.warning(
                    f"Validation for {account_name} ({service_name}) failed (attempt {attempt + 1}) due to connection issue: {e}. Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
                continue
            else:
                logger.error(
                    f"Validation for {account_name} ({service_name}) failed on attempt {attempt + 1} (non-retryable or max retries)."
                )
                break

    if last_exception:
        base_error_message = str(last_exception).splitlines()[-1]
        detailed_error_message = f"Invalid {service_name} credentials for {account_name}. Verification failed: {base_error_message}"
        if (
            service_name == "spotify"
            and "incorrect padding" in base_error_message.lower()
        ):
            detailed_error_message += (
                ". Hint: For Spotify, ensure the credentials blob content is correct."
            )
        raise ValueError(detailed_error_message)
    else:
        raise ValueError(
            f"Invalid {service_name} credentials for {account_name}. Verification failed (unknown reason after retries)."
        )


def create_credential(service, name, data):
    """
    Creates a new credential.
    Args:
        service (str): 'spotify' or 'deezer'
        name (str): Custom name for the credential
        data (dict): For Spotify: {'region', 'blob_content', 'device_info'}
                     For Deezer: {'arl', 'region'}
    Raises:
        ValueError, FileExistsError
    """
    if service not in ["spotify", "deezer"]:
        raise ValueError("Service must be 'spotify' or 'deezer'")
    if not name or not isinstance(name, str):
        raise ValueError("Credential name must be a non-empty string.")

    current_time = time.time()

    with _get_db_connection() as conn:
        cursor = conn.cursor()
        conn.row_factory = sqlite3.Row
        try:
            if service == "spotify":
                required_fields = {
                    "region",
                    "blob_content",
                }  # client_id/secret are global
                if not required_fields.issubset(data.keys()):
                    raise ValueError(
                        f"Missing fields for Spotify. Required: {required_fields}"
                    )

                device_info = _normalize_device_info(data.get("device_info"))

                blob_path = BLOBS_DIR / name / "credentials.json"
                validation_data = {
                    "blob_file_path": str(blob_path),
                    "device_info": device_info,
                }  # Validation uses global API creds

                blob_path.parent.mkdir(parents=True, exist_ok=True)
                with open(blob_path, "w") as f_blob:
                    if isinstance(data["blob_content"], dict):
                        json.dump(data["blob_content"], f_blob, indent=4)
                    else:  # assume string
                        f_blob.write(data["blob_content"])

                try:
                    _validate_with_retry("spotify", name, validation_data)
                    cursor.execute(
                        "INSERT INTO spotify (name, region, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (name, data["region"], current_time, current_time),
                    )
                    if device_info:
                        _write_device_info(name, device_info)
                        logger.info(
                            "Stored Spotify device info for '%s' (%s)",
                            name,
                            _device_info_summary(device_info),
                        )
                except Exception:
                    device_path = _get_device_info_path(name)
                    if device_path.exists():
                        device_path.unlink()
                    if blob_path.exists():
                        blob_path.unlink()  # Cleanup blob
                    if blob_path.parent.exists() and not any(
                        blob_path.parent.iterdir()
                    ):
                        blob_path.parent.rmdir()
                    raise  # Re-raise validation or DB error

            elif service == "deezer":
                required_fields = {"arl", "region"}
                if not required_fields.issubset(data.keys()):
                    raise ValueError(
                        f"Missing fields for Deezer. Required: {required_fields}"
                    )

                validation_data = {"arl": data["arl"]}
                _validate_with_retry("deezer", name, validation_data)

                cursor.execute(
                    "INSERT INTO deezer (name, arl, region, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (name, data["arl"], data["region"], current_time, current_time),
                )
            conn.commit()
            logger.info(f"Credential '{name}' for {service} created successfully.")
            return {"status": "created", "service": service, "name": name}
        except sqlite3.IntegrityError:
            raise FileExistsError(f"Credential '{name}' already exists for {service}.")
        except Exception as e:
            logger.error(
                f"Error creating credential {name} for {service}: {e}", exc_info=True
            )
            raise ValueError(f"Could not create credential: {e}")


def get_credential(service, name):
    """
    Retrieves a specific credential by name.
    For Spotify, returns dict with name, region, blob_content, and device_info (from file).
    For Deezer, returns dict with name, arl, and region.
    Raises FileNotFoundError if the credential does not exist.
    """
    if service not in ["spotify", "deezer"]:
        raise ValueError("Service must be 'spotify' or 'deezer'")

    with _get_db_connection() as conn:
        cursor = conn.cursor()
        conn.row_factory = sqlite3.Row  # Ensure row_factory is set for this cursor
        cursor.execute(f"SELECT * FROM {service} WHERE name = ?", (name,))
        row = cursor.fetchone()

        if not row:
            raise FileNotFoundError(f"No {service} credential found with name '{name}'")

        data = dict(row)

        if service == "spotify":
            blob_file_path = BLOBS_DIR / name / "credentials.json"
            data["blob_file_path"] = str(blob_file_path)  # Keep for internal use
            try:
                with open(blob_file_path, "r") as f_blob:
                    blob_data = json.load(f_blob)
                data["blob_content"] = blob_data
            except FileNotFoundError:
                logger.warning(
                    f"Spotify blob file not found for {name} at {blob_file_path} during get_credential."
                )
                data["blob_content"] = None
            except json.JSONDecodeError:
                logger.warning(
                    f"Error decoding JSON from Spotify blob file for {name} at {blob_file_path}."
                )
                data["blob_content"] = None
            except Exception as e:
                logger.error(
                    f"Unexpected error reading Spotify blob for {name}: {e}",
                    exc_info=True,
                )
                data["blob_content"] = None

            device_info = _read_device_info(name)
            cleaned_data = {
                "name": data.get("name"),
                "region": data.get("region"),
                "blob_content": data.get("blob_content"),
                "device_info": device_info,
                "blob_file_path": data.get(
                    "blob_file_path"
                ),  # Ensure blob_file_path is returned
            }
            return cleaned_data

        elif service == "deezer":
            cleaned_data = {
                "name": data.get("name"),
                "region": data.get("region"),
                "arl": data.get("arl"),
            }
            return cleaned_data

    # Fallback, should not be reached if service is spotify or deezer
    return None


def list_credentials(service):
    if service not in ["spotify", "deezer"]:
        raise ValueError("Service must be 'spotify' or 'deezer'")

    with _get_db_connection() as conn:
        cursor = conn.cursor()
        conn.row_factory = sqlite3.Row
        cursor.execute(f"SELECT name FROM {service}")
        return [row["name"] for row in cursor.fetchall()]


def delete_credential(service, name):
    if service not in ["spotify", "deezer"]:
        raise ValueError("Service must be 'spotify' or 'deezer'")

    with _get_db_connection() as conn:
        cursor = conn.cursor()
        conn.row_factory = sqlite3.Row
        cursor.execute(f"DELETE FROM {service} WHERE name = ?", (name,))
        if cursor.rowcount == 0:
            raise FileNotFoundError(f"Credential '{name}' not found for {service}.")

        if service == "spotify":
            blob_dir = BLOBS_DIR / name
            if blob_dir.exists():
                shutil.rmtree(blob_dir)
        conn.commit()
        logger.info(f"Credential '{name}' for {service} deleted.")
        return {"status": "deleted", "service": service, "name": name}


def edit_credential(service, name, new_data):
    """
    Edits an existing credential.
    new_data for Spotify can include: region, blob_content, device_info.
    new_data for Deezer can include: arl, region.
    Fields not in new_data remain unchanged.
    """
    if service not in ["spotify", "deezer"]:
        raise ValueError("Service must be 'spotify' or 'deezer'")

    current_time = time.time()

    # Fetch existing data first to preserve unchanged fields and for validation backup
    try:
        existing_cred = get_credential(
            service, name
        )  # This will raise FileNotFoundError if not found
    except FileNotFoundError:
        raise
    except Exception as e:  # Catch other errors from get_credential
        raise ValueError(f"Could not retrieve existing credential {name} for edit: {e}")

    if not existing_cred:
        raise ValueError(f"Existing credential '{name}' for {service} could not be loaded.")

    updated_fields = new_data.copy()

    with _get_db_connection() as conn:
        cursor = conn.cursor()
        conn.row_factory = sqlite3.Row

        if service == "spotify":
            # Prepare data for DB update
            db_update_data = {
                "region": updated_fields.get("region", existing_cred.get("region")),
                "updated_at": current_time,
                "name": name,  # for WHERE clause
            }

            has_device_update = "device_info" in updated_fields
            device_info = (
                _normalize_device_info(updated_fields.get("device_info"))
                if has_device_update
                else None
            )
            device_path = _get_device_info_path(name)
            original_device_payload = None
            if device_path.exists():
                try:
                    with open(device_path, "r") as device_file:
                        original_device_payload = device_file.read()
                except Exception:
                    original_device_payload = None

            blob_file_path = existing_cred.get("blob_file_path")
            if not blob_file_path:
                raise ValueError(
                    f"Spotify blob file path missing for existing credential '{name}'."
                )
            blob_path = Path(blob_file_path)  # Use path from existing
            original_blob_content = None
            if blob_path.exists():
                with open(blob_path, "r") as f_orig_blob:
                    original_blob_content = f_orig_blob.read()

            # If blob_content is being updated, write it temporarily for validation
            if "blob_content" in updated_fields:
                blob_path.parent.mkdir(parents=True, exist_ok=True)
                with open(blob_path, "w") as f_new_blob:
                    if isinstance(updated_fields["blob_content"], dict):
                        json.dump(updated_fields["blob_content"], f_new_blob, indent=4)
                    else:
                        f_new_blob.write(updated_fields["blob_content"])

            validation_data = {"blob_file_path": str(blob_path), "device_info": device_info}

            try:
                _validate_with_retry("spotify", name, validation_data)

                set_clause = ", ".join(
                    [f"{key} = ?" for key in db_update_data if key != "name"]
                )
                values = [
                    db_update_data[key] for key in db_update_data if key != "name"
                ] + [name]
                cursor.execute(
                    f"UPDATE spotify SET {set_clause} WHERE name = ?", tuple(values)
                )

                if has_device_update:
                    if device_info:
                        _write_device_info(name, device_info)
                        logger.info(
                            "Updated Spotify device info for '%s' (%s)",
                            name,
                            _device_info_summary(device_info),
                        )
                    elif device_path.exists():
                        device_path.unlink()
                        logger.info("Cleared Spotify device info for '%s'", name)

                # If validation passed and blob was in new_data, it's already written.
                # If blob_content was NOT in new_data, the existing blob (if any) remains.
            except Exception:
                # Revert blob if it was changed and validation failed
                if (
                    "blob_content" in updated_fields
                    and original_blob_content is not None
                ):
                    with open(blob_path, "w") as f_revert_blob:
                        f_revert_blob.write(original_blob_content)
                elif (
                    "blob_content" in updated_fields
                    and original_blob_content is None
                    and blob_path.exists()
                ):
                    # If new blob was written but there was no original to revert to, delete the new one.
                    blob_path.unlink()
                if has_device_update:
                    if original_device_payload is not None:
                        device_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(device_path, "w") as device_file:
                            device_file.write(original_device_payload)
                    elif device_path.exists():
                        device_path.unlink()
                raise  # Re-raise validation or DB error

        elif service == "deezer":
            db_update_data = {
                "arl": updated_fields.get("arl", existing_cred.get("arl")),
                "region": updated_fields.get("region", existing_cred.get("region")),
                "updated_at": current_time,
                "name": name,  # for WHERE clause
            }

            validation_data = {"arl": db_update_data["arl"]}
            _validate_with_retry(
                "deezer", name, validation_data
            )  # Validation happens before DB write for Deezer

            set_clause = ", ".join(
                [f"{key} = ?" for key in db_update_data if key != "name"]
            )
            values = [
                db_update_data[key] for key in db_update_data if key != "name"
            ] + [name]
            cursor.execute(
                f"UPDATE deezer SET {set_clause} WHERE name = ?", tuple(values)
            )

        if cursor.rowcount == 0:  # Should not happen if get_credential succeeded
            raise FileNotFoundError(
                f"Credential '{name}' for {service} disappeared during edit."
            )

        conn.commit()
        logger.info(f"Credential '{name}' for {service} updated successfully.")
        return {"status": "updated", "service": service, "name": name}


# --- Helper for credential file path (mainly for Spotify blob) ---
def get_spotify_blob_path(account_name: str) -> Path:
    return BLOBS_DIR / account_name / "credentials.json"


def get_spotify_device_info(account_name: str):
    return _read_device_info(account_name)


def set_spotify_device_info(account_name: str, device_info: dict):
    normalized = _normalize_device_info(device_info)
    if not normalized:
        raise ValueError("device_info is empty or invalid.")
    _write_device_info(account_name, normalized)
    return normalized


# It's good practice to call init_credentials_db() when the app starts.
# This can be done in the main application setup. For now, defining it here.
# If this script is run directly for setup, you could add:
# if __name__ == '__main__':
#     init_credentials_db()
#     print("Credentials database initialized.")
