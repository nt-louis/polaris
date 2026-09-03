# Doppler Migration & Historical SOPS Commit Reference

This document records the exact Git commit hashes associated with the Doppler SaaS migration. If you ever need to restore, inspect, or reference legacy SOPS scripts or `.env.enc` files, use the commit hashes listed below.

---

## 📌 Commit Reference Table

| Commit Hash | Description | Restorable Artifacts |
| :--- | :--- | :--- |
| `15ac8ec` | **Legacy SOPS Purge** | Final removal of `Scripts/deploy/core/sops_manager.py` and SOPS CLI hooks |
| `25bc315` | **SOPS Ciphertext Removal** | All 92 `.env.enc` files, `.env.vps-*.enc`, and `.sops.yaml` |
| `11d9d03` | **CLI & TUI Streamlining** | Update `./manage.py secrets` & TUI dashboard for Doppler |
| `4dc1971` | **Workflow Wrapping** | `doppler run` integration in `updater.py` and custom update scripts |
| `8c55dc5` | **Initial Doppler Migration** | Core migration script & multi-VPS project topology |
| `52d9873` | **Pre-Doppler Baseline (SOPS)** | Last commit on `main` before Doppler migration with all `.env.enc` files intact |

---

## 🛠️ How to Restore SOPS Artifacts from Git History

### 1. Restore `sops_manager.py`:
```bash
git checkout 52d9873 -- Scripts/deploy/core/sops_manager.py
```

### 2. Restore `.sops.yaml` configuration:
```bash
git checkout 52d9873 -- .sops.yaml
```

### 3. Restore all `.env.enc` files for a service:
```bash
git checkout 52d9873 -- Media/stremio/addons/comet/.env.enc
```

### 4. Restore all `.env.vps-*.enc` global configs:
```bash
git checkout 52d9873 -- .env.vps-a.enc .env.vps-b.enc
```

---
*Maintained as part of the Net-Stream Doppler Migration Project.*
