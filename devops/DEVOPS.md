# GitHub Actions CI/CD Setup Guide

This document explains how to set up your local Fedora machine (`msi-fedora-docker`) as a self-hosted runner for the `core_customizations` CI pipeline. 

Because we use the `container: frappe/erpnext:version-16` architecture in our workflow, your Fedora host stays perfectly clean. Docker handles all the isolated test environments.

## Step 1: Generate the Runner Token
Before running the setup script, you need a Registration Token from GitHub. This proves to GitHub that your machine is authorized to pull and test the private code.

1. Go to your GitHub repository in your browser.
2. Click on **Settings** (the gear icon tab).
3. On the left sidebar, click **Actions** $\rightarrow$ **Runners**.
4. Click the green **New self-hosted runner** button.
5. In the "Configure" section of the page that appears, look for a long random string under the `config.sh` command. It will look like this:
   `--token ABCD1234EFGH5678IJKL9012MNOP`
6. Copy just that token string. Keep the Repository URL handy as well (e.g. `https://github.com/your-org/your-repo`).

## Step 2: Run the Setup Script
Copy the provided setup script to your Fedora machine and execute it. 

1. On your Fedora machine, open a terminal.
2. Ensure the script is executable:
   ```bash
   chmod +x devops/setup_fedora_runner.sh
   ```
3. Run the script **as your normal user** (do not run with `sudo`; the script will prompt for `sudo` internally when installing Docker or systemd services).
   ```bash
   ./devops/setup_fedora_runner.sh
   ```
4. The script will ask you to paste the **Repository URL** and the **Runner Token** you copied in Step 1.

## What the script does
- **Docker Installation**: It checks if Docker CE is installed. If not, it installs Docker and adds your user to the `docker` group.
- **GitHub Runner Download**: Downloads and extracts the latest runner tarball to `~/actions-runner`.
- **Runner Configuration**: Configures the runner and assigns it the label `msi-fedora-docker`.
- **Service Installation**: Installs the runner as a background `systemd` service so it stays online even if you close the terminal.

## Troubleshooting

- **Permissions Error**: If Docker fails to start containers because of permissions, you may need to log out and log back in to apply the `usermod` group changes.
- **Check Status**: To check if the runner is actively listening for jobs, run:
  ```bash
  cd ~/actions-runner
  sudo ./svc.sh status
  ```
