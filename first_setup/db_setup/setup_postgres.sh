#!/usr/bin/env bash
# =============================================================================
# setup_postgres.sh
# Installs PostgreSQL + PostGIS on Ubuntu, stores the database cluster under
# /root/postgres/data/, runs the schema DDL, and creates a restricted user.
#
# Safe to re-run at any time:
#   - Skips cluster creation if already set up at the correct data directory
#   - Re-applies all config, grants, and schema changes on every run
#   - Existing data is never deleted
#
# Must be run as a user with sudo privileges.
# =============================================================================

set -euo pipefail

# ---------- configuration ----------------------------------------------------
SCRIPT_DIR="$(dirname "$0")"
PROJECT_ROOT="$(realpath "${SCRIPT_DIR}/../..")"
PROD_CONFIG="${PROJECT_ROOT}/production.cfg"
SQL_FILE="${SCRIPT_DIR}/create_all_tables.sql"
SQL_ID_TRIGGERS="${SCRIPT_DIR}/create_id_resolution_triggers.sql"
SQL_HISTORY_TRIGGERS="${SCRIPT_DIR}/create_history_triggers.sql"
SQL_STAGING="${SCRIPT_DIR}/create_staging_tables.sql"
SQL_QUERY_FUNCTIONS="${SCRIPT_DIR}/create_query_functions.sql"
SQL_VIEWS="${SCRIPT_DIR}/create_history_views.sql"

if [[ ! -f "$PROD_CONFIG" ]]; then
    echo "ERROR: Production config not found: $PROD_CONFIG"
    echo "       Copy sample_production.cfg to production.cfg and fill in the values."
    exit 1
fi

cfg() { sed -n "/^\[$1\]/,/^\[/{/^$2[[:space:]]*:/{s/^$2[[:space:]]*:[[:space:]]*//;p;q}}" "$PROD_CONFIG"; }

DB_NAME=$(cfg db DB_NAME)
ADMIN_USER=$(cfg db ADMIN_USER)
ADMIN_PASSWORD=$(cfg db ADMIN_PASSWORD)
INTERNAL_READER_USER=$(cfg db INTERNAL_READER_USER)
INTERNAL_READER_PASSWORD=$(cfg db INTERNAL_READER_PASSWORD)
DB_DATA_DIR=$(cfg db DB_DATA_DIR)
DB_DATA_DIR="${DB_DATA_DIR/#\~/$HOME}"

if [[ "$ADMIN_PASSWORD" == "???" ]]; then
    echo "ERROR: ADMIN_PASSWORD is not set in $PROD_CONFIG"
    echo "       Replace the ??? placeholder with a real password and re-run."
    exit 1
fi

if [[ "$INTERNAL_READER_PASSWORD" == "???" ]]; then
    echo "ERROR: INTERNAL_READER_PASSWORD is not set in $PROD_CONFIG"
    echo "       Replace the ??? placeholder with a real password and re-run."
    exit 1
fi
# -----------------------------------------------------------------------------

for f in "$SQL_FILE" "$SQL_ID_TRIGGERS" "$SQL_HISTORY_TRIGGERS" "$SQL_STAGING" "$SQL_QUERY_FUNCTIONS" "$SQL_VIEWS"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: SQL file not found: $f"
        exit 1
    fi
done

echo "=== [1/9] Configuring swap (guards against OOM kills on low-RAM servers) ==="
SWAP_FILE="/swapfile"
SWAP_SIZE="2G"

# Detect environments where swap cannot be enabled (containers, certain VMs).
# Signs: /proc/1/cgroup shows docker/lxc, or the kernel explicitly disallows swapon.
_swap_supported=true
if grep -qE '(docker|lxc|kubepods)' /proc/1/cgroup 2>/dev/null; then
    echo "    Container environment detected — swap is controlled by the host, skipping."
    _swap_supported=false
fi

