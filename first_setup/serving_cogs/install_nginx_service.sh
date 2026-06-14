#!/usr/bin/env bash
# Installs a systemd service that starts the COG nginx server (port 8090) on
# every system reboot.  Run once as root:
#   sudo bash first_setup/serving_cogs/install_nginx_service.sh
#   verify: systemctl status nginx-cog

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CONDA=""
for _c in "$(which conda 2>/dev/null || true)" /root/miniconda3/bin/conda /opt/miniconda3/bin/conda /usr/local/bin/conda; do
    if [[ -x "$_c" ]]; then CONDA="$_c"; break; fi
done
if [[ -z "$CONDA" ]]; then echo "ERROR: conda not found" >&2; exit 1; fi
CONDA_RUN="${CONDA} run -n myenv"

SERVICE_NAME="nginx-cog"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Nginx COG image server (port 8090)
After=network.target remote-fs.target

[Service]
Type=forking
PIDFile=${SCRIPT_DIR}/nginx_cog.pid
ExecStartPre=-${CONDA_RUN} python ${SCRIPT_DIR}/serve_cog_nginx.py stop
ExecStartPre=-/usr/bin/fuser -k 8090/tcp
ExecStart=${CONDA_RUN} python ${SCRIPT_DIR}/serve_cog_nginx.py start
ExecStop=-${CONDA_RUN} python ${SCRIPT_DIR}/serve_cog_nginx.py stop
RemainAfterExit=no
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=120
StartLimitBurst=3

[Install]
WantedBy=multi-user.target
EOF

echo "Service file written to $SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo ""
echo "Done. Service status:"
systemctl status "$SERVICE_NAME" --no-pager -l
