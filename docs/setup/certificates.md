# Certificates & the trust model

This is the piece that makes the robot trust *your* broker. It's a one-time
setup and, once you understand the model, only a few `openssl` commands.

## How trust works

The robot verifies the broker's TLS server certificate
(`MBEDTLS_SSL_VERIFY_REQUIRED`) and checks the **hostname** against whatever host
you provisioned it with. So two things must line up:

1. You generate **your own Certificate Authority (CA)**. whiskerless provisions
   that CA into the robot's *root-CA slot* over BLE (replacing Amazon's). That's
   what tells the robot "trust certificates signed by this CA."
2. Your broker presents a **server certificate signed by your CA**, and that
   cert must carry the **address you provisioned as the broker host** in its
   Subject Alternative Name (SAN).

> **If you provision an IP address** as the broker host (the common case), the
> server cert must include that IP as **both an `IP` SAN and a `DNS` SAN** — some
> TLS stacks match an IP literal against the DNS-name list, so cover both.

```
your CA  ──signs──▶  broker server cert (SAN = <broker-ip>)
   │                        ▲
   │ provisioned            │ presented on :8883
   ▼                        │
 robot ───────TLS verify────┘   ✔ trusts the broker
```

## Generate the CA

A long-lived CA (10 years here) so you don't have to revisit the robot often.
**Keep `ca.key` safe** — it's your trust anchor. (You only ever provision
`ca.crt` into the robot; the key just signs the server cert.)

```bash
# 1. CA private key + self-signed CA certificate.
openssl genrsa -out ca.key 2048
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
  -subj "/CN=whiskerless local CA" \
  -out ca.crt
```

## Generate the broker server cert (with IP SAN)

Replace `<broker-ip>` with your broker's address (e.g. `192.0.2.10`).

```bash
# 2. Server key + CSR.
openssl genrsa -out server.key 2048
openssl req -new -key server.key -subj "/CN=<broker-ip>" -out server.csr

# 3. Sign it with your CA, embedding the IP as BOTH an IP and DNS SAN.
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days 3650 -sha256 \
  -extfile <(printf "subjectAltName=IP:<broker-ip>,DNS:<broker-ip>\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n") \
  -out server.crt
```

You now have:

| File | Goes to |
|---|---|
| `ca.crt` | the broker (`cafile`) **and** provisioned into the robot (and into Home Assistant's MQTT integration, if it connects to the broker over TLS) |
| `server.crt` | the broker (`certfile`) |
| `server.key` | the broker (`keyfile`) — keep private |
| `ca.key` | kept offline/safe — signs future server certs |

Verify the SANs landed correctly:

```bash
openssl x509 -in server.crt -noout -text | grep -A1 "Subject Alternative Name"
# X509v3 Subject Alternative Name:
#     IP Address:<broker-ip>, DNS:<broker-ip>
```

## Using a hostname instead of an IP

If you'd rather provision a hostname (e.g. `mqtt.example.lan`) than an IP, make a
DNS record that resolves to the broker for the robot's network, and set the SAN
to `DNS:mqtt.example.lan`. Then provision that hostname as the broker host.

## Hostname verification

The CA check is always enforced. The **hostname** check is the one that can trip
you up when you reach the broker indirectly (by IP, or through a tunnel /
port-forward where the SNI no longer matches the cert SAN):

- **The robot** verifies the broker host against the SAN you provision, so make
  the SAN match the host you give it (an IP-SAN for an IP, a DNS-SAN for a name).
- **Home Assistant** reaches the broker through *its own* MQTT integration —
  configure that integration's TLS/CA there (Whiskerless itself takes no broker
  details; it discovers the robot over HA's MQTT connection).
- **CLI:** pass `--insecure` to skip only the hostname match (the CA is still
  verified) when reaching the broker by IP/tunnel.

For a normal same-subnet setup with a matching IP SAN, leave verification on.

## Next steps

- Put `ca.crt` / `server.crt` / `server.key` on your broker →
  [mqtt-broker.md](mqtt-broker.md).
- Provision `ca.crt` into the robot → `whiskerless provision`.
- Point Home Assistant's MQTT integration at the broker; Whiskerless then
  discovers the robot → [home-assistant.md](home-assistant.md).