if [[ "$_swap_supported" == true ]]; then
    if swapon --show | grep -q "$SWAP_FILE"; then
        echo "    Swap file ${SWAP_FILE} already active, skipping."
    elif [[ -f "$SWAP_FILE" ]]; then
        echo "    Swap file ${SWAP_FILE} exists but is not active — activating..."
        if ! sudo swapon "$SWAP_FILE" 2>/dev/null; then
            echo "    WARNING: swapon failed (unsupported by this kernel/environment) — skipping swap."
            _swap_supported=false
        fi
    else
        # Check root filesystem has enough space before allocating
        _root_avail_kb=$(df --output=avail / | tail -1)
        _needed_kb=$((2 * 1024 * 1024))  # 2 GB in KB
        if [[ "$_root_avail_kb" -lt "$_needed_kb" ]]; then
            echo "    WARNING: Less than 2 GB free on / (${_root_avail_kb} KB available) — skipping swap."
            _swap_supported=false
        else
            echo "    Creating ${SWAP_SIZE} swap file at ${SWAP_FILE}..."
            # fallocate is instant but unsupported on btrfs/NFS; fall back to dd
            if ! sudo fallocate -l "$SWAP_SIZE" "$SWAP_FILE" 2>/dev/null; then
                echo "    fallocate unsupported on this filesystem — using dd fallback..."
                if ! sudo dd if=/dev/zero of="$SWAP_FILE" bs=1M count=2048 status=none 2>/dev/null; then
                    echo "    WARNING: dd failed (I/O error or filesystem full) — cleaning up."
                    sudo rm -f "$SWAP_FILE"
                    _swap_supported=false
                fi
            fi
            if [[ "$_swap_supported" == true ]]; then
                sudo chmod 600 "$SWAP_FILE"
                if ! sudo mkswap "$SWAP_FILE" > /dev/null 2>&1; then
                    echo "    WARNING: mkswap failed — cleaning up."
                    sudo rm -f "$SWAP_FILE"
                    _swap_supported=false
                fi
            fi
            if [[ "$_swap_supported" == true ]]; then
                if ! sudo swapon "$SWAP_FILE" 2>/dev/null; then
                    echo "    WARNING: swapon failed (unsupported by this kernel/environment) — cleaning up."
                    sudo rm -f "$SWAP_FILE"
                    _swap_supported=false
                else
                    # Persist across reboots via a systemd swap unit rather than
                    # /etc/fstab: a missing/corrupt swap file at boot time will be
                    # logged and skipped rather than dropping the system to an
                    # emergency shell.
                    SWAP_UNIT="/etc/systemd/system/swapfile.swap"
                    if [[ ! -f "$SWAP_UNIT" ]]; then
                        sudo tee "$SWAP_UNIT" > /dev/null <<EOF
[Unit]
Description=Swap file
After=local-fs.target

[Swap]
What=${SWAP_FILE}

[Install]
WantedBy=swap.target
EOF
                        sudo systemctl daemon-reload
                        sudo systemctl enable swapfile.swap
                        echo "    Registered ${SWAP_FILE} as systemd swap unit (persists across reboots)."
                    fi
                    echo "    Swap created and active."
                fi
            fi
        fi
    fi
fi

# Set swappiness=1: kernel uses swap only as a last resort (~last 5% of RAM pressure),
# keeping all hot data in RAM under normal load.
if [[ "$_swap_supported" == true ]]; then
    echo "    Setting vm.swappiness=1 (use swap only under extreme memory pressure)..."
    sudo sysctl -w vm.swappiness=1 > /dev/null
    # Write to a drop-in file rather than /etc/sysctl.conf so that the setting
    # wins over distro-shipped files (which use lower numeric prefixes like 10-,
    # 50-) regardless of what the base image or prior tooling has set.
    echo "vm.swappiness=1" | sudo tee /etc/sysctl.d/99-mom-swappiness.conf > /dev/null
    echo "    Persisted vm.swappiness=1 in /etc/sysctl.d/99-mom-swappiness.conf."
fi

free -h | grep -E "^(Mem|Swap):"

echo "=== [2/9] Installing PostgreSQL and PostGIS ==="
sudo apt-get update -y
sudo apt-get install -y \
    postgresql \
    postgresql-contrib \
    postgis \
    postgresql-postgis

PG_VERSION=$(ls /usr/lib/postgresql/ | sort -V | tail -1)
PG_CONF_DIR="/etc/postgresql/${PG_VERSION}/main"
echo "    PostgreSQL version: ${PG_VERSION}"

echo "=== [3/9] Setting up database cluster at ${DB_DATA_DIR} ==="
EXISTING_DATADIR=$(pg_lsclusters -h 2>/dev/null | awk 'NR==1{print $6}')

