# Radeski PBX: Asterisk 20 (Ubuntu package) with a config rendered from env at start.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Tashkent

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asterisk asterisk-modules asterisk-moh-opsound-wav asterisk-core-sounds-ru-wav \
        ca-certificates openssl tzdata \
    && rm -rf /var/lib/apt/lists/* \
    # Asterisk reads /etc/localtime, not $TZ (clinic hours in the IVR, log times)
    && ln -sf /usr/share/zoneinfo/Asia/Tashkent /etc/localtime \
    && echo Asia/Tashkent > /etc/timezone \
    # keep only what the package needs to boot; everything else is ours
    && find /etc/asterisk -type f ! -name asterisk.conf ! -name indications.conf -delete \
    # recordings are shared with the CRM worker (uid/gid 10001 in the backend image)
    && groupadd --gid 10001 crm \
    && usermod -aG crm asterisk

COPY asterisk/ /opt/radeski/asterisk/
COPY sounds/ /opt/radeski/sounds/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5060/udp 8088
ENTRYPOINT ["/entrypoint.sh"]
