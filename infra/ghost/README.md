# Ghost on AWS, reachable only through a tunnel

`deploy.sh` creates an EC2 VM running [Ghost](https://ghost.org) and publishes it
through a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).
The VM has no SSH key and its security group has **no inbound rules**, so
nothing on it can be reached from the internet directly.

```bash
export AWS_REGION=eu-central-1
./deploy.sh
# ...
# Ghost is up.
#   Site:   https://<random-words>.trycloudflare.com
#   Admin:  https://<random-words>.trycloudflare.com/ghost
```

Open `/ghost` straight away and create the owner account: until you do, anyone
with the URL could claim it.

To remove everything: `./destroy.sh`.

## How it works

```
browser ──https──> Cloudflare edge <──outbound tunnel── cloudflared ─┐
                                                                     │ docker network
                                                   Ghost :2368 <─────┘ (no published ports)
                                                     │
                                                   MySQL 8
```

| Piece | What it does |
|---|---|
| `deploy.sh` | Creates an IAM role (SSM only), a security group with zero ingress rules, and an Ubuntu 24.04 `t3.small` with IMDSv2 and an encrypted disk; then polls the VM through SSM until the site answers and prints the URL. Re-running it reuses what exists. |
| `user-data.sh` | Runs on first boot: installs Docker, writes a compose file (Ghost 6, MySQL 8, cloudflared), generates DB passwords on the VM, and installs a systemd unit so the stack comes back after a reboot. |
| `destroy.sh` | Terminates the VM and deletes the security group, instance profile and role. |

Admin access to the VM is through AWS Systems Manager, not SSH:

```bash
aws ssm start-session --target <instance-id>
sudo tail -f /var/log/ghost-setup.log
```

## Quick tunnel vs. your own domain

With no options the script uses a Cloudflare *quick tunnel*: no Cloudflare
account needed, but the hostname is random and changes if the VM reboots
(`start.sh` reads the new hostname and restarts Ghost with it). That suits a demo.

For a stable address, create a tunnel in the Cloudflare dashboard, route a
public hostname to `http://ghost:2368`, and pass its token:

```bash
CF_TUNNEL_TOKEN=eyJ... GHOST_URL=https://blog.example.com ./deploy.sh
```

The token is passed in EC2 user data, which anyone with
`ec2:DescribeInstanceAttribute` in the account can read. For production I would
put it in SSM Parameter Store as a SecureString and have the VM fetch it.

## Requirements and limits

- AWS CLI v2 with credentials, `jq` and `curl` on the machine running the script.
- A default VPC in the region. The VM keeps a public IP for outbound traffic
  only (pulling images, reaching Cloudflare and SSM); no port is open on it.
- Email is not configured, so Ghost cannot send newsletters or staff invites
  until `mail__*` settings are added to the compose file.
- Tested with `bash -n` and `shellcheck`; the cloud flow itself needs an AWS
  account to run end to end.
