#!/bin/bash

# Ensure running as a normal user (not root, GitHub runners block root execution)
if [ "$EUID" -eq 0 ]; then
  echo "Please do not run this script as root. Run it as your normal fedora user."
  exit 1
fi

echo "============================================="
echo "   GitHub Actions Runner Setup for Fedora    "
echo "============================================="
echo ""
echo "This script will download and configure a self-hosted runner labeled 'msi-fedora-docker'."

read -p "Enter your GitHub Repository URL (e.g., https://github.com/your-org/your-repo): " REPO_URL
read -p "Enter your Runner Registration Token (From Settings -> Actions -> Runners -> New Runner): " RUNNER_TOKEN

if [ -z "$REPO_URL" ] || [ -z "$RUNNER_TOKEN" ]; then
    echo "Repository URL and Token are required. Exiting."
    exit 1
fi

# 1. Install Docker if not present (since our CI uses containerized frappe:v16)
echo "Checking for Docker..."
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker CE..."
    sudo dnf -y install dnf-plugins-core
    sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
    sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -aG docker $USER
    echo "Docker installed. You may need to log out and log back in for group changes to take effect."
fi

# Check if runner already exists
if [ -f ~/actions-runner/.runner ]; then
    echo "Warning: A GitHub Actions runner is already configured in ~/actions-runner."
    echo "You must remove the existing runner before setting up a new one."
    echo "To remove it, run: cd ~/actions-runner && sudo ./svc.sh stop && sudo ./svc.sh uninstall && ./config.sh remove"
    exit 1
fi

# 2. Download and configure the runner
mkdir -p ~/actions-runner && cd ~/actions-runner

# Fetch latest runner version dynamically or use hardcoded known stable version
RUNNER_VERSION="2.321.0"
echo "Downloading GitHub Actions Runner v${RUNNER_VERSION}..."
curl -o actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz -L https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz

echo "Extracting..."
tar xzf ./actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz

echo "Configuring runner..."
./config.sh --url "$REPO_URL" --token "$RUNNER_TOKEN" --name "msi-fedora-docker" --labels "msi-fedora-docker" --unattended --replace

echo "Installing runner as a systemd service..."
sudo ./svc.sh install

echo "Starting runner service..."
sudo ./svc.sh start

echo "============================================="
echo "   Setup Complete!                           "
echo "============================================="
echo "Your runner is now active and listening for jobs."
echo "Check its status using: sudo ./svc.sh status"
