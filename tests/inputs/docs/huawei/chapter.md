# Test Configuration Commands

## Basic Commands

### display test-thing

#### Function

The **display test-thing** command displays things.

#### Format

**display test-thing**

#### Views

All views

### ip vpn-instance(System view)

#### Function

The **ip vpn-instance** command creates a VPN instance and displays the VPN instance view.

By default, no VPN instance is configured.

#### Format

**ip vpn-instance** *vpn-instance-name*

**undo ip vpn-instance** *vpn-instance-name*

#### Parameters

| Parameter | Description | Value |
|---|---|---|
| *vpn-instance-name* | Specifies the name of a VPN instance. | The value is a string of 1 to 31 case-sensitive characters. It cannot contain spaces. |

#### Views

System view

### vpn-target

#### Function

The **vpn-target** command configures VPN targets.

#### Format

**vpn-target** { *vpn-target* } &<1-8> [ *vrfRtType* ]

**undo vpn-target** { *vpn-target* } &<1-8> [ *vrfRtType* ]

#### Parameters

| Parameter | Description | Value |
|---|---|---|
| *vpn-target* | Adds VPN targets. | The value is a string of 3 to 21 characters. |
| *vrfRtType* | Type of the VPN target. | The value is an enumerated type:<br>- both: Both directions. - export-extcommunity: Export only. - import-extcommunity: Import only. |

#### Views

VPN instance view, VPN instance IPv4 address family view

### peer timer

#### Function

The **peer timer** command sets the Keepalive time and hold time for a peer.

By default, the keepalive time is 60s, and the hold time is 180s.

#### Format

**peer** *ipv4-address* **timer** **keepalive** *keepalive-time* **hold** *hold-time* [ **min-holdtime** *min-hold-value* | **send-hold** *send-hold-time* ]

**undo peer** *ipv4-address* **timer** **keepalive** **hold**

#### Parameters

| Parameter | Description | Value |
|---|---|---|
| **peer** *ipv4-address* | Specifies an IPv4 peer address. | It is in dotted decimal notation. |
| **keepalive** *keepalive-time* | Specifies the Keepalive time. | The value is an integer ranging from 0 to 21845, in seconds. |
| **hold** *hold-time* | Indicates the hold time. | The value is 0 or an integer ranging from 3 to 65535, in seconds. |

#### Views

BGP view, BGP multi-instance view

### peer timer (multi-instance only)

#### Format

**peer** *ipv4-address* **timer** **connect-retry** *t*

#### Views

BGP multi-instance view
