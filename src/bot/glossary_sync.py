from __future__ import annotations

import argparse
import csv
import io
import logging
import time

from google.cloud import storage, translate

from .config import load_config
from .db import fetch_termbase, get_conn
from .logging import configure_logging


def _build_csv(term_rows: list[dict[str, str | bool | None]]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    for row in term_rows:
        source = (row.get("term") or "").strip()
        target = (row.get("preferred") or "").strip()
        if not source or not target:
            continue
        writer.writerow([source, target])
    return output.getvalue().encode("utf-8")


def _upload_to_gcs(
    bucket_name: str,
    object_name: str,
    data: bytes,
    credentials_path: str | None,
) -> str:
    if credentials_path:
        client = storage.Client.from_service_account_json(credentials_path)
    else:
        client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_string(data, content_type="text/csv")
    return f"gs://{bucket_name}/{object_name}"


def _ensure_glossary(
    project_id: str,
    location: str,
    glossary_id: str,
    gcs_uri: str,
    source_lang: str,
    target_lang: str,
    credentials_path: str | None,
    replace: bool,
) -> None:
    if credentials_path:
        client = translate.TranslationServiceClient.from_service_account_file(
            credentials_path
        )
    else:
        client = translate.TranslationServiceClient()

    parent = f"projects/{project_id}/locations/{location}"
    glossary_path = client.glossary_path(project_id, location, glossary_id)

    if replace:
        try:
            client.get_glossary(name=glossary_path)
            logging.getLogger("glossary").info("deleting glossary: %s", glossary_path)
            op = client.delete_glossary(name=glossary_path)
            op.result(timeout=300)
        except Exception:
            pass

    glossary = {
        "name": glossary_path,
        "language_pair": {
            "source_language_code": source_lang,
            "target_language_code": target_lang,
        },
        "input_config": {
            "gcs_source": {"input_uri": gcs_uri},
        },
    }

    logging.getLogger("glossary").info(
        "creating glossary %s from %s", glossary_path, gcs_uri
    )
    op = client.create_glossary(parent=parent, glossary=glossary)
    op.result(timeout=600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, help="Target language code (e.g., sr)")
    parser.add_argument("--glossary-id", required=True, help="GCP glossary id")
    parser.add_argument("--gcs-bucket", default=None)
    parser.add_argument("--gcs-prefix", default="glossaries")
    parser.add_argument("--gcs-uri", default=None)
    parser.add_argument("--replace", action="store_true", default=False)
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    if not cfg.pg_dsn:
        raise SystemExit("DATABASE_URL is required to build glossary from termbase")

    with get_conn(cfg.pg_dsn) as conn:
        termbase = fetch_termbase(conn, args.lang)

    csv_bytes = _build_csv(termbase)
    if not csv_bytes:
        raise SystemExit("no termbase entries found for glossary")

    if args.gcs_uri:
        gcs_uri = args.gcs_uri
    else:
        if not args.gcs_bucket:
            raise SystemExit("gcs-bucket is required when gcs-uri is not provided")
        timestamp = int(time.time())
        object_name = f"{args.gcs_prefix.rstrip('/')}/{args.glossary_id}-{args.lang}-{timestamp}.csv"
        gcs_uri = _upload_to_gcs(
            args.gcs_bucket, object_name, csv_bytes, cfg.gcp_credentials_path
        )

    project_id = cfg.gcp_project_id
    if not project_id:
        raise SystemExit("GCP project id is required")

    _ensure_glossary(
        project_id=project_id,
        location=cfg.gcp_location,
        glossary_id=args.glossary_id,
        gcs_uri=gcs_uri,
        source_lang=cfg.source_lang,
        target_lang=args.lang,
        credentials_path=cfg.gcp_credentials_path,
        replace=args.replace,
    )

    logging.getLogger("glossary").info(
        "glossary synced: id=%s lang=%s uri=%s", args.glossary_id, args.lang, gcs_uri
    )


if __name__ == "__main__":
    main()
