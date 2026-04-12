import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from routes.utils.credentials import (
    build_default_device_info,
    device_info_summary,
    get_credential,
    get_spotify_device_info,
    list_credentials,
    merge_device_info,
    set_spotify_device_info,
)


logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Backfill device_info for existing Spotify accounts."
    )
    parser.add_argument("--dry-run", action="store_true", help="Log actions only.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing device.json.")
    parser.add_argument(
        "--only",
        help="Only backfill a single account name.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    accounts = list_credentials("spotify")
    if args.only:
        accounts = [name for name in accounts if name == args.only]

    if not accounts:
        logger.info("No Spotify accounts found to backfill.")
        return

    created = 0
    skipped = 0
    updated = 0

    for name in accounts:
        existing = get_spotify_device_info(name)

        cred = get_credential("spotify", name)
        if not cred:
            logger.warning("Skipping '%s': credentials not found.", name)
            skipped += 1
            continue

        region = cred.get("region")
        blob_content = cred.get("blob_content")
        defaults = build_default_device_info(name, region, blob_content)
        if existing and not args.force:
            merged = merge_device_info(existing, defaults)
        else:
            merged = defaults

        if existing and merged == existing and not args.force:
            logger.info("Skipping '%s' (%s)", name, device_info_summary(existing))
            skipped += 1
            continue

        if args.dry_run:
            logger.info("Dry-run: would write '%s' (%s)", name, device_info_summary(merged))
            skipped += 1
            continue

        saved = set_spotify_device_info(name, merged)
        if existing:
            updated += 1
            logger.info("Updated '%s' (%s)", name, device_info_summary(saved))
        else:
            created += 1
            logger.info("Created '%s' (%s)", name, device_info_summary(saved))

    logger.info(
        "Backfill complete: created=%s updated=%s skipped=%s",
        created,
        updated,
        skipped,
    )


if __name__ == "__main__":
    main()
