# Deploy VoiceBot on AWS Free Tier

## 1. Launch EC2 instance
- AMI: Ubuntu 24.04 LTS (free tier eligible)
- Instance type: `t2.micro` (1 vCPU, 1 GB RAM) — free for 750 hrs/month
- Storage: 20 GB gp2 (free tier: 30 GB)
- Security group inbound rules:
  - TCP 22 (SSH) from your IP
  - TCP 80 (HTTP) from anywhere
  - TCP 443 (HTTPS) from anywhere

## 2. Allocate and attach an Elastic IP
Console → EC2 → Elastic IPs → Allocate → Associate with your instance.
This gives a stable public IP for DNS.

## 3. Set up a free DuckDNS subdomain
1. Go to duckdns.org, sign in, create a subdomain (e.g. `aria-voicebot`)
2. Set its IP to your Elastic IP
3. Note your subdomain: `aria-voicebot.duckdns.org`

## 4. Install Docker on the instance
```bash
ssh ubuntu@<elastic-ip>
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker ubuntu && newgrp docker
```

## 5. Upload the project
From your local machine:
```bash
scp -r ~/Downloads/VoiceBot ubuntu@<elastic-ip>:~/VoiceBot
```
Or clone from your GitHub repo.

## 6. Configure .env on the instance
```bash
cd ~/VoiceBot
nano .env   # add your API keys
```

## 7. Update Caddyfile with your domain
```bash
nano deploy/Caddyfile
# Replace "your-subdomain.duckdns.org" with "aria-voicebot.duckdns.org"
```

## 8. Run with Docker Compose
```bash
cd ~/VoiceBot
docker compose -f deploy/docker-compose.yml up -d --build
```

## 9. Verify
- `curl https://aria-voicebot.duckdns.org/api/health`
- Open the URL in Chrome (required for mic access)

## Cost guardrails
- Set a AWS billing alert at $5 in Billing → Budgets
- EC2 free tier covers 750 hrs/month for the first 12 months
- API costs: ~$0.01–0.05 per voice conversation (Claude + Deepgram + ElevenLabs)
- Stop the instance when not in use: `sudo shutdown now` (Elastic IP stays attached)

## Update the app
```bash
ssh ubuntu@<elastic-ip>
cd ~/VoiceBot && git pull  # if using git
docker compose -f deploy/docker-compose.yml up -d --build
```
