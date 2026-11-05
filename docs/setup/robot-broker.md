# A separate broker for the robot (optional)

Most setups do not need this. The robot needs a broker it can reach on **TLS port
8883** that accepts it **without a username or password**: anonymous, or by client
certificate ([mqtt-broker.md](mqtt-broker.md) explains why). If you run your own
Mosquitto, add the robot's listener to it as [mqtt-broker.md](mqtt-broker.md)
describes, and stop reading here.

You need a separate broker for the robot when either of these is true:

- **Your broker cannot take a password-less client.** The official Mosquitto add-on
  for Home Assistant OS is the common case: it requires a username and password
  from every client, even one that presents a certificate, and the robot has no way
  to send them.
- **Something else already holds port 8883 on the host.** The robot's port is
  fixed in its firmware, so the broker must answer on 8883 at the address the robot
  was provisioned with. Another service on the same host using 8883, such as
  another cloud-replacement broker for different appliances, rules that out. The
  [port redirect](#when-8883-is-already-taken) below gets around it.

For Home Assistant OS, the **Whiskerless robot broker** add-on in this repository
is that separate broker: Mosquitto with a TLS listener for the robot, bridged into
the Mosquitto add-on, where Home Assistant and the whiskerless integration see the
robot's topics as if it were connected there directly.

## Install the add-on

1. In Home Assistant, open **Settings → Add-ons → Add-on store**, open the ⋮ menu,
   choose **Repositories**, and add `https://github.com/SisyphusMD/whiskerless`.
2. Install **Whiskerless robot broker**. Leave the Mosquitto add-on and the MQTT
   integration as they are; this add-on bridges into them using the Supervisor's
   MQTT service account, so it needs no login of its own.
3. Run `whiskerless setup --host <home-assistant-ip>` on your computer. It writes
   `ca.crt`, `server.crt` and `server.key` (see [certificates.md](certificates.md)).
4. Copy those three files into the add-on's config folder. With the Samba or SSH
   add-on it is `addon_configs/<id>_whiskerless_broker/`; the `<id>` prefix depends
   on the repository and is shown in the folder name.
5. Start the add-on. Its log ends with
   `robot listener on 8883, client certificate optional; bridging to core-mosquitto:1883`.
6. Provision the robot with `whiskerless provision`. Its broker address is Home
   Assistant's IP, the same address as in step 3.

The add-on's log shows the robot connecting from its own IP with its serial as
the client id.

### Options

| Option | Default | Meaning |
|---|---|---|
| `require_client_certificate` | `false` | Require a certificate signed by your CA. Turn it on only after every robot has been provisioned by whiskerless; see [Requiring certificates](mqtt-broker.md#requiring-certificates-instead-recommended). |
| `log_subscriptions` | `false` | Log every subscribe and unsubscribe; useful to see which topics a robot uses. |
| `robot_acl_pattern` | `prod/#` | Topics an anonymous client may use. Ignored when certificates are required. |
| `bridge_topics` | `prod/# both 1` | Mosquitto bridge `topic` lines into the Mosquitto add-on. |

## When 8883 is already taken

The robot always connects to port 8883 on the broker's address. When another
service holds 8883 on that host, publish the add-on on a different host port and
have the router send the robot's 8883 there:

1. In the add-on's **Network** settings, change the host port for `8883/tcp` to a
   free port, for example `8885`. The add-on still listens on 8883 inside its
   container.
2. On the router, add a **destination NAT** (port redirect) rule:

   | Field | Value |
   |---|---|
   | Protocol | TCP |
   | Source address | the robot's IP |
   | Destination address | the broker host's IP |
   | Destination port | 8883 |
   | Translate to | the broker host's IP, port 8885 |

   Matching on the robot's source address leaves 8883 untouched for everything
   else that uses it.
3. If the router filters traffic between networks, allow the robot to reach the
   broker host on the **translated** port (8885). Routers usually apply filtering
   after the translation, so a rule for 8883 alone does not let it through.

The robot never sees the redirect. It connects to the broker host's IP on 8883 as
provisioned, and the server certificate still matches because the destination
address does not change.

The rule only applies to traffic that **passes through the router**, so the robot
and the broker host must be on **different subnets**, as with a separate IoT VLAN.
On a single flat subnet the robot reaches the host directly and the redirect never
happens. Move the robot to its own network, or use the router's hairpin
NAT (NAT loopback) feature if it can apply one to local-to-local traffic.

On a Linux-based router the rule looks like this, with the robot at
`192.168.2.50`, the broker host at `192.168.1.10`, and the add-on published on
`8885`:

```bash
# nftables
nft add rule ip nat prerouting ip saddr 192.168.2.50 ip daddr 192.168.1.10 \
  tcp dport 8883 dnat to 192.168.1.10:8885

# iptables
iptables -t nat -A PREROUTING -s 192.168.2.50 -d 192.168.1.10 \
  -p tcp --dport 8883 -j DNAT --to-destination 192.168.1.10:8885
```

Consumer and prosumer routers offer the same rule in their web interface, under
names such as *Destination NAT*, *Port forwarding* with a source restriction, or
*NAT rules*.

## Give both ends fixed addresses

- **The robot.** The redirect matches the robot's source IP. Give the robot a
  **DHCP reservation** (static lease) before adding the rule. If its address
  changes, the rule stops matching, its connection lands on whatever else holds
  8883, the TLS handshake fails, and the robot drops offline with nothing on its
  panel to say why.
- **The broker host.** Its IP is written into the robot during provisioning and
  into the server certificate. If it changes, the robot cannot connect until you
  re-run `whiskerless setup` and `whiskerless provision`. Give Home Assistant a
  fixed address too.

## Checking it works

- The add-on's log shows `New client connected from <robot-ip> … as <serial>`.
- Turn on `log_subscriptions` to see the robot subscribe to its command topic.
- In Home Assistant, **Settings → Devices & services → MQTT → Configure → Listen
  to a topic** on `prod/#` shows the robot's messages arriving through the bridge.
