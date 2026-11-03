"""
Push the new final alert csv files (settings.FINAL_MOM_DIR) to a GitHub repo
through the GitHub API, without a local clone.

Every local csv whose name sorts after the last csv existing on remote,
is pushed all in one commit. With no csv in the repo folder yet, only the newest
local one is pushed.

Needs GITHUB_REPO and GITHUB_ALERTS_TOKEN (see publish_utils).

"""

import argparse
import logging
import os
import sys

import settings
from processing.publish.publish_utils import (
    REPO,
    RETRIES,
    blob_entry,
    commit,
    commit_message,
    github_session,
    local_alerts,
    remote_state,
)

FOLDER = "Alerts/csv"


def new_alerts(remote_names, local):
    """local csv files later than the newest one in the repo"""
    if not remote_names:
        return local[-1:]
    last = max(remote_names)
    return [f for f in local if os.path.basename(f) > last]


def commit_files(session, head, tree, files):
    """one commit adding files to the repo folder; False if the branch moved"""
    entries = [blob_entry(session, f"{FOLDER}/{os.path.basename(f)}", f) for f in files]
    return commit(session, head, tree, entries, commit_message("alerts", files))


def publish_alerts(alerts_dir, dry_run=False):
    """push the final alerts newer than the newest one in the repo"""
    local = local_alerts(alerts_dir)
    session = github_session("publish alerts", dry_run)
    if session is None:
        return

    for _ in range(RETRIES):
        head, tree, remote_names = remote_state(session, FOLDER, ".csv", "publish alerts")
        files = new_alerts(remote_names, local)
        if not files:
            logging.info(f"publish alerts: {REPO}/{FOLDER} is up to date")
            return
        if dry_run:
            logging.info(
                f"publish alerts (dry run): newest in repo: {max(remote_names, default='none')}"
            )
            for f in files:
                logging.info(f"publish alerts (dry run): would push {os.path.basename(f)}")
            return
        if commit_files(session, head, tree, files):
            logging.info(
                f"publish alerts: pushed {len(files)} file(s) to {REPO}/{FOLDER}, last {os.path.basename(files[-1])}"
            )
            return
        logging.info("publish alerts: branch moved during the push, retrying")
    logging.warning(f"publish alerts: gave up after {RETRIES} attempts")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="push new final alerts to GitHub")
    parser.add_argument("alerts_dir", help="the final alerts folder to publish")
    parser.add_argument(
        "--dry-run", action="store_true", help="only list what would be pushed"
    )
    # stdout: run_mom_job.sh's cron entry appends it to the job's cron log
    logging.basicConfig(
        stream=sys.stdout, level=logging.INFO, format=settings.LOG_FORMAT, force=True
    )
    args = parser.parse_args()
    publish_alerts(args.alerts_dir, args.dry_run)
