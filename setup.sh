#!/usr/bin/env bash
# Reproducible setup: prepare the Windows-side debug Chrome + CDP bridge for
# the SIMASTER scraper. Run this from WSL after closing the Windows Chrome
# whose profile holds the SIMASTER session.
#
#   bash setup.sh
#
# What it does:
#   1. Copies the session profile files (Local State + cookie DB) to a dedicated
#      user-data dir so Chrome 136+ accepts --remote-debugging-port.
#   2. Ensures a Windows portproxy 9223 -> 9222 (WSL2 NAT cannot reach a
#      loopback-only port) plus a firewall rule.
#   3. Launches Chrome detached with the debugging flags.
#   4. Verifies CDP connectivity from WSL.
set -euo pipefail

# --- Config -------------------------------------------------------------
WIN_USER="${WIN_USER:-asus}"          # Windows user whose profile has the session
UD_DST_NAME="simaster-scrape-udata"
CHROME_EXE="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
PORT_DEBUG=9222
PORT_PROXY=9223

UD_SOURCE="/mnt/c/Users/${WIN_USER}/AppData/Local/Google/Chrome/User Data"
UD_DST="/mnt/c/Users/${WIN_USER}/${UD_DST_NAME}"
WIN_UD_DST="C:\\Users\\${WIN_USER}\\${UD_DST_NAME}"

GW=$(ip route show default | awk '{print $3}')
echo "[setup] Windows host: ${GW}"

DEBUG_RUNNING=$(powershell.exe -NoProfile -Command "
  Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" |
    Where-Object { \$_.CommandLine -like '*${UD_DST_NAME}*' } |
    Measure-Object | Select-Object -ExpandProperty Count
" 2>/dev/null | tr -d '\r')

# --- 1. Copy session profile --------------------------------------------
if [ "$DEBUG_RUNNING" -gt 0 ] 2>/dev/null; then
    echo "[setup] debug Chrome already running on ${UD_DST_NAME} -- skipping profile copy and relaunch."
elif [ ! -d "$UD_SOURCE" ]; then
    echo "[setup] ERROR: source profile not found at $UD_SOURCE" >&2
    exit 1
else
mkdir -p "$UD_DST/Default/Network"
cp "$UD_SOURCE/Local State" "$UD_DST/"
cp "$UD_SOURCE/Default/Network/Cookies" "$UD_DST/Default/Network/"
cp "$UD_SOURCE/Default/Network/Cookies-journal" "$UD_DST/Default/Network/" 2>/dev/null || true
for f in "Preferences" "Secure Preferences"; do
    cp "$UD_SOURCE/Default/$f" "$UD_DST/Default/" 2>/dev/null || true
done
SIZE=$(stat -c %s "$UD_DST/Default/Network/Cookies")
if [ "$SIZE" -lt 100000 ]; then
    echo "[setup] WARNING: copied Cookies DB is only ${SIZE} bytes; the source "
    echo "         profile may still be running (close all Chrome windows first)."
fi
echo "[setup] copied session profile to ${UD_DST}"
fi

# --- 2. Portproxy + firewall rule (idempotent, needs admin) ---------------
powershell.exe -NoProfile -Command "
  \$pp = netsh interface portproxy show v4tov4 | Select-String '${PORT_PROXY}'
  if (\$null -eq \$pp) {
    netsh interface portproxy add v4tov4 listenport=${PORT_PROXY} listenaddress=0.0.0.0 connectport=${PORT_DEBUG} connectaddress=127.0.0.1
    netsh advfirewall firewall add rule name='wsl-cdp' dir=in action=allow protocol=TCP localport=${PORT_PROXY}
    Write-Output 'portproxy + firewall rule added'
  } else {
    Write-Output 'portproxy already present'
  }
" 2>&1

# --- 3. Launch debug Chrome (detached) -----------------------------------
if [ "$DEBUG_RUNNING" -eq 0 ] 2>/dev/null; then
    echo "[setup] launching debug Chrome on ${WIN_UD_DST}..."
    powershell.exe -NoProfile -Command "
      Start-Process -FilePath '$CHROME_EXE' -ArgumentList '--remote-debugging-address=0.0.0.0','--remote-debugging-port=${PORT_DEBUG}','--user-data-dir=${WIN_UD_DST}','https://simaster.ugm.ac.id'
    " 2>&1
fi

# --- 4. Verify CDP -------------------------------------------------------
echo "[setup] waiting for CDP on ${GW}:${PORT_PROXY}..."
for i in $(seq 1 15); do
    if curl -s -m 5 "http://${GW}:${PORT_PROXY}/json/version" | grep -q '"Browser"'; then
        echo "[setup] OK: CDP reachable at http://${GW}:${PORT_PROXY}"
        exit 0
    fi
    sleep 2
done
echo "[setup] ERROR: CDP not reachable. Is the firewall/portproxy in place?" >&2
exit 1