if [[ "$EXISTING_DATADIR" == "$DB_DATA_DIR" ]]; then
    echo "    Cluster already at ${DB_DATA_DIR}, skipping cluster creation."
else
    echo "    Creating new cluster at ${DB_DATA_DIR}..."
    sudo pg_dropcluster --stop "${PG_VERSION}" main || true

    sudo mkdir -p "${DB_DATA_DIR}"
    # Allow the postgres OS user to traverse into /root and the parent folder.
    # o+x = execute only (can enter the directory, cannot list its contents).
    sudo chmod o+x /root
    sudo chmod o+x "$(dirname "${DB_DATA_DIR}")"
    sudo chown postgres:postgres "${DB_DATA_DIR}"
    sudo chmod 700 "${DB_DATA_DIR}"

    sudo pg_createcluster --datadir "${DB_DATA_DIR}" "${PG_VERSION}" main
fi

echo "=== [4/9] Enabling remote connections ==="
sudo sed -i "s/^#*listen_addresses\s*=.*/listen_addresses = '*'/" \
    "${PG_CONF_DIR}/postgresql.conf"

REMOTE_RULE="host    ${DB_NAME}    ${ADMIN_USER}    0.0.0.0/0    scram-sha-256"
if ! sudo grep -qF "${REMOTE_RULE}" "${PG_CONF_DIR}/pg_hba.conf"; then
    echo "${REMOTE_RULE}" | sudo tee -a "${PG_CONF_DIR}/pg_hba.conf" > /dev/null
    echo "    Remote access rule added."
else
    echo "    Remote access rule already present, skipping."
fi

if command -v ufw &>/dev/null; then
    sudo ufw allow 5432/tcp
fi

echo "=== [5/9] Starting PostgreSQL service ==="
sudo systemctl enable postgresql
sudo systemctl restart postgresql

echo "=== [6/9] Running schema DDL (PostGIS extension + all tables + triggers + functions) ==="
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" -f "${SQL_FILE}"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" -f "${SQL_ID_TRIGGERS}"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" -f "${SQL_HISTORY_TRIGGERS}"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" -f "${SQL_STAGING}"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" -f "${SQL_QUERY_FUNCTIONS}"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" -f "${SQL_VIEWS}"

echo "=== [7/9] Loading watershed shapefile into watershed_shapes ==="
WATERSHED_DIR="${PROJECT_ROOT}/data/watershed_shp"
SHP_FILE="${WATERSHED_DIR}/Watershed_pfaf_id.shp"
SHP_ZIP="${SHP_FILE}.zip"

ROW_COUNT=$(sudo -u postgres psql -t -d "${DB_NAME}" \
    -c "SELECT COUNT(*) FROM watershed_shapes;" | tr -d ' \n')

if [[ "$ROW_COUNT" -gt 0 ]]; then
    echo "    watershed_shapes already has ${ROW_COUNT} rows, skipping load."
else
    if [[ ! -f "$SHP_FILE" ]]; then
        if [[ -f "$SHP_ZIP" ]]; then
            echo "    Shapefile not found — unzipping ${SHP_ZIP}..."
            unzip -q "$SHP_ZIP" -d "$WATERSHED_DIR"
        else
            echo "ERROR: Shapefile not found at ${SHP_FILE}"
            echo "       Expected zip at ${SHP_ZIP}"
            exit 1
        fi
    fi
    echo "    Loading ${SHP_FILE} into watershed_shapes..."
    shp2pgsql -s 4326 -a "${SHP_FILE}" watershed_shapes \
        | sed 's/"iso"/"ISO"/g; s/"admin0"/"Admin0"/g; s/"admin1"/"Admin1"/g' \
        | sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}"
    echo "    Shapefile loaded."
fi

echo "=== [8/9] Creating/updating restricted admin user '${ADMIN_USER}' ==="
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${ADMIN_USER}') THEN
        CREATE ROLE "${ADMIN_USER}" WITH LOGIN PASSWORD '${ADMIN_PASSWORD}';
    ELSE
        ALTER ROLE "${ADMIN_USER}" WITH LOGIN PASSWORD '${ADMIN_PASSWORD}';
    END IF;
