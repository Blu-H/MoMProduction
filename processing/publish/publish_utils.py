"""
Shared by publish_alerts and publish_tiles: the GitHub API calls that push
files into a repo folder without a local clone, and the local final alerts.

Needs in the environment or .env (without them, nothing is pushed):
    GITHUB_REPO              the target repo as owner/name
    GITHUB_ALERTS_TOKEN   fine-grained token with Contents read/write on it

"""

import base64
import glob
import logging
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()

# setting GITHUB_REPO / GITHUB_ALERTS_TOKEN on Linux:
#   - for cron: add them to .env in the repository root, which
#     load_dotenv() above reads; cron jobs do not load ~/.bashrc or ~/.profile
#         GITHUB_REPO=owner/name
#         GITHUB_ALERTS_TOKEN=github_pat_...
#   - for the current shell only (e.g. a manual --dry-run):
#         export GITHUB_REPO=owner/name
#         export GITHUB_ALERTS_TOKEN=github_pat_...

API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPO")
BRANCH = "main"
# a concurrent job may move the branch between our read and our update
RETRIES = 3


def gh(session, method, path, **kwargs):
    """call the GitHub API, raise on error, return the json"""
    r = session.request(method, f"{API}/repos/{REPO}/{path}", timeout=60, **kwargs)
    r.raise_for_status()
    return r.json()


def github_session(label, dry_run=False):
    """an API session, or None (logged) when the repo or token is missing"""
    if not REPO:
        logging.info(f"{label}: no GITHUB_REPO configured, skipped")
        return None
    token = os.getenv("GITHUB_ALERTS_TOKEN")
    if not token and not dry_run:
        logging.info(f"{label}: no GitHub token configured, skipped")
        return None
    session = requests.Session()
    session.headers.update(
        {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    )
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def remote_state(session, folder, suffix, label):
    """head commit, its tree and the names of the suffix files in the repo folder"""
    head = gh(session, "GET", f"git/ref/heads/{BRANCH}")["object"]["sha"]
    tree = gh(session, "GET", f"git/commits/{head}")["tree"]["sha"]
    listing = gh(session, "GET", f"git/trees/{tree}", params={"recursive": 1})
    if listing.get("truncated"):
        logging.warning(f"{label}: {REPO} tree listing truncated")
    prefix = folder + "/"
    names = [
        e["path"][len(prefix) :]
        for e in listing["tree"]
        if e["type"] == "blob"
        and e["path"].startswith(prefix)
        and e["path"].endswith(suffix)
    ]
    return head, tree, names


def local_alerts(alerts_dir):
    """the final alert csv files in alerts_dir, oldest first"""
    return sorted(glob.glob(os.path.join(alerts_dir, "*.csv")))


CYCLE = re.compile(r"_(\d{10})")


def alert_cycle(name):
    """the YYYYMMDDHH cycle of an alert file name, else the name itself"""
    m = CYCLE.search(name)
    return m.group(1) if m else name


def blob_entry(session, path, local_file):
    """tree entry adding local_file to the repo at path"""
    with open(local_file, "rb") as fh:
        content = base64.b64encode(fh.read()).decode("ascii")
    blob = gh(
        session,
        "POST",
        "git/blobs",
        json={"content": content, "encoding": "base64"},
    )
    return {"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}


def commit_message(kind, files):
    """<kind>_<cycle>, or <kind>_<first>_to_<last> for several files"""
    cycles = [alert_cycle(os.path.basename(f)) for f in files]
    return (
        f"{kind}_{cycles[0][:8]}_{cycles[0][8:]}"
        if len(cycles) == 1
        else f"{kind}_{cycles[0][:8]}_{cycles[0][8:]}_to_{cycles[-1][:8]}_{cycles[-1][8:]}"
    )


def commit(session, head, tree, entries, message):
    """one commit of the tree entries on the branch; False if the branch moved"""
    new_tree = gh(
        session, "POST", "git/trees", json={"base_tree": tree, "tree": entries}
    )["sha"]
    sha = gh(
        session,
        "POST",
        "git/commits",
        json={"message": message, "tree": new_tree, "parents": [head]},
    )["sha"]
    r = session.patch(
        f"{API}/repos/{REPO}/git/refs/heads/{BRANCH}",
        json={"sha": sha, "force": False},
        timeout=60,
    )
    if r.status_code == 422:  # not a fast-forward: someone pushed meanwhile
        return False
    r.raise_for_status()
    return True
