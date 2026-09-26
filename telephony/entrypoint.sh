#!/bin/sh
# Renders /opt/radeski/asterisk/*.conf into /etc/asterisk (placeholders are @@NAME@@, taken from
# the environment) and starts Asterisk in the foreground.
set -eu

: "${PBX_API_SECRET:?PBX_API_SECRET kerak}"
: "${PBX_SIP_SECRET:?PBX_SIP_SECRET kerak}"
export PBX_CRM_URL="${PBX_CRM_URL:-http://web}"
export PBX_SIP_PORT="${PBX_SIP_PORT:-5060}"
export PBX_RTP_START="${PBX_RTP_START:-17000}"
export PBX_RTP_END="${PBX_RTP_END:-17039}"
export PBX_OPEN_HOURS="${PBX_OPEN_HOURS:-08:00-17:59}"
export PBX_OPEN_DAYS="${PBX_OPEN_DAYS:-mon-sat}"
export PBX_QUEUE_WAIT="${PBX_QUEUE_WAIT:-90}"
export PBX_EXTENSIONS="${PBX_EXTENSIONS:-101 102 103 104}"
export SIP_PORT="${SIP_PORT:-5060}"
export SIP_NUMBER="${SIP_NUMBER:-}"
export SIP_DIAL_PREFIX="${SIP_DIAL_PREFIX:-998}"

SRC=/opt/radeski/asterisk
DST=/etc/asterisk

render() {
    perl -pe 's/@@(\w+)@@/exists $ENV{$1} ? $ENV{$1} : die "missing \@\@$1\@\@ in $ARGV\n"/ge' "$1" > "$2"
}

for f in "$SRC"/*.conf; do
    render "$f" "$DST/$(basename "$f")"
done

# operator softphones (WebRTC): password = HMAC(PBX_SIP_SECRET, "ext:<n>")[:32], the CRM derives
# the same value and hands it only to the user who owns that extension
: > "$DST/pjsip_operators.conf"
for ext in $PBX_EXTENSIONS; do
    password=$(printf 'ext:%s' "$ext" | openssl dgst -sha256 -hmac "$PBX_SIP_SECRET" -r | cut -c1-32)
    EXT="$ext" EXT_PASSWORD="$password" render "$SRC/templates/operator.conf" /tmp/op.conf
    cat /tmp/op.conf >> "$DST/pjsip_operators.conf"
    echo "member => PJSIP/$ext" >> "$DST/queue_members.conf.tmp"
done
mv "$DST/queue_members.conf.tmp" "$DST/queue_members.conf"
rm -f /tmp/op.conf

# Uztelecom trunk only once its credentials are known; without it the PBX still serves the
# softphones (echo test 600, operator-to-operator calls)
if [ -n "${SIP_HOST:-}" ]; then
    render "$SRC/templates/trunk.conf" "$DST/pjsip_trunk.conf"
else
    echo "; SIP_HOST is empty: no trunk" > "$DST/pjsip_trunk.conf"
    echo "WARNING: SIP_HOST bo'sh — Uztelecom trunk ulanmagan" >&2
fi

# NAT: the container sits behind Docker and the office router
: > "$DST/pjsip_nat.conf"
: > "$DST/rtp_ice.conf"
if [ -n "${PBX_PUBLIC_IP:-}" ]; then
    {
        echo "external_media_address=$PBX_PUBLIC_IP"
        echo "external_signaling_address=$PBX_PUBLIC_IP"
        for net in ${PBX_LOCAL_NETS:-172.16.0.0/12 192.168.0.0/16 10.0.0.0/8}; do
            echo "local_net=$net"
        done
    } > "$DST/pjsip_nat.conf"
    {
        echo "[ice_host_candidates]"
        for ip in $(hostname -i); do
            echo "$ip => $PBX_PUBLIC_IP"
        done
    } > "$DST/rtp_ice.conf"
fi

# custom voice prompts (radeski/*.wav); files mounted into /opt/radeski/sounds-custom win
mkdir -p /usr/share/asterisk/sounds/radeski
cp -f /opt/radeski/sounds/*.wav /usr/share/asterisk/sounds/radeski/ 2>/dev/null || true
cp -f /opt/radeski/sounds-custom/*.wav /usr/share/asterisk/sounds/radeski/ 2>/dev/null || true

mkdir -p /var/run/asterisk /var/log/asterisk
chown -R asterisk:asterisk /var/lib/asterisk /var/spool/asterisk /var/log/asterisk /var/run/asterisk "$DST"
# recordings: group "crm" (gid 10001 = the backend's user) may convert and delete them
REC=/var/spool/asterisk/recordings
mkdir -p "$REC"
chown -R asterisk:crm "$REC"
chmod 2775 "$REC"
chmod -R g+rw "$REC"

umask 002
# no -v: verbose dialplan tracing would print the CRM secret into the container log
exec asterisk -f -U asterisk -G asterisk