END
\$\$;

GRANT CONNECT ON DATABASE "${DB_NAME}" TO "${ADMIN_USER}";
GRANT USAGE ON SCHEMA public TO "${ADMIN_USER}";

-- SELECT, INSERT, UPDATE on all tables; DELETE also granted on staging tables
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "${ADMIN_USER}";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO "${ADMIN_USER}";

-- DELETE on staging and latest tables
GRANT DELETE ON
    stage_gfms, stage_hwrf, stage_viirs, stage_dfo, stage_glofas, stage_final_alert,
    stage_mom_gfms, stage_mom_hwrf, stage_mom_dfo, stage_mom_viirs,
    summary_gfms_latest, summary_hwrf_latest, summary_viirs_latest,
    summary_dfo_latest, summary_glofas_latest, summary_final_alert_latest,
    mom_gfms_latest, mom_hwrf_latest, mom_dfo_latest, mom_viirs_latest
    TO "${ADMIN_USER}";

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "${ADMIN_USER}";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO "${ADMIN_USER}";

ALTER ROLE "${ADMIN_USER}" SET statement_timeout = '300s';
SQL

echo "=== [9/9] Creating/updating reader roles ==="

# Allow mom_internal_reader to connect remotely
READER_RULE="host    ${DB_NAME}    ${INTERNAL_READER_USER}    0.0.0.0/0    scram-sha-256"
if ! sudo grep -qF "${READER_RULE}" "${PG_CONF_DIR}/pg_hba.conf"; then
    echo "${READER_RULE}" | sudo tee -a "${PG_CONF_DIR}/pg_hba.conf" > /dev/null
    echo "    Remote access rule for ${INTERNAL_READER_USER} added."
else
    echo "    Remote access rule for ${INTERNAL_READER_USER} already present, skipping."
fi
sudo systemctl reload postgresql

sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<SQL
-- mom_reader: permission group only, no login — sub-roles inherit SELECT from here
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mom_reader') THEN
        CREATE ROLE mom_reader;
    END IF;
END
\$\$;

-- mom_internal_reader: login role, inherits from mom_reader
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${INTERNAL_READER_USER}') THEN
        CREATE ROLE "${INTERNAL_READER_USER}" WITH LOGIN PASSWORD '${INTERNAL_READER_PASSWORD}' IN ROLE mom_reader;
    ELSE
        ALTER ROLE "${INTERNAL_READER_USER}" WITH LOGIN PASSWORD '${INTERNAL_READER_PASSWORD}';
        GRANT mom_reader TO "${INTERNAL_READER_USER}";
    END IF;
END
\$\$;

GRANT CONNECT ON DATABASE "${DB_NAME}" TO mom_reader;
GRANT USAGE ON SCHEMA public TO mom_reader;

-- SELECT on all data tables (not staging)
GRANT SELECT ON
    watershed_shapes,
    all_glofas_stations,
    all_watersheds,
    summary_gfms, summary_hwrf, summary_viirs, summary_dfo, summary_glofas, summary_final_alert,
    summary_gfms_latest, summary_hwrf_latest, summary_viirs_latest,
    summary_dfo_latest, summary_glofas_latest, summary_final_alert_latest,
    mom_gfms, mom_hwrf, mom_dfo, mom_viirs,
    mom_gfms_latest, mom_hwrf_latest, mom_dfo_latest, mom_viirs_latest,
    view_summary_gfms, view_summary_hwrf, view_summary_viirs,
    view_summary_dfo, view_summary_glofas, view_summary_final_alert,
    view_mom_gfms, view_mom_hwrf, view_mom_dfo, view_mom_viirs
    TO mom_reader;

ALTER ROLE mom_reader SET statement_timeout = '300s';
SQL

echo ""
echo "============================================================"
echo "Setup complete."
echo "  Database     : ${DB_NAME}"
echo "  Data dir     : ${DB_DATA_DIR}"
echo "  App user     : ${ADMIN_USER}  (remote access, restricted)"
echo "  Host         : <this machine's IP address>"
echo "  Port         : 5432"
echo ""
echo "  Change app user password with:"
echo "  sudo -u postgres psql -c \"ALTER ROLE ${ADMIN_USER} WITH PASSWORD 'newpassword';\""
echo "============================================================"
