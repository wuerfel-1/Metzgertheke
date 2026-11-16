#!/usr/bin/env bash
# Fleischer-Theke – Ersteinrichtung eines frischen Ubuntu-24.04-Servers (als root ausführen)
set -euo pipefail

REPO="https://github.com/wuerfel-1/Metzgertheke.git"
DIR="/srv/fleischer-theke"

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq git ufw fail2ban unattended-upgrades debian-keyring debian-archive-keyring apt-transport-https curl gnupg

# Sicherheitsupdates automatisch einspielen
dpkg-reconfigure -f noninteractive unattended-upgrades

# SSH: nur noch Schlüssel, keine Passwörter
cat > /etc/ssh/sshd_config.d/10-fleischer-theke.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
# Neuere Ubuntu-Versionen starten sshd per Socket je Verbindung und lesen die Konfiguration dann ohnehin neu
systemctl try-reload-or-restart ssh || true

# Firewall: nur SSH und Web
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Caddy aus dem offiziellen Repository
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt-get update -q
apt-get install -yq caddy

# App-Dateien: eigener Benutzer ohne Login, holt den Stand von GitHub
id site >/dev/null 2>&1 || useradd --system --home "$DIR" --shell /usr/sbin/nologin site
mkdir -p "$DIR"
chown site:site "$DIR"
if [ ! -d "$DIR/site/.git" ]; then
  sudo -u site git clone -q "$REPO" "$DIR/site"
fi

# Alle 5 Minuten aktualisieren (Montags-Update läuft weiter über GitHub Actions)
cat > /etc/cron.d/fleischer-theke <<EOF
*/5 * * * * site cd $DIR/site && git pull -q --ff-only
EOF

install -m 644 "$DIR/site/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

echo "Fertig. Caddy holt die Zertifikate, sobald die DNS-Einträge auf diesen Server zeigen."
