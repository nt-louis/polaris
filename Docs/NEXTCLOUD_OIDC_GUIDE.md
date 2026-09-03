# Nextcloud & PocketID OIDC Administrator Guide

This guide documents post-deployment commands, configurations, and recovery
procedures for an optional Nextcloud `user_oidc` integration with PocketID.
Nextcloud runs in the dedicated `Utilities/cloud-docs/nextcloud/gateway`
(`cloud`) Gluetun namespace. The active compose file does not install or
configure `user_oidc` automatically; complete the prerequisite section before
using the commands below.

## OIDC Prerequisites

1. Deploy Nextcloud through the manager and confirm the `cloud` gateway is
   healthy.
2. Install and enable the app if it is not already present:
   ```bash
   docker exec -u www-data nextcloud php occ app:install user_oidc
   docker exec -u www-data nextcloud php occ app:enable user_oidc
   ```
3. Register a PocketID client for this Nextcloud instance. Use the callback and
   issuer values required by the installed `user_oidc` app version, then store
   the client secret in the `cloud_docs_nextcloud` Doppler config. Do not put it
   in a local `.env` or in this guide.
4. Configure the provider and claim mapping in Nextcloud's **Administration
   settings -> OpenID Connect** UI, then test with a non-admin account before
   enforcing SSO.

The exact callback path and `occ` options vary by `user_oidc` release. Verify
them with `docker exec -u www-data nextcloud php occ app:list` and the app's
current administrator documentation rather than copying an obsolete callback.

---

## SSO & OIDC Commands (Nextcloud `occ`)

These commands customize how the OpenID Connect (`user_oidc`) app behaves. Run these directly on your VPS host.

### Force SSO (Disable Local Username/Password Fields)
To secure your instance and force all users to authenticate exclusively through the PocketID button:
```bash
docker exec -u www-data nextcloud php occ config:app:set user_oidc allow_multiple_user_backends --value=0
```

### Restore Local Login (Bypass SSO/Allow Passwords)
If you need to re-enable the standard username/password forms alongside the PocketID button:
```bash
docker exec -u www-data nextcloud php occ config:app:set user_oidc allow_multiple_user_backends --value=1
```

### Disable OIDC Single Logout (Fix Logout Redirect Errors)
Prevents Nextcloud from redirecting you to PocketID's `end-session` endpoint on logout, avoiding the "Bad Request / Malformed Request" screen and cleanly returning you to the Nextcloud login page:
```bash
docker exec -u www-data nextcloud php occ config:system:set user_oidc single_logout --value=false --type=boolean
```

---

## Maintenance & Database Tuning

Use these commands to keep the database and file types in pristine condition.

### Run Mimetype Migrations
Clears the yellow mimetype warning by updating Nextcloud's file-type icon association database:
```bash
docker exec -u www-data nextcloud php occ maintenance:repair --include-expensive
```

### Manually Set Default Phone Region
If not configured via environment variables, you can set your country code (e.g., `US`) to validate phone numbers in user profiles:
```bash
docker exec -u www-data nextcloud php occ config:system:set default_phone_region --value="US"
```

### Unlock Stuck Files (File Locks)
If Nextcloud ever reports a file is "locked" and cannot be edited or deleted:
```bash
docker exec -u www-data nextcloud php occ maintenance:mode --on
docker exec -u www-data nextcloud php occ maintenance:data-fingerprint
docker exec -u www-data nextcloud php occ maintenance:mode --off
```

---

## Background Jobs (Cron) Configuration

To keep your instance fast and performant, background cron tasks must run automatically.

### Host VPS Crontab entry
Open the host crontab (`sudo crontab -e`) and add this line to trigger Nextcloud's background scheduler every 5 minutes:
```cron
*/5 * * * * docker exec -u www-data nextcloud php -f /var/www/html/cron.php
```

---

## Emergency Recovery & Troubleshooting

Keep these in reserve if you ever accidentally lock yourself out of the web interface.

### Emergency Local Login Bypass URL
If your OIDC provider is down or misconfigured, you can bypass the SSO redirect completely to log in with your master local administrator account by adding `?direct=1` to the login URL:
```
https://<your-nextcloud-domain>/login?direct=1
```
*(Replace `<your-nextcloud-domain>` with your actual Nextcloud domain.)*

### Disable the OIDC App via Command Line
If the OIDC configuration is completely broken and the interface is throwing constant redirect loops, you can completely disable the OIDC integration from the CLI to restore standard access:
```bash
docker exec -u www-data nextcloud php occ app:disable user_oidc
```
